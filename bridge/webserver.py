"""Крошечный HTTP-сервер: отдаёт телефону перекодированные фотографии.

Своих зависимостей не тянет и умеет ровно один маршрут — /p/<токен>.jpg.
"""

from __future__ import annotations

import asyncio
import logging

from .access import AccessControl
from .photos import PhotoStore

log = logging.getLogger("web")

MAX_REQUEST_LINE = 2048
MAX_HEADERS = 40             # больше телефон не пришлёт, а поток — сколько угодно
_NOT_FOUND_BODY = "не найдено".encode("utf-8")
NOT_FOUND = (b"HTTP/1.1 404 Not Found\r\n"
             b"Content-Type: text/plain; charset=utf-8\r\n"
             + f"Content-Length: {len(_NOT_FOUND_BODY)}\r\n".encode("ascii")
             + b"Connection: close\r\n\r\n"
             + _NOT_FOUND_BODY)


class PhotoServer:
    def __init__(self, store: PhotoStore, host: str, port: int,
                 access: AccessControl | None = None):
        self.store = store
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
        token = ""
        if path.startswith("/p/") and path.endswith(".jpg"):
            token = path[len("/p/"):-len(".jpg")]

        file_path = self.store.path_for(token) if token else None
        if file_path is None:
            log.info("запрос мимо: %s", path[:64])
            writer.write(NOT_FOUND)
            await writer.drain()
            return

        with open(file_path, "rb") as fh:
            body = fh.read()
        header = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: image/jpeg\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Cache-Control: max-age=86400\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        writer.write(header if head_only else header + body)
        await writer.drain()
        log.info("отдана картинка %s (%d байт)", token, len(body))
