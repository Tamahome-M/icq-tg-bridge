"""Сторона eXpress (corp.express): вход в аккаунт, чаты одной группой,
приём и отправка сообщений и вложений.

Официального API для пользовательского аккаунта у eXpress нет, а переписка
шифруется на стороне клиента. Поэтому мост держит настоящий веб-клиент в
Chromium без окна (см. web.py) и работает через него. Веб-клиент могут
обновить без предупреждения, поэтому всё, что берём со страницы, переживает
отсутствие поля: в худшем случае чат останется без подробностей, но мост
не упадёт.

Чаты и сообщения eXpress нумеруются UUID, а мост и телефон считают
числами. Номер чата — старшие биты UUID со сдвигом EXPRESS_BASE (по нему
же видно сеть, как у MAX), номер сообщения — тоже старшие биты UUID;
обратное соответствие держим в памяти и восстанавливаем из списка чатов и
истории.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
import tempfile
import time
import uuid
from typing import Awaitable, Callable

from ..history import HistoryItem
from ..tg.client import Dialog, RECENTLY_SECONDS

log = logging.getLogger("express")

# Окно номеров eXpress в общей базе — выше окна MAX (4·10^15 ± 10^15).
EXPRESS_BASE = 6_000_000_000_000_000
EXPRESS_SPAN = 1_000_000_000_000_000
CHAT_BITS = 49                   # 2^49 < EXPRESS_SPAN
MESSAGE_BITS = 62

START_TIMEOUT = 120
FIND_DEPTH = 200                 # сколько сообщений чата перебирать в поисках вложения
KNOWN_MESSAGES = 2000

KINDS = {"chat": "user", "group_chat": "chat", "channel": "channel", "botx": "bot"}
KIND_NAMES = {"user": "Личный чат", "chat": "Группа", "channel": "Канал", "bot": "Бот"}
TAGS = {"photo": "[фото]", "video": "[видео]", "voice": "[голосовое]", "sticker": "[стикер]"}


def chat_peer(chat_id: str) -> int:
    return EXPRESS_BASE + (uuid.UUID(chat_id).int >> (128 - CHAT_BITS))


def message_number(sync_id: str) -> int:
    return uuid.UUID(sync_id).int >> (128 - MESSAGE_BITS)


def is_express_peer(peer_id: int) -> bool:
    return 0 <= int(peer_id) - EXPRESS_BASE < EXPRESS_SPAN


def presence_name(status: str, changed: float) -> str:
    """«online» / «away» / «offline»: недавно ушедший — «отошёл», как у
    остальных сетей; без данных — «не в сети»."""
    if status == "online":
        return "online"
    if changed and time.time() - changed < RECENTLY_SECONDS:
        return "away"
    return "offline"


def media_kind(message) -> str:
    """Что во вложении: photo, video, voice, file — или ничего."""
    attachment = message.attachment
    if attachment is None or attachment.kind == "sticker":
        return ""
    if attachment.kind == "image":
        return "photo"
    if attachment.kind == "voice":
        return "voice"
    if attachment.kind == "video" or attachment.mime.startswith("video/"):
        return "video"
    return "file"


def describe_message(message) -> str:
    """Текст сообщения; для вложений — пометка, как у остальных сетей."""
    text = (message.text or "").strip()
    attachment = message.attachment
    if attachment is None:
        return text
    if attachment.kind == "sticker":
        return f"{TAGS['sticker']} {text}".strip()
    kind = media_kind(message)
    tag = TAGS.get(kind) or (f"[файл {attachment.name}]" if attachment.name else "[файл]")
    return f"{tag} {text}".strip()


class ExpressSide:
    def __init__(self, cfg, on_message: Callable[[int, str, str, int, int], Awaitable[bool]],
                 on_status: Callable[[int, str], Awaitable[None]] | None = None,
                 on_typing: Callable[[int, bool], Awaitable[None]] | None = None,
                 on_read: Callable[[int, int], Awaitable[None]] | None = None,
                 client=None):
        self.cfg = cfg
        self.on_message = on_message
        self.on_status = on_status
        self.on_typing = on_typing
        self.client = client              # подмена для проверок
        self._chats: dict[int, object] = {}        # peer_id -> Chat
        self._messages: dict[int, object] = {}     # номер сообщения -> Message
        self._own_ids: set[str] = set()
        self._sending: dict[str, int] = {}         # чат -> сколько отправок идёт

    # --- запуск ---------------------------------------------------------

    def _make_client(self):
        from .web import ExpressClient
        return ExpressClient(self.cfg.express_session, self._on_new_message,
                             on_typing=self._on_typing, on_presence=self._on_presence)

    async def start(self) -> None:
        if self.client is None:
            self.client = self._make_client()
        try:
            await asyncio.wait_for(self.client.start(), START_TIMEOUT)
        except asyncio.TimeoutError:
            raise RuntimeError(f"eXpress не ответил за {START_TIMEOUT} с") from None
        except Exception as exc:
            raise RuntimeError(f"eXpress не запустился: {exc}") from exc
        log.info("вошли в eXpress как %s", self.client.name or "?")

    async def login(self) -> None:
        """Интерактивный вход: телефон, текст с капчи, код из SMS."""
        from .login import main
        if await main(self.cfg.express_session):
            raise RuntimeError("вход прерван")

    async def stop(self) -> None:
        if self.client is not None:
            try:
                await self.client.stop()
            except Exception:
                log.debug("eXpress: браузер закрылся с ошибкой", exc_info=True)

    # --- контакт-лист ---------------------------------------------------

    async def _all_chats(self) -> list:
        chats = [c for c in await self.client.chats() if not c.left]
        self._chats = {chat_peer(c.id): c for c in chats}
        return chats

    async def _chat(self, peer_id: int):
        if peer_id not in self._chats:
            await self._all_chats()
        return self._chats.get(peer_id)

    async def _chat_id(self, peer_id: int) -> str:
        chat = await self._chat(peer_id)
        if chat is None:
            raise LookupError(f"чат eXpress {peer_id} не найден")
        return chat.id

    @staticmethod
    def _kind(chat) -> str:
        return KINDS.get(chat.type, "chat")

    @staticmethod
    def _title(chat) -> str:
        return (chat.title or "").strip() or f"eXpress {chat.id[:8]}"

    async def dialogs(self) -> list[Dialog]:
        out: list[Dialog] = []
        for position, chat in enumerate(await self._all_chats()):
            out.append(Dialog(
                chat_peer(chat.id), self._kind(chat), self._title(chat)[:self.cfg.alias_max_chars],
                self.cfg.express_group, position,
                # У групп и каналов статуса нет; у человека — по присутствию.
                status=(presence_name(chat.status, chat.status_changed)
                        if self._kind(chat) == "user" else "online"),
                unread=chat.unread, pinned=chat.pinned, muted=chat.muted,
                photo_id=0))
        log.debug("eXpress: получено %d чатов", len(out))
        return out

    async def title_for(self, peer_id: int) -> tuple[str, str]:
        chat = await self._chat(peer_id)
        if chat is None:
            return f"eXpress {peer_id - EXPRESS_BASE}", "chat"
        return self._title(chat), self._kind(chat)

    async def search_chats(self, query: str, limit: int) -> list[dict]:
        """Ищет по названиям своих чатов."""
        needle = query.strip().lower()
        if not needle:
            return []
        found = []
        for chat in await self._all_chats():
            title = self._title(chat)
            if needle in title.lower():
                found.append({"peer_id": chat_peer(chat.id), "kind": self._kind(chat),
                              "title": title, "username": ""})
                if len(found) >= limit:
                    break
        return found

    async def chat_info(self, peer_id: int) -> dict | None:
        chat = await self._chat(peer_id)
        if chat is None:
            return None
        kind = self._kind(chat)
        count = chat.members_count
        return {
            "title": self._title(chat), "kind": KIND_NAMES.get(kind, "Чат"),
            "username": "", "phone": "", "about": "",
            "members": f"участников: {count}" if kind != "user" and count else "",
        }

    # --- события --------------------------------------------------------

    def _remember(self, message) -> int:
        number = message_number(message.id)
        self._messages[number] = message
        if len(self._messages) > KNOWN_MESSAGES:
            self._messages.pop(next(iter(self._messages)))
        return number

    async def _on_new_message(self, message) -> None:
        try:
            if message.event != "message_new" or message.edited or message.deleted:
                return
            if message.outgoing:
                # Своё сообщение страница показывает раньше, чем отправка
                # вернёт его номер, поэтому смотрим и на идущие отправки.
                if message.id in self._own_ids or self._sending.get(message.chat_id):
                    self._own_ids.discard(message.id)
                    return                      # отправлено самим мостом
                if not self.cfg.mirror_outgoing:
                    return
            text = describe_message(message)
            if not text:
                return
            peer = chat_peer(message.chat_id)
            chat = await self._chat(peer)
            private = chat is not None and self._kind(chat) == "user"
            sender = ""
            if message.outgoing:
                sender = "Я"
            elif self.cfg.show_sender_in_groups and not private:
                sender = message.sender_name
            kind = media_kind(message)
            number = self._remember(message)
            log.debug("событие eXpress: сообщение %s в чате %s, %s%s",
                      message.id, message.chat_id, kind or "текст",
                      ", меня упомянули" if message.mentions_me else "")
            shown = await self.on_message(peer, sender, text, int(message.ts), 0,
                                          attach=f"{kind}:{number}" if kind else "",
                                          mention=message.mentions_me)
            if self.cfg.mark_read and shown and not message.outgoing:
                await self.client.mark_read(message.chat_id)
        except Exception:
            log.exception("ошибка обработки входящего сообщения eXpress")

    async def _on_typing(self, chat_id: str, active: bool) -> None:
        if self.on_typing is not None:
            await self.on_typing(chat_peer(chat_id), active)

    async def _on_presence(self, huid: str, status: str, changed: float) -> None:
        """Присутствие приходит по человеку, а контакт у нас — личный чат с ним."""
        if self.on_status is None:
            return
        for peer, chat in self._chats.items():
            if chat.opponent == huid and self._kind(chat) == "user":
                chat.status, chat.status_changed = status, changed
                await self.on_status(peer, presence_name(status, changed))

    # --- сообщения ------------------------------------------------------

    def _own(self, message) -> int:
        """Запоминает отправленное мостом, чтобы оно не вернулось эхом."""
        self._own_ids.add(message.id)
        if len(self._own_ids) > 500:
            self._own_ids.pop()
        self._remember(message)
        return int(time.time() * 1000)

    async def _sent(self, chat_id: str, sending) -> int | None:
        self._sending[chat_id] = self._sending.get(chat_id, 0) + 1
        try:
            message = await sending
        finally:
            self._sending[chat_id] -= 1
        if message is None:
            raise RuntimeError("сообщение не появилось в чате eXpress")
        return self._own(message)

    async def send(self, peer_id: int, text: str, topic_id: int = 0) -> int | None:
        chat_id = await self._chat_id(peer_id)
        return await self._sent(chat_id, self.client.send(chat_id, text))

    async def _send_bytes(self, peer_id: int, data: bytes, name: str, caption: str = "",
                          as_document: bool = False) -> int | None:
        folder = tempfile.mkdtemp(prefix="express-")
        path = os.path.join(folder, name)
        try:
            with open(path, "wb") as out:
                out.write(data)
            return await self.send_document(peer_id, path, name, caption=caption,
                                            as_document=as_document)
        finally:
            try:
                os.remove(path)
                os.rmdir(folder)
            except OSError:
                pass

    async def send_document(self, peer_id: int, path: str, name: str, topic_id: int = 0,
                            caption: str = "", as_document: bool = True) -> int | None:
        """Файл с телефона — в чат eXpress. Имя берётся из пути, поэтому при
        другом имени файл отправляется из временной копии."""
        if os.path.basename(path) != name:
            with open(path, "rb") as source:
                return await self._send_bytes(peer_id, source.read(), name, caption, as_document)
        chat_id = await self._chat_id(peer_id)
        return await self._sent(chat_id, self.client.send_file(chat_id, path, caption,
                                                               as_document=as_document))

    async def send_photo(self, peer_id: int, data: bytes, caption: str = "",
                         topic_id: int = 0) -> int | None:
        return await self._send_bytes(peer_id, data, "camera.jpg", caption)

    async def send_voice(self, peer_id: int, data: bytes, seconds: int = 0,
                         voice: bool = True, topic_id: int = 0) -> int | None:
        """Голосовое с телефона уходит файлом: записать «настоящее» голосовое
        веб-клиент даёт только с микрофона."""
        return await self._send_bytes(peer_id, data, "voice.ogg" if voice else "voice.amr",
                                      as_document=True)

    async def send_video(self, peer_id: int, data: bytes, seconds: int = 0,
                         note: bool = True, topic_id: int = 0, name: str = "") -> int | None:
        return await self._send_bytes(peer_id, data, name or ("note.mp4" if note else "video.3gp"))

    async def set_typing(self, peer_id: int, active: bool) -> None:
        return None

    async def set_muted(self, peer_id: int, muted: bool) -> bool:
        """Заглушает чат в eXpress или возвращает ему голос — тем же пунктом
        меню чата, которым это делает человек."""
        try:
            done = await self.client.set_muted(await self._chat_id(peer_id), muted)
        except Exception:
            log.exception("eXpress: не удалось изменить уведомления чата %s", peer_id)
            return False
        if done and peer_id in self._chats:
            self._chats[peer_id].muted = muted
        return done

    async def delete_chat(self, peer_id: int, revoke: bool = False) -> bool:
        return False

    # --- история --------------------------------------------------------

    async def _fetch(self, peer_id: int, limit: int) -> list:
        """Сообщения чата, новые первыми. Открытие чата веб-клиент считает
        прочтением — так же, как если бы вы открыли его сами."""
        try:
            messages = await self.client.history(await self._chat_id(peer_id), limit)
        except Exception as exc:
            log.warning("eXpress: история чата %s не получена: %s", peer_id, exc)
            return []
        messages = [m for m in messages if m.event == "message_new" and not m.deleted]
        for message in messages:
            self._remember(message)
        messages.reverse()
        return messages

    def _who(self, message, private: bool, chat_name: str) -> tuple[str, bool]:
        if message.outgoing:
            return "Я", True
        if private:
            return chat_name, False
        return message.sender_name or "?", False

    async def history(self, peer_id: int, count: int | None,
                      since: dt.datetime | None, cap: int,
                      topic_id: int = 0) -> list[HistoryItem]:
        chat = await self._chat(peer_id)
        private = chat is not None and self._kind(chat) == "user"
        chat_name = self._title(chat) if chat is not None else str(peer_id)
        items: list[HistoryItem] = []
        for message in await self._fetch(peer_id, min(count or cap, cap)):
            when = dt.datetime.fromtimestamp(message.ts, dt.timezone.utc)
            if since is not None and when < since:
                break
            text = describe_message(message)
            if not text:
                continue
            who, _ = self._who(message, private, chat_name)
            items.append(HistoryItem(when, who, text, message_number(message.id),
                                     media_kind(message)))
        items.reverse()
        return items

    async def missed(self, peer_id: int, since_ts: int, cap: int,
                     topic_id: int = 0) -> list[tuple[int, str, str]]:
        chat = await self._chat(peer_id)
        private = chat is not None and self._kind(chat) == "user"
        out: list[tuple[int, str, str]] = []
        for message in await self._fetch(peer_id, cap):
            if int(message.ts) <= since_ts:
                break
            if message.outgoing:
                continue
            text = describe_message(message)
            if not text:
                continue
            out.append((int(message.ts), "" if private else (message.sender_name or "?"), text))
        out.reverse()
        return out

    async def render_items(self, peer_id: int, count: int | None,
                           since: dt.datetime | None, cap: int, topic_id: int = 0,
                           max_media_bytes: int = 0) -> list[dict]:
        chat = await self._chat(peer_id)
        private = chat is not None and self._kind(chat) == "user"
        chat_name = self._title(chat) if chat is not None else str(peer_id)
        out: list[dict] = []
        for message in await self._fetch(peer_id, min(count or cap, cap)):
            when = dt.datetime.fromtimestamp(message.ts, dt.timezone.utc)
            if since is not None and when < since:
                break
            who, mine = self._who(message, private, chat_name)
            media = media_kind(message)
            if media == "file":
                media = ""                  # документы на странице — пометкой в тексте
            text = (message.text or "").strip() if media else describe_message(message)
            if not text and not media:
                continue
            fetch = None
            if media and not (max_media_bytes and message.attachment.size > max_media_bytes):
                fetch = (lambda m=message: self.client.download(m))
            out.append({
                "when": when.astimezone().strftime("%H:%M"), "who": who, "text": text,
                "mine": mine, "kind": media, "raw": None, "fetch": fetch, "thumb": None,
                "seconds": message.attachment.duration if media else 0, "name": "",
            })
        out.reverse()
        log.info("страница eXpress: собрано %d сообщений, из них с вложениями %d",
                 len(out), sum(1 for r in out if r["kind"]))
        return out

    # --- вложения -------------------------------------------------------

    async def _message(self, peer_id: int, number: int):
        message = self._messages.get(number)
        if message is None:
            await self._fetch(peer_id, FIND_DEPTH)
            message = self._messages.get(number)
        if message is None:
            log.warning("eXpress: сообщение %s в чате %s не нашлось", number, peer_id)
        return message

    async def _media(self, peer_id: int, number: int, kind: str, max_bytes: int = 0):
        message = await self._message(peer_id, number)
        if message is None or media_kind(message) != kind:
            return None, None
        if max_bytes and message.attachment.size > max_bytes:
            log.info("eXpress: вложение %d КБ больше потолка — пропускаю",
                     message.attachment.size // 1024)
            return None, None
        try:
            return message, await self.client.download(message)
        except Exception as exc:
            log.warning("eXpress: не удалось скачать вложение: %s", exc)
            return None, None

    async def photo_bytes(self, peer_id: int, message_id: int) -> bytes | None:
        return (await self._media(peer_id, message_id, "photo"))[1]

    async def voice_bytes(self, peer_id: int, message_id: int, max_bytes: int) -> bytes | None:
        return (await self._media(peer_id, message_id, "voice", max_bytes))[1]

    async def video_bytes(self, peer_id: int, message_id: int, max_bytes: int) -> bytes | None:
        return (await self._media(peer_id, message_id, "video", max_bytes))[1]

    async def file_bytes(self, peer_id: int, message_id: int,
                         max_bytes: int) -> tuple[str, bytes] | None:
        message, data = await self._media(peer_id, message_id, "file", max_bytes)
        if not data:
            return None
        return (message.attachment.name or "file.bin"), data

    async def last_photos(self, peer_id: int, count: int,
                          topic_id: int = 0) -> list[tuple[bytes, str]]:
        out: list[tuple[bytes, str]] = []
        for message in await self._fetch(peer_id, FIND_DEPTH):
            if len(out) >= count:
                break
            if media_kind(message) != "photo":
                continue
            raw = await self.client.download(message)
            if raw:
                out.append((raw, (message.text or "").strip()))
        return out

    async def avatar(self, peer_id: int) -> bytes | None:
        return None
