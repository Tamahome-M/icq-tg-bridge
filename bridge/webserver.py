"""Крошечный HTTP-сервер: отдаёт телефону перекодированные фотографии
и собранные командой !render страницы переписки.

Своих зависимостей не тянет. Маршруты: /p/<токен>.jpg — снимок, страница
!render по адресу из настроек (по умолчанию /r/<номер>), /m/<токен>.<тип> —
вложение страницы, /r/ — список страниц, если он включён, /login — вход.

Пароль, если задан, проверяется тремя способами, потому что браузер старого
телефона может не уметь какой-то из них: HTTP Basic, cookie после формы входа
и ключ прямо в адресе (?key=…) — последнее удобно набирать на кнопках.
"""

from __future__ import annotations

import asyncio
import base64
import email.utils
import hmac
import html
import logging
import os
import re
import secrets
import time
from urllib.parse import parse_qs, quote, unquote

from .access import AccessControl
from .photos import PhotoStore
from .render import RenderStore

log = logging.getLogger("web")

MAX_REQUEST_LINE = 2048
MAX_HEADERS = 40             # больше телефон не пришлёт, а поток — сколько угодно
MAX_BODY = 4096              # форма входа — и только она
# Браузеры таких телефонов ждут именно этот тип для XHTML Mobile Profile.
MIME_PAGE = "application/vnd.wap.xhtml+xml"
REALM = "icq-tg-bridge"
COOKIE = "bridge_auth"
SESSION_PARAM = "s"                   # токен сеанса в адресе — для браузеров без cookie
SESSION_SECONDS = 30 * 24 * 3600     # вошёл с телефона — и на месяц свободен
# Ссылки внутри страниц, к которым дописывается токен сеанса.
_LINK_RE = re.compile(rb'(href|src)="(/[^"?#]*)"')
_NOT_FOUND_BODY = "не найдено".encode("utf-8")

# Раздел «Загрузки»: типы файлов, которые телефон должен опознать. JAD и JAR
# важнее всего — по ним ставятся программы; для остального хватит общего типа.
DOWNLOAD_TYPES = {
    ".jad": "text/vnd.sun.j2me.app-descriptor", ".jar": "application/java-archive",
    ".txt": "text/plain; charset=utf-8", ".html": "text/html; charset=utf-8",
    ".xhtml": MIME_PAGE, ".wml": "text/vnd.wap.wml",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".png": "image/png",
    ".bmp": "image/bmp", ".wbmp": "image/vnd.wap.wbmp",
    ".3gp": "video/3gpp", ".mp4": "video/mp4", ".amr": "audio/amr", ".mp3": "audio/mpeg",
    ".mid": "audio/midi", ".midi": "audio/midi", ".wav": "audio/x-wav",
    ".zip": "application/zip", ".sis": "application/vnd.symbian.install",
    ".thm": "application/vnd.eri.thm", ".cab": "application/vnd.ms-cab-compressed",
}


class PhotoServer:
    def __init__(self, store: PhotoStore, host: str, port: int,
                 access: AccessControl | None = None,
                 render: RenderStore | None = None, password: str = "",
                 downloads_dir: str = "", downloads_protected: bool = False):
        self.store = store
        self.render = render
        self.host = host
        self.port = port
        self.access = access or AccessControl()
        self.password = password
        # Каталог с файлами для телефона: jad/jar, картинки, что угодно.
        # По умолчанию без пароля: JAR по ссылке из JAD качает не браузер,
        # а установщик телефона, и пароля он спросить не умеет.
        self.downloads_dir = downloads_dir
        self.downloads_protected = downloads_protected
        self._sessions: dict[str, float] = {}       # cookie -> срок
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        log.info("раздача фотографий и страниц на %s:%d%s", self.host, self.port,
                 " (с паролем)" if self.password else "")

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    # --- разбор запроса ---------------------------------------------------

    async def _handle(self, reader: asyncio.StreamReader,
                      writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        host = peer[0] if peer else ""
        if not self.access.allowed(host) or self.access.banned(host) \
                or not self.access.take_slot():
            log.warning("отказано %s в доступе к веб-серверу", host)
            writer.close()
            return
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=10)
            if not line or len(line) > MAX_REQUEST_LINE:
                return
            parts = line.decode("latin-1", "replace").split()
            if len(parts) < 2 or parts[0] not in ("GET", "HEAD", "POST"):
                await self._reply(writer, 404, "text/plain; charset=utf-8", _NOT_FOUND_BODY)
                return
            method = parts[0]

            headers: dict[str, str] = {}
            for _ in range(MAX_HEADERS):
                header = await asyncio.wait_for(reader.readline(), timeout=10)
                if header in (b"\r\n", b"\n", b"") or len(header) > MAX_REQUEST_LINE:
                    break
                name, _, value = header.decode("latin-1", "replace").partition(":")
                headers[name.strip().lower()] = value.strip()

            body = b""
            if method == "POST":
                length = min(int(headers.get("content-length", "0") or 0), MAX_BODY)
                if length:
                    body = await asyncio.wait_for(reader.readexactly(length), timeout=10)

            path, _, query = parts[1].partition("?")
            params = parse_qs(query, keep_blank_values=True)
            log.debug("HTTP %s %s от %s", method, parts[1][:120], host)
            await self._route(writer, host, method, path, params, headers, body)
        except (asyncio.TimeoutError, ConnectionError, OSError, asyncio.IncompleteReadError):
            pass
        except Exception:
            log.exception("ошибка обработки запроса")
        finally:
            self.access.free_slot()
            try:
                writer.close()
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def _route(self, writer, host: str, method: str, path: str, params: dict,
                     headers: dict, body: bytes) -> None:
        head_only = method == "HEAD"

        if path == "/login":
            await self._login(writer, host, method, params, body)
            return

        set_cookie = ""
        url_token = ""
        open_area = path.startswith("/d/") and self.downloads_dir and not self.downloads_protected
        if self.password and not open_area:
            ok, set_cookie, url_token = self._authorized(host, params, headers)
            if not ok:
                await self._challenge(writer, path, head_only)
                return

        found = self._find(path)
        if found is None:
            log.info("запрос мимо: %s", path[:64])
            await self._reply(writer, 404, "text/plain; charset=utf-8", _NOT_FOUND_BODY)
            return
        content, mime, what = found
        if url_token and what in ("страница", "список", "загрузки"):
            # Браузер без cookie: токен сеанса едет дальше в каждой ссылке —
            # и в картинках, и во вложениях, — иначе следующий шаг снова
            # спросит пароль.
            content = _LINK_RE.sub(
                lambda m: m.group(1) + b'="' + m.group(2)
                + f"?{SESSION_PARAM}={url_token}".encode() + b'"', content)
        # Страницы не кэшируем: они живут недолго и должны честно исчезать.
        cache = "no-cache" if what in ("страница", "список", "загрузки") else "max-age=86400"
        await self._reply(writer, 200, mime, content, head_only,
                          extra=[f"Cache-Control: {cache}"] + ([set_cookie] if set_cookie else []))
        log.info("отдана %s %s (%d байт)", what, path[:48], len(content))

    # --- пароль -----------------------------------------------------------

    def _check(self, given: str) -> bool:
        return hmac.compare_digest(given.encode("utf-8"), self.password.encode("utf-8"))

    def _session(self) -> str:
        now = time.time()
        self._sessions = {t: exp for t, exp in self._sessions.items() if exp > now}
        token = secrets.token_urlsafe(18)
        self._sessions[token] = now + SESSION_SECONDS
        return token

    def session_token(self) -> str:
        """Токен сеанса для ссылки, которую мост шлёт телефону: открыв её,
        не нужно вводить пароль. Пусто, если пароля нет — тогда и токен ни к чему."""
        return self._session() if self.password else ""

    def _cookie_header(self, token: str) -> str:
        # Старые браузеры знают только Expires, новые — Max-Age: шлём оба.
        expires = email.utils.formatdate(time.time() + SESSION_SECONDS, usegmt=True)
        return (f"Set-Cookie: {COOKIE}={token}; Path=/; Max-Age={SESSION_SECONDS}; "
                f"Expires={expires}")

    def _session_alive(self, token: str) -> bool:
        return bool(token) and self._sessions.get(token, 0) > time.time()

    def _authorized(self, host: str, params: dict, headers: dict) -> tuple[bool, str, str]:
        """Пускать ли.

        Второе — заголовок Set-Cookie, если вход только что случился; третье —
        токен сеанса, который надо пронести в ссылках страницы (для браузера,
        который вошёл по адресу и cookie не хранит).
        """
        auth = headers.get("authorization", "")
        if auth.lower().startswith("basic "):
            try:
                raw = base64.b64decode(auth[6:].strip()).decode("utf-8", "replace")
            except Exception:
                raw = ""
            _, _, password = raw.partition(":")
            if self._check(password):
                self.access.note_success(host)
                return True, "", ""
            self.access.note_failure(host)
            log.warning("неверный пароль (Basic) с %s", host)
            return False, "", ""

        cookies = {}
        for piece in headers.get("cookie", "").split(";"):
            name, _, value = piece.strip().partition("=")
            cookies[name] = value
        if self._session_alive(cookies.get(COOKIE, "")):
            return True, "", ""

        # Токен сеанса в адресе: его получают ссылки страницы после входа по
        # ключу, так что пароль сам по себе в адресах дальше не гуляет.
        url_token = (params.get(SESSION_PARAM) or [""])[0]
        if self._session_alive(url_token):
            return True, "", url_token

        key = (params.get("key") or [""])[0]
        if key:
            if self._check(key):
                self.access.note_success(host)
                token = self._session()
                log.info("вход по ключу в адресе с %s", host)
                return True, self._cookie_header(token), token
            self.access.note_failure(host)
            log.warning("неверный ключ в адресе с %s", host)
        return False, "", ""

    async def _challenge(self, writer, path: str, head_only: bool) -> None:
        """401 с Basic и формой входа в теле: кто умеет Basic, увидит окно,
        остальным достанется форма."""
        body = self._login_form(path, "").encode("utf-8", "xmlcharrefreplace")
        await self._reply(writer, 401, f"{MIME_PAGE}; charset=utf-8", body, head_only,
                          extra=[f'WWW-Authenticate: Basic realm="{REALM}"',
                                 "Cache-Control: no-cache"])

    async def _login(self, writer, host: str, method: str, params: dict, body: bytes) -> None:
        if not self.password:
            await self._reply(writer, 404, "text/plain; charset=utf-8", _NOT_FOUND_BODY)
            return
        if method == "POST":
            form = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True)
        else:
            form = params
        password = (form.get("p") or [""])[0]
        nxt = unquote((form.get("next") or ["/r/"])[0]) or "/r/"
        if not nxt.startswith("/") or nxt.startswith("//"):
            nxt = "/r/"
        if method == "POST" and self._check(password):
            self.access.note_success(host)
            log.info("вход через форму с %s", host)
            await self._reply(writer, 302, "text/plain; charset=utf-8", b"",
                              extra=[f"Location: {nxt}", self._cookie_header(self._session()),
                                     "Cache-Control: no-cache"])
            return
        error = ""
        if method == "POST":
            self.access.note_failure(host)
            log.warning("неверный пароль в форме с %s", host)
            error = "Пароль не подошёл"
        page = self._login_form(nxt, error).encode("utf-8", "xmlcharrefreplace")
        await self._reply(writer, 200, f"{MIME_PAGE}; charset=utf-8", page,
                          extra=["Cache-Control: no-cache"])

    def _login_form(self, nxt: str, error: str) -> str:
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<!DOCTYPE html PUBLIC "-//WAPFORUM//DTD XHTML Mobile 1.0//EN" '
            '"http://www.wapforum.org/DTD/xhtml-mobile10.dtd">\n'
            '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
            '<meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>'
            "<title>Вход</title></head><body>"
            "<p><b>icq-tg-bridge</b></p>"
            + (f'<p style="color:#c00">{html.escape(error)}</p>' if error else "")
            + '<form method="post" action="/login"><p>Пароль:<br/>'
            '<input type="password" name="p" size="12"/>'
            f'<input type="hidden" name="next" value="{html.escape(quote(nxt, safe="/"))}"/>'
            '<br/><input type="submit" value="Войти"/></p></form>'
            "<p>Или добавьте к адресу ?key=пароль.</p>"
            "</body></html>\n"
        )

    # --- содержимое -------------------------------------------------------

    def _find(self, path: str) -> tuple[bytes, str, str] | None:
        """Ищет, что отдать по этому пути: снимок, список, страницу или вложение."""
        if path.startswith("/p/") and path.endswith(".jpg"):
            file_path = self.store.path_for(path[len("/p/"):-len(".jpg")])
            if file_path is None:
                return None
            with open(file_path, "rb") as fh:
                return fh.read(), "image/jpeg", "картинка"

        if path.startswith("/d/") and self.downloads_dir:
            return self._download(path[len("/d/"):])

        if self.render is None:
            return None
        page_mime = f"{MIME_PAGE}; charset={self.render.encoding}"

        if self.render.is_index(path):
            return self.render.index_html(), page_mime, "список"

        if path.startswith("/m/"):
            token = path[len("/m/"):].split(".", 1)[0]
            asset = self.render.asset_for(token)
            if asset is None:
                return None
            with open(asset.path, "rb") as fh:
                return fh.read(), asset.mime, "вложение"

        body = self.render.page_by_path(path)
        if body is not None:
            return body, page_mime, "страница"
        return None

    # --- загрузки ---------------------------------------------------------

    def _download_names(self) -> list[str]:
        try:
            names = os.listdir(self.downloads_dir)
        except OSError:
            return []
        return sorted(n for n in names if not n.startswith(".")
                      and os.path.isfile(os.path.join(self.downloads_dir, n)))

    def _download(self, name: str) -> tuple[bytes, str, str] | None:
        """Файл из каталога загрузок или их список — только по имени файла,
        без подкаталогов и обходных путей."""
        name = unquote(name)
        if name in ("", "index"):
            return self._downloads_index(), f"{MIME_PAGE}; charset=utf-8", "загрузки"
        if "/" in name or "\\" in name or name.startswith(".") or name in (".", ".."):
            return None
        path = os.path.join(self.downloads_dir, name)
        if not os.path.isfile(path):
            return None
        mime = DOWNLOAD_TYPES.get(os.path.splitext(name)[1].lower(),
                                  "application/octet-stream")
        with open(path, "rb") as fh:
            return fh.read(), mime, "файл"

    def _downloads_index(self) -> bytes:
        rows = []
        for name in self._download_names():
            size = os.path.getsize(os.path.join(self.downloads_dir, name))
            shown = f"{size // 1024 or 1} КБ" if size < 1024 * 1024 else f"{size / 1048576:.1f} МБ"
            rows.append(f'<p><a href="/d/{quote(name)}">{html.escape(name)}</a> '
                        f'<small>({shown})</small></p>')
        if not rows:
            rows.append("<p>Пусто.</p>")
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<!DOCTYPE html PUBLIC "-//WAPFORUM//DTD XHTML Mobile 1.0//EN" '
            '"http://www.wapforum.org/DTD/xhtml-mobile10.dtd">\n'
            '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
            '<meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>'
            "<title>Загрузки</title></head><body><p><b>Загрузки</b></p>"
            + "".join(rows) + "</body></html>\n"
        ).encode("utf-8", "xmlcharrefreplace")

    async def _reply(self, writer, status: int, mime: str, body: bytes,
                     head_only: bool = False, extra: list[str] | None = None) -> None:
        reasons = {200: "OK", 302: "Found", 401: "Unauthorized", 404: "Not Found"}
        lines = [f"HTTP/1.1 {status} {reasons.get(status, 'OK')}",
                 f"Content-Type: {mime}", f"Content-Length: {len(body)}"]
        lines.extend(extra or [])
        lines.append("Connection: close")
        header = ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8")
        writer.write(header if head_only else header + body)
        await writer.drain()
