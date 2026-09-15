"""TeleMotoMax — расширенный клиент: мост узнаёт его по способности."""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.config import Config
from bridge.db import Storage
from bridge.oscar import const as C
from bridge.oscar.server import OscarServer
from tests.fake_jimm import FakeJimm

PORT = 15900


def make_server(port: int) -> tuple[OscarServer, Storage]:
    cfg = Config(tg_api_id=1, tg_api_hash="x")
    cfg.oscar_host, cfg.oscar_port = "127.0.0.1", port
    cfg.oscar_uin, cfg.oscar_password = "100500", "s3cret"
    storage = Storage(":memory:")
    storage.uin_for_peer(555, kind="user", title="Мама", group_name="Личные")

    async def on_outgoing(*_):
        return 1

    return OscarServer(cfg, storage, on_outgoing, storage.contacts), storage


async def run_detection() -> None:
    server, _ = make_server(PORT)
    await server.start()

    # Обычный Jimm: способности без нашей — сессия обычная.
    client = FakeJimm("127.0.0.1", PORT, "100500", "s3cret")
    await client.connect()
    await client.bos(await client.login_md5_jimm())
    await client.drain_for(0.5)
    session = server.session
    assert session is not None and not session.extended and session.client_name == "?", \
        (session.extended, session.client_name)
    await client.close()
    await asyncio.sleep(0.2)

    # TeleMotoMax 0.1: та же цепочка плюс способность «TMM:» — сессия расширенная.
    client = FakeJimm("127.0.0.1", PORT, "100500", "s3cret")
    client.tmm_version = (0, 1)
    await client.connect()
    await client.bos(await client.login_md5_jimm())
    await client.drain_for(0.5)
    session = server.session
    assert session is not None and session.extended, "TeleMotoMax не опознан"
    assert session.tmm_version == (0, 1) and session.client_name == "TeleMotoMax 0.1", \
        (session.tmm_version, session.client_name)
    # Всё обычное при этом работает: сообщение доходит.
    await server.deliver(server.storage.contact_by_peer(555).uin, "привет")
    await client.drain_for(0.5)
    assert any("привет" in t for _, t in client.received), client.received
    await client.close()
    server._server.close()
    print("  опознание: ок (Jimm — обычная сессия, TeleMotoMax 0.1 — расширенная)")


async def main() -> None:
    await run_detection()
    print("TELEMOTOMAX ПРОВЕРЕН")


if __name__ == "__main__":
    asyncio.run(main())
