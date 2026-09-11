"""Склейка двух сторон: контакт-лист, маршрутизация сообщений в обе стороны."""

from __future__ import annotations

import asyncio
import logging
import time

from telethon import errors

from . import avatars as avatar_lib
from . import emoji, history, policy
from .access import AccessControl
from .photos import PhotoStore
from .render import Item, RenderStore, Transcoder
from .webserver import PhotoServer
from .config import Config
from .db import Contact, Storage
from .oscar import const as C
from .oscar.server import OscarServer
from .tg.client import KIND_TITLES, TelegramSide

log = logging.getLogger("bridge")

# Ошибки, после которых сессия Telegram больше не оживёт — нужен новый вход.
DEAD_SESSION = (
    errors.rpcerrorlist.AuthKeyUnregisteredError,
    errors.rpcerrorlist.SessionRevokedError,
    errors.rpcerrorlist.SessionExpiredError,
    errors.rpcerrorlist.AuthKeyDuplicatedError,
    errors.rpcerrorlist.UserDeactivatedError,
)

ROSTER_REFRESH_SECONDS = 600
SEARCH_LIMIT = 10                # столько результатов отдаём телефону
# Telegram повторяет «печатает» каждые несколько секунд, а Jimm сам индикатор
# не гасит — снимаем его по молчанию.
TYPING_TIMEOUT = 8

# Как статусы Telegram выглядят в контакт-листе Jimm
STATUS_CODES = {
    "online": C.STATUS_ONLINE,
    "away": C.STATUS_AWAY,
    "offline": C.STATUS_OFFLINE,
}


class Bridge:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.storage = Storage(cfg.db)
        self.telegram = TelegramSide(cfg, self.on_telegram_message, self.on_telegram_status,
                                     self.on_telegram_typing, self.on_telegram_read)
        self.oscar = OscarServer(cfg, self.storage, self.on_phone_message,
                                 self.roster, self.status_of, self.chat_info,
                                 self.search_chats, self.verdict_for,
                                 self.on_phone_remove, self.on_phone_privacy,
                                 self.avatar, self.icon_hash)
        self._roster: list[Contact] = []
        self._statuses: dict[int, int] = {}   # реальные статусы из Telegram
        self._shown: dict[int, int] = {}      # что сейчас показано на телефоне
        self._by_uin: dict[int, Contact] = {}
        self._unread: dict[tuple[int, int], int] = {}   # (peer_id, topic_id)
        self._typing: dict[int, asyncio.Task] = {}
        self._refresh_task: asyncio.Task | None = None
        self.mode = policy.UNMUTED
        self.oscar.on_owner_status = self.on_owner_status
        self.oscar.on_typing = self.on_phone_typing
        self.avatars = (avatar_lib.AvatarStore(cfg.avatar_size, cfg.avatar_max_kb * 1024)
                        if cfg.avatars else None)
        self.photos: PhotoStore | None = None
        self.photo_server: PhotoServer | None = None
        self.render: RenderStore | None = None
        if cfg.render_enabled and cfg.photos_enabled:
            self.render = RenderStore(
                cfg.render_dir,
                Transcoder(cfg.render_ffmpeg, cfg.render_video_seconds,
                           cfg.render_audio_seconds, cfg.render_timeout,
                           cfg.render_dir),
                cfg.render_ttl_minutes, cfg.photo_width, cfg.photo_height,
                cfg.photo_max_kb * 1024, cfg.render_encoding)
        if cfg.photos_enabled:
            self.photos = PhotoStore(cfg.photos_dir, cfg.photo_width, cfg.photo_height,
                                     cfg.photo_max_kb * 1024, cfg.photo_keep_hours)
            self.photo_server = PhotoServer(self.photos, cfg.photos_host, cfg.photos_port,
                                            AccessControl(
                                                allow_from=cfg.allow_from,
                                                max_connections=cfg.max_connections),
                                            render=self.render)

    # --- контакт-лист ---------------------------------------------------

    def roster(self) -> list[Contact]:
        return self._roster

    def _reload_roster(self) -> None:
        """Перечитывает контакт-лист из базы — всегда с roster_limit.

        Без ограничения телефон при следующем входе получил бы все чаты
        разом, а индекс по UIN разошёлся бы со списком.
        """
        self._roster = self.storage.contacts(self.cfg.roster_limit)
        self._by_uin = {c.uin: c for c in self._roster}

    def status_of(self, uin: int) -> int:
        """Статус контакта для контакт-листа.

        Кроме присутствия он показывает, дойдут ли сообщения при текущем
        статусе владельца: «не беспокоить» — от этого чата не придёт ничего,
        «недоступен» — сообщения копятся и приедут после смены статуса.
        """
        real = self._statuses.get(uin, C.STATUS_ONLINE)
        if real == C.STATUS_OFFLINE:
            return real          # собеседника нет — это важнее любой подмены

        contact = self._by_uin.get(uin)
        if contact is not None and not policy.allows(self.mode, contact.kind,
                                                     bool(contact.favourite),
                                                     bool(contact.muted)):
            return C.STATUS_NA if policy.holds(self.mode) else C.STATUS_DND
        return real

    async def refresh_shown_statuses(self) -> None:
        """Рассылает изменившиеся статусы: после смены режима меняется сразу
        много контактов, поэтому шлём только то, что действительно поменялось,
        и небольшими порциями — канал у телефона узкий."""
        sent = 0
        for contact in self._roster:
            shown = self.status_of(contact.uin)
            if self._shown.get(contact.uin) == shown:
                continue
            self._shown[contact.uin] = shown
            await self.oscar.notify_status(contact.uin, shown)
            sent += 1
            if sent % 20 == 0:
                await asyncio.sleep(0.2)
        if sent:
            log.info("обновлено статусов контактов: %d", sent)

    async def search_chats(self, query: str) -> list[dict]:
        """Поиск из Jimm: сначала по уже известным чатам, потом по Telegram."""
        needle = query.strip().lower()
        found = [
            {"uin": c.uin, "title": c.title,
             "kind": KIND_TITLES.get(c.kind, "Чат"), "username": ""}
            for c in self.storage.contacts() if needle in c.title.lower()
        ][:SEARCH_LIMIT]
        if found:
            return found

        # Поиск возвращает и убранные ранее: нашли — значит снова нужны.
        for contact in self.storage.contacts_all():
            if contact.hidden and needle in contact.title.lower():
                self.storage.set_hidden(contact.uin, False)
                found.append({"uin": contact.uin, "title": contact.title,
                              "kind": KIND_TITLES.get(contact.kind, "Чат"),
                              "username": ""})
        if found:
            self._reload_roster()
            return found[:SEARCH_LIMIT]

        for item in await self.telegram.search_chats(query, SEARCH_LIMIT):
            known = self.storage.contact_by_peer(item["peer_id"])
            if known is not None:
                # Чат уже есть — его группу, позицию и мьют трогать нельзя.
                uin = known.uin
            else:
                uin = self.storage.uin_for_peer(
                    item["peer_id"], kind=item["kind"], title=item["title"],
                    group_name=KIND_TITLES.get(item["kind"], "Чаты"), position=9999)
            found.append({"uin": uin, "title": item["title"],
                          "kind": KIND_TITLES.get(item["kind"], "Чат"),
                          "username": item["username"]})
        if found:
            # Новые чаты появятся в контакт-листе после перезахода в Jimm.
            self._reload_roster()
        return found

    def verdict_for(self, uin: int) -> str:
        """Что делать с накопленным сообщением при текущем статусе.

        Статус мог смениться, пока сообщения лежали в очереди: доставлять
        групповые в «не беспокоить» нельзя, иначе телефон получит при входе
        ровно то, от чего его просили избавить.
        """
        contact = self.storage.contact_by_uin(uin)
        if contact is None:
            return "send"
        if policy.allows(self.mode, contact.kind, bool(contact.favourite),
                         bool(contact.muted)):
            return "send"
        return "hold" if policy.holds(self.mode) else "drop"

    async def on_owner_status(self, status: int) -> None:
        """Владелец сменил статус в Jimm."""
        previous = self.mode
        self.mode = policy.mode_for(status)
        log.info("статус «%s» — %s", policy.status_name(status),
                 policy.MODE_NAMES[self.mode])
        if previous != self.mode:
            await self.refresh_shown_statuses()
        if policy.holds(previous) and not policy.holds(self.mode):
            await self.release_held()

    async def release_held(self) -> None:
        """Отдаёт то, что придержали на время «занят».

        Доставляем всё, что моложе busy_hold_minutes, не пропуская через новый
        фильтр: эти сообщения и так отложены из-за «занят», а человек вернулся.
        Исключения два: переход в тихий режим («не беспокоить», «недоступен») —
        там телефон должен молчать, и заглушённые в Telegram чаты — они
        придержаны как раз из-за мьюта, и снимать его возврат в сеть не должен.
        """
        rows = self.storage.take_held()
        if not rows:
            return
        if not policy.releases(self.mode):
            log.info("после «занят» выбран режим тишины (%s) — %d придержанных не отдаю",
                     policy.MODE_NAMES[self.mode], len(rows))
            return

        cutoff = time.time() - self.cfg.busy_hold_minutes * 60
        delivered = 0
        for uin, text, ts in rows:
            if ts < cutoff:
                continue
            contact = self.storage.contact_by_uin(uin)
            if (self.mode != policy.ALL and contact is not None
                    and contact.muted):
                continue
            await self.oscar.deliver(uin, text, ts=ts)
            delivered += 1
        log.info("после «занят» доставлено %d из %d придержанных (свежее %d минут)",
                 delivered, len(rows), self.cfg.busy_hold_minutes)

    async def chat_info(self, uin: int) -> dict | None:
        """Сведения для карточки контакта: их запрашивает Jimm по «Информация»."""
        contact = self.storage.contact_by_uin(uin)
        if contact is None:
            return None
        info = await self.telegram.chat_info(contact.peer_id)
        if info and self.cfg.emoji_to_text:
            info = {k: emoji.to_text(v) if isinstance(v, str) else v
                    for k, v in info.items()}
        if info is not None:
            # Пометки чата — то, чего в Telegram-профиле нет, но что решает
            # судьбу его сообщений: избранное и выключенные уведомления.
            marks = []
            if contact.favourite:
                marks.append("Избранный")
            if contact.muted:
                marks.append("Заглушенный")
            info["marks"] = ", ".join(marks)
        return info

    def icon_hash(self, uin: int) -> bytes | None:
        """Примета аватарки для блока сведений о контакте."""
        return self.avatars.hash_of(uin) if self.avatars else None

    async def avatar(self, uin: int) -> tuple[bytes, bytes] | None:
        """Аватарка по запросу телефона: берём из кэша или тянем из Telegram."""
        if self.avatars is None:
            return None
        ready = self.avatars.cached(uin)
        if ready is not None:
            return ready
        contact = self.storage.contact_by_uin(uin)
        if contact is None or self.avatars.hash_of(uin) is None:
            return None
        raw = await self.telegram.avatar(contact.peer_id)
        if raw is None:
            return None
        got = self.avatars.store(uin, raw)
        if got is not None:
            log.info("аватарка чата %r готова: %d байт", contact.title, len(got[1]))
        return got

    async def refresh_roster(self) -> None:
        dialogs = await self.telegram.dialogs()
        for d in dialogs:
            favourite = int(d.pinned or d.title.strip().lower() in self.cfg.favourites)
            uin = self.storage.uin_for_peer(d.peer_id, kind=d.kind, title=d.title,
                                            group_name=d.group_name, position=d.position,
                                            favourite=favourite, topic_id=d.topic_id,
                                            muted=int(d.muted))
            self._unread[(d.peer_id, d.topic_id)] = d.unread
            if self.avatars is not None:
                self.avatars.remember(uin, d.photo_id)
            self._statuses[uin] = STATUS_CODES.get(d.status, C.STATUS_ONLINE)
        # Чаты, которых больше нет в Telegram, убираем из контакт-листа.
        for contact in self.storage.mark_missing([d.peer_id for d in dialogs]):
            log.info("чат %r исчез из Telegram — убираю из списка", contact.title)
            self._statuses[contact.uin] = C.STATUS_OFFLINE
            self._shown[contact.uin] = C.STATUS_OFFLINE
            await self.oscar.notify_status(contact.uin, C.STATUS_OFFLINE)

        self._reload_roster()
        total = len(self.storage.contacts())
        if self.cfg.roster_limit and total > len(self._roster):
            log.info("в контакт-лист телефона идут %d чатов из %d (roster_limit); "
                     "остальные приходят как сообщения и находятся поиском",
                     len(self._roster), total)
        online = sum(1 for c in self._roster
                     if self._statuses.get(c.uin, C.STATUS_ONLINE) != C.STATUS_OFFLINE)
        log.info("контакт-лист: %d чатов, из них в сети %d", len(self._roster), online)
        # Статусы шлём после сборки списка: и настоящие обновления из Telegram,
        # и подмену для тех, от кого сообщения сейчас не доходят. Снятый на
        # десктопе мьют иначе доехал бы до телефона только со сменой статуса.
        await self.refresh_shown_statuses()

    async def _refresh_loop(self) -> None:
        while True:
            await asyncio.sleep(ROSTER_REFRESH_SECONDS)
            try:
                await self.refresh_roster()
                if self.photos is not None:
                    removed = self.photos.cleanup()
                    if removed:
                        log.info("удалено %d старых снимков", removed)
                if self.render is not None:
                    gone = self.render.cleanup()
                    if gone:
                        log.info("просроченные страницы убраны, файлов удалено: %d", gone)
            except Exception:
                log.exception("не удалось обновить контакт-лист")

    # --- маршрутизация --------------------------------------------------

    async def on_telegram_message(self, peer_id: int, sender: str, text: str,
                                  ts: int = 0, topic_id: int = 0) -> bool:
        """Возвращает True, если сообщение ушло телефону (или встало в очередь).

        По этому Telegram-сторона решает, помечать ли его прочитанным:
        отброшенное по статусу телефон не видел, значит и читать его нечем.
        """
        if not text:
            return False
        contact = self.storage.contact_by_peer(peer_id, topic_id)
        if contact is not None and contact.hidden:
            log.debug("чат %r убран с телефона — сообщение не доставляю", contact.title)
            if ts:
                self.storage.note_delivered(peer_id, ts, topic_id)
            return False
        if contact is None:
            title, kind = await self.telegram.title_for(peer_id)
            if topic_id:
                # Новая тема форума: сам форум становится группой контактов.
                group = title[:self.cfg.alias_max_chars]
                title = f"Тема {topic_id}"
                kind = "chat"
            else:
                group = KIND_TITLES.get(kind, "Чаты")
            uin = self.storage.uin_for_peer(
                peer_id, kind=kind, title=title, group_name=group,
                position=9999, topic_id=topic_id)
            self._reload_roster()
            log.info("новый чат %r получил UIN %d (появится в списке после перевхода)", title, uin)
        else:
            uin = contact.uin
        # Статус в Jimm решает, что доставлять, а что оставить в Telegram.
        contact = self.storage.contact_by_uin(uin)
        if sender:
            text = f"{sender}: {text}"
        if self.cfg.emoji_to_text:
            text = emoji.to_text(text)

        # Сообщение пришло — значит набор закончен.
        await self.stop_typing(uin)

        # Статус в Jimm решает, что доставлять, а что придержать или пропустить.
        if contact is not None and not policy.allows(self.mode, contact.kind,
                                                     bool(contact.favourite),
                                                     bool(contact.muted)):
            if policy.holds(self.mode):
                self.storage.hold(uin, text, ts or int(time.time()),
                                  self.cfg.offline_queue_per_chat)
                log.debug("«занят»: придержал сообщение из %r", contact.title)
            else:
                log.debug("статус «%s»: сообщение из %r не доставляю",
                          policy.status_name(self.oscar.owner_status), contact.title)
            if ts:
                self.storage.note_delivered(peer_id, ts, topic_id)
            return False
        await self.oscar.deliver(uin, text, ts=ts)
        # Отмечаем даже то, что легло в очередь: оно уже сохранено в базе,
        # и при следующем запуске догружать его повторно не нужно.
        if ts:
            self.storage.note_delivered(peer_id, ts, topic_id)
        return True

    async def on_telegram_status(self, peer_id: int, status: str) -> None:
        contact = self.storage.contact_by_peer(peer_id)
        if contact is None:
            return
        code = STATUS_CODES.get(status, C.STATUS_ONLINE)
        if self._statuses.get(contact.uin) == code:
            return
        self._statuses[contact.uin] = code
        log.debug("%s теперь %s", contact.title, status)

        # На телефон уходит не сам статус, а то, что должно быть видно:
        # у отфильтрованных чатов он подменён на «не беспокоить».
        shown = self.status_of(contact.uin)
        if self._shown.get(contact.uin) != shown:
            self._shown[contact.uin] = shown
            await self.oscar.notify_status(contact.uin, shown)

    async def on_telegram_typing(self, peer_id: int, active: bool) -> None:
        """Собеседник набирает сообщение — покажем это на телефоне."""
        contact = self.storage.contact_by_peer(peer_id)
        if contact is None:
            return
        if not active:
            await self.stop_typing(contact.uin)
            return
        if not policy.allows(self.mode, contact.kind, bool(contact.favourite),
                             bool(contact.muted)):
            return

        await self.oscar.notify_typing(contact.uin, True)
        old = self._typing.pop(contact.uin, None)
        if old is not None:
            old.cancel()
        self._typing[contact.uin] = asyncio.create_task(self._typing_expiry(contact.uin))

    async def _typing_expiry(self, uin: int) -> None:
        """Снимает «печатает», если из Telegram давно ничего не приходило."""
        try:
            await asyncio.sleep(TYPING_TIMEOUT)
        except asyncio.CancelledError:
            return
        self._typing.pop(uin, None)
        await self.oscar.notify_typing(uin, False)

    async def stop_typing(self, uin: int) -> None:
        """Гасит индикатор сразу — клиент сам этого не делает."""
        task = self._typing.pop(uin, None)
        if task is None:
            return
        task.cancel()
        await self.oscar.notify_typing(uin, False)

    async def on_telegram_read(self, peer_id: int, max_id: int) -> None:
        """Собеседник прочитал наши сообщения — телефон ставит галочку."""
        contact = self.storage.contact_by_peer(peer_id)
        if contact is not None:
            await self.oscar.confirm_read(contact.uin, max_id)

    async def on_phone_privacy(self, uin: int, muted: bool) -> None:
        """Списки видимости в клиенте управляют уведомлениями Telegram.

        «В невид. список» заглушает чат, «В видим. список» возвращает ему
        голос — то же самое, что выключить уведомления в самом Telegram.
        Во всех статусах, кроме «свободен для беседы», это сразу решает,
        дойдут ли от чата сообщения.
        """
        contact = self.storage.contact_by_uin(uin)
        if contact is None:
            log.warning("список видимости для неизвестного UIN %d", uin)
            return
        if bool(contact.muted) == muted:
            return

        if not await self.telegram.set_muted(contact.peer_id, muted):
            await self.reply(contact, "Не получилось изменить уведомления в Telegram")
            return

        self.storage.set_muted(contact.uin, muted)
        self._reload_roster()
        log.info("чат %r %s в Telegram", contact.title,
                 "заглушён" if muted else "снова со звуком")

        shown = self.status_of(contact.uin)
        if self._shown.get(contact.uin) != shown:
            self._shown[contact.uin] = shown
            await self.oscar.notify_status(contact.uin, shown)

    async def on_phone_remove(self, uin: int, revoke: bool) -> None:
        """Удаление контакта с телефона.

        «Удалить» убирает чат у себя, «Удалиться из его КЛ» — ещё и у
        собеседника. Обе операции необратимы, поэтому каждая закрывается
        своей настройкой, а сделанное записывается в журнал.
        """
        contact = self.storage.contact_by_uin(uin)
        if contact is None:
            log.warning("просьба удалить неизвестный UIN %d", uin)
            return

        if contact.topic_id:
            # Удалить тему в Telegram нельзя — такой операции там нет.
            # Зато можно убрать её с телефона: из контакт-листа она уйдёт,
            # а сообщения из неё перестанут доходить.
            await self.reply(contact,
                             "Удаление тем форума в Telegram не поддерживается. "
                             "Убрал тему из контакт-листа, сообщения из неё "
                             "приходить не будут.")
            self.storage.set_hidden(contact.uin)
            self._reload_roster()
            await self.oscar.notify_status(contact.uin, C.STATUS_OFFLINE)
            log.info("тема %r убрана с телефона (в Telegram осталась)", contact.title)
            return

        allowed = self.cfg.allow_delete_revoke if revoke else self.cfg.allow_delete
        if not allowed:
            setting = "allow_delete_revoke" if revoke else "allow_delete"
            log.warning("удаление чата %r запрещено настройкой %s",
                        contact.title, setting)
            await self.reply(contact, f"Удаление запрещено настройкой {setting}")
            return

        log.warning("удаляю чат %r%s", contact.title,
                    " у обеих сторон" if revoke else "")
        if not await self.telegram.delete_chat(contact.peer_id, revoke):
            await self.reply(contact, "Не получилось удалить чат в Telegram")
            return

        # Из контакт-листа чат уходит при следующем входе; запись остаётся,
        # чтобы за ним сохранился прежний UIN, если он вернётся.
        self.storage.mark_gone(contact.uin)
        self._reload_roster()
        await self.oscar.notify_status(contact.uin, C.STATUS_OFFLINE)
        log.info("чат %r удалён%s", contact.title,
                 " у обеих сторон" if revoke else "")

    async def on_phone_typing(self, uin: int, active: bool) -> None:
        """Владелец печатает в Jimm — передаём в Telegram."""
        contact = self.storage.contact_by_uin(uin)
        if contact is not None:
            await self.telegram.set_typing(contact.peer_id, active)

    async def on_phone_message(self, uin: int, text: str) -> int | None:
        """Возвращает номер отправленного сообщения в Telegram либо None."""
        contact = self.storage.contact_by_uin(uin)
        if contact is None:
            log.warning("сообщение на неизвестный UIN %d", uin)
            return None

        command = history.parse(text)
        if command is not None:
            await self.run_command(contact, command)
            return -1          # команда обработана, номера сообщения нет
        if self.cfg.text_to_emoji:
            text = emoji.to_emoji(text)
        try:
            message_id = await self.telegram.send(contact.peer_id, text, contact.topic_id)
            log.info("-> %s: %d симв.", contact.title, len(text))
            log.debug("-> %s: %s", contact.title, text[:200])
            return message_id
        except errors.FloodWaitError as exc:
            log.warning("Telegram просит подождать %d с (чат %r)", exc.seconds, contact.title)
            await self.reply(contact, f"Не отправлено: Telegram просит подождать {exc.seconds} с")
            return None
        except Exception as exc:
            log.exception("не удалось отправить в чат %r", contact.title)
            await self.reply(contact, f"Не отправлено в Telegram: {type(exc).__name__}")
            return None

    async def catch_up(self) -> None:
        """Догружает в очередь то, что пришло, пока мост не работал.

        Берём только чаты с непрочитанным и только сообщения новее последнего
        доставленного — иначе при каждом запуске приезжало бы одно и то же.
        """
        if not self.cfg.catch_up:
            return
        self._reload_roster()          # отметки «доставлено» берём свежими
        total = 0
        for contact in self._roster:
            if (contact.last_ts <= 0
                    or self._unread.get((contact.peer_id, contact.topic_id), 0) <= 0):
                continue
            try:
                missed = await self.telegram.missed(contact.peer_id, contact.last_ts,
                                                    self.cfg.offline_queue_per_chat,
                                                    contact.topic_id)
            except Exception:
                log.exception("не удалось догрузить чат %r", contact.title)
                continue
            for ts, sender, text in missed:
                if sender:
                    text = f"{sender}: {text}"
                if self.cfg.emoji_to_text:
                    text = emoji.to_text(text)
                self.storage.queue(contact.uin, text, self.cfg.offline_queue_per_chat,
                                   ts=ts)
                self.storage.note_delivered(contact.peer_id, ts, contact.topic_id)
                total += 1
        if total:
            log.info("догружено %d пропущенных сообщений", total)

    async def run_command(self, contact: Contact, command: history.Command) -> None:
        """Выполняет команду, набранную в окне чата на телефоне."""
        if command.name == "help":
            await self.reply(contact, history.HELP)
            return
        if command.error:
            await self.reply(contact, command.error)
            return

        if command.name == "fav":
            await self.toggle_favourite(contact)
            return

        if command.name == "photo":
            await self.send_photos(contact, command.count or 1)
            return

        if command.name == "render":
            await self.send_render(contact, command.count)
            return

        since = None if command.count else history.since_midnight()
        cap = self.cfg.history_limit
        try:
            items = await self.telegram.history(contact.peer_id, command.count, since, cap,
                                                contact.topic_id)
        except Exception:
            log.exception("не удалось получить историю чата %r", contact.title)
            await self.reply(contact, "Не получилось загрузить историю")
            return

        if not items:
            await self.reply(contact, "За сегодня сообщений нет" if since
                             else "Сообщений нет")
            return

        if self.cfg.emoji_to_text:
            items = [history.HistoryItem(i.when, i.who, emoji.to_text(i.text))
                     for i in items]

        blocks = history.format_items(items, self.cfg.max_message_chars)
        log.info("история %r: %d сообщений в %d частях", contact.title,
                 len(items), len(blocks))
        for block in blocks:
            await self.oscar.deliver(contact.uin, block, forced=True)
        if len(items) >= cap:
            await self.reply(contact, f"Показаны последние {cap} — это предел (history_limit)")

    async def toggle_favourite(self, contact: Contact) -> None:
        """Команда !fav: помечает чат избранным или снимает отметку."""
        value = self.storage.toggle_favourite(contact.uin)
        if value is None:
            await self.reply(contact, "Этот чат мне неизвестен")
            return
        self._reload_roster()

        if contact.kind in ("user", "bot"):
            note = " (на личные чаты это не влияет — они приходят всегда)"
        else:
            note = (" — сообщения будут приходить и в статусе «в сети»" if value
                    else " — в статусе «в сети» сообщения приходить не будут")
        await self.reply(contact,
                         f"{contact.title}: {'в избранном' if value else 'не в избранном'}{note}")
        log.info("чат %r %s избранным", contact.title, "стал" if value else "перестал быть")

    async def send_photos(self, contact: Contact, count: int) -> None:
        """Отдаёт последние фотографии чата ссылками на свой мини-сервер."""
        if self.photos is None or self.photo_server is None:
            await self.reply(contact, "Передача фото выключена в настройках моста")
            return

        count = min(count, self.cfg.photos_per_request)
        photos = await self.telegram.last_photos(contact.peer_id, count, contact.topic_id)
        if not photos:
            await self.reply(contact, "Фотографий в этом чате нет")
            return

        sent = 0
        for raw, caption in photos:
            photo = self.photos.convert(raw, caption)
            if photo is None:
                continue
            link = self.photo_url(photo.token)
            line = f"{link} ({photo.size // 1024 or 1} КБ)"
            if caption:
                text = emoji.to_text(caption) if self.cfg.emoji_to_text else caption
                line = f"{text}\n{line}"
            await self.oscar.deliver(contact.uin, line, forced=True, url=link)
            sent += 1
        if not sent:
            await self.reply(contact, "Не получилось подготовить фото")

    async def send_render(self, contact: Contact, count: int | None) -> None:
        """Команда !render: собирает переписку в страницу для браузера телефона.

        Как и !last, без числа берёт сегодняшние сообщения, с числом — столько
        последних. Ссылка одна на всю страницу и живёт ограниченное время.
        """
        if self.render is None or self.photo_server is None:
            await self.reply(contact, "Сборка страницы выключена в настройках моста")
            return

        cap = self.cfg.render_messages
        if count and count > cap:
            await self.reply(contact, f"Больше {cap} сообщений за раз не соберу (render.messages)")
            count = cap
        since = None if count else history.since_midnight()
        try:
            rows = await self.telegram.render_items(
                contact.peer_id, count, since, cap, contact.topic_id,
                self.cfg.render_source_max_mb * 1024 * 1024)
        except Exception:
            log.exception("не удалось собрать сообщения чата %r", contact.title)
            await self.reply(contact, "Не получилось загрузить сообщения")
            return

        if not rows:
            await self.reply(contact, "За сегодня сообщений нет" if since
                             else "Сообщений нет")
            return

        items = [Item(when=r["when"], who=r["who"],
                      text=emoji.to_text(r["text"]) if self.cfg.emoji_to_text else r["text"],
                      mine=r["mine"], kind=r["kind"], raw=r.get("raw"),
                      fetch=r.get("fetch"), seconds=r["seconds"], name=r["name"])
                 for r in rows]
        attachments = sum(1 for i in items if i.kind)
        await self.reply(contact, f"Собираю {len(items)} сообщений"
                         + (f", вложений {attachments} — это займёт время…"
                            if attachments else "…"))

        last_note = time.time()

        async def progress(done: int, total: int) -> None:
            # На GPRS минуты тишины пугают — но и трещать на каждое вложение
            # незачем: отчёт не чаще раза в двадцать секунд.
            nonlocal last_note
            if done < total and time.time() - last_note > 20:
                last_note = time.time()
                await self.reply(contact, f"Готово {done} из {total} вложений…")

        page = await self.render.build(contact.title, items, progress)
        if page is None:
            await self.reply(contact, "Не получилось собрать страницу")
            return

        minutes = self.cfg.render_ttl_minutes
        note = f", ссылка живёт {minutes} мин" if minutes > 0 else ""
        link = self.render_url(page.token)
        # Ссылка идёт и текстом, и отдельным полем: по полю клиент печатает
        # её своей строкой, по тексту — добавляет в меню «Открыть ссылку».
        await self.reply(contact,
                         f"{link}\n{len(items)} сообщений, "
                         f"{len(page.assets)} вложений{note}", url=link)

    def render_url(self, token: str) -> str:
        host = self.cfg.photos_public_host or self.cfg.bos_host or "127.0.0.1"
        return f"http://{host}:{self.cfg.photos_port}/r/{token}"

    def photo_url(self, token: str) -> str:
        host = self.cfg.photos_public_host or self.cfg.bos_host or "127.0.0.1"
        return f"http://{host}:{self.cfg.photos_port}/p/{token}.jpg"

    async def reply(self, contact: Contact, text: str, url: str = "") -> None:
        """Служебный ответ моста — приходит от того же контакта.

        Такие сообщения — ответ на команду с телефона, поэтому доставляются
        при любом статусе, даже в «не беспокоить».

        С непустым url ответ уходит URL-сообщением: клиент печатает ссылку
        отдельной строкой и даёт открыть её браузером телефона.
        """
        await self.oscar.deliver(contact.uin, text, forced=True, url=url)

    # --- запуск ---------------------------------------------------------

    async def run(self) -> None:
        await self.telegram.start()
        await self.refresh_roster()
        await self.catch_up()
        await self.oscar.start()
        if self.photo_server is not None:
            await self.photo_server.start()
        if self.render is not None:
            self.render.cleanup()          # осиротевшее после прошлого запуска
        self._refresh_task = asyncio.create_task(self._refresh_loop())
        log.info("мост готов, ждём подключения Jimm")
        try:
            await self.telegram.client.run_until_disconnected()
        except DEAD_SESSION as exc:
            raise RuntimeError(
                f"Telegram аннулировал сессию ({type(exc).__name__}). "
                f"Войдите заново: ./run.py login\n"
                f"Если это повторяется через минуту после каждого входа — дело в чужих "
                f"публично известных ключах (например, api_id 2899 из telegram-cli): "
                f"Telegram гасит созданные с ними сессии. "
                f"Получите свои api_id/api_hash на my.telegram.org и впишите в config.toml."
            ) from exc

    async def close(self) -> None:
        # Порядок важен: сначала перестаём принимать и отдавать, и только
        # потом закрываем базу — иначе уходящая сессия обратится к ней уже
        # закрытой.
        if self._refresh_task is not None:
            self._refresh_task.cancel()
        for task in self._typing.values():
            task.cancel()
        self._typing.clear()
        if self.photo_server is not None:
            await self.photo_server.stop()
        await self.oscar.stop()
        await self.telegram.stop()
        self.storage.close()
