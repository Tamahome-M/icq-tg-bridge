"""Проверка ограничений доступа: перебор пароля, наплыв соединений, чужие адреса."""

from __future__ import annotations

import asyncio
import os
import struct
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.access import AccessControl
from bridge.config import Config
from bridge.db import Storage
from bridge.oscar import const as C
from bridge.oscar.server import OscarServer
from bridge.oscar import server as oscar_server
from bridge.oscar.proto import flap, tlv
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


async def run_auth_timeout() -> None:
    """Молчание, неполные кадры и пинги не удерживают слот до входа."""
    cfg = make_config()
    cfg.oscar_port = 0
    cfg.max_connections = 1
    cfg.idle_timeout = 0             # защита входа не зависит от сторожа BOS
    storage = Storage(":memory:")

    async def on_outgoing(*_):
        return 1

    server = OscarServer(cfg, storage, on_outgoing, storage.contacts)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]
    clients = []
    ping_task = None
    try:
        with patch.object(oscar_server, "AUTH_TIMEOUT", 0.5):
            for mode in ("silent", "header", "payload", "pings"):
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                clients.append(writer)
                await asyncio.wait_for(reader.readexactly(10), timeout=2)
                assert server.access.connections == 1

                # Все слоты действительно заняты: следующее подключение
                # отвергается, пока первое не освободится по сроку входа.
                blocked_r, blocked_w = await asyncio.open_connection("127.0.0.1", port)
                clients.append(blocked_w)
                assert await asyncio.wait_for(blocked_r.read(), timeout=2) == b""
                blocked_w.close()
                await blocked_w.wait_closed()

                if mode == "header":
                    writer.write(b"\x2a")
                    await writer.drain()
                elif mode == "payload":
                    writer.write(flap(1, 1, struct.pack(">I", 1))[:-1])
                    await writer.drain()
                elif mode == "pings":
                    async def ping():
                        while True:
                            writer.write(flap(5, 1, b""))
                            await writer.drain()
                            await asyncio.sleep(0.05)
                    ping_task = asyncio.create_task(ping())

                # read() завершается только на EOF; ответы на пинги сами
                # по себе не считаются освобождением соединения.
                await asyncio.wait_for(reader.read(), timeout=2)
                if ping_task is not None:
                    ping_task.cancel()
                    await asyncio.gather(ping_task, return_exceptions=True)
                    ping_task = None
                writer.close()
                await writer.wait_closed()
                for _ in range(100):
                    if server.access.connections == 0:
                        break
                    await asyncio.sleep(0.01)
                assert server.access.connections == 0, f"слот после {mode} не освобождён"
                assert not server._active, f"соединение после {mode} осталось в активных"

        # После освобождения слота обычный вход по MD5 снова работает.
        # Получившие cookie BOS и служба аватарок живут дольше срока входа.
        cfg.max_connections = server.access.max_connections = 3
        client = FakeJimm("127.0.0.1", port, cfg.oscar_uin, cfg.oscar_password)
        bart = FakeJimm("127.0.0.1", port, cfg.oscar_uin, cfg.oscar_password)
        try:
            await client.connect()
            cookie = await client.login_md5_jimm()
            with patch.object(oscar_server, "AUTH_TIMEOUT", 0.5):
                await client.bos(cookie)
                session = server.session
                await bart.connect()
                await bart.send_flap(1, struct.pack(">I", 1)
                                     + tlv(C.TLV_AUTH_COOKIE, server.new_cookie("bart")))
                await bart.expect(C.OSERVICE, C.SRV_READY)
                await asyncio.sleep(0.6)
                assert session is not None and session.authorized and not session.closed
                await client.ping()
                channel, _ = await client.recv_flap()
                while channel != 5:
                    channel, _ = await client.recv_flap()
                await bart.ping()
                channel, _ = await bart.recv_flap()
                assert channel == 5, "служба аватарок закрылась по сроку входа"
        finally:
            await client.close()
            await bart.close()
    finally:
        if ping_task is not None:
            ping_task.cancel()
            await asyncio.gather(ping_task, return_exceptions=True)
        for writer in clients:
            writer.close()
        await asyncio.gather(*(w.wait_closed() for w in clients), return_exceptions=True)
        await server.stop()
        for task in list(server._own_tasks):
            task.cancel()
        await asyncio.gather(*server._own_tasks, return_exceptions=True)
        storage.close()
    print("  срок входа: ок (молчание, части кадра, пинги, освобождение слота, MD5/BOS/BART)")


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
    await run_auth_timeout()
    run_photo_paths()
    print("ОГРАНИЧЕНИЯ ДОСТУПА ПРОВЕРЕНЫ")


if __name__ == "__main__":
    asyncio.run(main())
