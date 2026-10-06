"""Ошибка записи в сокет закрывает сессию и возвращает очередь к доставке."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.config import Config
from bridge.db import Storage
from bridge.oscar.server import OscarServer, Session
from bridge.oscar import server as oscar_server


class BrokenWriter:
    def __init__(self, failure):
        self.failure = failure
        self.close_count = 0

    def get_extra_info(self, name):
        return ("127.0.0.1", 10000)

    def write(self, data):
        if self.failure == "write":
            raise BrokenPipeError("test socket failure")

    async def drain(self):
        if self.failure == "drain":
            raise ConnectionResetError("test socket failure")
        if self.failure == "timeout":
            await asyncio.Event().wait()

    def close(self):
        self.close_count += 1

    async def wait_closed(self):
        pass


async def run_cleanup(failure):
    storage = Storage(":memory:")
    cfg = Config()
    server = OscarServer(cfg, storage, lambda *_: None, storage.contacts)
    writer = BrokenWriter(failure)
    session = Session(server, asyncio.StreamReader(), writer)
    server.session = session
    session.authorized = session.ready = True
    storage.queue(1000001, "не подтверждено", 30)
    row_id = storage.peek_pending()[0][0]
    storage.mark_sent(row_id)
    server.awaiting[b"cookie"] = row_id
    started = asyncio.Event()

    async def pending_job():
        started.set()
        await asyncio.Event().wait()

    background = session.spawn(pending_job())
    await started.wait()
    with tempfile.TemporaryDirectory() as work:
        upload = os.path.join(work, "partial-upload")
        with open(upload, "wb") as fh:
            fh.write(b"partial")
        session.file_path = upload
        try:
            with patch.object(oscar_server, "SEND_TIMEOUT", 0.01):
                assert await session.send_flap(5, b"") is False
            assert session.closed and server.session is None, "сессия не снята с сервера"
            await asyncio.wait_for(asyncio.gather(background, return_exceptions=True), timeout=1)
            assert writer.close_count == 1, "сокет не закрыт"
            assert background.cancelled(), "фоновая задача осталась работать"
            assert not os.path.exists(upload) and not session.file_path, "временная загрузка осталась"
            assert not server.awaiting, "подтверждения старой сессии остались"
            assert storage.in_flight_count() == 0
            assert storage.peek_pending()[0][2] == "не подтверждено", "сообщение не вернулось в очередь"
            assert session.close_reason
            # Повторное закрытие и попытка отправки не повторяют очистку.
            await session.close()
            assert await session.send_flap(5, b"") is False
            assert writer.close_count == 1
        finally:
            background.cancel()
            await asyncio.gather(background, return_exceptions=True)
            await session.close()
            storage.close()
    print(f"  ошибка {failure}: сокет, фоновые задачи, загрузка и очередь очищены — ок")


async def main():
    await run_cleanup("write")
    await run_cleanup("drain")
    await run_cleanup("timeout")
    print("ОЧИСТКА СЕССИИ ПРИ ОБРЫВЕ ПРОВЕРЕНА")


if __name__ == "__main__":
    asyncio.run(main())
