"""Клиент пользовательского аккаунта eXpress.

Официального API для обычного аккаунта у eXpress нет, а переписка
шифруется на стороне клиента. Поэтому здесь работает сам веб-клиент
corp.express в Chromium без окна: он входит, получает ключи и
расшифровывает сообщения, а мы читаем уже готовое из его состояния
(redux-хранилище страницы) и отправляем через его же поле ввода.

Страница одна, и открыт в ней один чат, поэтому все действия идут по
очереди под замком. Открытый чат веб-клиент считает прочитанным, так что
после истории и отправки возвращаемся к списку: иначе всё входящее в этот
чат помечалось бы прочитанным само.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from .browser import is_logged_in, open_app, open_context

log = logging.getLogger("express")

READY_TIMEOUT = 60          # сколько ждать связи с сервером после запуска
CHAT_TIMEOUT = 20           # сколько ждать, пока откроется чат
DOWNLOAD_TIMEOUT = 60       # сколько ждать, пока страница скачает и расшифрует файл
UPLOAD_TIMEOUT = 180        # сколько ждать загрузки файла на сервер
SEND_TIMEOUT = 20           # сколько ждать появления отправленного сообщения
WATCHDOG_SECONDS = 30
MESSAGE_INPUT = ".slate-message-input"
# Что веб-клиент принимает как картинку; остальное уходит документом.
IMAGE_MIMES = {"image/gif", "image/jpeg", "image/png", "image/webp", "image/bmp", "image/vnd.microsoft.icon"}
PENDING_ATTACHMENT = ".attachment-dialog, .input-attachment__file"
# Упоминание в тексте — заглушка с номером, а кто упомянут, лежит рядом в
# payload.mentions: @ — человек или «все», @@ — контакт, ## — чат, канал, тема.
MENTION = re.compile(r"(##|@{1,2})\{mention:([0-9a-fA-F-]{36})\}")
MENU_READ = "Отметить как прочитанное"
MENU_MUTE = "Выключить уведомления"
MENU_UNMUTE = "Включить уведомления"
MODAL_DISMISS = "Больше не показывать"

# Находит redux-хранилище приложения через корень React и кладёт в window.
JS_STORE = """() => {
  if (window.__store) return true;
  const root = document.querySelector('#app');
  if (!root) return false;
  const key = Object.keys(root).find(k => k.startsWith('__reactContainer') || k.startsWith('_reactRootContainer'));
  let fiber = root[key];
  if (fiber && fiber._internalRoot) fiber = fiber._internalRoot.current;
  const seen = new Set(), stack = [fiber];
  let n = 0;
  while (stack.length && n < 20000) {
    const f = stack.pop();
    if (!f || seen.has(f)) continue;
    seen.add(f); n++;
    const p = f.memoizedProps;
    const store = p && (p.store || (p.value && p.value.store));
    if (store && store.getState) { window.__store = store; return true; }
    stack.push(f.sibling, f.child);
  }
  return false;
}"""

# Веб-клиент расшифровывает файл и отдаёт его странице как Blob. Запоминаем
# последние такие объекты, чтобы забрать уже расшифрованное содержимое.
JS_BLOBS = """(() => {
  if (window.__exBlobs) return;
  window.__exBlobs = [];
  window.__exBlobSeq = 0;
  const create = URL.createObjectURL;
  URL.createObjectURL = function (b) {
    const url = create.call(URL, b);
    if (b instanceof Blob && b.size) {
      window.__exBlobs.push({seq: ++window.__exBlobSeq, blob: b, size: b.size, type: b.type});
      if (window.__exBlobs.length > 30) window.__exBlobs.shift();
    }
    return url;
  };
})()"""

JS_BLOB_BYTES = """async (seq) => {
  const entry = window.__exBlobs.find(b => b.seq === seq);
  const bytes = new Uint8Array(await entry.blob.arrayBuffer());
  let text = '';
  for (let i = 0; i < bytes.length; i += 0x8000) text += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(text);
}"""

# Общие помощники страницы: событие без тяжёлых и секретных полей, имя по huid.
JS_HELPERS = """() => {
  window.__exSlim = (e) => {
    if (!e) return null;
    const p = Object.assign({}, e.payload || {});
    delete p.bodyAstTree;
    return {syncId: e.syncId, groupChatId: e.groupChatId, eventType: e.eventType, sender: e.sender,
            insertedAt: e.insertedAt, editedAt: e.editedAt, deletedAt: e.deletedAt, payload: p,
            decryptionStatus: e.decryptionStatus};
  };
  window.__exName = (huid) => {
    const p = window.__store.getState().profiles[huid];
    if (!p) return '';
    const pick = (x) => (x && x.name) || '';
    return pick(p.phonebookProfile) || pick(p.ctsProfile) || pick(p.rtsProfile);
  };
  window.__exPresence = (huid) => {
    const p = window.__store.getState().presences.userPresences.get(huid);
    return p ? {status: p.status, changed: p.statusChanged || 0} : null;
  };
  window.__exChat = (c) => ({
    id: c.groupChatId, type: c.chatType, name: c.name || (c.opponent ? window.__exName(c.opponent.userHuid) : ''),
    opponent: c.opponent ? c.opponent.userHuid : null, unread: c.unreadCounter || 0,
    muted: !!(c.chatSettings && c.chatSettings.dnd), pinned: !!(c.chatSettings && c.chatSettings.pinned), members: (c.members || []).map(m => m.userHuid),
    presence: c.opponent ? window.__exPresence(c.opponent.userHuid) : null,
    left: !!c.left, membersCount: c.membersCount || (c.members || []).length, updatedAt: c.lastEventInsertedAt || c.updatedAt, last: window.__exSlim(c.lastEvent),
  });
}"""

# Следит за последним событием каждого чата: оно меняется при новом,
# изменённом и удалённом сообщении, даже если чат не открыт.
JS_WATCH = """() => {
  if (window.__exWatching) return;
  window.__exWatching = true;
  const store = window.__store;
  const key = (e) => e ? [e.syncId, e.editedAt || '', e.deletedAt || ''].join('|') : '';
  const last = new Map();
  let prev = store.getState().chats;
  for (const c of prev) last.set(c.groupChatId, key(c.lastEvent));
  store.subscribe(() => {
    const chats = store.getState().chats;
    if (chats === prev) return;
    prev = chats;
    for (const c of chats) {
      const k = key(c.lastEvent);
      if (last.get(c.groupChatId) === k) continue;
      last.set(c.groupChatId, k);
      if (c.lastEvent) window.__expressEmit(JSON.stringify(window.__exSlim(c.lastEvent)));
    }
  });
  // «Печатает»: Map чат -> Map человек -> чем занят. Себя не считаем.
  const typingNow = () => {
    const me = store.getState().user.huid, out = new Set();
    for (const [chat, who] of store.getState().typing)
      for (const huid of who.keys()) if (huid !== me) out.add(chat);
    return out;
  };
  let typingMap = store.getState().typing, typing = typingNow();
  store.subscribe(() => {
    if (store.getState().typing === typingMap) return;
    typingMap = store.getState().typing;
    const now = typingNow();
    for (const chat of now) if (!typing.has(chat)) window.__expressEmit(JSON.stringify({watch: 'typing', chat, active: true}));
    for (const chat of typing) if (!now.has(chat)) window.__expressEmit(JSON.stringify({watch: 'typing', chat, active: false}));
    typing = now;
  });
  // Присутствие: Map человек -> {status, statusChanged}.
  const seen = new Map();
  let presences = null;
  const presence = () => {
    const map = store.getState().presences.userPresences;
    if (map === presences) return;
    presences = map;
    for (const [huid, p] of map) {
      const k = p.status + '|' + p.statusChanged;
      if (seen.get(huid) === k) continue;
      seen.set(huid, k);
      window.__expressEmit(JSON.stringify({watch: 'presence', huid, status: p.status, changed: p.statusChanged || 0}));
    }
  };
  presence();
  store.subscribe(presence);
}"""

# Помечает строку чата в списке слева, чтобы по ней можно было щёлкнуть:
# номер чата лежит только в свойствах React-компонента строки.
JS_TAG_ENTRY = """(id) => {
  for (const el of document.querySelectorAll('.chat-list-entry')) {
    const key = Object.keys(el).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
    let fiber = el[key];
    for (let i = 0; i < 12 && fiber; i++, fiber = fiber.return) {
      const chat = (fiber.memoizedProps || {}).chat;
      if (chat && chat.groupChatId) {
        if (chat.groupChatId === id) { el.setAttribute('data-ex-chat', id); return true; }
        break;
      }
    }
  }
  return false;
}"""

JS_STATUS = """() => {
  const s = window.__store.getState();
  return {alive: !!s.ui.isConnectionAlive, huid: s.user.huid, name: s.user.name, path: s.router.location.pathname};
}"""


@dataclass
class Attachment:
    kind: str                   # image, voice, file, video, sticker, ...
    name: str
    size: int
    mime: str
    duration: int = 0           # секунды, для голосовых и видео
    width: int = 0              # размеры уменьшенной копии
    height: int = 0
    url: str = ""               # открытая ссылка (только стикеры)


@dataclass
class Message:
    chat_id: str
    id: str                     # syncId события на сервере
    sender: str                 # huid отправителя
    sender_name: str
    text: str
    kind: str                   # payload.type: text, image, file, ...
    event: str                  # eventType: message_new, added_to_chat, ...
    ts: float                   # секунды Unix
    outgoing: bool
    edited: bool = False
    deleted: bool = False
    mentions_me: bool = False   # упомянули меня лично или всех участников
    mentions: list[str] = field(default_factory=list)   # huid упомянутых людей
    attachment: Attachment | None = None
    raw: dict = field(default_factory=dict, repr=False)


@dataclass
class Chat:
    id: str
    type: str                   # chat (личный), group_chat, channel, ...
    title: str
    opponent: str | None        # huid собеседника в личном чате
    unread: int
    muted: bool
    pinned: bool
    members: list[str]
    left: bool
    status: str = ""            # online / offline собеседника личного чата; пусто — неизвестно
    status_changed: float = 0   # когда статус сменился, секунды Unix
    members_count: int = 0
    updated: float = 0
    last: Message | None = None


class NotLoggedIn(RuntimeError):
    pass


class ExpressClient:
    def __init__(self, profile_dir: str = "session",
                 on_message: Callable[[Message], Awaitable[None]] | None = None,
                 headless: bool = True,
                 on_typing: Callable[[str, bool], Awaitable[None]] | None = None,
                 on_presence: Callable[[str, str, float], Awaitable[None]] | None = None):
        self.profile_dir = profile_dir
        self.on_message = on_message
        self.on_typing = on_typing          # (чат, печатают ли)
        self.on_presence = on_presence      # (huid, online/offline, когда сменился)
        self.headless = headless
        self.huid = ""
        self.name = ""
        self._pw = None
        self._ctx = None
        self._page = None
        self._lock = asyncio.Lock()
        self._watchdog: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()

    # --- запуск и остановка ---

    async def start(self) -> None:
        self._pw = await async_playwright().start()
        self._ctx = await open_context(self._pw, self.profile_dir, self.headless)
        await self._ctx.expose_binding("__expressEmit", self._on_emit)
        await self._ctx.add_init_script(JS_BLOBS)
        # Содержимое забираем из памяти страницы, сохранение на диск не нужно.
        self._ctx.on("page", lambda page: page.on("download", self._drop_download))
        for page in self._ctx.pages:
            page.on("download", self._drop_download)
        await self._load()
        self._watchdog = asyncio.create_task(self._watch())

    async def stop(self) -> None:
        if self._watchdog:
            self._watchdog.cancel()
        if self._ctx:
            await self._ctx.close()
        if self._pw:
            await self._pw.stop()
        self._ctx = self._pw = self._page = None

    def _drop_download(self, download) -> None:
        task = asyncio.create_task(download.cancel())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _load(self) -> None:
        page = self._page = await open_app(self._ctx)
        if not await is_logged_in(page):
            raise NotLoggedIn(f"в профиле {self.profile_dir} нет входа: python3 run.py login express")
        await page.wait_for_function(JS_STORE, timeout=READY_TIMEOUT * 1000)
        await page.evaluate(JS_HELPERS)
        try:
            await page.wait_for_function("() => window.__store.getState().ui.isConnectionAlive",
                                         timeout=READY_TIMEOUT * 1000)
        except PlaywrightError:
            log.warning("нет связи с сервером eXpress, продолжаю ждать в фоне")
        # Список чатов досинхронизируется после соединения: дать ему улечься,
        # чтобы старые последние сообщения не пришли как новые.
        await page.wait_for_timeout(3000)
        dismiss = page.get_by_text(MODAL_DISMISS)
        if await dismiss.count():
            await dismiss.first.click()
        status = await page.evaluate(JS_STATUS)
        self.huid, self.name = status["huid"], status["name"]
        await page.evaluate(JS_WATCH)
        log.info("eXpress: вошли как %s (%s)", self.name, self.huid)

    async def _watch(self) -> None:
        """Страница могла перезагрузиться или упасть — поднять и перевесить слежение."""
        while True:
            await asyncio.sleep(WATCHDOG_SECONDS)
            try:
                async with self._lock:
                    if not await self._page.evaluate("() => !!window.__exWatching"):
                        log.warning("страница eXpress перезагрузилась, подключаюсь заново")
                        await self._load()
            except NotLoggedIn:
                log.error("сессия eXpress разлогинена")
                return
            except PlaywrightError as exc:
                log.warning("страница eXpress не отвечает (%s), открываю заново", exc)
                try:
                    async with self._lock:
                        await self._load()
                except Exception:
                    log.exception("не удалось переоткрыть eXpress")

    # --- события ---

    def _message(self, raw: dict, names: dict[str, str] | None = None) -> Message:
        payload = raw.get("payload") or {}
        sender = raw.get("sender") or payload.get("from") or ""
        text = payload.get("body") or ""
        found = {m.get("mentionId"): m for m in payload.get("mentions") or [] if isinstance(m, dict)}
        mentions: list[str] = []
        mentions_me = False

        def named(match: re.Match) -> str:
            nonlocal mentions_me
            mention = found.get(match.group(2)) or {}
            data = mention.get("mentionData") or {}
            kind = mention.get("mentionType") or ""
            huid = data.get("userHuid") or ""
            if huid:
                mentions.append(huid)
            if kind == "all" or (huid and huid == self.huid):
                mentions_me = True
            name = data.get("name") or ("все" if kind == "all" else "?")
            return ("#" if match.group(1) == "##" else "@") + name

        text = MENTION.sub(named, text)
        attachment = None
        file = payload.get("payload") or {}
        sticker = payload.get("sticker") or {}
        if file.get("file"):
            attachment = Attachment(
                kind=payload.get("type") or "file", name=file.get("fileName") or "",
                size=file.get("fileSize") or 0, mime=file.get("fileMimeType") or "",
                duration=file.get("duration") or 0, width=file.get("filePreviewWidth") or 0,
                height=file.get("filePreviewHeight") or 0)
        elif sticker.get("link"):
            attachment = Attachment(kind="sticker", name="sticker.png", size=0, mime="image/png",
                                    url=sticker["link"])
        return Message(
            chat_id=raw.get("groupChatId") or payload.get("groupChatId") or "",
            id=raw.get("syncId") or "",
            sender=sender,
            sender_name=(names or {}).get(sender, ""),
            text=text,
            kind=payload.get("type") or "",
            event=raw.get("eventType") or "",
            ts=(raw.get("insertedAt") or 0) / 1000,
            outgoing=sender == self.huid,
            edited=bool(raw.get("editedAt")),
            deleted=bool(raw.get("deletedAt")),
            mentions_me=mentions_me,
            mentions=mentions,
            attachment=attachment,
            raw=raw,
        )

    def _on_emit(self, _source, data: str) -> None:
        raw = json.loads(data)
        watch = raw.get("watch")
        if watch == "typing":
            job = self.on_typing and self.on_typing(raw["chat"], bool(raw["active"]))
        elif watch == "presence":
            job = self.on_presence and self.on_presence(raw["huid"], raw.get("status") or "",
                                                        (raw.get("changed") or 0) / 1000)
        else:
            job = self.on_message and self._deliver(raw)
        if not job:
            return
        task = asyncio.create_task(self._guard(job))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _guard(self, job) -> None:
        try:
            await job
        except Exception:
            log.exception("обработчик события eXpress упал")

    async def _deliver(self, raw: dict) -> None:
        name = await self._page.evaluate("(h) => window.__exName(h)", raw.get("sender") or "")
        await self.on_message(self._message(raw, {raw.get("sender") or "": name}))

    # --- чтение ---

    async def connected(self) -> bool:
        return bool((await self._page.evaluate(JS_STATUS))["alive"])

    async def chats(self) -> list[Chat]:
        rows = await self._page.evaluate(
            "() => window.__store.getState().chats.map(window.__exChat)")
        result = []
        for row in rows:
            last = self._message(row["last"]) if row["last"] else None
            result.append(Chat(id=row["id"], type=row["type"], title=row["name"], opponent=row["opponent"],
                               unread=row["unread"], muted=row["muted"], pinned=row["pinned"],
                               members=row["members"],
                               left=row["left"], status=(row["presence"] or {}).get("status") or "",
                               status_changed=((row["presence"] or {}).get("changed") or 0) / 1000,
                               members_count=row["membersCount"], updated=(row["updatedAt"] or 0) / 1000, last=last))
        result.sort(key=lambda c: c.updated, reverse=True)
        return result

    async def user_name(self, huid: str) -> str:
        return await self._page.evaluate("(h) => window.__exName(h)", huid)

    async def _open(self, chat_id: str) -> None:
        page = self._page
        await page.evaluate("(id) => { location.hash = '#/chats/' + id }", chat_id)
        await page.wait_for_function(
            """(id) => { const s = window.__store.getState(); const ui = s.ui.chats[id];
                 return s.router.location.pathname.endsWith(id) && ui && ui.state === 'idle'
                        && !ui.loaderTop && !ui.loaderMiddle && !ui.loaderBottom; }""",
            arg=chat_id, timeout=CHAT_TIMEOUT * 1000)
        await page.wait_for_selector(MESSAGE_INPUT, timeout=CHAT_TIMEOUT * 1000)

    async def _close(self) -> None:
        try:
            await self._page.evaluate("() => { location.hash = '#/chats' }")
        except PlaywrightError:
            pass

    async def _loaded(self, chat_id: str) -> list[Message]:
        rows = await self._page.evaluate(
            """(id) => { const s = window.__store.getState();
                 const rows = s.messages.filter(m => m.groupChatId === id).map(window.__exSlim);
                 const names = {}; for (const r of rows) names[r.sender] = window.__exName(r.sender);
                 return {rows, names}; }""", chat_id)
        items = [self._message(row, rows["names"]) for row in rows["rows"]]
        items.sort(key=lambda m: m.ts)
        return items

    async def history(self, chat_id: str, count: int = 50) -> list[Message]:
        """Последние сообщения чата, от старых к новым. Открытие чата
        помечает его прочитанным — так устроен веб-клиент."""
        async with self._lock:
            try:
                await self._open(chat_id)
                items = await self._loaded(chat_id)
                # Старое подгружается прокруткой вверх, пока список растёт.
                while len(items) < count:
                    await self._page.locator(MESSAGE_INPUT).hover()
                    await self._page.mouse.move(640, 300)
                    await self._page.mouse.wheel(0, -20000)
                    await self._page.wait_for_timeout(1500)
                    more = await self._loaded(chat_id)
                    if len(more) <= len(items):
                        break
                    items = more
                return items[-count:]
            finally:
                await self._close()

    async def _menu(self, chat_id: str, label: str) -> bool:
        """Выбрать пункт в меню чата (правая кнопка по строке списка).
        False — строки чата нет на экране или такого пункта в меню нет."""
        page = self._page
        if not await page.evaluate(JS_TAG_ENTRY, chat_id):
            return False
        await page.locator(f'[data-ex-chat="{chat_id}"]').click(button="right")
        item = page.locator(".react-contextmenu--visible .react-contextmenu-item").filter(
            has=page.get_by_text(label, exact=True))
        try:
            await item.first.click(timeout=3000)
        except PlaywrightError:
            await page.keyboard.press("Escape")
            return False
        return True

    async def mark_read(self, chat_id: str) -> None:
        async with self._lock:
            if await self._menu(chat_id, MENU_READ):
                return
            try:
                await self._open(chat_id)
                await self._page.wait_for_timeout(1000)
            finally:
                await self._close()

    async def set_muted(self, chat_id: str, muted: bool) -> bool:
        """Выключить или включить уведомления чата — как из меню чата."""
        state = "(id) => { const c = window.__store.getState().chats.find(c => c.groupChatId === id); return !!(c && c.chatSettings && c.chatSettings.dnd); }"
        async with self._lock:
            if await self._page.evaluate(state, chat_id) == muted:
                return True
            if not await self._menu(chat_id, MENU_MUTE if muted else MENU_UNMUTE):
                return False
            for _ in range(20):
                await self._page.wait_for_timeout(250)
                if await self._page.evaluate(state, chat_id) == muted:
                    return True
            return False

    # --- вложения ---

    async def _blob(self, size: int, after: int, timeout: float) -> bytes | None:
        """Дождаться расшифрованного файла нужного размера и забрать его."""
        page = self._page
        find = "([size, after]) => { const b = window.__exBlobs.find(b => b.size === size && b.seq > after); return b ? b.seq : 0; }"
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            seq = await page.evaluate(find, [size, after])
            if seq:
                return base64.b64decode(await page.evaluate(JS_BLOB_BYTES, seq))
            await page.wait_for_timeout(300)
        return None

    async def download(self, message: Message) -> bytes | None:
        """Содержимое вложения. Файл скачивает и расшифровывает сама
        страница — мы нажимаем на сообщение так же, как нажал бы человек."""
        attachment = message.attachment
        if not attachment:
            return None
        if attachment.url:
            origin = await self._page.evaluate("() => 'https://' + window.__store.getState().user.rtsHost")
            response = await self._ctx.request.get(origin + attachment.url)
            return await response.body() if response.ok else None
        async with self._lock:
            try:
                await self._open(message.chat_id)
                page = self._page
                node = page.locator(f'[id="{message.id}"]')
                if not await node.count():
                    return None
                await node.scroll_into_view_if_needed()
                # Уже расшифрованное (например, недавно проигранное) берём как есть.
                data = await self._blob(attachment.size, 0, 0.5)
                if data is not None:
                    return data
                if attachment.kind == "voice":
                    button = node.locator(".chat-message-voice__button")
                    await button.click()
                    data = await self._blob(attachment.size, 0, DOWNLOAD_TIMEOUT)
                    await button.click()        # остановить воспроизведение
                elif attachment.kind == "image":
                    await node.locator(".chat-message__img-wrp").click()
                    data = await self._blob(attachment.size, 0, DOWNLOAD_TIMEOUT)
                    await page.keyboard.press("Escape")
                elif await node.locator(".chat-message-file").count():
                    # Документ: страница расшифровывает его и предлагает сохранить.
                    await node.locator(".chat-message-file").click()
                    data = await self._blob(attachment.size, 0, DOWNLOAD_TIMEOUT)
                else:
                    log.warning("вложение типа %s скачивать не умею", attachment.kind)
                return data
            finally:
                await self._close()

    # --- отправка ---

    async def _type(self, text: str) -> None:
        page = self._page
        await page.locator(MESSAGE_INPUT).click()
        for index, line in enumerate(text.split("\n")):
            if index:
                await page.keyboard.press("Shift+Enter")
            if line:
                await page.keyboard.insert_text(line)

    async def _sent(self, chat_id: str, before: set[str], timeout: float) -> Message | None:
        """Дождаться своего нового сообщения в открытом чате."""
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            await self._page.wait_for_timeout(300)
            for message in reversed(await self._loaded(chat_id)):
                if message.id not in before and message.outgoing:
                    return message
        return None

    async def send(self, chat_id: str, text: str) -> Message | None:
        """Отправить текст в чат. Возвращает сообщение, как оно легло в чат,
        или None, если за SEND_TIMEOUT оно там не появилось."""
        text = text.strip("\n")
        if not text:
            return None
        async with self._lock:
            try:
                await self._open(chat_id)
                before = {m.id for m in await self._loaded(chat_id)}
                await self._type(text)
                await self._page.keyboard.press("Enter")
                return await self._sent(chat_id, before, SEND_TIMEOUT)
            finally:
                await self._close()

    async def send_file(self, chat_id: str, path: str, caption: str = "",
                        as_document: bool = False) -> Message | None:
        """Отправить файл с подписью. Картинки и видео уходят как медиа,
        остальное (или всё при as_document) — документом."""
        mime = mimetypes.guess_type(path)[0] or ""
        if not as_document and mime in IMAGE_MIMES:
            field = "image-input"
        elif not as_document and mime.startswith("video/"):
            field = "video-input"
        else:
            field = "document-input"
        async with self._lock:
            try:
                await self._open(chat_id)
                page = self._page
                before = {m.id for m in await self._loaded(chat_id)}
                await page.locator(f'input[id^="{field}"]').set_input_files(path)
                # Картинка открывает экран предпросмотра, документ встаёт в поле ввода.
                await page.wait_for_selector(PENDING_ATTACHMENT, timeout=CHAT_TIMEOUT * 1000)
                if caption.strip("\n"):
                    await self._type(caption.strip("\n"))
                else:
                    await page.locator(MESSAGE_INPUT).click()
                await page.keyboard.press("Enter")
                message = await self._sent(chat_id, before, UPLOAD_TIMEOUT)
                if message is None and await page.locator(PENDING_ATTACHMENT).count():
                    await page.keyboard.press("Escape")     # не оставлять висящий диалог
                return message
            finally:
                await self._close()
