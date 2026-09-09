"""Списки видимости в клиенте управляют уведомлениями Telegram."""

from __future__ import annotations

import asyncio
import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge import policy
from bridge.bridge import Bridge
from bridge.config import Config
from bridge.db import Storage
from bridge.oscar import blocks
from bridge.oscar import const as C
from bridge.oscar.proto import pstr16
from bridge.oscar.server import OscarServer
from tests.fake_jimm import FakeJimm

PORT = 15500


def ssi_item(uin: int, item_type: int) -> bytes:
    """Элемент списка так, как его шлёт клиент."""
    return (pstr16(str(uin).encode()) + struct.pack(">HHH", 0, 100, item_type)
            + pstr16(b""))


def make_bridge() -> Bridge:
    cfg = Config(tg_api_id=1, tg_api_hash="x")
    work = tempfile.mkdtemp()
    cfg.db = os.path.join(work, "test.db")
    cfg.tg_session = os.path.join(work, "test.session")
    cfg.photos_enabled = False
    bridge = Bridge(cfg)

    calls: list[tuple[int, bool]] = []

    async def set_muted(peer_id, muted):
        calls.append((peer_id, muted))
        return True

    async def chat_info(peer_id):
        return {"title": "Шумный", "kind": "Личный чат", "username": "",
                "phone": "", "members": "", "about": ""}

    bridge.telegram.set_muted = set_muted
    bridge.telegram.chat_info = chat_info
    bridge.calls = calls
    bridge._roster = bridge.storage.contacts()
    bridge._by_uin = {c.uin: c for c in bridge._roster}
    return bridge


async def run_bridge_side() -> None:
    bridge = make_bridge()
    uin = bridge.storage.uin_for_peer(-4001, kind="user", title="Шумный",
                                      group_name="Личные")
    bridge._roster = bridge.storage.contacts()
    bridge._by_uin = {c.uin: c for c in bridge._roster}

    # «В невид. список» — заглушаем чат в Telegram.
    await bridge.on_phone_privacy(uin, muted=True)
    assert bridge.calls == [(-4001, True)], bridge.calls
    assert bridge.storage.contact_by_uin(uin).muted == 1

    # Повтор ничего не делает: состояние уже такое.
    await bridge.on_phone_privacy(uin, muted=True)
    assert len(bridge.calls) == 1, bridge.calls

    # В «не беспокоить» заглушённый чат больше не доходит.
    await bridge.on_owner_status(C.STATUS_DND)
    assert bridge.verdict_for(uin) == "drop", "заглушённый собеседник молчит"
    assert bridge.status_of(uin) == C.STATUS_DND, "и выглядеть заглушённым"

    # Карточка контакта показывает пометки чата в поле «Должность».
    assert (await bridge.chat_info(uin))["marks"] == "Заглушенный"
    bridge.storage.toggle_favourite(uin)
    assert (await bridge.chat_info(uin))["marks"] == "Избранный, Заглушенный"

    # «В видим. список» — возвращаем звук.
    await bridge.on_phone_privacy(uin, muted=False)
    assert bridge.calls[-1] == (-4001, False), bridge.calls
    assert bridge.storage.contact_by_uin(uin).muted == 0
    assert bridge.verdict_for(uin) == "send", "снова должен доходить"
    assert (await bridge.chat_info(uin))["marks"] == "Избранный", \
        "со звуком остаётся только пометка избранного"
    bridge.storage.toggle_favourite(uin)
    assert (await bridge.chat_info(uin))["marks"] == "", "пометок нет — поле пустое"

    bridge.storage.close()
    print("  списки видимости: ок (заглушают и возвращают звук)")


async def run_protocol_side() -> None:
    """Проверяем, что пакеты клиента разбираются в нужные действия."""
    cfg = Config(tg_api_id=1, tg_api_hash="x")
    cfg.oscar_host, cfg.oscar_port = "127.0.0.1", PORT
    cfg.oscar_uin, cfg.oscar_password = "100500", "s3cret"
    storage = Storage(":memory:")
    uin = storage.uin_for_peer(-4001, kind="chat", title="Шумная", group_name="Группы")

    async def on_outgoing(*_):
        return 1

    seen: list[tuple[int, bool]] = []

    async def on_privacy(target: int, muted: bool) -> None:
        seen.append((target, muted))

    removed: list[int] = []

    async def on_remove(target: int, revoke: bool) -> None:
        removed.append(target)

    server = OscarServer(cfg, storage, on_outgoing, storage.contacts,
                         on_remove=on_remove, on_privacy=on_privacy)
    await server.start()

    client = FakeJimm("127.0.0.1", PORT, cfg.oscar_uin, cfg.oscar_password)
    await client.connect()
    await client.bos(await client.login_md5_jimm())

    # «В невид. список» — добавление в список запрета.
    await client.send_snac(C.SSI, C.SSI_ADD, ssi_item(uin, C.SSI_TYPE_DENY))
    await asyncio.sleep(0.3)
    assert seen == [(uin, True)], seen

    # «В видим. список» — добавление в список разрешённых.
    await client.send_snac(C.SSI, C.SSI_ADD, ssi_item(uin, C.SSI_TYPE_PERMIT))
    await asyncio.sleep(0.3)
    assert seen[-1] == (uin, False), seen

    # Удаление из списка запрета тоже возвращает звук.
    await client.send_snac(C.SSI, C.SSI_DELETE, ssi_item(uin, C.SSI_TYPE_DENY))
    await asyncio.sleep(0.3)
    assert seen[-1] == (uin, False), seen

    # «Отменить видим. список» — удаление разрешения, звук выключается обратно.
    await client.send_snac(C.SSI, C.SSI_DELETE, ssi_item(uin, C.SSI_TYPE_PERMIT))
    await asyncio.sleep(0.3)
    assert seen[-1] == (uin, True), seen

    # «Отменить невид. список» — обратное ему, звук возвращается.
    await client.send_snac(C.SSI, C.SSI_DELETE, ssi_item(uin, C.SSI_TYPE_IGNORE))
    await asyncio.sleep(0.3)
    assert seen[-1] == (uin, False), seen
    assert removed == [], "списки видимости не должны удалять чат"

    # Клиент шлёт правку пачкой: сперва снимает одну пометку, потом ставит
    # другую. Так выглядит «В невид. список» у контакта, уже бывшего видимым.
    before = len(seen)
    await client.send_snac(C.SSI, C.SSI_DELETE, ssi_item(uin, C.SSI_TYPE_PERMIT))
    await client.send_snac(C.SSI, C.SSI_ADD, ssi_item(uin, C.SSI_TYPE_DENY))
    await asyncio.sleep(0.3)
    assert seen[before:] == [(uin, True), (uin, True)], seen[before:]

    # А удаление самого контакта по-прежнему удаляет чат.
    await client.send_snac(C.SSI, C.SSI_DELETE, ssi_item(uin, C.SSI_TYPE_BUDDY))
    await asyncio.sleep(0.3)
    assert removed == [uin], removed

    await client.close()
    server._server.close()
    storage.close()
    print("  разбор пакетов: ок (запрет, разрешение и удаление различаются)")


async def main() -> None:
    await run_bridge_side()
    await run_protocol_side()
    print("СПИСКИ ВИДИМОСТИ ПРОВЕРЕНЫ")


if __name__ == "__main__":
    asyncio.run(main())
