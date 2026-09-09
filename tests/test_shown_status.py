"""Статус контакта показывает, дойдут ли от него сообщения."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge import policy
from bridge.bridge import Bridge
from bridge.config import Config
from bridge.oscar import const as C

NAMES = {C.STATUS_ONLINE: "в сети", C.STATUS_AWAY: "отошёл",
         C.STATUS_DND: "не беспокоить", C.STATUS_NA: "недоступен"}


def make_bridge() -> tuple[Bridge, list[tuple[int, int]]]:
    cfg = Config(tg_api_id=1, tg_api_hash="x")
    work = tempfile.mkdtemp()
    cfg.db = os.path.join(work, "test.db")
    cfg.tg_session = os.path.join(work, "test.session")
    cfg.photos_enabled = False
    bridge = Bridge(cfg)

    bridge.storage.uin_for_peer(555, kind="user", title="Мама", group_name="Личные")
    bridge.storage.uin_for_peer(-4001, kind="chat", title="Дача", group_name="Группы")
    bridge.storage.uin_for_peer(-100200, kind="channel", title="Новости",
                                group_name="Каналы", favourite=1)
    bridge.storage.uin_for_peer(-4002, kind="chat", title="Шумная",
                                group_name="Группы", muted=1)
    bridge._roster = bridge.storage.contacts()
    bridge._by_uin = {c.uin: c for c in bridge._roster}

    sent: list[tuple[int, int]] = []

    async def notify(uin: int, status: int) -> None:
        sent.append((uin, status))

    bridge.oscar.notify_typing = notify
    bridge.oscar.notify_status = notify
    return bridge, sent


async def main() -> None:
    bridge, sent = make_bridge()
    mom = bridge.storage.contact_by_peer(555).uin
    group = bridge.storage.contact_by_peer(-4001).uin
    favourite = bridge.storage.contact_by_peer(-100200).uin

    # «Свободен для беседы»: проходят все, статусы настоящие.
    muted = bridge.storage.contact_by_peer(-4002).uin
    await bridge.on_owner_status(C.STATUS_FREE_FOR_CHAT)
    assert bridge.status_of(group) == C.STATUS_ONLINE, NAMES[bridge.status_of(group)]
    assert bridge.status_of(muted) == C.STATUS_ONLINE, "тут доходит и заглушённое"

    # «В сети»: отсеивается только заглушённое в Telegram.
    await bridge.on_owner_status(C.STATUS_ONLINE)
    assert bridge.status_of(muted) == C.STATUS_DND, "заглушённый выглядит молчащим"
    assert bridge.status_of(group) == C.STATUS_ONLINE, "незаглушённая группа проходит"
    assert bridge.status_of(favourite) == C.STATUS_ONLINE, "избранное не заглушаем"
    assert bridge.status_of(mom) == C.STATUS_ONLINE, "личные всегда проходят"

    # «Занят»: групповое копится — показываем «недоступен», личное и избранное идут.
    sent.clear()
    await bridge.on_owner_status(C.STATUS_OCCUPIED)
    assert bridge.status_of(group) == C.STATUS_NA, "в «занят» показываем «недоступен»"
    assert bridge.status_of(favourite) == C.STATUS_ONLINE, "избранное проходит"
    assert bridge.status_of(mom) == C.STATUS_ONLINE, "личные проходят"
    assert (group, C.STATUS_NA) in sent, "смена режима должна разослать статусы"

    # «Не беспокоить»: то же, что «занят», но непрошедшее пропадает.
    await bridge.on_owner_status(C.STATUS_DND)
    assert bridge.status_of(muted) == C.STATUS_DND, "заглушённый молчит"
    assert bridge.status_of(group) == C.STATUS_DND, "обычная группа тоже молчит"
    assert bridge.status_of(favourite) == C.STATUS_ONLINE, "избранное проходит"
    assert bridge.status_of(mom) == C.STATUS_ONLINE

    # «Недоступен»: доходит только избранное, даже мама молчит.
    await bridge.on_owner_status(C.STATUS_NA)
    assert bridge.status_of(favourite) == C.STATUS_ONLINE, "избранное проходит"
    assert bridge.status_of(mom) == C.STATUS_DND, "личные тоже отсеиваются"
    assert bridge.status_of(group) == C.STATUS_DND

    # «Невидимый»: доходят только избранные собеседники.
    bridge.storage.toggle_favourite(mom)
    bridge._roster = bridge.storage.contacts()
    bridge._by_uin = {c.uin: c for c in bridge._roster}
    await bridge.on_owner_status(policy.STATUS_INVISIBLE)
    assert bridge.status_of(mom) == C.STATUS_ONLINE, "избранный собеседник проходит"
    assert bridge.status_of(favourite) == C.STATUS_DND, "избранный канал молчит"
    assert bridge.status_of(group) == C.STATUS_DND
    bridge.storage.toggle_favourite(mom)
    bridge._roster = bridge.storage.contacts()
    bridge._by_uin = {c.uin: c for c in bridge._roster}

    # Офлайн важнее подмены: если собеседника нет, так и показываем.
    bridge._statuses[group] = C.STATUS_OFFLINE
    await bridge.on_owner_status(C.STATUS_DND)
    assert bridge.status_of(group) == C.STATUS_OFFLINE, \
        "офлайн нельзя подменять на «не беспокоить»"
    await bridge.on_owner_status(C.STATUS_OCCUPIED)
    assert bridge.status_of(group) == C.STATUS_OFFLINE, \
        "офлайн нельзя подменять и на «недоступен»"
    bridge._statuses[group] = C.STATUS_ONLINE
    assert bridge.status_of(group) == C.STATUS_NA, "вернулся в сеть — снова подмена"

    # Настоящий статус собеседника не теряется: вернули режим — вернулся и он.
    bridge._statuses[mom] = C.STATUS_AWAY
    await bridge.on_owner_status(C.STATUS_FREE_FOR_CHAT)
    assert bridge.status_of(mom) == C.STATUS_AWAY, NAMES.get(bridge.status_of(mom))
    assert bridge.status_of(group) == C.STATUS_ONLINE

    # Лишних рассылок нет: повтор того же режима ничего не шлёт.
    sent.clear()
    await bridge.on_owner_status(C.STATUS_FREE_FOR_CHAT)
    assert sent == [], sent

    bridge.storage.close()
    print("  подмена статусов: ок (заглушённые — «не беспокоить», копятся — «недоступен»)")
    print("СТАТУСЫ КОНТАКТОВ ПРОВЕРЕНЫ")


if __name__ == "__main__":
    asyncio.run(main())
