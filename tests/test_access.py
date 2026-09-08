"""Проверка ограничений доступа: перебор пароля, наплыв соединений, чужие адреса."""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.access import AccessControl
from bridge.config import Config
from bridge.db import Storage
from bridge.oscar.server import OscarServer
from bridge.photos import PhotoStore
from tests.fake_jimm import FakeJimm

PORT = 15200


def make_config() -> Config:
    cfg = Config(tg_api_id=1, tg_api_hash="x")
    cfg.oscar_host = "127.0.0.1"
    cfg.oscar_port = PORT
    cfg.oscar_uin = "100500"
    cfg.oscar_password = "s3cret"
    cfg.login_attempts = 3
    cfg.login_ban_seconds = 60
    cfg.max_connections = 5
    return cfg


async def run_bruteforce() -> None:
    """После нескольких промахов адрес перестают пускать вовсе."""
    cfg = make_config()
    storage = Storage(":memory:")

    async def on_outgoing(*_):
        return 1

    server = OscarServer(cfg, storage, on_outgoing, storage.contacts)
    await server.start()

    for attempt in range(cfg.login_attempts):
        client = FakeJimm("127.0.0.1", PORT, cfg.oscar_uin, "неверный")
        await client.connect()
        try:
            await client.login_md5_jimm()
        except AssertionError:
            pass                      # сервер отказал — этого и ждём
        await client.close()
        await asyncio.sleep(0.2)      # даём серверу закрыть сессию и освободить слот

    assert server.access.banned("127.0.0.1"), "перебор пароля не привёл к блокировке"

    # Даже с верным паролем заблокированный адрес не пускают: сервер рвёт
    # соединение, не дожидаясь приветствия.
    client = FakeJimm("127.0.0.1", PORT, cfg.oscar_uin, cfg.oscar_password)
    let_in = False
    try:
        await asyncio.wait_for(client.connect(), timeout=2)
        await asyncio.wait_for(client.login_md5_jimm(), timeout=2)
        let_in = True
    except (asyncio.TimeoutError, AssertionError, ConnectionError, OSError,
            asyncio.IncompleteReadError):
        pass
    await client.close()
    assert not let_in, "заблокированный адрес всё же пустили"

    # Удачный вход снимает счётчик промахов.
    server.access.note_success("127.0.0.1")
    assert not server.access.banned("127.0.0.1")

    server._server.close()
    storage.close()
    print("  перебор пароля: адрес блокируется — ок")


async def run_limits() -> None:
    """Число одновременных соединений ограничено, чужие адреса не проходят."""
    access = AccessControl(allow_from=["10.0.0.0/8"], max_connections=2)
    assert access.allowed("10.1.1.1") and not access.allowed("203.0.113.5")
    assert access.take_slot() and access.take_slot()
    assert not access.take_slot(), "лимит соединений не сработал"
    access.free_slot()
    assert access.take_slot()
    print("  список адресов и лимит соединений: ок")


def run_photo_paths() -> None:
    """Токен в ссылке не должен уводить за пределы каталога."""
    import tempfile
    store = PhotoStore(tempfile.mkdtemp())
    for bad in ("../../etc/passwd", "..", "a/b", "", "a b", "тест", "٣٤٥",
                "x" * 64, "file.jpg"):
        assert store.path_for(bad) is None, f"токен {bad!r} прошёл проверку"
    print("  имена файлов в ссылках: ок")


async def main() -> None:
    await run_bruteforce()
    await run_limits()
    run_photo_paths()
    print("ОГРАНИЧЕНИЯ ДОСТУПА ПРОВЕРЕНЫ")


if __name__ == "__main__":
    asyncio.run(main())
