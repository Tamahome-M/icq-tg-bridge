"""Удаление контакта с телефона: чат в Telegram и тема форума."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge import policy
from bridge.bridge import Bridge
from bridge.config import Config

FORUM = -1001234567890


def make_bridge() -> Bridge:
    cfg = Config(tg_api_id=1, tg_api_hash="x")
    work = tempfile.mkdtemp()
    cfg.db = os.path.join(work, "test.db")
    cfg.tg_session = os.path.join(work, "test.session")
    cfg.photos_enabled = False
    bridge = Bridge(cfg)

    deleted: list[tuple[int, bool]] = []

    async def delete_chat(peer_id, revoke=False):
        deleted.append((peer_id, revoke))
        return True

    async def title_for(peer_id):
        return "Рабочий форум", "chat"

    bridge.telegram.delete_chat = delete_chat
    bridge.telegram.title_for = title_for
    bridge.deleted = deleted
    bridge.mode = policy.ALL
    return bridge


async def main() -> None:
    # --- «Удалить» обычный чат: уходит и из Telegram, и из списка ---------
    bridge = make_bridge()
    mom = bridge.storage.uin_for_peer(555, kind="user", title="Мама", group_name="Личные")
    await bridge.on_phone_remove(mom, revoke=False)
    assert bridge.deleted == [(555, False)], bridge.deleted
    assert not bridge.storage.contacts(), "чат должен уйти из контакт-листа"

    # --- «Удалиться из его КЛ»: то же, но у обеих сторон ------------------
    dad = bridge.storage.uin_for_peer(556, kind="user", title="Папа", group_name="Личные")
    await bridge.on_phone_remove(dad, revoke=True)
    assert bridge.deleted[-1] == (556, True), bridge.deleted

    # --- запрет в настройках --------------------------------------------
    bridge.cfg.allow_delete_revoke = False
    friend = bridge.storage.uin_for_peer(557, kind="user", title="Друг", group_name="Личные")
    await bridge.on_phone_remove(friend, revoke=True)
    assert bridge.deleted[-1] == (556, True), "запрещённое удаление всё же прошло"
    assert bridge.storage.contact_by_uin(friend) is not None
    bridge.storage.close()

    # --- тема форума: в Telegram не трогаем, с телефона убираем ----------
    bridge = make_bridge()
    topic = bridge.storage.uin_for_peer(FORUM, kind="chat", title="Флуд",
                                        group_name="Рабочий форум", topic_id=9)
    other = bridge.storage.uin_for_peer(FORUM, kind="chat", title="Общее",
                                        group_name="Рабочий форум", topic_id=1)
    await bridge.on_phone_remove(topic, revoke=False)

    assert bridge.deleted == [], "тему в Telegram удалять нельзя"
    assert [c.uin for c in bridge.storage.contacts()] == [other], "тема осталась в списке"
    assert bridge.storage.contact_by_uin(topic).hidden == 1

    # Сообщения из убранной темы не доходят, из соседней — доходят.
    now = int(time.time())
    before = bridge.storage.pending_count()
    await bridge.on_telegram_message(FORUM, "Вася", "во флуде", now, 9)
    assert bridge.storage.pending_count() == before, "из убранной темы пришло сообщение"
    await bridge.on_telegram_message(FORUM, "Вася", "в общем", now, 1)
    assert bridge.storage.pending_count() == before + 1, "из обычной темы не дошло"

    # Обновление списка тему не возвращает.
    bridge.storage.uin_for_peer(FORUM, kind="chat", title="Флуд",
                                group_name="Рабочий форум", topic_id=9)
    assert len(bridge.storage.contacts()) == 1, "тема вернулась сама"

    # А поиск — возвращает.
    found = await bridge.search_chats("флуд")
    assert [f["uin"] for f in found] == [topic], found
    assert len(bridge.storage.contacts()) == 2, "после поиска тема должна вернуться"
    bridge.storage.close()

    print("  удаление чата: ок (у себя и у обеих сторон, с запретом в настройках)")
    print("  тема форума: ок (в Telegram цела, с телефона убрана, поиск возвращает)")
    print("УДАЛЕНИЕ ПРОВЕРЕНО")


if __name__ == "__main__":
    asyncio.run(main())
