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

Обсуждения (треды) устроены как темы форума в Telegram: обсуждение — это
отдельный собеседник того же чата с topic_id, равным номеру сообщения, под
которым оно начато; группой контактов для него служит название чата.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
import tempfile
import time
import uuid
import zlib
from typing import Awaitable, Callable

from ..history import HistoryItem, MissedMessage, SentMessage
from ..quotes import QuoteContent, QuoteMedia, filename, check_size, save_bytes
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


def thread_topic(thread_id: str) -> int:
    """topic_id обсуждения — номер сообщения, под которым оно начато: у
    eXpress это один и тот же UUID."""
    return message_number(thread_id)


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
    """Что во вложении: photo, video, voice, file — или ничего. Стикер —
    тоже картинка: телефон получает его как фото."""
    attachment = message.attachment
    if attachment is None:
        return ""
    if attachment.kind in ("image", "sticker"):
        return "photo"
    if attachment.kind == "voice":
        return "voice"
    if attachment.kind in ("video", "video_message") or attachment.mime.startswith("video/"):
        return "video"
    return "file"


def describe_message(message) -> str:
    """Текст сообщения; для вложений — пометка, как у остальных сетей; под
    сообщением с обсуждением — пометка о нём."""
    text = (message.text or "").strip()
    attachment = message.attachment
    if attachment is not None:
        if attachment.kind == "sticker":
            text = f"{TAGS['sticker']} {text}".strip()
        else:
            kind = media_kind(message)
            tag = TAGS.get(kind) or (f"[файл {attachment.name}]" if attachment.name else "[файл]")
            text = f"{tag} {text}".strip()
    if getattr(message, "thread_started", False) and text:
        count = getattr(message, "thread_count", 0)
        text += f" [обсуждение: {count}]" if count else " [есть обсуждение]"
    return text


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
        self.on_read = on_read
        self.client = client              # подмена для проверок
        self._chats: dict[int, object] = {}        # peer_id -> Chat
        self._threads: dict[tuple[int, int], object] = {}   # (peer_id, topic_id) -> Chat обсуждения
        self._messages: dict[int, object] = {}     # номер сообщения -> Message
        self._own_ids: set[str] = set()
        self._passed: dict[str, None] = {}         # что уже отдано мосту — чтобы не дважды
        self._sending: dict[str, int] = {}         # чат -> сколько отправок идёт

    # --- запуск ---------------------------------------------------------

    def _make_client(self):
        from .web import ExpressClient
        return ExpressClient(self.cfg.express_session, self._on_new_message,
                             on_typing=self._on_typing, on_presence=self._on_presence,
                             on_read=self._on_read, executable=self.cfg.express_browser,
                             trust_ca=list(self.cfg.express_trust_ca),
                             devtools_port=self.cfg.express_devtools_port)

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
        if await main(self.cfg.express_session, self.cfg.express_browser,
                      self.cfg.express_devtools_port, list(self.cfg.express_trust_ca)):
            raise RuntimeError("вход прерван")

    async def stop(self) -> None:
        if self.client is not None:
            try:
                await self.client.stop()
            except Exception:
                log.debug("eXpress: браузер закрылся с ошибкой", exc_info=True)
        self.client = None
        self._chats.clear()

    # --- контакт-лист ---------------------------------------------------

    async def _all_chats(self) -> list:
        """Обычные чаты; обсуждения откладываются в _threads."""
        if self.client is None:
            raise RuntimeError("сторона eXpress выключена")
        chats, threads = [], {}
        for chat in await self.client.chats():
            if chat.left:
                continue
            if chat.type == "thread" and chat.parent:
                threads[(chat_peer(chat.parent), thread_topic(chat.id))] = chat
            else:
                chats.append(chat)
        self._chats = {chat_peer(c.id): c for c in chats}
        self._threads = threads
        return chats

    async def _chat(self, peer_id: int):
        if peer_id not in self._chats:
            await self._all_chats()
        return self._chats.get(peer_id)

    async def _thread(self, peer_id: int, topic_id: int):
        if (peer_id, topic_id) not in self._threads:
            await self._all_chats()
        return self._threads.get((peer_id, topic_id))

    async def _chat_id(self, peer_id: int, topic_id: int = 0) -> str:
        if topic_id:
            thread = await self._thread(peer_id, topic_id)
            if thread is not None:
                return thread.id
            # Обсуждение, на которое не подписаны, в списке чатов страницы не
            # значится, но у него тот же номер, что у сообщения, под которым
            # оно начато, — а сообщение мы видели в истории чата.
            root = self._root_message(peer_id, topic_id)
            if root is not None:
                return root.id
            raise LookupError(f"обсуждение eXpress {peer_id}/{topic_id} не найдено")
        chat = await self._chat(peer_id)
        if chat is None:
            raise LookupError(f"чат eXpress {peer_id} не найден")
        return chat.id

    def _root_message(self, peer_id: int, topic_id: int):
        """Сообщение чата, под которым начато обсуждение с таким topic_id."""
        message = self._messages.get(topic_id)
        if message is not None and chat_peer(message.chat_id) == peer_id and message.thread_started:
            return message
        return None

    def _locate(self, chat_id: str) -> tuple[int, int] | None:
        """(peer_id, topic_id) по номеру чата страницы — обычного или обсуждения."""
        peer = chat_peer(chat_id)
        if peer in self._chats:
            return peer, 0
        for key, thread in self._threads.items():
            if thread.id == chat_id:
                return key
        # Обсуждение не из списка: его номер — номер сообщения-корня.
        root = self._messages.get(message_number(chat_id))
        if root is not None and root.id == chat_id and chat_peer(root.chat_id) in self._chats:
            return chat_peer(root.chat_id), message_number(chat_id)
        return None

    @staticmethod
    def _thread_title(thread) -> str:
        text = " ".join((thread.starter or "").split())
        return text or "Обсуждение"

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
                photo_id=zlib.crc32(chat.avatar.encode()) if chat.avatar else 0))
        # Обсуждения — отдельными собеседниками в группе с названием чата,
        # как темы форума; мьют берут у чата.
        position = len(out)
        for (peer, topic), thread in self._threads.items():
            parent = self._chats.get(peer)
            if parent is None:
                continue
            out.append(Dialog(
                peer, "chat", self._thread_title(thread)[:self.cfg.alias_max_chars],
                self._title(parent)[:self.cfg.alias_max_chars], position,
                status="online", unread=thread.unread, pinned=False,
                muted=parent.muted or thread.muted, topic_id=topic,
                photo_id=zlib.crc32(parent.avatar.encode()) if parent.avatar else 0))
            position += 1
        log.debug("eXpress: получено %d чатов и %d обсуждений", len(self._chats), len(self._threads))
        return out

    async def topic_title(self, peer_id: int, topic_id: int) -> str:
        """Название обсуждения — сообщение, под которым оно начато."""
        thread = await self._thread(peer_id, topic_id)
        if thread is not None:
            return self._thread_title(thread)
        root = self._root_message(peer_id, topic_id)
        return " ".join((root.text or "").split()) or "Обсуждение" if root is not None else ""

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

    async def chat_info(self, peer_id: int, topic_id: int = 0) -> dict | None:
        chat = await self._chat(peer_id)
        if chat is None:
            return None
        if topic_id:
            thread = await self._thread(peer_id, topic_id)
            if thread is None:
                return None
            # Карточка обсуждения: откуда оно и под каким сообщением начато.
            starter = " ".join((thread.starter or "").split())
            author = f"{thread.starter_sender}: " if thread.starter_sender else ""
            return {
                "title": self._thread_title(thread), "kind": "Обсуждение",
                "username": "", "phone": "",
                "members": f"участников: {thread.members_count}" if thread.members_count else "",
                "about": f"Чат: {self._title(chat)}\nНачато под сообщением — {author}{starter}",
            }
        kind = self._kind(chat)
        count = chat.members_count
        return {
            "title": self._title(chat), "kind": KIND_NAMES.get(kind, "Чат"),
            "username": "", "phone": "", "about": "",
            "members": f"участников: {count}" if kind != "user" and count else "",
        }

    # --- события --------------------------------------------------------

    def _pass(self, message) -> bool:
        """Одно сообщение может прийти и событием, и догрузкой пропущенного
        (при старте они идут одновременно). False — уже отдавали."""
        if message.id in self._passed:
            return False
        self._passed[message.id] = None
        if len(self._passed) > KNOWN_MESSAGES:
            self._passed.pop(next(iter(self._passed)))
        return True

    def _remember(self, message) -> int:
        number = message_number(message.id)
        self._messages[number] = message
        if len(self._messages) > KNOWN_MESSAGES:
            self._messages.pop(next(iter(self._messages)))
        return number

    async def _on_new_message(self, message) -> None:
        try:
            if not (message.event == "message_new" or message.call) or message.edited \
                    or message.deleted:
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
            if not text or not self._pass(message):
                return
            where = self._locate(message.chat_id)
            if where is None:
                await self._all_chats()         # новый чат или обсуждение
                where = self._locate(message.chat_id) or (chat_peer(message.chat_id), 0)
            peer, topic = where
            chat = await self._chat(peer)
            private = not topic and chat is not None and self._kind(chat) == "user"
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
            shown = await self.on_message(peer, sender, text, int(message.ts), topic,
                                          attach=f"{kind}:{number}" if kind else "",
                                          mention=message.mentions_me, always=bool(message.call),
                                          message_id=message.id)
            if self.cfg.mark_read and shown and not message.outgoing:
                await self.client.mark_read(message.chat_id)
        except Exception:
            log.exception("ошибка обработки входящего сообщения eXpress")

    async def _on_typing(self, chat_id: str, active: bool) -> None:
        # Набор в обсуждении телефону не показать: у «печатает» нет темы.
        if self.on_typing is not None and chat_peer(chat_id) in self._chats:
            await self.on_typing(chat_peer(chat_id), active)

    async def _on_read(self, chat_id: str, at: int) -> None:
        """Отметка прочтения в eXpress — время, а не номер сообщения; отправка
        возвращает время сообщения тем же счётом, так что сравнение сходится."""
        if self.on_read is not None and chat_peer(chat_id) in self._chats:
            await self.on_read(chat_peer(chat_id), at)

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
        return SentMessage(message.sent_mark or int(time.time() * 1000), message.id)

    async def _sent(self, chat_id: str, sending) -> int | None:
        self._sending[chat_id] = self._sending.get(chat_id, 0) + 1
        try:
            message = await sending
        finally:
            self._sending[chat_id] -= 1
        if message is None:
            raise RuntimeError("сообщение не появилось в чате eXpress")
        return self._own(message)

    async def send(self, peer_id: int, text: str, topic_id: int = 0, *, plain: bool = False) -> int | None:
        chat_id = await self._chat_id(peer_id, topic_id)
        return await self._sent(chat_id, self.client.send(chat_id, text))

    async def _send_bytes(self, peer_id: int, data: bytes, name: str, caption: str = "",
                          as_document: bool = False, topic_id: int = 0) -> int | None:
        folder = tempfile.mkdtemp(prefix="express-")
        path = os.path.join(folder, name)
        try:
            with open(path, "wb") as out:
                out.write(data)
            return await self.send_document(peer_id, path, name, topic_id, caption=caption,
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
                return await self._send_bytes(peer_id, source.read(), name, caption, as_document,
                                              topic_id)
        chat_id = await self._chat_id(peer_id, topic_id)
        return await self._sent(chat_id, self.client.send_file(chat_id, path, caption,
                                                               as_document=as_document))

    async def send_photo(self, peer_id: int, data: bytes, caption: str = "",
                         topic_id: int = 0) -> int | None:
        return await self._send_bytes(peer_id, data, "camera.jpg", caption, topic_id=topic_id)

    async def _quote_source(self, peer_id: int, source_id: str, topic_id: int = 0):
        chat_id = await self._chat_id(peer_id, topic_id)
        message = self._messages.get(message_number(source_id))
        if message is None or message.id != source_id or message.chat_id != chat_id:
            message = next((m for m in await self._fetch(peer_id, FIND_DEPTH, topic_id)
                            if m.id == source_id and m.chat_id == chat_id), None)
        return message if message and not message.deleted and message.event == "message_new" else None

    async def quote(self, peer_id: int, source_peer: int, source_id: str,
                    topic_id: int = 0, source_topic: int = 0) -> int | None:
        message = await self._quote_source(source_peer, source_id, source_topic)
        if message is None:
            return None
        chat_id = await self._chat_id(peer_id, topic_id)
        return await self._sent(chat_id, self.client.forward(message, chat_id))

    async def quote_content(self, peer_id: int, source_id: str,
                            topic_id: int = 0) -> QuoteContent | None:
        message = await self._quote_source(peer_id, source_id, topic_id)
        if message is None or not await self.client.can_forward(message):
            return None
        kind = media_kind(message)
        if not kind:
            return QuoteContent(describe_message(message))
        attach = message.attachment
        name = filename(attach.name or {"photo": "photo.jpg", "video": "video.mp4",
                                        "voice": "voice.ogg"}.get(kind, "file.bin"))
        async def save(path, maximum):
            check_size(attach.size, maximum)
            await save_bytes(lambda: self.client.download(message, max_bytes=maximum), path, maximum)
        return QuoteContent(message.text, [QuoteMedia(kind, name, attach.size, save)])

    async def send_quote_media(self, peer_id: int, path: str, kind: str, name: str,
                               caption: str, topic_id: int = 0) -> int | None:
        return await self.send_document(peer_id, path, name, topic_id, caption,
                                        as_document=kind not in ("photo", "video"))

    async def send_voice(self, peer_id: int, data: bytes, seconds: int = 0,
                         voice: bool = True, topic_id: int = 0) -> int | None:
        """Голосовое с телефона уходит файлом: записать «настоящее» голосовое
        веб-клиент даёт только с микрофона."""
        return await self._send_bytes(peer_id, data, "voice.ogg" if voice else "voice.amr",
                                      as_document=True, topic_id=topic_id)

    async def send_video(self, peer_id: int, data: bytes, seconds: int = 0,
                         note: bool = True, topic_id: int = 0, name: str = "") -> int | None:
        return await self._send_bytes(peer_id, data, name or ("note.mp4" if note else "video.3gp"),
                                      topic_id=topic_id)

    async def set_typing(self, peer_id: int, active: bool) -> None:
        """«Печатает» с телефона. Веб-клиент сообщает о наборе только из
        открытого чата, так что чат при этом считается прочитанным."""
        try:
            await self.client.set_typing(await self._chat_id(peer_id), active)
        except Exception:
            log.debug("eXpress: «печатает» не передано", exc_info=True)

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

    async def _fetch(self, peer_id: int, limit: int, topic_id: int = 0,
                     *, strict: bool = False) -> list:
        """Сообщения чата или обсуждения, новые первыми. Открытие чата
        веб-клиент считает прочтением — так же, как если бы вы открыли его сами."""
        try:
            messages = await self.client.history(await self._chat_id(peer_id, topic_id), limit)
        except Exception as exc:
            log.warning("eXpress: история чата %s не получена: %s", peer_id, exc,
                        exc_info=True)
            if strict:
                raise
            return []
        messages = [m for m in messages
                    if (m.event == "message_new" or m.call == "missed") and not m.deleted]
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
        private = not topic_id and chat is not None and self._kind(chat) == "user"
        chat_name = self._title(chat) if chat is not None else str(peer_id)
        items: list[HistoryItem] = []
        for message in await self._fetch(peer_id, min(count or cap, cap), topic_id, strict=True):
            when = dt.datetime.fromtimestamp(message.ts, dt.timezone.utc)
            if since is not None and when < since:
                break
            text = describe_message(message)
            if not text:
                continue
            who, _ = self._who(message, private, chat_name)
            items.append(HistoryItem(when, who, text, message_number(message.id),
                                     media_kind(message),
                                     thread_topic(message.id) if message.thread_started else 0,
                                     source_id=message.id))
        items.reverse()
        return items

    async def missed(self, peer_id: int, since_ts: int, cap: int,
                     topic_id: int = 0) -> list[MissedMessage]:
        chat = await self._chat(peer_id)
        private = not topic_id and chat is not None and self._kind(chat) == "user"
        out: list[MissedMessage] = []
        for message in await self._fetch(peer_id, cap, topic_id):
            if int(message.ts) < since_ts:
                break
            if message.outgoing:
                continue
            text = describe_message(message)
            if not text:
                continue
            number = self._remember(message)
            kind = media_kind(message)
            out.append(MissedMessage(
                int(message.ts), "" if private else (message.sender_name or "?"), text,
                message.id, f"{kind}:{number}" if kind else "",
                message.mentions_me, bool(message.call)))
        out.reverse()
        return out

    async def render_items(self, peer_id: int, count: int | None,
                           since: dt.datetime | None, cap: int, topic_id: int = 0,
                           max_media_bytes: int = 0) -> list[dict]:
        chat = await self._chat(peer_id)
        private = not topic_id and chat is not None and self._kind(chat) == "user"
        chat_name = self._title(chat) if chat is not None else str(peer_id)
        out: list[dict] = []
        for message in await self._fetch(peer_id, min(count or cap, cap), topic_id, strict=True):
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

    def _cached_message(self, peer_id: int, number: int):
        message = self._messages.get(number)
        if message is not None and (chat_peer(message.chat_id) == peer_id
                or any(peer == peer_id and chat.id == message.chat_id
                       for (peer, _), chat in self._threads.items())):
            return message
        return None

    async def _message(self, peer_id: int, number: int):
        """Сообщение по номеру: из памяти, иначе из истории чата, а затем его
        обсуждений — телефон просит вложение по номеру, не называя темы."""
        message = self._cached_message(peer_id, number)
        if message is None:
            await self._fetch(peer_id, FIND_DEPTH)
            message = self._cached_message(peer_id, number)
        for (peer, topic) in list(self._threads):
            if message is not None:
                break
            if peer == peer_id:
                await self._fetch(peer_id, FIND_DEPTH, topic)
                message = self._cached_message(peer_id, number)
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
        for message in await self._fetch(peer_id, FIND_DEPTH, topic_id, strict=True):
            if len(out) >= count:
                break
            if media_kind(message) != "photo":
                continue
            raw = await self.client.download(message)
            if raw:
                out.append((raw, (message.text or "").strip()))
        return out

    async def avatar(self, peer_id: int) -> bytes | None:
        try:
            return await self.client.avatar(await self._chat_id(peer_id))
        except Exception as exc:
            log.debug("eXpress: аватарка чата %s не получена: %s", peer_id, exc)
            return None
