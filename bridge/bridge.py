"""Склейка двух сторон: контакт-лист, маршрутизация сообщений в обе стороны."""

from __future__ import annotations

import asyncio
import logging
import os
import time

from telethon import errors

from . import avatars as avatar_lib
from .assistant import ASSISTANT_PEER, Assistant, AssistantError
from . import emoji, history, policy
from .access import AccessControl
from . import photos
from .photos import PhotoStore
from . import profiles
from .render import Item, RenderStore, Transcoder
from .webserver import PhotoServer
from .config import Config
from .db import Contact, Storage, limit_contacts
from .oscar import const as C
from .oscar.server import OscarServer
from .tg.client import GENERAL_TOPIC, KIND_TITLES, TelegramSide
from .max.client import MaxSide, is_max_peer

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
MAX_ROSTER_SLOTS = 100_000       # чаты MAX стоят в списке раньше любого чата Telegram
SEARCH_LIMIT = 10                # столько результатов отдаём телефону
TG_RETRY_START = 5               # через сколько поднимать связь с Telegram
TG_RETRY_MAX = 300               # и когда сдаваться, чтобы мост перезапустила служба
SEARCH_ALL_LIMIT = 50            # а столько — на поиск без запроса, «покажи всё»
CATCH_UP_AT_ONCE = 6             # столько чатов разом догружаем при старте
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
        # Вторая сеть: чаты MAX живут в той же базе под своими номерами и
        # ходят через те же обработчики — по номеру видно, чьё сообщение.
        self.max: MaxSide | None = None
        if cfg.max_enabled:
            try:
                import pymax  # noqa: F401
            except ImportError as exc:
                raise RuntimeError(
                    "Для MAX нужна библиотека maxapi-python: "
                    ".venv/bin/python -m pip install -r requirements.txt") from exc
            if not cfg.max_phone:
                raise RuntimeError("Для MAX укажите phone в секции [max]")
            self.max = MaxSide(cfg, self.on_telegram_message, self.on_telegram_status,
                               self.on_telegram_typing, self.on_telegram_read)
        self.oscar = OscarServer(cfg, self.storage, self.on_phone_message,
                                 self.roster, self.status_of, self.chat_info,
                                 self.search_chats, self.verdict_for,
                                 self.on_phone_remove, self.on_phone_privacy,
                                 self.avatar, self.icon_hash, self.fetch_attachment,
                                 self.fetch_history, self.fetch_video, self.send_camera_photo,
                                 self.fetch_voice, self.send_voice_message,
                                 self.send_video_note, self._reload_roster,
                                 self.fetch_file, self.send_document,
                                 self.chat_list, self.open_chat)
        self._roster: list[Contact] = []
        self._statuses: dict[int, int] = {}   # реальные статусы из Telegram
        self._shown: dict[int, int] = {}      # что сейчас показано на телефоне
        self._by_uin: dict[int, Contact] = {}
        self._unread: dict[tuple[int, int], int] = {}   # (peer_id, topic_id)
        self._typing: dict[int, asyncio.Task] = {}
        self._typing_sent: dict[int, float] = {}   # когда телефону ушло «печатает»
        self._refresh_task: asyncio.Task | None = None
        self._background: set[asyncio.Task] = set()
        self.mode = policy.UNMUTED
        self._stopping = False
        self.oscar.on_owner_status = self.on_owner_status
        self.oscar.on_typing = self.on_phone_typing
        self.avatars = (avatar_lib.AvatarStore(cfg.avatar_size, cfg.avatar_max_kb * 1024)
                        if cfg.avatars else None)
        self.photos: PhotoStore | None = None
        self.photo_server: PhotoServer | None = None
        self.render: RenderStore | None = None
        self.assistant: Assistant | None = None
        if cfg.assistant_enabled:
            # Сеансы claude лежат в ~/.claude по рабочему каталогу — держим
            # ему свой, чтобы разговор продолжался и не цеплял чужих CLAUDE.md.
            os.makedirs(cfg.assistant_workdir, exist_ok=True)
            self.assistant = Assistant(
                cfg.assistant_command, cfg.assistant_workdir, cfg.assistant_model,
                cfg.assistant_effort, cfg.assistant_system, cfg.assistant_tools,
                cfg.assistant_args, cfg.assistant_timeout, cfg.assistant_session_hours)
            if not self.assistant.available:
                log.warning("контакт «%s» включён, но программа %r не найдена — "
                            "поставьте Claude Code и войдите под пользователем моста",
                            cfg.assistant_title, cfg.assistant_command)
        if cfg.render_enabled and cfg.photos_enabled:
            self.render = RenderStore(
                cfg.render_dir,
                Transcoder(cfg.render_ffmpeg, cfg.render_video_seconds,
                           cfg.render_audio_seconds, cfg.render_timeout,
                           cfg.render_dir, cfg.render_video_codec,
                           cfg.render_video_kbps, cfg.render_video_fps),
                cfg.render_ttl_minutes, cfg.photo_width, cfg.photo_height,
                cfg.photo_max_kb * 1024, cfg.render_encoding, cfg.render_path,
                lambda: self.storage.next_seq("render"), cfg.render_index,
                cfg.render_page_max_kb * 1024)
        if cfg.photos_enabled:
            self.photos = PhotoStore(cfg.photos_dir, cfg.photo_width, cfg.photo_height,
                                     cfg.photo_max_kb * 1024, cfg.photo_keep_hours)
            self.photo_server = PhotoServer(self.photos, cfg.photos_host, cfg.photos_port,
                                            AccessControl(
                                                allow_from=cfg.allow_from,
                                                max_connections=cfg.max_connections),
                                            render=self.render,
                                            password=cfg.photos_password,
                                            downloads_dir=cfg.downloads_dir,
                                            downloads_protected=cfg.downloads_protected,
                                            client_dir=os.path.join(
                                                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                "telemotomax", "dist"))

    # --- контакт-лист ---------------------------------------------------

    def roster(self) -> list[Contact]:
        return self._roster

    def side_for(self, peer_id: int):
        """Сеть, которой принадлежит чат: по номеру видно, MAX это или Telegram."""
        if self.max is not None and is_max_peer(peer_id):
            return self.max
        return self.telegram

    def network_of(self, peer_id: int) -> str:
        return "MAX" if self.max is not None and is_max_peer(peer_id) else "Telegram"

    async def topic_title(self, peer_id: int, topic_id: int) -> str:
        """Название темы форума — если сторона сети умеет его узнать."""
        ask = getattr(self.side_for(peer_id), "topic_title", None)
        if ask is None:
            return ""
        try:
            return (await ask(peer_id, topic_id)) or ""
        except Exception:
            log.debug("название темы %s не получено", topic_id, exc_info=True)
            return ""

    def group_for(self, peer_id: int, kind: str) -> str:
        """Группа для чата, впервые пришедшего сообщением или найденного поиском."""
        if self.max is not None and is_max_peer(peer_id):
            return self.cfg.max_group
        return KIND_TITLES.get(kind, "Чаты")

    def _reload_roster(self) -> None:
        """Перечитывает контакт-лист из базы — всегда с roster_limit.

        Без ограничения телефон при следующем входе получил бы все чаты
        разом, а индекс по UIN разошёлся бы со списком.
        """
        since = 0
        if self.cfg.background_groups and self.cfg.background_hours > 0:
            since = int(time.time()) - self.cfg.background_hours * 3600
        everyone = self.storage.contacts()
        # У каждой сети своё ограничение: чатов в MAX обычно мало, и общий
        # потолок с Telegram их бы просто вытеснил.
        from_max = [c for c in everyone if self.max is not None and is_max_peer(c.peer_id)]
        rest = [c for c in everyone if c not in from_max]
        roster = (limit_contacts(rest, self.tmm("roster_limit"), self.cfg.background_groups, since)
                  + limit_contacts(from_max, self.cfg.max_roster_limit,
                                   self.cfg.background_groups, since))
        self._roster = sorted(roster, key=lambda c: (c.position, c.uin))
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

    def _mark(self, contact: Contact) -> str:
        """Название с пометкой сети: [T] — Telegram, [M] — MAX."""
        return ("[M] " if self.network_of(contact.peer_id) == "MAX" else "[T] ") + contact.title

    def _quiet_days(self, contact: Contact) -> int:
        """Сколько дней в чате тихо; -1 — сообщений не было вовсе."""
        if not contact.last_ts:
            return -1
        return max(0, int((time.time() - contact.last_ts) // 86400))

    async def chat_list(self) -> list[tuple[int, str, bool, int, bool]]:
        """Все чаты для отдельного экрана TeleMotoMax — и те, что в
        контакт-листе, и те, что в него не влезли или были убраны.

        Ради этого экрана список и заводился: чат, в который давно не
        писали, с телефона иначе не открыть."""
        in_list = {c.uin for c in self._roster}
        rows = []
        for contact in self.storage.contacts_all():
            if contact.peer_id == ASSISTANT_PEER:
                continue
            rows.append((contact.uin, contact.title,
                         self.network_of(contact.peer_id) == "MAX",
                         self._quiet_days(contact), contact.uin in in_list))
        rows.sort(key=lambda row: row[1].lower())
        log.info("список чатов для телефона: %d, из них в контакт-листе %d",
                 len(rows), sum(1 for row in rows if row[4]))
        return rows

    async def open_chat(self, uin: int) -> bool:
        """Вернуть чат на телефон: снять скрытие и показать последнее
        сообщение — тогда переписка появится в клиенте и в неё можно писать."""
        contact = self.storage.contact_by_uin(uin)
        if contact is None:
            return False
        if contact.hidden:
            self.storage.set_hidden(uin, False)
        # Мало снять скрытие: чат, в который давно не писали, стоит в конце
        # списка и в roster_limit не влезет — поднимаем его наверх.
        self.storage.raise_contact(uin)
        self._reload_roster()
        await self.refresh_shown_statuses()
        got = await self.fetch_history(uin, 1)
        rows = got[0] if got else []
        last = rows[0][0] if rows else ""
        contact = self.storage.contact_by_uin(uin) or contact
        await self.reply(contact, last or "— чат открыт, сообщений пока не было —")
        log.info("чат «%s» открыт с телефона", contact.title)
        return True

    async def search_chats(self, query: str) -> list[dict]:
        """Поиск из Jimm: сначала по уже известным чатам, потом по Telegram.

        Пустой запрос (или «*») — это «покажи всё»: обычный Jimm листает
        выдачу по одной карточке, но иначе до забытого чата с него не
        добраться. У TeleMotoMax для этого есть отдельный экран списком."""
        needle = query.strip().lower()
        if needle in ("", "*", "все", "all"):
            rows = await self.chat_list()
            found = [{"uin": uin, "title": ("[M] " if is_max else "[T] ") + title,
                      "kind": ("молчит %d дн." % days) if days > 0 else
                              ("сегодня" if days == 0 else "без сообщений"),
                      "username": ""}
                     for uin, title, is_max, days, _ in rows]
            log.info("поиск без запроса: отдаю %d чатов из %d",
                     min(len(found), SEARCH_ALL_LIMIT), len(found))
            return found[:SEARCH_ALL_LIMIT]
        found = [
            {"uin": c.uin, "title": self._mark(c),
             "kind": KIND_TITLES.get(c.kind, "Чат"), "username": ""}
            for c in self.storage.contacts() if needle in c.title.lower()
        ][:SEARCH_LIMIT]
        if found:
            return found

        # Поиск возвращает и убранные ранее: нашли — значит снова нужны.
        for contact in self.storage.contacts_all():
            if contact.hidden and needle in contact.title.lower():
                self.storage.set_hidden(contact.uin, False)
                found.append({"uin": contact.uin, "title": self._mark(contact),
                              "kind": KIND_TITLES.get(contact.kind, "Чат"),
                              "username": ""})
        if found:
            self._reload_roster()
            return found[:SEARCH_LIMIT]

        items = await self.telegram.search_chats(query, SEARCH_LIMIT)
        if self.max is not None:
            items += await self.max.search_chats(query, SEARCH_LIMIT)
        for item in items[:SEARCH_LIMIT]:
            known = self.storage.contact_by_peer(item["peer_id"])
            if known is not None:
                # Чат уже есть — его группу, позицию и мьют трогать нельзя.
                uin = known.uin
            else:
                uin = self.storage.uin_for_peer(
                    item["peer_id"], kind=item["kind"], title=item["title"],
                    group_name=self.group_for(item["peer_id"], item["kind"]), position=9999)
            mark = "[M] " if self.network_of(item["peer_id"]) == "MAX" else "[T] "
            found.append({"uin": uin, "title": mark + item["title"],
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
        if contact.peer_id == ASSISTANT_PEER:
            return {"title": contact.title, "kind": "Бот", "username": "", "phone": "",
                    "members": "", "marks": "", "network": "Claude Code",
                    "about": ("Claude Code с этой машины. Пишите как обычно; "
                              "!reset — начать разговор заново.")}
        try:
            info = await self.side_for(contact.peer_id).chat_info(contact.peer_id)
        except Exception:
            log.exception("карточка «%s»: сторона %s не ответила", contact.title,
                          self.network_of(contact.peer_id))
            info = None
        if info is None:
            # Подробностей нет — покажем хотя бы то, что знаем сами.
            log.info("карточка «%s»: подробностей от %s нет, отдаю своё",
                     contact.title, self.network_of(contact.peer_id))
            info = {"title": contact.title,
                    "kind": KIND_TITLES.get(contact.kind, "Чат"),
                    "username": "", "phone": "", "members": "", "about": ""}
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
            # Поле «организация» в карточке — сеть, откуда чат.
            info.setdefault("network", self.network_of(contact.peer_id))
        return info

    def tmm(self, key: str):
        """Настройка [telemotomax] с учётом профиля телефона, который сейчас
        подключён: photo_width, video_seconds, voice_kbps и т. п."""
        oscar = getattr(self, "oscar", None)
        session = oscar.session if oscar is not None else None
        if session is not None:
            # Что владелец выбрал в настройках телефона («Медиа») — важнее
            # профиля: он видит результат на своём экране, а профиль — общая
            # прикидка по модели.
            media = getattr(session, "media", None)
            if media and key in media:
                return media[key]
            if session.profile and key in session.profile:
                return session.profile[key]
        return getattr(self.cfg, profiles.KEYS.get(key, "tmm_" + key))

    async def fetch_attachment(self, uin: int, attach: str, rotate: str = "auto") -> bytes | None:
        """Снимок из сообщения для TeleMotoMax — ужатый под экран телефона;
        rotate — класть ли боком (флаги запроса, как у ролика).

        Достаётся только когда клиент за ним пришёл: пометка [фото] в тексте
        ничего не стоит, а сам снимок — трафик на GPRS."""
        contact = self.storage.contact_by_uin(uin)
        kind, _, ident = attach.partition(":")
        if contact is None or kind not in ("photo", "video") or not ident.isdigit():
            return None
        raw = await self.side_for(contact.peer_id).photo_bytes(contact.peer_id, int(ident))
        if not raw:
            return None
        got = photos.shrink(raw, self.tmm("photo_width"), self.tmm("photo_height"),
                            self.tmm("photo_max_kb") * 1024, self.tmm("photo_quality"), rotate)
        if got is None:
            return None
        data, width, height = got
        log.info("%s для «%s» ужат до %d×%d, %d байт", "кадр видео" if kind == "video" else "снимок",
                 contact.title, width, height, len(data))
        return data

    def _video_kbps(self, seconds: int) -> int:
        """Битрейт ролика с оглядкой на предел размера: клип целиком лежит
        в куче телефона, и на V3 32 КБ уже кончались OutOfMemoryError."""
        kbps = self.tmm("video_kbps")
        limit_kb = self.tmm("video_max_kb")
        if limit_kb and seconds > 0:
            # 8 кбит на килобайт; часть места съест звук и заголовки — берём
            # с запасом в четверть.
            fit = int(limit_kb * 8 / seconds * 0.75)
            if fit < kbps:
                kbps = max(8, fit)
        return kbps

    def _transcoder(self, seconds: int) -> "Transcoder":
        """Перекодировщик с теми же кодеками, что у страницы !render."""
        return Transcoder(self.cfg.render_ffmpeg, seconds,
                          self.cfg.render_audio_seconds, self.cfg.render_timeout,
                          self.cfg.render_dir, self.cfg.render_video_codec,
                          self._video_kbps(seconds), self.cfg.render_video_fps,
                          self.tmm("voice_kbps"),
                          (self.tmm("video_width"), self.tmm("video_height")),
                          self.tmm("video_rotate"))

    async def fetch_voice(self, uin: int, attach: str) -> bytes | None:
        """Голосовое из сообщения — AMR в 3GP, который телефон умеет играть."""
        contact = self.storage.contact_by_uin(uin)
        kind, _, ident = attach.partition(":")
        if contact is None or kind != "voice" or not ident.isdigit():
            return None
        transcoder = self._transcoder(self.tmm("voice_seconds"))
        if not transcoder.available:
            log.warning("голосовое для «%s»: ffmpeg %r не найден",
                        contact.title, self.cfg.render_ffmpeg)
            return None
        raw = await self.side_for(contact.peer_id).voice_bytes(
            contact.peer_id, int(ident), self.cfg.render_source_max_mb * 1024 * 1024)
        if not raw:
            return None
        os.makedirs(self.cfg.render_dir, exist_ok=True)
        data = await transcoder.convert(raw, "voice")
        if data:
            log.info("голосовое для «%s»: %d КБ", contact.title, len(data) // 1024)
        return data

    async def send_voice_message(self, uin: int, data: bytes, seconds: int) -> bool:
        """Записанное на телефоне голосовое — в чат. True, если ушло.

        Телефон пишет в своём формате (обычно AMR); в Telegram и MAX
        голосовое — это OGG, поэтому перекодируем. Не вышло — отправляем
        записанное как обычный звуковой файл, чтобы не потерять его."""
        contact = self.storage.contact_by_uin(uin)
        if contact is None or contact.peer_id == ASSISTANT_PEER:
            return False
        transcoder = self._transcoder(self.tmm("voice_seconds"))
        ogg = await transcoder.to_ogg(data) if transcoder.available else None
        if ogg is None:
            log.warning("голосовое не перекодировалось в OGG — отправляю файлом; "
                        "в чате это будет вложение, а не голосовое")
        try:
            message_id = await self.side_for(contact.peer_id).send_voice(
                contact.peer_id, ogg or data, seconds, voice=ogg is not None,
                topic_id=contact.topic_id)
        except Exception as exc:
            log.exception("голосовое в чат «%s» не ушло", contact.title)
            await self.reply(contact, f"Голосовое не отправлено: {type(exc).__name__}")
            return False
        log.info("голосовое с телефона → «%s»: %d с, %d КБ, номер %s",
                 contact.title, seconds, len(ogg or data) // 1024, message_id)
        # Своё голосовое телефон в переписке не показывает — скажем сами,
        # иначе после отправки в окне чата пусто и непонятно, ушло ли.
        await self.reply(contact, f"[голосовое {seconds // 60}:{seconds % 60:02d}] отправлено"
                                  + ("" if ogg else " (файлом)"))
        return True

    async def send_video_note(self, uin: int, data: bytes, seconds: int) -> bool:
        """«Кружок», снятый камерой телефона, — в чат. True, если ушёл.

        Телефон пишет 3GP (H.263 + AMR); кружок в Telegram и MAX — квадратный
        MP4 с H.264, поэтому перекодируем. Нет H.264 в ffmpeg или не вышло —
        отправляем как обычное видео, чтобы запись не пропала."""
        contact = self.storage.contact_by_uin(uin)
        if contact is None or contact.peer_id == ASSISTANT_PEER:
            return False
        transcoder = self._transcoder(max(seconds, 1) + 1)
        mp4 = await transcoder.to_note(data) if transcoder.available else None
        if mp4 is None:
            log.warning("кружок не перекодировался в MP4/H.264 — отправляю обычным видео")
        try:
            message_id = await self.side_for(contact.peer_id).send_video(
                contact.peer_id, mp4 or data, seconds, note=mp4 is not None,
                topic_id=contact.topic_id)
        except Exception as exc:
            log.exception("кружок в чат «%s» не ушёл", contact.title)
            await self.reply(contact, f"Кружок не отправлен: {type(exc).__name__}")
            return False
        log.info("кружок с телефона → «%s»: %d с, %d КБ, номер %s",
                 contact.title, seconds, len(mp4 or data) // 1024, message_id)
        await self.reply(contact, f"[кружок {seconds // 60}:{seconds % 60:02d}] отправлен"
                                  + ("" if mp4 else " (обычным видео)"))
        return True

    async def fetch_file(self, uin: int, attach: str) -> tuple[str, bytes] | None:
        """Документ из сообщения — имя и содержимое, как есть, не больше
        file_max_mb профиля телефона."""
        contact = self.storage.contact_by_uin(uin)
        kind, _, ident = attach.partition(":")
        if contact is None or kind != "file" or not ident.isdigit():
            return None
        limit = int(self.tmm("file_max_mb")) * 1024 * 1024
        got = await self.side_for(contact.peer_id).file_bytes(contact.peer_id, int(ident), limit)
        if not got:
            return None
        name, data = got
        log.info("файл «%s» из «%s»: %d КБ", name, contact.title, len(data) // 1024)
        return name, data

    async def send_document(self, uin: int, path: str, name: str, kind: int = 0) -> bool:
        """Файл с телефона (лежит на диске моста) — в чат: документом, а с
        видом 1 — фотографией, 2 — видео. Так в чат попадают снимок
        1200×1600 и ролик, снятые штатной камерой телефона: из Java на V8
        больше 480×640 не снять, а файл с карты — любого размера."""
        contact = self.storage.contact_by_uin(uin)
        if contact is None or contact.peer_id == ASSISTANT_PEER:
            return False
        what = "файл"
        try:
            size = os.path.getsize(path)
            side = self.side_for(contact.peer_id)
            if kind == 1:
                with open(path, "rb") as fh:
                    data = fh.read()
                if data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n":
                    what = "фото"
                    message_id = await side.send_photo(contact.peer_id, data, topic_id=contact.topic_id)
                else:
                    log.warning("«%s» просили отправить фотографией, но это не JPEG/PNG — документом", name)
                    kind = 0
            elif kind == 2:
                with open(path, "rb") as fh:
                    data = fh.read()
                transcoder = self._transcoder(self.tmm("video_seconds"))
                mp4 = await transcoder.to_mp4(data) if transcoder.available else None
                if mp4 is None:
                    log.warning("видео «%s» не перекодировалось в MP4/H.264 — отправляю как есть", name)
                what = "видео"
                message_id = await side.send_video(
                    contact.peer_id, mp4 or data, 0, note=False, topic_id=contact.topic_id,
                    name=(os.path.splitext(name)[0] + ".mp4") if mp4 else name)
                size = len(mp4 or data)
            if kind == 0:
                message_id = await side.send_document(
                    contact.peer_id, path, name, topic_id=contact.topic_id)
        except Exception as exc:
            log.exception("%s «%s» в чат «%s» не ушёл", what, name, contact.title)
            await self.reply(contact, f"{what.capitalize()} не отправлен{'о' if what != 'файл' else ''}: {type(exc).__name__}")
            return False
        log.info("%s «%s» с телефона → «%s»: %d КБ, номер %s",
                 what, name, contact.title, size // 1024, message_id)
        await self.reply(contact, f"[{what} {name}, {max(1, size // 1024)} КБ] отправлен"
                                  + ("о" if what != "файл" else ""))
        return True

    @staticmethod
    def jpeg_size(data: bytes) -> str:
        """«640x480» по заголовку JPEG (SOF), без раскодирования; «?» если
        заголовок не нашёлся. Нужен в журнале: телефон может отдать не тот
        размер, что просили в настройках, — по нему и разбираться."""
        i = 2
        try:
            while i + 9 < len(data):
                if data[i] != 0xFF:
                    i += 1
                    continue
                m = data[i + 1]
                if m == 0xFF:
                    i += 1
                    continue
                if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
                    i += 2
                    continue
                if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
                    h = (data[i + 5] << 8) | data[i + 6]
                    w = (data[i + 7] << 8) | data[i + 8]
                    return f"{w}x{h}"
                i += 2 + ((data[i + 2] << 8) | data[i + 3])
        except IndexError:
            pass
        return "?"

    async def send_camera_photo(self, uin: int, data: bytes) -> bool:
        """Снимок с камеры телефона — в чат. True, если ушёл."""
        contact = self.storage.contact_by_uin(uin)
        if contact is None or contact.peer_id == ASSISTANT_PEER:
            return False
        try:
            message_id = await self.side_for(contact.peer_id).send_photo(
                contact.peer_id, data, topic_id=contact.topic_id)
        except Exception as exc:
            log.exception("снимок в чат «%s» не ушёл", contact.title)
            await self.reply(contact, f"Снимок не отправлен: {type(exc).__name__}")
            return False
        log.info("снимок с камеры → «%s»: %s, %d КБ, номер %s",
                 contact.title, self.jpeg_size(data), len(data) // 1024, message_id)
        await self.reply(contact, "[фото] отправлено")
        return True

    async def fetch_video(self, uin: int, attach: str, rotate: str = "auto",
                          segment: int = 0) -> bytes | None:
        """Кусок ролика для TeleMotoMax — 3GP под плеер телефона.

        Ролик качается и перекодируется только по запросу клиента; тем же
        ffmpeg и с тем же кодеком, что страница !render, но короче. segment —
        какой кусок по счёту: телефон смотрит длинный ролик по video_seconds
        и просит следующий кнопкой «Дальше»."""
        contact = self.storage.contact_by_uin(uin)
        kind, _, ident = attach.partition(":")
        if contact is None or kind != "video" or not ident.isdigit():
            return None
        if self.tmm("video_seconds") <= 0:
            return None
        transcoder = self._transcoder(self.tmm("video_seconds"))
        if not transcoder.available:
            log.warning("ролик для «%s»: ffmpeg %r не найден", contact.title, self.cfg.render_ffmpeg)
            return None
        raw = await self.side_for(contact.peer_id).video_bytes(
            contact.peer_id, int(ident), self.cfg.render_source_max_mb * 1024 * 1024)
        if not raw:
            return None
        os.makedirs(self.cfg.render_dir, exist_ok=True)
        # Боком или нет: «always»/«never» — как сказал телефон; «auto» —
        # только если профиль это разрешает и исходник широкий (портретный
        # ролик или кружок на вертикальном экране и так смотрятся как надо).
        if rotate == "always":
            transcoder.video_rotate = True
        elif rotate == "never":
            transcoder.video_rotate = False
        elif transcoder.video_rotate:
            size = await transcoder.probe_size(raw)
            transcoder.video_rotate = bool(size and size[0] > size[1])
            log.info("ролик для «%s»: исходник %s — %s", contact.title,
                     f"{size[0]}×{size[1]}" if size else "размер неизвестен",
                     "широкий, кладу боком" if transcoder.video_rotate else "боком не кладу")
        seconds = self.tmm("video_seconds")
        start = max(0, int(segment)) * seconds
        data = await transcoder.convert(raw, "video", start=start)
        if data:
            log.info("ролик для «%s» готов: %s, %d КБ", contact.title,
                     f"секунды {start}–{start + seconds}" if start else f"первые {seconds} с",
                     len(data) // 1024)
        elif start:
            log.info("ролик для «%s»: с секунды %d ничего не вышло — видимо, конец",
                     contact.title, start)
        return data

    async def fetch_history(self, uin: int, count: int,
                            offset: int = 0) -> tuple[list[tuple[str, str, bool]], bool] | None:
        """История чата для TeleMotoMax — то же, что !last, но не в переписку,
        а на отдельный экран. Каждое сообщение — строка и вложение
        («photo:<номер>» или пусто), чтобы фото из истории тоже открывались.

        offset — сколько сообщений телефон уже показал: следующая пачка
        берётся старее них. Вместе со списком возвращаем, осталось ли ещё
        что листать. Курсор именно счётчиком, а не номером сообщения: у
        Telegram это номер, у MAX — время, и общего у них нет.
        """
        contact = self.storage.contact_by_uin(uin)
        if contact is None or contact.peer_id == ASSISTANT_PEER:
            return None
        count = min(count or 20, self.cfg.history_limit)
        cap = max(self.cfg.history_limit, self.tmm("history_max"))
        # На одно сообщение больше, чем нужно: по нему и видно, осталось ли
        # что листать дальше.
        want = min(offset + count + 1, cap)
        items = await self.side_for(contact.peer_id).history(contact.peer_id, want, None, cap,
                                                             contact.topic_id)
        # items идут от старых к новым: нужное окно — то, что старее уже
        # показанных, и не длиннее пачки.
        end = max(0, len(items) - offset)
        start = max(0, end - count)
        more = start > 0
        items = items[start:end]
        out: list[tuple[str, str, bool]] = []
        for i in items:
            line = f"[{i.when.astimezone():%d.%m %H:%M}] {i.who}: {i.text}"
            if self.cfg.emoji_to_text:
                line = emoji.to_text(line)
            has_picture = i.kind in ("photo", "video", "voice", "file") and i.msg_id
            out.append((line, f"{i.kind}:{i.msg_id}" if has_picture else "", i.who == "Я"))
        log.info("история «%s» для TeleMotoMax: %d сообщений%s, с фото %d%s",
                 contact.title, len(items),
                 f" (пропущено свежих {offset})" if offset else "",
                 sum(1 for row in out if row[1]), ", есть ещё" if more else "")
        return out, more

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
        raw = await self.side_for(contact.peer_id).avatar(contact.peer_id)
        if raw is None:
            return None
        got = self.avatars.store(uin, raw)
        if got is not None:
            log.info("аватарка чата %r готова: %d байт", contact.title, len(got[1]))
        return got

    async def refresh_roster(self) -> None:
        dialogs = await self.telegram.dialogs()
        keep_max = False
        if self.max is not None:
            try:
                extra = await self.max.dialogs()
            except Exception:
                log.exception("список чатов MAX не получен — оставляю прежний")
                extra, keep_max = [], True
            # Чаты MAX — перед чатами Telegram: их немного, и roster_limit
            # не должен их отрезать; свой порядок по свежести у них остаётся.
            for d in extra:
                d.position -= MAX_ROSTER_SLOTS
            dialogs += extra
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
        present = [d.peer_id for d in dialogs]
        if keep_max:
            # MAX не ответил — его чаты не пропали, просто не проверены.
            present += [c.peer_id for c in self.storage.contacts_all() if is_max_peer(c.peer_id)]
        if self.assistant is not None:
            # Контакт Claude — не из Telegram, но в списке наравне со всеми:
            # избранный, чтобы roster_limit его не вытеснил.
            uin = self.storage.uin_for_peer(ASSISTANT_PEER, kind="bot",
                                            title=self.cfg.assistant_title,
                                            group_name=self.cfg.assistant_group,
                                            position=-1, favourite=1)
            self._statuses[uin] = C.STATUS_ONLINE
            present.append(ASSISTANT_PEER)
        # Чаты, которых больше нет в Telegram, убираем из контакт-листа.
        gone = self.storage.mark_missing(present)
        # Форум разложен на темы — отдельный контакт «всего форума» лишний.
        # Такой заводился, пока сообщения из «General» считались обычными.
        forums = {d.peer_id for d in dialogs if d.topic_id}
        gone += self.storage.mark_forum_shells(forums)
        for contact in gone:
            log.info("чат %r исчез из Telegram — убираю из списка", contact.title)
            self._statuses[contact.uin] = C.STATUS_OFFLINE
            self._shown[contact.uin] = C.STATUS_OFFLINE
            await self.oscar.notify_status(contact.uin, C.STATUS_OFFLINE)

        self._reload_roster()
        if self.avatars is not None:
            with_photo = sum(1 for c in self._roster if self.avatars.hash_of(c.uin))
            log.info("аватарки: примета есть у %d из %d чатов в списке",
                     with_photo, len(self._roster))
        total = len(self.storage.contacts())
        if (self.cfg.roster_limit or self.cfg.max_roster_limit) and total > len(self._roster):
            log.debug("в контакт-лист телефона идут %d чатов из %d (roster_limit); "
                     "остальные приходят как сообщения и находятся поиском",
                     len(self._roster), total)
            if self.cfg.background_groups:
                shown = {c.uin for c in self._roster}
                left = sum(1 for c in self.storage.contacts()
                           if c.uin not in shown
                           and c.group_name.strip().lower() in self.cfg.background_groups)
                log.debug("из фоновых групп отложено %d чатов — появятся, когда напишут",
                         left)
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
                    self.photos.cleanup()
                if self.render is not None:
                    self.render.cleanup()
            except Exception:
                log.exception("не удалось обновить контакт-лист")

    # --- маршрутизация --------------------------------------------------

    async def on_telegram_message(self, peer_id: int, sender: str, text: str,
                                  ts: int = 0, topic_id: int = 0, attach: str = "") -> bool:
        """Возвращает True, если сообщение ушло телефону (или встало в очередь).

        По этому Telegram-сторона решает, помечать ли его прочитанным:
        отброшенное по статусу телефон не видел, значит и читать его нечем.
        """
        if not text:
            return False
        contact = self.storage.contact_by_peer(peer_id, topic_id)
        if not topic_id and (contact is None or contact.gone):
            # Сообщение без темы из чата, который у нас разложен на темы, —
            # это тема «General»: её сообщения приходят без заголовка темы.
            general = self.storage.contact_by_peer(peer_id, GENERAL_TOPIC)
            if general is not None:
                contact, topic_id = general, GENERAL_TOPIC
        if contact is not None and contact.hidden:
            log.debug("чат %r убран с телефона — сообщение не доставляю", contact.title)
            if ts:
                self.storage.note_delivered(peer_id, ts, topic_id)
            return False
        if contact is None:
            title, kind = await self.side_for(peer_id).title_for(peer_id)
            if topic_id:
                # Новая тема форума: сам форум становится группой контактов,
                # название темы спрашиваем у Telegram (MAX тем не знает).
                group = title[:self.cfg.alias_max_chars]
                title = await self.topic_title(peer_id, topic_id) or f"Тема {topic_id}"
                kind = "chat"
            else:
                group = self.group_for(peer_id, kind)
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
        name = f"«{contact.title}» ({uin})" if contact else f"UIN {uin}"

        # Сообщение пришло — значит набор закончен.
        await self.stop_typing(uin)

        # Статус в Jimm решает, что доставлять, а что придержать или пропустить.
        net = self.network_of(peer_id)
        if contact is not None and not policy.allows(self.mode, contact.kind,
                                                     bool(contact.favourite),
                                                     bool(contact.muted)):
            why = (f"заглушён в {net}" if contact.muted
                   else f"режим «{policy.MODE_NAMES[self.mode]}»")
            # Отсеянных бывает много (заглушённые каналы шумят), поэтому
            # уровень этих строк выбирается настройкой.
            level = logging.INFO if self.cfg.log_filtered else logging.DEBUG
            if policy.holds(self.mode):
                self.storage.hold(uin, text, ts or int(time.time()),
                                  self.cfg.offline_queue_per_chat)
                log.log(level, "из %s: %s — придержано до смены статуса (%s)", net, name, why)
            else:
                log.log(level, "из %s: %s — не доставляю (%s)", net, name, why)
            log.debug("из %s: %s: %s", net, name, text[:300])
            if ts:
                self.storage.note_delivered(peer_id, ts, topic_id)
            return False
        log.info("из %s: %s → в очередь телефону, %d симв.%s", net, name, len(text),
                 "" if self.oscar.online else " (телефон не в сети)")
        log.debug("из %s: %s: %s", net, name, text[:300])
        await self.oscar.deliver(uin, text, ts=ts, attach=attach)
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
        log.debug("статус Telegram: «%s» теперь %s", contact.title, status)

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
            await self.stop_typing(contact.uin, "собеседник закончил")
            return
        if not policy.allows(self.mode, contact.kind, bool(contact.favourite),
                             bool(contact.muted)):
            log.debug("Telegram: в чате «%s» печатают, но чат отсеян — не показываю",
                      contact.title)
            return

        old = self._typing.pop(contact.uin, None)
        now = time.time()
        # Telegram повторяет «печатает» каждые несколько секунд. Телефону
        # каждый такой повтор — отдельное уведомление со звуком, поэтому
        # шлём начало, а продления только продлевают показ; повторять их
        # телефону можно, но не чаще, чем раз в typing_repeat секунд
        # (0 — не повторять вовсе).
        repeat = self.cfg.typing_repeat
        send = True
        if old is None:
            log.info("«%s» печатает — показываю на телефоне", contact.title)
        else:
            old.cancel()
            since = now - self._typing_sent.get(contact.uin, 0.0)
            send = repeat > 0 and since >= repeat
            log.debug("«%s» всё ещё печатает%s", contact.title,
                      "" if send else " (телефону не повторяю)")
        if send:
            self._typing_sent[contact.uin] = now
            await self.oscar.notify_typing(contact.uin, True)
        self._typing[contact.uin] = asyncio.create_task(self._typing_expiry(contact.uin))

    async def _typing_expiry(self, uin: int) -> None:
        """Снимает «печатает», если из Telegram давно ничего не приходило."""
        try:
            await asyncio.sleep(TYPING_TIMEOUT)
        except asyncio.CancelledError:
            return
        self._typing.pop(uin, None)
        self._typing_sent.pop(uin, None)
        contact = self._by_uin.get(uin) or self.storage.contact_by_uin(uin)
        log.info("«%s» перестал печатать — гашу по молчанию (%d с)",
                 contact.title if contact else uin, TYPING_TIMEOUT)
        await self.oscar.notify_typing(uin, False)

    async def stop_typing(self, uin: int, why: str = "пришло сообщение") -> None:
        """Гасит индикатор сразу — клиент сам этого не делает."""
        task = self._typing.pop(uin, None)
        self._typing_sent.pop(uin, None)
        if task is None:
            return
        task.cancel()
        contact = self._by_uin.get(uin) or self.storage.contact_by_uin(uin)
        log.info("«%s» перестал печатать — %s", contact.title if contact else uin, why)
        await self.oscar.notify_typing(uin, False)

    async def on_telegram_read(self, peer_id: int, max_id: int) -> None:
        """Собеседник прочитал наши сообщения — телефон ставит галочку."""
        contact = self.storage.contact_by_peer(peer_id)
        if contact is not None:
            log.debug("Telegram: в чате «%s» прочитано до %d", contact.title, max_id)
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
        if contact.peer_id == ASSISTANT_PEER or bool(contact.muted) == muted:
            return

        if not await self.side_for(contact.peer_id).set_muted(contact.peer_id, muted):
            await self.reply(contact, f"Не получилось изменить уведомления в {self.network_of(contact.peer_id)}")
            return

        self.storage.set_muted(contact.uin, muted)
        self._reload_roster()
        log.info("чат %r %s в %s", contact.title,
                 "заглушён" if muted else "снова со звуком", self.network_of(contact.peer_id))

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
        if contact.peer_id == ASSISTANT_PEER:
            await self.reply(contact, "Контакт Claude выключается в настройках моста, "
                                      "а не удалением контакта.")
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
        if not await self.side_for(contact.peer_id).delete_chat(contact.peer_id, revoke):
            await self.reply(contact, f"Не получилось удалить чат в {self.network_of(contact.peer_id)}")
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
        if contact is not None and contact.peer_id != ASSISTANT_PEER:
            log.info("телефон %s в чате «%s»", "печатает" if active else "перестал печатать",
                     contact.title)
            await self.side_for(contact.peer_id).set_typing(contact.peer_id, active)

    async def on_phone_message(self, uin: int, text: str) -> int | None:
        """Возвращает номер отправленного сообщения в Telegram либо None."""
        contact = self.storage.contact_by_uin(uin)
        if contact is None:
            log.warning("сообщение на неизвестный UIN %d", uin)
            return None

        if contact.peer_id == ASSISTANT_PEER:
            # Галочку телефону — сразу, ответ придёт отдельным сообщением,
            # когда Claude закончит думать.
            task = asyncio.create_task(self.ask_assistant(contact, text))
            self._background.add(task)
            task.add_done_callback(self._background.discard)
            return -1

        command = history.parse(text)
        if command is not None:
            await self.run_command(contact, command)
            return -1          # команда обработана, номера сообщения нет
        if self.cfg.text_to_emoji:
            text = emoji.to_emoji(text)
        try:
            message_id = await self.side_for(contact.peer_id).send(contact.peer_id, text, contact.topic_id)
            log.info("-> %s: %d симв.", contact.title, len(text))
            log.debug("-> %s: %s", contact.title, text[:200])
            return message_id
        except errors.FloodWaitError as exc:
            log.warning("Telegram просит подождать %d с (чат %r)", exc.seconds, contact.title)
            await self.reply(contact, f"Не отправлено: Telegram просит подождать {exc.seconds} с")
            return None
        except Exception as exc:
            log.exception("не удалось отправить в чат %r", contact.title)
            await self.reply(contact, f"Не отправлено в {self.network_of(contact.peer_id)}: {type(exc).__name__}")
            return None

    async def ask_assistant(self, contact: Contact, text: str) -> None:
        """Вопрос Claude: пока он думает, на телефоне «печатает»."""
        if self.assistant is None:
            await self.reply(contact, "Контакт Claude выключен в настройках моста")
            return
        stripped = text.strip()
        if stripped.lower() in ("!reset", "!сброс"):
            self.assistant.reset()
            await self.reply(contact, "Разговор забыт, начнём заново.")
            return
        if stripped.lower() == "!help":
            await self.reply(contact, "Это Claude Code: просто пишите вопрос. "
                                      "!reset — начать разговор заново.")
            return
        if not stripped:
            return
        log.info("вопрос Claude от телефона: %d симв.", len(stripped))
        log.debug("вопрос Claude: %s", stripped[:300])
        await self.oscar.notify_typing(contact.uin, True)
        try:
            answer = await self.assistant.ask(stripped)
        except AssistantError as exc:
            log.warning("Claude не ответил: %s", exc)
            await self.oscar.notify_typing(contact.uin, False)
            await self.reply(contact, f"Claude не ответил: {exc}")
            return
        except Exception as exc:
            log.warning("Claude не ответил: %s: %s", type(exc).__name__, str(exc)[:200])
            await self.oscar.notify_typing(contact.uin, False)
            await self.reply(contact, f"Claude не ответил: {type(exc).__name__}")
            return
        await self.oscar.notify_typing(contact.uin, False)
        if self.cfg.emoji_to_text:
            answer = emoji.to_text(answer)
        log.info("ответ Claude: %d симв.", len(answer))
        log.debug("ответ Claude: %s", answer[:300])
        await self.reply(contact, answer)

    async def catch_up(self) -> None:
        """Догружает в очередь то, что пришло, пока мост не работал.

        Берём только чаты с непрочитанным и только сообщения новее последнего
        доставленного — иначе при каждом запуске приезжало бы одно и то же.
        """
        if not self.cfg.catch_up:
            return
        self._reload_roster()          # отметки «доставлено» берём свежими
        wanted = [c for c in self._roster
                  if c.last_ts > 0 and self._unread.get((c.peer_id, c.topic_id), 0) > 0]
        if not wanted:
            return
        # Чаты опрашиваются разом, по нескольку за раз: по одному это
        # секунда-другая на чат, и на десятке непрочитанных мост «поднимался»
        # почти минуту. Больше CATCH_UP_AT_ONCE сразу не просим — у Telegram
        # свои пределы на частоту запросов.
        started = time.monotonic()
        gate = asyncio.Semaphore(CATCH_UP_AT_ONCE)

        async def fetch(contact):
            async with gate:
                try:
                    return contact, await self.side_for(contact.peer_id).missed(
                        contact.peer_id, contact.last_ts,
                        self.cfg.offline_queue_per_chat, contact.topic_id)
                except Exception:
                    log.exception("не удалось догрузить чат %r", contact.title)
                    return contact, []

        total = 0
        for contact, missed in await asyncio.gather(*(fetch(c) for c in wanted)):
            for ts, sender, text in missed:
                if sender:
                    text = f"{sender}: {text}"
                if self.cfg.emoji_to_text:
                    text = emoji.to_text(text)
                self.storage.queue(contact.uin, text, self.cfg.offline_queue_per_chat,
                                   ts=ts)
                self.storage.note_delivered(contact.peer_id, ts, contact.topic_id)
                total += 1
        log.info("догружено %d пропущенных сообщений из %d чатов за %.1f с",
                 total, len(wanted), time.monotonic() - started)

    async def run_command(self, contact: Contact, command: history.Command) -> None:
        """Выполняет команду, набранную в окне чата на телефоне."""
        log.info("команда !%s%s от телефона в чате «%s»", command.name,
                 f" {command.count}" if command.count else "", contact.title)
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
            items = await self.side_for(contact.peer_id).history(contact.peer_id, command.count, since, cap,
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
        photos = await self.side_for(contact.peer_id).last_photos(contact.peer_id, count, contact.topic_id)
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
            rows = await self.side_for(contact.peer_id).render_items(
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
                      fetch=r.get("fetch"), thumb=r.get("thumb"),
                      seconds=r["seconds"], name=r["name"])
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
        link = self.web_url(page.path)
        # Ссылка идёт и текстом, и отдельным полем: по полю клиент печатает
        # её своей строкой, по тексту — добавляет в меню «Открыть ссылку».
        await self.reply(contact,
                         f"{link}\n{len(items)} сообщений, "
                         f"{len(page.assets)} вложений{note}", url=link)

    def web_url(self, path: str) -> str:
        """Полный адрес на мини-сервере: public_url, если задан, иначе хост и порт.

        При включённом пароле в ссылку добавляется токен сеанса: открывший её
        телефон пароля не вводит, а дальше страница проносит токен сама. Сам
        пароль в ссылку не попадает — он ушёл бы открытым текстом по OSCAR и
        остался бы в истории клиента.
        """
        if self.cfg.photos_public_url:
            base = self.cfg.photos_public_url
        else:
            host = self.cfg.photos_public_host or self.cfg.bos_host or "127.0.0.1"
            port = "" if self.cfg.photos_port == 80 else f":{self.cfg.photos_port}"
            base = f"http://{host}{port}"
        token = ""
        if self.cfg.photos_link_session and self.cfg.photos_password:
            token = getattr(self.photo_server, "session_token", lambda: "")()
        # Токен — в начале пути, чтобы адрес кончался расширением файла: старый
        # браузер определяет тип файла по концу адреса.
        return base + (f"/s/{token}" if token else "") + path

    def photo_url(self, token: str) -> str:
        return self.web_url(f"/p/{token}.jpg")

    async def reply(self, contact: Contact, text: str, url: str = "") -> None:
        """Служебный ответ моста — приходит от того же контакта.

        Такие сообщения — ответ на команду с телефона, поэтому доставляются
        при любом статусе, даже в «не беспокоить».

        С непустым url ответ уходит URL-сообщением: клиент печатает ссылку
        отдельной строкой и даёт открыть её браузером телефона.
        """
        log.debug("ответ телефону в чат «%s»: %s", contact.title, text[:300])
        await self.oscar.deliver(contact.uin, text, forced=True, url=url)

    # --- запуск ---------------------------------------------------------

    async def run(self) -> None:
        await self.telegram.start()
        if self.max is not None:
            await self.max.start()
        await self.refresh_roster()
        # Догрузка пропущенного идёт в своём потоке: она ходит в Telegram и
        # MAX за каждым непрочитанным чатом, и телефону незачем ждать её,
        # чтобы подключиться — накопленное он получит очередью, как обычно.
        catch_up = asyncio.create_task(self.catch_up())
        await self.oscar.start()
        if self.photo_server is not None:
            await self.photo_server.start()
        # Уборка при старте: снимки старше срока и страницы, осиротевшие после
        # прошлого запуска. Что убрали — пишут сами модули.
        if self.photos is not None:
            self.photos.cleanup()
        if self.render is not None:
            self.render.cleanup()
        self._refresh_task = asyncio.create_task(self._refresh_loop())
        self._catch_up_task = catch_up          # держим ссылку: иначе задачу соберёт сборщик
        log.info("мост готов, ждём подключения Jimm")
        try:
            await self._keep_telegram()
        except DEAD_SESSION as exc:
            raise RuntimeError(
                f"Telegram аннулировал сессию ({type(exc).__name__}). "
                f"Войдите заново: ./run.py login\n"
                f"Если это повторяется через минуту после каждого входа — дело в чужих "
                f"публично известных ключах (например, api_id 2899 из telegram-cli): "
                f"Telegram гасит созданные с ними сессии. "
                f"Получите свои api_id/api_hash на my.telegram.org и впишите в config.toml."
            ) from exc

    async def _keep_telegram(self) -> None:
        """Держит связь с Telegram, пока мост работает.

        Telethon переподключается сам, но когда сдаётся окончательно,
        `run_until_disconnected` просто возвращается — и мост раньше тихо
        заканчивал работу, будто его попросили. Поднимаем связь сами, а
        если не выходит совсем долго — выходим с ошибкой, чтобы служба
        подняла мост заново.
        """
        delay = TG_RETRY_START
        while not self._stopping:
            await self.telegram.client.run_until_disconnected()
            if self._stopping:
                return
            log.warning("Telegram отключился — пробую подключиться снова через %.0f с", delay)
            await asyncio.sleep(delay)
            try:
                await self.telegram.client.connect()
            except Exception as exc:
                log.warning("Telegram не отвечает: %s: %s", type(exc).__name__, exc)
            if self.telegram.client.is_connected():
                log.info("связь с Telegram восстановлена — догоняю пропущенное")
                delay = TG_RETRY_START
                try:
                    await self.refresh_roster()
                    await self.catch_up()
                except Exception:
                    log.exception("после обрыва не получилось обновить список и очередь")
                continue
            delay = min(delay * 2, TG_RETRY_MAX)
            if delay >= TG_RETRY_MAX:
                raise RuntimeError(
                    "Telegram не отвечает уже долго — выхожу, пусть служба поднимет мост заново")

    async def close(self) -> None:
        self._stopping = True
        # Порядок важен: сначала перестаём принимать и отдавать, и только
        # потом закрываем базу — иначе уходящая сессия обратится к ней уже
        # закрытой.
        if self._refresh_task is not None:
            self._refresh_task.cancel()
        for task in list(self._background):
            task.cancel()
        for task in self._typing.values():
            task.cancel()
        self._typing.clear()
        if self.photo_server is not None:
            await self.photo_server.stop()
        await self.oscar.stop()
        if self.max is not None:
            await self.max.stop()
        await self.telegram.stop()
        self.storage.close()
