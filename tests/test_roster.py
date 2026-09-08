"""Проверка выдачи контакт-листа, в том числе большого."""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.config import Config
from bridge.db import Storage
from bridge.oscar.server import OscarServer
from tests.fake_jimm import FakeJimm

PORT = 15300


def make_config(port: int) -> Config:
    cfg = Config(tg_api_id=1, tg_api_hash="x")
    cfg.oscar_host = "127.0.0.1"
    cfg.oscar_port = port
    cfg.oscar_uin = "100500"
    cfg.oscar_password = "s3cret"
    return cfg


async def run_big_roster() -> None:
    """Список, не влезающий в один пакет, должен доезжать целиком.

    Jimm считает список принятым по ненулевой метке времени, поэтому метка
    ставится только в последней части. Со меткой в каждой части клиент
    обрывает приём на первой — и в контактах остаётся десятая доля чатов.
    """
    cfg = make_config(PORT)
    storage = Storage(":memory:")
    total, groups = 300, 6
    for i in range(total):
        storage.uin_for_peer(1000 + i, kind="user", title=f"Контакт номер {i:03d}",
                             group_name=f"Группа {i // 50}", position=i)

    async def on_outgoing(*_):
        return 1

    server = OscarServer(cfg, storage, on_outgoing, storage.contacts)
    await server.start()

    client = FakeJimm("127.0.0.1", PORT, cfg.oscar_uin, cfg.oscar_password)
    await client.connect()
    await client.bos(await client.login_md5_jimm())

    assert len(client.contacts) == total, \
        f"доехало {len(client.contacts)} контактов из {total}"
    assert len(client.groups) == groups, f"групп {len(client.groups)}, ждали {groups}"
    assert client.ssi_stamp, "метка времени списка не пришла"

    # Названия и распределение по группам не должны перепутаться.
    assert client.aliases[client.contacts[0][0]].startswith("Контакт номер"), client.aliases
    assert sorted(client.groups.values()) == [f"Группа {i}" for i in range(groups)], \
        client.groups

    await client.close()
    server._server.close()
    print(f"  большой список: ок ({total} чатов в {groups} группах доехали целиком)")


async def run_small_roster() -> None:
    """Короткий список умещается в одну часть и тоже приходит с меткой."""
    cfg = make_config(PORT + 1)
    storage = Storage(":memory:")
    for i in range(3):
        storage.uin_for_peer(2000 + i, kind="user", title=f"Кто-то {i}",
                             group_name="Личные", position=i)

    async def on_outgoing(*_):
        return 1

    server = OscarServer(cfg, storage, on_outgoing, storage.contacts)
    await server.start()
    client = FakeJimm("127.0.0.1", cfg.oscar_port, cfg.oscar_uin, cfg.oscar_password)
    await client.connect()
    await client.bos(await client.login_md5_jimm())

    assert len(client.contacts) == 3, client.contacts
    assert list(client.groups.values()) == ["Личные"], client.groups
    await client.close()
    server._server.close()
    print("  короткий список: ок")


async def run_limited_roster() -> None:
    """roster_limit оставляет свежие чаты и все избранные."""
    storage = Storage(":memory:")
    for i in range(200):
        storage.uin_for_peer(3000 + i, kind="user", title=f"Чат {i}",
                             group_name="Личные", position=i,
                             favourite=1 if i in (150, 180) else 0)

    assert len(storage.contacts()) == 200
    limited = storage.contacts(50)
    assert len(limited) == 50, len(limited)

    positions = {c.position for c in limited}
    assert {150, 180} <= positions, "избранные должны оставаться при любом лимите"
    assert positions & set(range(48)), "свежие чаты должны попадать в список"
    assert limited == sorted(limited, key=lambda c: (c.position, c.uin)), \
        "порядок списка должен сохраняться"

    # Ограничение не выбрасывает чаты из базы: сообщения из них дойдут.
    assert storage.contact_by_peer(3199) is not None
    print("  ограничение списка: ок (свежие чаты и избранные)")


async def main() -> None:
    await run_big_roster()
    await run_small_roster()
    await run_limited_roster()
    print("КОНТАКТ-ЛИСТ ПРОВЕРЕН")


if __name__ == "__main__":
    asyncio.run(main())
