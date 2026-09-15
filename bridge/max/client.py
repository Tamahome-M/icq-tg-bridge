"""Сторона MAX (max.ru): вход в аккаунт, чаты одной группой, приём и
отправка сообщений.

Официального API для пользовательского аккаунта у MAX нет — работаем через
библиотеку PyMax (maxapi-python), которая говорит с сервером тем же
протоколом, что и приложение. Протокол может смениться без предупреждения,
поэтому всё, что берём из библиотеки, обёрнуто и переживает отсутствие
поля или метода: в худшем случае чат останется без подробностей, но мост
не упадёт.

Чаты MAX живут в мосту под своими номерами со сдвигом MAX_BASE: так они
не сталкиваются с номерами Telegram в одной базе, а по номеру сразу видно,
в какую сеть его отправлять.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
import time
import zlib
from typing import Awaitable, Callable

from ..history import HistoryItem
from ..tg.client import Dialog, RECENTLY_SECONDS

log = logging.getLogger("max")

# Сдвиг номеров чатов MAX в общей базе. У Telegram номера не длиннее
# четырнадцати знаков (каналы — -100 и десять-одиннадцать цифр). У MAX
# личные чаты нумеруются положительными числами, группы и каналы —
# отрицательными (порядка -2^46), поэтому сеть узнаётся по окну вокруг
# сдвига: всё в пределах MAX_BASE ± MAX_SPAN — из MAX.
MAX_BASE = 4_000_000_000_000_000
MAX_SPAN = 1_000_000_000_000_000

# Сколько страниц списка чатов запрашивать у сервера, не больше.
CHATS_PAGES = 20
# Чат с самим собой: у него номер 0 (me ^ me), а в MAX он зовётся «Избранное».
SAVED_TITLE = "Избранное"
# Кадры, в ответе на которые сервер присылает присутствие контактов.
OP_LOGIN = 19
OP_SYNC = 21
START_TIMEOUT = 60

TAGS = {
    "PHOTO": "[фото]",
    "VIDEO": "[видео]",
    "AUDIO": "[голосовое]",
    "STICKER": "[стикер]",
    "CALL": "[звонок]",
    "POLL": "[опрос]",
    "CONTACT": "[контакт]",
    "CONTROL": "",
    "SHARE": "",
    "INLINE_KEYBOARD": "",
}


def to_peer(chat_id: int) -> int:
    chat_id = int(chat_id)
    if abs(chat_id) >= MAX_SPAN:
        raise ValueError(f"номер чата MAX {chat_id} не помещается в окно сети")
    return MAX_BASE + chat_id


def from_peer(peer_id: int) -> int:
    return int(peer_id) - MAX_BASE


def is_max_peer(peer_id: int) -> bool:
    return abs(int(peer_id) - MAX_BASE) < MAX_SPAN


def _seconds(value: int | None) -> int:
    """Время MAX приходит в миллисекундах; на всякий случай понимаем и секунды."""
    value = int(value or 0)
    return value // 1000 if value > 10_000_000_000 else value


def _attr(obj, name: str, default=None):
    value = getattr(obj, name, default)
    return default if value is None else value


def _enum_value(value) -> str:
    return str(getattr(value, "value", value) or "")


def attachment_tag(attach) -> str:
    """Короткая пометка вложения, понятная старому клиенту."""
    kind = _enum_value(_attr(attach, "type", "")).upper()
    if kind == "FILE":
        name = _attr(attach, "name", "")
        return f"[файл {name}]" if name else "[файл]"
    if kind == "CONTACT":
        name = _attr(attach, "name", "") or " ".join(
            x for x in (_attr(attach, "first_name", ""), _attr(attach, "last_name", "")) if x)
        return f"[контакт {name}]" if name else "[контакт]"
    if kind in TAGS:
        return TAGS[kind]
    return "[вложение]"


def media_kind(msg) -> str:
    """Что во вложении: фото, видео, голосовое — или ничего."""
    for attach in _attr(msg, "attaches", []) or []:
        kind = _enum_value(_attr(attach, "type", "")).upper()
        if kind == "PHOTO":
            return "photo"
        if kind == "VIDEO":
            return "video"
        if kind == "AUDIO":
            return "voice"
    return ""


def describe_message(msg) -> str:
    """Текст сообщения; для вложений — пометка, как у стороны Telegram."""
    text = (_attr(msg, "text", "") or "").strip()
    tags = [t for t in (attachment_tag(a) for a in _attr(msg, "attaches", []) or []) if t]
    tag = " ".join(dict.fromkeys(tags))
    if tag and text:
        return f"{tag} {text}"
    return tag or text


def presence_name(presence) -> str:
    """«online» / «away» / «offline» по времени последней активности.

    Присутствие приходит и объектом (из события), и словарём (из сырого
    кадра входа) — читаем оба вида."""
    if isinstance(presence, dict):
        seen, status = presence.get("seen"), presence.get("status")
    else:
        seen, status = _attr(presence, "seen", 0), _attr(presence, "status", None)
    seen = _seconds(seen)
    if not seen:
        return "online" if status else "offline"
    ago = time.time() - seen
    if ago < 60:
        return "online"
    if ago < RECENTLY_SECONDS:
        return "away"
    return "offline"


class NoConsoleCode:
    """Под службой SMS-код спросить не у кого: вход делается заранее."""

    async def get_code(self, phone: str) -> str:
        raise RuntimeError("аккаунт MAX не авторизован — выполните: python3 run.py login max")

    async def get_password(self, hint: str | None = None) -> str:
        raise RuntimeError("аккаунт MAX просит пароль — выполните: python3 run.py login max")


class MaxSide:
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
        self.me_id: int = 0
        self._task: asyncio.Task | None = None
        self._started = asyncio.Event()
        self._chats: dict[int, object] = {}
        self._users: dict[int, object] = {}
        self._own_ids: dict[tuple[int, int], float] = {}
        self._presence: dict[int, object] = {}     # user_id -> присутствие
        self._http = None

    # --- запуск ---------------------------------------------------------

    def _make_client(self, interactive: bool):
        from pymax import Client
        from pymax.config import ExtraConfig
        kwargs = {}
        if not interactive:
            kwargs["sms_code_provider"] = NoConsoleCode()
            kwargs["password_provider"] = NoConsoleCode()
        work_dir = os.path.dirname(os.path.abspath(self.cfg.max_session)) or "."
        # Телеметрию в MAX не шлём: мосту она ни к чему, а лишний след — тем
        # более. Журнал библиотеки — своим уровнем, как у Telethon.
        # chats_sync=-1 — полная синхронизация при каждом входе: иначе сервер
        # отдаёт лишь чаты, изменившиеся с прошлого раза, и список пуст.
        from pymax.types.domain.sync import SyncOverrides
        extra = ExtraConfig(telemetry=False, log_level=self.cfg.log_max_level,
                            sync=SyncOverrides(chats_sync=-1))
        return Client(phone=self.cfg.max_phone, work_dir=work_dir,
                      session_name=os.path.basename(self.cfg.max_session),
                      extra_config=extra, **kwargs)

    def _bind_handlers(self) -> None:
        client = self.client

        @client.on_start()
        async def _started(*_):
            self._on_started()

        @client.on_message()
        async def _message(message, *_):
            await self._on_new_message(message)

        @client.on_typing()
        async def _typing(event, *_):
            await self._on_typing(event)

        @client.on_presence()
        async def _presence(event, *_):
            await self._on_presence(event)

        @client.on_message_read()
        async def _read(event, *_):
            await self._on_read(event)

        @client.on_raw()
        async def _raw(frame, *_):
            self._on_raw(frame)

        @client.on_disconnect()
        async def _gone(*args):
            log.warning("соединение с MAX потеряно%s", " — переподключаюсь" if
                        len(args) > 1 and args[1] else "")

    def _on_raw(self, frame) -> None:
        """Ответ на вход и синхронизацию несёт присутствие всех контактов —
        модель PyMax его отбрасывает, поэтому берём из сырого кадра."""
        if getattr(frame, "opcode", None) not in (OP_LOGIN, OP_SYNC):
            return
        payload = getattr(frame, "payload", None)
        got = payload.get("presence") if isinstance(payload, dict) else None
        if not got:
            return
        pairs = got.items() if isinstance(got, dict) else (
            (p.get("userId") or p.get("contactId"), p) for p in got if isinstance(p, dict))
        count = 0
        for user_id, info in pairs:
            try:
                self._presence[int(user_id)] = info
                count += 1
            except (TypeError, ValueError):
                continue
        sample = next(iter(self._presence.values()), None)
        log.debug("MAX: присутствие получено для %d контактов, например %r", count, sample)

    def _on_started(self) -> None:
        me = _attr(self.client, "me", None)
        contact = _attr(me, "contact", None)
        self.me_id = int(_attr(contact, "id", 0) or 0)
        log.info("вошли в MAX как %s (id=%s)", self._user_name(contact) or "?", self.me_id)
        self._started.set()

    async def start(self) -> None:
        if self.client is None:
            self.client = self._make_client(interactive=False)
        self._bind_handlers()
        self._task = asyncio.create_task(self._run(), name="max-client")
        waiter = asyncio.create_task(self._started.wait())
        done, _ = await asyncio.wait({waiter, self._task}, timeout=START_TIMEOUT,
                                     return_when=asyncio.FIRST_COMPLETED)
        if self._task in done:
            waiter.cancel()
            exc = self._task.exception()
            raise RuntimeError(f"MAX не запустился: {exc}") if exc else \
                RuntimeError("MAX не запустился: клиент завершился сразу")
        if waiter not in done:
            waiter.cancel()
            raise RuntimeError(f"MAX не ответил за {START_TIMEOUT} с")

    async def _run(self) -> None:
        try:
            await self.client.start()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("клиент MAX остановился: %s: %s", type(exc).__name__, exc)
            raise

    async def login(self) -> None:
        """Интерактивный вход: телефон из настроек, код из SMS, при необходимости пароль."""
        self.client = self._make_client(interactive=True)
        self._bind_handlers()
        await self.client.connect()
        await asyncio.wait_for(self._started.wait(), START_TIMEOUT)
        log.info("авторизация в MAX завершена")
        await self.client.close()

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        if self._http is not None:
            await self._http.close()

    # --- контакт-лист ---------------------------------------------------

    async def dialogs(self) -> list[Dialog]:
        chats = await self._all_chats()
        out: list[Dialog] = []
        for position, chat in enumerate(chats):
            try:
                peer = to_peer(chat.id)
            except ValueError as exc:
                log.warning("MAX: пропускаю чат %r: %s", _attr(chat, "title", chat.id), exc)
                continue
            kind = self._kind(chat)
            title = await self._chat_title(chat, kind)
            photo = _attr(chat, "base_icon_url", "") or ""
            status = "online"               # у групп и каналов статуса нет
            if kind == "user":
                user = await self._peer_user(chat)
                photo = str(_attr(user, "photo_id", 0) or _attr(user, "base_url", "") or "")
                status = self._status_of(int(_attr(user, "id", 0) or 0))
            out.append(Dialog(
                peer, kind, title[:self.cfg.alias_max_chars],
                self.cfg.max_group, position,
                status=status, unread=int(_attr(chat, "new_messages", 0) or 0),
                pinned=False, muted=False,
                photo_id=zlib.crc32(photo.encode()) if photo else 0))
        log.info("MAX: получено %d чатов", len(out))
        return out

    def _status_of(self, user_id: int) -> str:
        """Статус человека по последнему известному присутствию; без данных —
        «не в сети», как и у стороны Telegram."""
        info = self._presence.get(user_id)
        return presence_name(info) if info is not None else "offline"

    async def _all_chats(self) -> list:
        """Все чаты: то, что пришло при входе, плюс список с сервера
        страницами — маркер каждой следующей страницы старше самой старой
        полученной."""
        found: dict[int, object] = {}
        for chat in _attr(self.client, "chats", None) or []:
            if _attr(chat, "id", None) is not None:
                found[int(chat.id)] = chat
        marker = None
        for _ in range(CHATS_PAGES):
            try:
                page = list(await self.client.fetch_chats(marker) or [])
            except Exception as exc:
                log.warning("MAX: список чатов не получен: %s", exc)
                break
            page = [c for c in page if _attr(c, "id", None) is not None]
            if not page:
                break
            for chat in page:
                found[int(chat.id)] = chat
            # Страница целиком из уже известных — дальше только старьё, которое
            # мы тоже хотим; останавливаемся, лишь когда маркер перестал сдвигаться.
            oldest = min(int(_attr(c, "last_event_time", 0) or 0) for c in page)
            if oldest <= 0 or (marker is not None and oldest >= marker):
                break
            marker = oldest - 1
        chats = sorted(found.values(), key=lambda c: -int(_attr(c, "last_event_time", 0) or 0))
        self._chats = {int(c.id): c for c in chats}
        return chats

    def _kind(self, chat) -> str:
        kind = _enum_value(_attr(chat, "type", "")).upper()
        return {"DIALOG": "user", "CHAT": "chat", "CHANNEL": "channel"}.get(kind, "chat")

    async def _chat(self, chat_id: int):
        chat = self._chats.get(chat_id)
        if chat is None:
            try:
                chat = await self.client.get_chat(chat_id)
            except Exception as exc:
                log.debug("MAX: get_chat(%s) не удался: %s", chat_id, exc)
                chat = None
            if chat is not None:
                self._chats[chat_id] = chat
        return chat

    async def _peer_user(self, chat):
        """Собеседник личного чата: тот из участников, кто не мы."""
        others = [int(uid) for uid in (_attr(chat, "participants", {}) or {})
                  if int(uid) != self.me_id]
        if not others and self.me_id and _attr(chat, "id", None) is not None:
            # Участников может не быть в кратком объекте: номер личного чата —
            # это XOR номеров собеседников.
            others = [int(chat.id) ^ self.me_id]
        return await self._user(others[0]) if others else None

    async def _user(self, user_id: int):
        if user_id in self._users:
            return self._users[user_id]
        user = None
        try:
            user = self.client.get_cached_user(user_id)
        except Exception:
            user = None
        if user is None:
            try:
                user = await self.client.get_user(user_id)
            except Exception:
                user = None
        if user is not None:
            self._users[user_id] = user
        return user

    @staticmethod
    def _user_name(user) -> str:
        """Самое полное из имён контакта: у MAX их несколько (из профиля,
        из адресной книги), и первое бывает без фамилии — тогда две Татьяны
        в списке неотличимы."""
        if user is None:
            return ""
        best = ""
        for name in _attr(user, "names", []) or []:
            candidates = [
                (_attr(name, "name", "") or "").strip(),
                " ".join(x.strip() for x in (_attr(name, "first_name", "") or "",
                                             _attr(name, "last_name", "") or "") if x.strip()),
            ]
            for full in candidates:
                if len(full) > len(best):
                    best = full
        return best

    async def _chat_title(self, chat, kind: str) -> str:
        if kind == "user":
            if int(_attr(chat, "id", 0) or 0) == 0:
                return SAVED_TITLE        # чат с самим собой
            user = await self._peer_user(chat)
            name = self._user_name(user)
            if name:
                return name
        return (_attr(chat, "title", "") or "").strip() or f"MAX {chat.id}"

    async def title_for(self, peer_id: int) -> tuple[str, str]:
        chat = await self._chat(from_peer(peer_id))
        if chat is None:
            return f"MAX {from_peer(peer_id)}", "chat"
        kind = self._kind(chat)
        return await self._chat_title(chat, kind), kind

    # --- события --------------------------------------------------------

    async def _on_new_message(self, message) -> None:
        try:
            chat_id = int(_attr(message, "chat_id", 0) or 0)
            if not chat_id:
                return
            sender_id = int(_attr(message, "sender", 0) or 0)
            ts = _seconds(_attr(message, "time", 0))
            mine = bool(self.me_id and sender_id == self.me_id)
            if mine:
                if self._own_ids.pop((chat_id, int(_attr(message, "id", 0) or 0)), None):
                    return                      # отправлено самим мостом
                if not self.cfg.mirror_outgoing:
                    return
            text = describe_message(message)
            log.debug("событие MAX: сообщение %s в чате %s, %s",
                      _attr(message, "id", "?"), chat_id, media_kind(message) or "текст")
            if not text:
                return
            chat = await self._chat(chat_id)
            private = chat is not None and self._kind(chat) == "user"
            sender = ""
            if mine:
                sender = "Я"
            elif self.cfg.show_sender_in_groups and not private:
                sender = self._user_name(await self._user(sender_id)) or ""
            shown = await self.on_message(to_peer(chat_id), sender, text, ts, 0)
            if self.cfg.mark_read and shown and not mine:
                try:
                    await self.client.read_message(int(message.id), chat_id)
                except Exception:
                    log.debug("MAX: не удалось отметить прочитанным", exc_info=True)
        except Exception:
            log.exception("ошибка обработки входящего сообщения MAX")

    async def _on_typing(self, event) -> None:
        if self.on_typing is None:
            return
        chat_id = int(_attr(event, "chat_id", 0) or 0)
        user_id = int(_attr(event, "user_id", 0) or 0)
        if chat_id and user_id != self.me_id:
            await self.on_typing(to_peer(chat_id), True)

    async def _on_presence(self, event) -> None:
        if self.on_status is None or not self.me_id:
            return
        user_id = int(_attr(event, "user_id", 0) or 0)
        if not user_id or user_id == self.me_id:
            return
        # Присутствие приходит по человеку, а контакт у нас — личный чат с ним.
        presence = _attr(event, "presence", None)
        if presence is not None:
            self._presence[user_id] = presence
        chat_id = user_id ^ self.me_id
        await self.on_status(to_peer(chat_id), presence_name(presence))

    async def _on_read(self, event) -> None:
        if self.on_read is None:
            return
        chat_id = int(_attr(event, "chat_id", 0) or 0)
        user_id = int(_attr(event, "user_id", 0) or 0)
        if not chat_id or user_id == self.me_id or _attr(event, "set_as_unread", False):
            return
        # Отметка прочтения в MAX — время, а не номер сообщения; отправка
        # возвращает время сообщения тем же счётом, так что сравнение сходится.
        await self.on_read(to_peer(chat_id), int(_attr(event, "mark", 0) or 0))

    # --- сообщения ------------------------------------------------------

    async def send(self, peer_id: int, text: str, topic_id: int = 0) -> int | None:
        """Отправляет сообщение; возвращает его время в счёте MAX — по нему
        же потом приходит отметка прочтения."""
        chat_id = from_peer(peer_id)
        message = await self.client.send_message(chat_id, text)
        message_id = int(_attr(message, "id", 0) or 0)
        if message_id:
            self._own_ids[(chat_id, message_id)] = time.time()
            if len(self._own_ids) > 500:
                oldest = min(self._own_ids, key=self._own_ids.get)
                self._own_ids.pop(oldest, None)
        return int(_attr(message, "time", 0) or 0) or message_id or None

    async def set_typing(self, peer_id: int, active: bool) -> None:
        return None                        # PyMax этого не умеет

    async def set_muted(self, peer_id: int, muted: bool) -> bool:
        log.info("MAX: заглушение чатов через мост не поддерживается")
        return False

    async def delete_chat(self, peer_id: int, revoke: bool = False) -> bool:
        chat_id = from_peer(peer_id)
        chat = await self._chat(chat_id)
        try:
            kind = self._kind(chat) if chat is not None else "chat"
            if kind == "channel":
                await self.client.leave_channel(chat_id)
            elif kind == "chat":
                await self.client.leave_group(chat_id)
            else:
                await self.client.delete_chat(chat_id, for_me=not revoke)
            self._chats.pop(chat_id, None)
            return True
        except Exception:
            log.exception("MAX: не удалось удалить чат %s", chat_id)
            return False

    async def search_chats(self, query: str, limit: int) -> list[dict]:
        """Ищет по названиям своих чатов: общего каталога у MAX через
        библиотеку нет."""
        needle = query.strip().lower()
        found: list[dict] = []
        if not needle:
            return found
        for chat in await self._all_chats():
            kind = self._kind(chat)
            title = await self._chat_title(chat, kind)
            if needle in title.lower():
                found.append({"peer_id": to_peer(chat.id), "kind": kind,
                              "title": title, "username": ""})
                if len(found) >= limit:
                    break
        return found

    async def chat_info(self, peer_id: int) -> dict | None:
        chat = await self._chat(from_peer(peer_id))
        if chat is None:
            log.info("MAX: чат %s не нашёлся ни в кэше, ни на сервере", from_peer(peer_id))
            return None
        kind = self._kind(chat)
        info = {
            "title": await self._chat_title(chat, kind),
            "kind": {"user": "Личный чат (MAX)", "chat": "Группа (MAX)",
                     "channel": "Канал (MAX)"}.get(kind, "Чат (MAX)"),
            "username": "", "phone": "", "members": "",
            "about": (_attr(chat, "description", "") or "").strip(),
        }
        if kind == "user":
            user = await self._peer_user(chat)
            phone = _attr(user, "phone", None)
            info["phone"] = f"+{phone}" if phone else ""
            info["about"] = (_attr(user, "description", "") or "").strip()
        else:
            count = int(_attr(chat, "participants_count", 0) or 0)
            info["members"] = f"участников: {count}" if count else ""
            link = _attr(chat, "link", "") or ""
            if link:
                info["username"] = link
        return info

    async def _fetch(self, chat_id: int, limit: int) -> list:
        try:
            messages = await self.client.fetch_history(chat_id, backward=limit)
        except Exception as exc:
            log.warning("MAX: история чата %s не получена: %s", chat_id, exc)
            return []
        messages = [m for m in messages or [] if _attr(m, "id", None) is not None]
        messages.sort(key=lambda m: -_seconds(_attr(m, "time", 0)))   # новые первыми
        return messages

    async def _who(self, msg, private: bool, chat_name: str) -> tuple[str, bool]:
        sender_id = int(_attr(msg, "sender", 0) or 0)
        mine = bool(self.me_id and sender_id == self.me_id)
        if mine:
            return "Я", True
        if private:
            return chat_name, False
        return self._user_name(await self._user(sender_id)) or "?", False

    async def history(self, peer_id: int, count: int | None,
                      since: dt.datetime | None, cap: int,
                      topic_id: int = 0) -> list[HistoryItem]:
        chat_id = from_peer(peer_id)
        chat = await self._chat(chat_id)
        kind = self._kind(chat) if chat is not None else "chat"
        chat_name = await self._chat_title(chat, kind) if chat is not None else str(chat_id)
        items: list[HistoryItem] = []
        for msg in await self._fetch(chat_id, min(count or cap, cap)):
            when = dt.datetime.fromtimestamp(_seconds(_attr(msg, "time", 0)), dt.timezone.utc)
            if since is not None and when < since:
                break
            text = describe_message(msg)
            if not text:
                continue
            who, _ = await self._who(msg, kind == "user", chat_name)
            items.append(HistoryItem(when, who, text))
        items.reverse()
        return items

    async def missed(self, peer_id: int, since_ts: int, cap: int,
                     topic_id: int = 0) -> list[tuple[int, str, str]]:
        chat_id = from_peer(peer_id)
        chat = await self._chat(chat_id)
        private = chat is not None and self._kind(chat) == "user"
        out: list[tuple[int, str, str]] = []
        for msg in await self._fetch(chat_id, cap):
            ts = _seconds(_attr(msg, "time", 0))
            if ts <= since_ts:
                break
            if self.me_id and int(_attr(msg, "sender", 0) or 0) == self.me_id:
                continue
            text = describe_message(msg)
            if not text:
                continue
            sender = "" if private else (self._user_name(
                await self._user(int(_attr(msg, "sender", 0) or 0))) or "?")
            out.append((ts, sender, text))
        out.reverse()
        return out

    async def render_items(self, peer_id: int, count: int | None,
                           since: dt.datetime | None, cap: int, topic_id: int = 0,
                           max_media_bytes: int = 0) -> list[dict]:
        chat_id = from_peer(peer_id)
        chat = await self._chat(chat_id)
        kind = self._kind(chat) if chat is not None else "chat"
        chat_name = await self._chat_title(chat, kind) if chat is not None else str(chat_id)
        out: list[dict] = []
        for msg in await self._fetch(chat_id, min(count or cap, cap)):
            when = dt.datetime.fromtimestamp(_seconds(_attr(msg, "time", 0)), dt.timezone.utc)
            if since is not None and when < since:
                break
            who, mine = await self._who(msg, kind == "user", chat_name)
            media = media_kind(msg)
            attach = self._first_media(msg)
            fetch = thumb = None
            seconds = 0
            name = ""
            if media == "photo":
                fetch = (lambda a=attach: self._download(_attr(a, "base_url", "")))
            elif media:
                seconds = int(_attr(attach, "duration", 0) or 0)
                if media == "video":
                    thumb = (lambda a=attach: self._download(_attr(a, "thumbnail", "")))
                    fetch = (lambda m=msg, a=attach: self._download_video(chat_id, m, a))
                else:
                    fetch = (lambda a=attach: self._download(_attr(a, "url", "")))
            text = (_attr(msg, "text", "") or "").strip()
            if not text and not media:
                text = describe_message(msg)
            if not text and not media:
                continue
            out.append({
                "when": when.astimezone().strftime("%H:%M"), "who": who, "text": text,
                "mine": mine, "kind": media, "raw": None, "fetch": fetch, "thumb": thumb,
                "seconds": seconds, "name": name,
            })
        out.reverse()
        log.info("страница MAX: собрано %d сообщений, из них с вложениями %d",
                 len(out), sum(1 for r in out if r["kind"]))
        return out

    async def last_photos(self, peer_id: int, count: int,
                          topic_id: int = 0) -> list[tuple[bytes, str]]:
        chat_id = from_peer(peer_id)
        out: list[tuple[bytes, str]] = []
        for msg in await self._fetch(chat_id, 200):
            if len(out) >= count:
                break
            if media_kind(msg) != "photo":
                continue
            raw = await self._download(_attr(self._first_media(msg), "base_url", ""))
            if raw:
                out.append((raw, (_attr(msg, "text", "") or "").strip()))
        return out

    async def avatar(self, peer_id: int) -> bytes | None:
        chat = await self._chat(from_peer(peer_id))
        if chat is None:
            return None
        url = _attr(chat, "base_icon_url", "") or ""
        if self._kind(chat) == "user":
            user = await self._peer_user(chat)
            url = _attr(user, "base_url", "") or url
        return await self._download(url) if url else None

    @staticmethod
    def _first_media(msg):
        for attach in _attr(msg, "attaches", []) or []:
            if _enum_value(_attr(attach, "type", "")).upper() in ("PHOTO", "VIDEO", "AUDIO"):
                return attach
        return None

    async def _download_video(self, chat_id: int, msg, attach) -> bytes | None:
        try:
            request = await self.client.get_video_by_id(
                chat_id, int(msg.id), int(_attr(attach, "video_id", 0) or 0))
        except Exception:
            log.debug("MAX: ссылка на видео не получена", exc_info=True)
            return None
        return await self._download(_attr(request, "url", "") or "")

    async def _download(self, url: str) -> bytes | None:
        """Скачивает вложение по ссылке из MAX."""
        if not url:
            return None
        try:
            import aiohttp
            if self._http is None:
                self._http = aiohttp.ClientSession()
            async with self._http.get(url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status != 200:
                    log.info("MAX: вложение не отдано (%s)", resp.status)
                    return None
                return await resp.read()
        except Exception as exc:
            log.warning("MAX: не удалось скачать вложение: %s", exc)
            return None
