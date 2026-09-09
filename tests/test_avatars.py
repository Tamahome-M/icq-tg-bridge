"""Аватарки: примета в блоке контакта и выдача картинки отдельной службой."""

from __future__ import annotations

import asyncio
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge import avatars
from bridge.bridge import Bridge
from bridge.config import Config
from bridge.db import Storage
from bridge.oscar import const as C
from bridge.oscar.server import OscarServer
from tests.fake_jimm import FakeJimm

PORT = 15600


def big_png() -> bytes:
    """Картинка «как из Telegram»: большая и не квадратная."""
    from PIL import Image
    out = io.BytesIO()
    img = Image.new("RGB", (640, 480))
    for x in range(640):
        for y in range(0, 480, 8):
            img.putpixel((x, y), (x % 256, y % 256, (x + y) % 256))
    img.save(out, format="PNG")
    return out.getvalue()


def run_store() -> None:
    """Перекодирование и кэш."""
    store = avatars.AvatarStore(size=64, max_bytes=4096)
    uin = 501

    assert store.hash_of(uin) is None, "без фотографии приметы нет"
    assert store.store(uin, big_png()) is None, "нечего класть, пока нет приметы"

    store.remember(uin, 12345)
    digest = store.hash_of(uin)
    assert digest is not None and len(digest) == 16, digest
    assert store.cached(uin) is None, "картинки ещё нет, только примета"

    got = store.store(uin, big_png())
    assert got is not None, "картинка должна была перекодироваться"
    assert got[0] == digest, "картинка помечается той приметой, что объявлена"
    assert len(got[1]) <= 4096, f"аватарка {len(got[1])} байт — не влезает в потолок"
    assert got[1][:3] == b"\xff\xd8\xff", "ждали JPEG"
    assert store.cached(uin) == got, "второй раз должно браться из кэша"

    # Размер квадратный — в списке контактов иначе некрасиво.
    from PIL import Image
    with Image.open(io.BytesIO(got[1])) as img:
        assert img.size == (64, 64), img.size

    # Сменилось фото — примета другая, а старая картинка больше не годится.
    store.remember(uin, 999)
    assert store.hash_of(uin) != digest, "новая фотография — новая примета"
    assert store.cached(uin) is None, "старая картинка не должна выдаваться"

    # Фото убрали совсем.
    store.remember(uin, 0)
    assert store.hash_of(uin) is None

    # Мусор вместо картинки не роняет мост.
    store.remember(uin, 42)
    assert store.store(uin, "это не картинка".encode()) is None
    print("  перекодирование и кэш: ок")


def make_config() -> Config:
    cfg = Config()
    cfg.oscar_host = "127.0.0.1"
    cfg.oscar_port = PORT
    cfg.oscar_uin = "1"
    cfg.oscar_password = "s3cret"
    cfg.bos_host = "127.0.0.1"
    cfg.avatars = True
    return cfg


async def run_protocol() -> None:
    """Полный путь: примета в 03/0B, служба 0x10 и картинка в ответе."""
    cfg = make_config()
    storage = Storage(":memory:")
    uin = storage.uin_for_peer(555, kind="user", title="Мама", group_name="Семья")
    without = storage.uin_for_peer(-4001, kind="chat", title="Дача", group_name="Семья")

    store = avatars.AvatarStore(size=64, max_bytes=4096)
    store.remember(uin, 777)
    raw = big_png()

    async def on_outgoing(*_):
        return 1

    async def avatar(asked: int):
        if asked != uin:
            return None
        ready = store.cached(asked)
        return ready if ready is not None else store.store(asked, raw)

    server = OscarServer(cfg, storage, on_outgoing, storage.contacts,
                         avatar=avatar, icon_hash=store.hash_of)
    await server.start()

    client = FakeJimm("127.0.0.1", cfg.oscar_port, cfg.oscar_uin, cfg.oscar_password)
    await client.connect()
    await client.bos(await client.login_md5_jimm())
    await client.drain_for(0.7)

    assert client.icon_hashes.get(uin) == store.hash_of(uin), \
        "в блоке контакта должна приехать примета аватарки"
    assert without not in client.icon_hashes, \
        "чату без фотографии примету слать не за чем"

    got = await client.request_avatar(uin)
    assert got["uin"] == uin, got
    assert got["image"][:3] == b"\xff\xd8\xff", "ждали JPEG"
    assert got["image"] == store.cached(uin)[1], "пришла не та картинка"

    # Соединение за аватарками не должно подменять основное: сообщения ходят.
    await server.deliver(uin, "я на месте")
    await client.drain_for(0.5)
    assert any("на месте" in text for _, text in client.received), client.received

    # У чата без фотографии картинки нет — сервер отвечает отказом.
    await client.request_service(C.SSBI)
    redirect = await client.expect(C.OSERVICE, C.SERVICE_REDIRECT)
    assert redirect.data, "в перенаправлении должен быть адрес службы"

    await client.close()
    server._server.close()
    print("  выдача аватарки: ок (примета, отдельная служба, картинка)")


async def run_bridge_side() -> None:
    """Мост: примета берётся из Telegram, картинка — по запросу."""
    cfg = Config(tg_api_id=1, tg_api_hash="x")
    work = tempfile.mkdtemp()
    cfg.db = os.path.join(work, "test.db")
    cfg.tg_session = os.path.join(work, "test.session")
    cfg.photos_enabled = False
    cfg.avatars = True
    bridge = Bridge(cfg)

    uin = bridge.storage.uin_for_peer(555, kind="user", title="Мама", group_name="Личные")
    asked: list[int] = []

    async def fake_avatar(peer_id: int):
        asked.append(peer_id)
        return big_png()

    bridge.telegram.avatar = fake_avatar

    assert bridge.icon_hash(uin) is None, "пока фотографии нет — приметы нет"
    assert await bridge.avatar(uin) is None, "и картинки тоже"

    bridge.avatars.remember(uin, 4242)
    digest = bridge.icon_hash(uin)
    assert digest is not None, "примета должна появиться"

    got = await bridge.avatar(uin)
    assert got is not None and got[0] == digest, got
    assert len(asked) == 1, "первый запрос должен сходить в Telegram"

    await bridge.avatar(uin)
    assert len(asked) == 1, "второй раз картинка должна браться из кэша"

    bridge.storage.close()
    print("  сторона моста: ок (примета из Telegram, картинка по запросу)")


async def run_disabled() -> None:
    """С выключенными аватарками мост ведёт себя как раньше."""
    cfg = make_config()
    cfg.oscar_port = PORT + 1
    cfg.avatars = False
    storage = Storage(":memory:")
    uin = storage.uin_for_peer(555, kind="user", title="Мама", group_name="Семья")

    store = avatars.AvatarStore(size=64, max_bytes=4096)
    store.remember(uin, 777)
    raw = big_png()

    async def on_outgoing(*_):
        return 1

    async def avatar(asked: int):
        return store.store(asked, raw)

    server = OscarServer(cfg, storage, on_outgoing, storage.contacts,
                         avatar=avatar, icon_hash=store.hash_of)
    await server.start()

    client = FakeJimm("127.0.0.1", cfg.oscar_port, cfg.oscar_uin, cfg.oscar_password)
    await client.connect()
    await client.bos(await client.login_md5_jimm())
    await client.drain_for(0.7)

    assert client.icon_hashes == {}, "приметы слать не должны"

    await client.request_service(C.SSBI)
    await client.drain_for(0.4)
    assert any(family == C.OSERVICE for family, _ in client.errors), \
        "на запрос службы должен быть отказ, а не молчание"

    await client.close()
    server._server.close()
    print("  выключенные аватарки: ок (ни примет, ни службы)")


async def main() -> None:
    run_store()
    await run_protocol()
    await run_bridge_side()
    await run_disabled()
    print("АВАТАРКИ ПРОВЕРЕНЫ")


if __name__ == "__main__":
    asyncio.run(main())
