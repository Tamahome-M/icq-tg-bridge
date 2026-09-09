"""Сторона Telegram: вход в аккаунт, построение контакт-листа из папок,
приём и отправка сообщений."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from telethon import TelegramClient, events, functions, types, utils

from ..history import HistoryItem

log = logging.getLogger("telegram")

KIND_TITLES = {
    "user": "Личные",
    "bot": "Боты",
    "chat": "Группы",
    "channel": "Каналы",
}


# Насколько давно человек был в сети, чтобы всё ещё считать его «отошёл»
RECENTLY_SECONDS = 15 * 60


@dataclass
class Dialog:
    peer_id: int
    kind: str
    title: str
    group_name: str
    position: int
    status: str = "online"
    unread: int = 0
    pinned: bool = False
    topic_id: int = 0          # тема форума; 0 — обычный чат
    muted: bool = False        # чат заглушён в Telegram


class TelegramSide:
    def __init__(self, cfg, on_message: Callable[[int, str, str, int, int], Awaitable[None]],
                 on_status: Callable[[int, str], Awaitable[None]] | None = None,
                 on_typing: Callable[[int, bool], Awaitable[None]] | None = None,
                 on_read: Callable[[int, int], Awaitable[None]] | None = None):
        self.cfg = cfg
        self.on_message = on_message
        self.on_status = on_status
        self.on_typing = on_typing
        self.on_read = on_read
        self.client = TelegramClient(
            cfg.tg_session, cfg.tg_api_id, cfg.tg_api_hash,
            device_model=cfg.tg_device_model,
            system_version=cfg.tg_system_version,
            app_version=cfg.tg_app_version,
            lang_code=cfg.tg_lang_code,
            system_lang_code=cfg.tg_lang_code,
        )
        self.me: types.User | None = None

    async def start(self) -> None:
        await self.client.connect()
        if not await self.client.is_user_authorized():
            raise RuntimeError(
                "Аккаунт Telegram не авторизован. Выполните: python3 run.py login")
        self.me = await self.client.get_me()
        log.info("вошли как %s (id=%s)", utils.get_display_name(self.me), self.me.id)
        self.client.add_event_handler(self._on_new_message, events.NewMessage(incoming=True))
        if self.on_status is not None or self.on_typing is not None:
            self.client.add_event_handler(self._on_user_update, events.UserUpdate)
        if self.on_read is not None:
            self.client.add_event_handler(self._on_read, events.MessageRead(inbox=False))

    async def login(self) -> None:
        """Интерактивный вход: телефон, код из Telegram, при необходимости пароль."""
        await self.client.start()
        me = await self.client.get_me()
        log.info("авторизация завершена: %s", utils.get_display_name(me))

    async def stop(self) -> None:
        await self.client.disconnect()

    # --- контакт-лист ---------------------------------------------------

    async def dialogs(self) -> list[Dialog]:
        folders = await self._folders() if self.cfg.grouping == "folders" else []
        if folders:
            log.info("папки Telegram (%d): %s", len(folders),
                     ", ".join(title for title, _ in folders))
        out: list[Dialog] = []
        position = 0
        async for dialog in self.client.iter_dialogs():
            entity = dialog.entity
            if isinstance(entity, types.UserFull):
                continue
            kind = self._kind(entity)
            peer_id = utils.get_peer_id(entity)
            group = self._folder_for(folders, entity, kind) or KIND_TITLES.get(kind, "Чаты")
            title = dialog.name or str(peer_id)
            pinned = bool(getattr(dialog, "pinned", False))
            muted = is_muted(dialog)
            status = status_of(entity, kind)

            # Форум — это несколько чатов в одном: каждая тема становится
            # отдельным собеседником, а сам форум — группой контакт-листа.
            topics = await self._topics(entity) if getattr(entity, "forum", False) else []
            if topics:
                for topic in topics:
                    out.append(Dialog(peer_id, "chat", topic.title or f"Тема {topic.id}",
                                      title[:self.cfg.alias_max_chars], position,
                                      status, topic.unread_count or 0, pinned,
                                      topic.id, muted))
                    position += 1
                continue

            out.append(Dialog(peer_id, kind, title, group, position,
                              status, dialog.unread_count or 0, pinned,
                              muted=muted))
            position += 1
        spread: dict[str, int] = {}
        for dialog in out:
            spread[dialog.group_name] = spread.get(dialog.group_name, 0) + 1
        log.info("получено %d чатов, групп %d: %s", len(out), len(spread),
                 ", ".join(f"{name} — {count}" for name, count in
                           sorted(spread.items(), key=lambda kv: -kv[1])))
        return out

    async def _topics(self, entity) -> list:
        """Темы форума. Пустой список — если это не форум или тем не видно."""
        try:
            result = await self.client(functions.messages.GetForumTopicsRequest(
                peer=entity, offset_date=0, offset_id=0, offset_topic=0,
                limit=self.cfg.topics_limit))
        except Exception as exc:
            log.warning("не удалось получить темы форума %s: %s",
                        utils.get_display_name(entity), type(exc).__name__)
            return []
        return [t for t in result.topics if isinstance(t, types.ForumTopic)]

    def _kind(self, entity) -> str:
        if isinstance(entity, types.User):
            return "bot" if entity.bot else "user"
        if isinstance(entity, types.Chat):
            return "chat"
        if isinstance(entity, types.Channel):
            return "chat" if entity.megagroup else "channel"
        return "chat"

    async def _folders(self) -> list[tuple[str, object]]:
        """Папки Telegram в порядке их следования у пользователя."""
        try:
            result = await self.client(functions.messages.GetDialogFiltersRequest())
        except Exception as exc:
            log.warning("не удалось получить папки (%s), группирую по типу чата", exc)
            return []
        raw = getattr(result, "filters", result)
        out = []
        for f in raw:
            title = getattr(f, "title", None)
            if title is None:                      # DialogFilterDefault — «Все чаты»
                continue
            out.append((_plain_title(title), f))
        if not out:
            log.info("папок в Telegram нет, группирую по типу чата")
        return out

    def _folder_for(self, folders, entity, kind: str) -> str | None:
        if not folders:
            return None
        peer_id = utils.get_peer_id(entity)
        for title, f in folders:
            if _peer_in(f, "exclude_peers", peer_id):
                continue
            if _peer_in(f, "pinned_peers", peer_id) or _peer_in(f, "include_peers", peer_id):
                return title
            if self._matches_flags(f, entity, kind):
                return title
        return self.cfg.other_group

    def _matches_flags(self, f, entity, kind: str) -> bool:
        if getattr(f, "bots", False) and kind == "bot":
            return True
        if getattr(f, "groups", False) and kind == "chat":
            return True
        if getattr(f, "broadcasts", False) and kind == "channel":
            return True
        if kind == "user":
            is_contact = bool(getattr(entity, "contact", False))
            if getattr(f, "contacts", False) and is_contact:
                return True
            if getattr(f, "non_contacts", False) and not is_contact:
                return True
        return False

    # --- сообщения ------------------------------------------------------

    async def _on_user_update(self, event) -> None:
        """Собеседник появился в сети, ушёл или начал набирать сообщение."""
        try:
            peer_id = utils.get_peer_id(types.PeerUser(event.user_id))
            if self.on_typing is not None:
                if getattr(event, "typing", False):
                    await self.on_typing(peer_id, True)
                elif getattr(event, "cancel", False):
                    await self.on_typing(peer_id, False)
            status = getattr(event, "status", None)
            if status is not None and self.on_status is not None:
                await self.on_status(peer_id, status_name(status))
        except Exception:
            log.exception("ошибка обработки события о пользователе")

    async def _on_read(self, event) -> None:
        """Собеседник прочитал наши сообщения — по этому телефон ставит галочку."""
        try:
            await self.on_read(utils.get_peer_id(event.chat_id), event.max_id)
        except Exception:
            log.exception("ошибка обработки отметки о прочтении")

    async def set_typing(self, peer_id: int, active: bool) -> None:
        """Показывает собеседнику, что владелец набирает сообщение."""
        action = (types.SendMessageTypingAction() if active
                  else types.SendMessageCancelAction())
        try:
            await self.client(functions.messages.SetTypingRequest(peer_id, action))
        except Exception:
            log.debug("не удалось передать «печатает» в чат %s", peer_id)

    async def _on_new_message(self, event) -> None:
        try:
            peer_id = utils.get_peer_id(event.message.peer_id)
            topic_id = topic_of(event.message)
            text = describe_message(event.message)
            sender = ""
            if self.cfg.show_sender_in_groups and not event.is_private:
                try:
                    sender = utils.get_display_name(await event.get_sender()) or ""
                except Exception:
                    sender = ""
            await self.on_message(peer_id, sender, text,
                                  int(event.message.date.timestamp()), topic_id)
            if self.cfg.mark_read:
                await event.message.mark_read()
        except Exception:
            log.exception("ошибка обработки входящего сообщения")

    async def history(self, peer_id: int, count: int | None,
                      since: dt.datetime | None, cap: int,
                      topic_id: int = 0) -> list[HistoryItem]:
        """Последние сообщения чата: либо count штук, либо всё начиная с since.

        Для темы форума берём сообщения только этой темы, иначе в ответ
        приедет вперемешку весь форум.
        """
        try:
            chat = await self.client.get_entity(peer_id)
        except Exception:
            chat = None
        private = isinstance(chat, types.User)
        chat_name = utils.get_display_name(chat) if chat else str(peer_id)
        names: dict[int, str] = {}

        items: list[HistoryItem] = []
        async for msg in self.client.iter_messages(peer_id, limit=min(count or cap, cap),
                                                  reply_to=topic_id or None):
            if since is not None and msg.date < since:
                break
            text = describe_message(msg)
            if not text:
                continue
            if msg.out:
                who = "Я"
            elif private:
                who = chat_name
            else:
                who = await self._sender_name(msg, names)
            items.append(HistoryItem(msg.date, who, text))
        items.reverse()
        return items

    async def last_photos(self, peer_id: int, count: int,
                          topic_id: int = 0) -> list[tuple[bytes, str]]:
        """Последние фотографии чата: сами данные и подпись.

        Берём миниатюру, а не оригинал: на телефоне всё равно 176 точек
        по ширине, а качать мегабайты незачем.
        """
        out: list[tuple[bytes, str]] = []
        try:
            iterator = self.client.iter_messages(
                peer_id, limit=200, filter=types.InputMessagesFilterPhotos(),
                reply_to=topic_id or None)
            async for msg in iterator:
                if len(out) >= count:
                    break
                raw = await self._download_small(msg)
                if raw:
                    out.append((raw, (msg.message or "").strip()))
        except Exception:
            log.exception("не удалось получить фотографии чата %s", peer_id)
        return out

    async def _download_small(self, msg) -> bytes | None:
        for thumb in (-1, None):          # сперва миниатюра, потом оригинал
            try:
                data = await msg.download_media(file=bytes, thumb=thumb)
                if data:
                    return data
            except Exception:
                continue
        return None

    async def delete_chat(self, peer_id: int, revoke: bool = False) -> bool:
        """Удаляет чат: для групп и каналов это выход из них, для личной
        переписки — удаление истории; revoke убирает её и у собеседника."""
        try:
            entity = await self.client.get_entity(peer_id)
            await self.client.delete_dialog(entity, revoke=revoke)
            return True
        except Exception:
            log.exception("не удалось удалить чат %s", peer_id)
            return False

    async def search_chats(self, query: str, limit: int) -> list[dict]:
        """Ищет чаты в Telegram — и среди своих, и в общем каталоге."""
        found: list[dict] = []
        try:
            result = await self.client(functions.contacts.SearchRequest(
                q=query, limit=limit))
        except Exception:
            log.warning("поиск «%s» в Telegram не удался", query)
            return found

        seen: set[int] = set()
        for entity in list(result.users) + list(result.chats):
            peer_id = utils.get_peer_id(entity)
            if peer_id in seen:
                continue
            seen.add(peer_id)
            kind = self._kind(entity)
            found.append({
                "peer_id": peer_id,
                "kind": kind,
                "title": utils.get_display_name(entity) or str(peer_id),
                "username": f"@{entity.username}" if getattr(entity, "username", None) else "",
            })
            if len(found) >= limit:
                break
        return found

    async def chat_info(self, peer_id: int) -> dict | None:
        """Сведения о чате для карточки контакта в Jimm."""
        try:
            entity = await self.client.get_entity(peer_id)
        except Exception:
            log.warning("не нашёл чат %s для карточки контакта", peer_id)
            return None

        kind = self._kind(entity)
        info = {
            "title": utils.get_display_name(entity) or str(peer_id),
            "kind": {"user": "Личный чат", "bot": "Бот",
                     "chat": "Группа", "channel": "Канал"}.get(kind, "Чат"),
            "username": f"@{entity.username}" if getattr(entity, "username", None) else "",
            "phone": f"+{entity.phone}" if getattr(entity, "phone", None) else "",
            "members": "",
            "about": "",
        }

        try:
            if isinstance(entity, types.User):
                full = await self.client(functions.users.GetFullUserRequest(entity))
                info["about"] = getattr(full.full_user, "about", "") or ""
                birthday = getattr(full.full_user, "birthday", None)
                if birthday is not None:
                    year = getattr(birthday, "year", None) or 0
                    info["bday"] = (birthday.day, birthday.month, year)
                    if not year:
                        # Без года клиент дату не покажет — добавим строкой.
                        note = f"День рождения: {birthday.day:02d}.{birthday.month:02d}"
                        info["about"] = f"{info['about']}\n{note}" if info["about"] else note
            elif isinstance(entity, types.Channel):
                full = await self.client(functions.channels.GetFullChannelRequest(entity))
                info["about"] = full.full_chat.about or ""
                count = getattr(full.full_chat, "participants_count", None)
                info["members"] = f"участников: {count}" if count else ""
            elif isinstance(entity, types.Chat):
                full = await self.client(functions.messages.GetFullChatRequest(entity.id))
                info["about"] = full.full_chat.about or ""
                participants = getattr(full.full_chat, "participants", None)
                members = getattr(participants, "participants", None)
                if members is not None:
                    info["members"] = f"участников: {len(members)}"
        except Exception:
            log.warning("подробности о чате %s недоступны", peer_id)

        return info

    async def missed(self, peer_id: int, since_ts: int, cap: int,
                     topic_id: int = 0) -> list[tuple[int, str, str]]:
        """Входящие сообщения чата новее since_ts — то, что мост пропустил."""
        try:
            chat = await self.client.get_entity(peer_id)
        except Exception:
            chat = None
        private = isinstance(chat, types.User)
        names: dict[int, str] = {}

        out: list[tuple[int, str, str]] = []
        async for msg in self.client.iter_messages(peer_id, limit=cap,
                                                  reply_to=topic_id or None):
            if int(msg.date.timestamp()) <= since_ts:
                break
            if msg.out:
                continue
            text = describe_message(msg)
            if not text:
                continue
            sender = "" if private else await self._sender_name(msg, names)
            out.append((int(msg.date.timestamp()), sender, text))
        out.reverse()
        return out

    async def _sender_name(self, msg, cache: dict[int, str]) -> str:
        sender_id = msg.sender_id or 0
        if sender_id not in cache:
            try:
                cache[sender_id] = utils.get_display_name(await msg.get_sender()) or "?"
            except Exception:
                cache[sender_id] = "?"
        return cache[sender_id]

    async def send(self, peer_id: int, text: str, topic_id: int = 0) -> int | None:
        """Отправляет сообщение и возвращает его номер в Telegram.

        Для форума ответ уходит в нужную тему: у Telegram тема — это ответ
        на её корневое сообщение.
        """
        if topic_id:
            message = await self.client.send_message(peer_id, text, reply_to=topic_id)
        else:
            message = await self.client.send_message(peer_id, text)
        return getattr(message, "id", None)

    async def title_for(self, peer_id: int) -> tuple[str, str]:
        """Название и тип чата — нужны, когда сообщение пришло из нового чата."""
        try:
            entity = await self.client.get_entity(peer_id)
        except Exception:
            return str(peer_id), "chat"
        return utils.get_display_name(entity) or str(peer_id), self._kind(entity)


def is_muted(dialog) -> bool:
    """Заглушён ли чат в самом Telegram.

    Уведомления там выключаются двумя способами: беззвучным режимом и
    отключением до определённого момента (у «навсегда» дата очень далёкая).
    """
    settings = getattr(getattr(dialog, "dialog", None), "notify_settings", None)
    if settings is None:
        return False
    if getattr(settings, "silent", False):
        return True
    until = getattr(settings, "mute_until", None)
    if until is None:
        return False
    try:
        return until > dt.datetime.now(dt.timezone.utc)
    except TypeError:              # на всякий случай, если пришло число
        return bool(until)


def topic_of(message) -> int:
    """Номер темы форума, из которой пришло сообщение. 0 — обычный чат."""
    reply = getattr(message, "reply_to", None)
    if reply is None or not getattr(reply, "forum_topic", False):
        return 0
    # Ответ внутри темы указывает на неё в reply_to_top_id, а первое
    # сообщение темы — прямо в reply_to_msg_id.
    return getattr(reply, "reply_to_top_id", None) or getattr(reply, "reply_to_msg_id", 0) or 0


def status_of(entity, kind: str) -> str:
    """Статус чата для контакт-листа: у групп, каналов и ботов его нет."""
    if kind != "user":
        return "online"
    return status_name(getattr(entity, "status", None))


def status_name(status) -> str:
    """Переводит статус Telegram в одно из «online» / «away» / «offline»."""
    if isinstance(status, types.UserStatusOnline):
        return "online"
    if isinstance(status, types.UserStatusRecently):
        return "away"
    if isinstance(status, types.UserStatusOffline):
        last = getattr(status, "was_online", None)
        if last is not None:
            seen = (dt.datetime.now(dt.timezone.utc) - last).total_seconds()
            if seen < RECENTLY_SECONDS:
                return "away"
        return "offline"
    return "offline"


def _plain_title(title) -> str:
    return getattr(title, "text", title) if not isinstance(title, str) else title


def _peer_in(f, attr: str, peer_id: int) -> bool:
    for peer in getattr(f, attr, None) or []:
        try:
            if utils.get_peer_id(peer) == peer_id:
                return True
        except Exception:
            continue
    return False


def describe_message(msg) -> str:
    """Текст сообщения; для вложений — короткая пометка, понятная старому клиенту."""
    if msg.action is not None:
        return f"[{type(msg.action).__name__.replace('MessageAction', '')}]"

    caption = (msg.message or "").strip()
    tag = _media_tag(msg)
    if tag and caption:
        return f"{tag} {caption}"
    return tag or caption


def _media_tag(msg) -> str:
    media = msg.media
    if media is None:
        return ""
    if isinstance(media, types.MessageMediaPhoto):
        return "[фото]"
    if isinstance(media, types.MessageMediaGeo):
        return "[геопозиция]"
    if isinstance(media, types.MessageMediaGeoLive):
        return "[трансляция геопозиции]"
    if isinstance(media, types.MessageMediaContact):
        return f"[контакт {media.first_name} {media.phone_number}]"
    if isinstance(media, types.MessageMediaPoll):
        return f"[опрос] {media.poll.question.text if hasattr(media.poll.question, 'text') else media.poll.question}"
    if isinstance(media, types.MessageMediaWebPage):
        return ""
    if isinstance(media, types.MessageMediaDice):
        return f"[{media.emoticon} {media.value}]"
    if isinstance(media, types.MessageMediaDocument):
        return _document_tag(media.document)
    return "[вложение]"


def _document_tag(document) -> str:
    if not isinstance(document, types.Document):
        return "[файл]"
    name = ""
    duration = 0
    is_voice = is_round = is_sticker = is_gif = is_video = is_audio = False
    sticker_emoji = ""
    for attr in document.attributes:
        if isinstance(attr, types.DocumentAttributeFilename):
            name = attr.file_name
        elif isinstance(attr, types.DocumentAttributeAudio):
            duration = attr.duration
            is_voice = attr.voice
            is_audio = not attr.voice
            if not attr.voice and (attr.performer or attr.title):
                name = f"{attr.performer or ''} — {attr.title or ''}".strip(" —")
        elif isinstance(attr, types.DocumentAttributeVideo):
            duration = attr.duration
            is_round = getattr(attr, "round_message", False)
            is_video = True
        elif isinstance(attr, types.DocumentAttributeSticker):
            is_sticker = True
            sticker_emoji = attr.alt or ""
        elif isinstance(attr, types.DocumentAttributeAnimated):
            is_gif = True

    if is_sticker:
        return f"[стикер {sticker_emoji}]".replace(" ]", "]")
    if is_voice:
        return f"[голосовое {_hms(duration)}]"
    if is_round:
        return f"[видеосообщение {_hms(duration)}]"
    if is_gif:
        return "[gif]"
    if is_audio:
        return f"[аудио {name} {_hms(duration)}]".replace("  ", " ")
    if is_video:
        return f"[видео {_hms(duration)}]"
    return f"[файл {name or 'без имени'}, {_size(document.size)}]"


def _hms(seconds: int) -> str:
    seconds = int(seconds or 0)
    if seconds >= 3600:
        return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60}:{seconds % 60:02d}"


def _size(size: int) -> str:
    size = int(size or 0)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024 or unit == "ГБ":
            return f"{size:.0f} {unit}" if unit == "Б" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} ГБ"
