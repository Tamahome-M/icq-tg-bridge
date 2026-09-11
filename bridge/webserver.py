"""Крошечный HTTP-сервер: отдаёт телефону перекодированные фотографии
и собранные командой !render страницы переписки.

Своих зависимостей не тянет и умеет три маршрута: /p/<токен>.jpg — снимок,
/r/<токен> — страница, /m/<токен>.<тип> — вложение этой страницы.
"""

from __future__ import annotations

import asyncio
import logging

from .access import AccessControl
from .photos import PhotoStore
from .render import RenderStore

log = logging.getLogger("web")

MAX_REQUEST_LINE = 2048
# Браузеры таких телефонов ждут именно этот тип для XHTML Mobile Profile.
MIME_PAGE = "application/vnd.wap.xhtml+xml"
MAX_HEADERS = 40             # больше телефон не пришлёт, а поток — сколько угодно
_NOT_FOUND_BODY = "не найдено".encode("utf-8")
NOT_FOUND = (b"HTTP/1.1 404 Not Found\r\n"
             b"Content-Type: text/plain; charset=utf-8\r\n"
             + f"Content-Length: {len(_NOT_FOUND_BODY)}\r\n".encode("ascii")
             + b"Connection: close\r\n\r\n"
             + _NOT_FOUND_BODY)


class PhotoServer:
    def __init__(self, store: PhotoStore, host: str, port: int,
                 access: AccessControl | None = None,
                 render: RenderStore | None = None):
        self.store = store
        self.render = render
        self.host = host
        self.port = port
        self.access = access or AccessControl()
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        log.info("раздача фотографий на %s:%d", self.host, self.port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader,
                      writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        host = peer[0] if peer else ""
        if not self.access.allowed(host) or not self.access.take_slot():
            log.warning("отказано %s в доступе к фотографиям", host)
            writer.close()
            return
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=10)
            if not line or len(line) > MAX_REQUEST_LINE:
                return
            parts = line.decode("latin-1", "replace").split()
            if len(parts) < 2 or parts[0] not in ("GET", "HEAD"):
                writer.write(NOT_FOUND)
                await writer.drain()
                return

            # Дочитываем заголовки, иначе браузер получит сброс соединения.
            for _ in range(MAX_HEADERS):
                header = await asyncio.wait_for(reader.readline(), timeout=10)
                if header in (b"\r\n", b"\n", b"") or len(header) > MAX_REQUEST_LINE:
                    break

            path = parts[1].split("?", 1)[0]
            await self._send(writer, path, head_only=parts[0] == "HEAD")
        except (asyncio.TimeoutError, ConnectionError, OSError):
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

    async def _send(self, writer: asyncio.StreamWriter, path: str,
                    head_only: bool) -> None:
        found = self._find(path)
        if found is None:
            log.info("запрос мимо: %s", path[:64])
            writer.write(NOT_FOUND)
            await writer.drain()
            return

        body, mime, what = found
        # Страницу не кэшируем: она живёт недолго и должна честно исчезать.
        cache = "no-cache" if what == "страница" else "max-age=86400"
        header = (
            "HTTP/1.1 200 OK\r\n"
            f"Content-Type: {mime}\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Cache-Control: {cache}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        writer.write(header if head_only else header + body)
        await writer.drain()
        log.info("отдана %s %s (%d байт)", what, path[:48], len(body))

    def _find(self, path: str) -> tuple[bytes, str, str] | None:
        """Ищет, что отдать по этому пути: снимок, страницу или вложение."""
        if path.startswith("/p/") and path.endswith(".jpg"):
            file_path = self.store.path_for(path[len("/p/"):-len(".jpg")])
            if file_path is None:
                return None
            with open(file_path, "rb") as fh:
                return fh.read(), "image/jpeg", "картинка"

        if self.render is None:
            return None

        if path.startswith("/r/"):
            body = self.render.page_for(path[len("/r/"):].rstrip("/"))
            if body is None:
                return None
            return body, f"{MIME_PAGE}; charset={self.render.encoding}", "страница"

        if path.startswith("/m/"):
            name = path[len("/m/"):]
            token = name.split(".", 1)[0]
            asset = self.render.asset_for(token)
            if asset is None:
                return None
            with open(asset.path, "rb") as fh:
                return fh.read(), asset.mime, "вложение"

        return None
