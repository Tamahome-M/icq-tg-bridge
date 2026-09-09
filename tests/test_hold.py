"""Проверка того, что «занят» придерживает сообщения, а «не беспокоить» — нет."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge import history, policy
from bridge.bridge import Bridge
from bridge.config import Config
from bridge.oscar import const as C


def make_bridge() -> Bridge:
    cfg = Config(tg_api_id=1, tg_api_hash="x")
    work = tempfile.mkdtemp()
    cfg.db = os.path.join(work, "test.db")
    # Telethon заводит файл сессии сразу при создании клиента — уводим его
    # во временный каталог, чтобы тесты не оставляли следов в проекте.
    cfg.tg_session = os.path.join(work, "test.session")
    cfg.photos_enabled = False
    cfg.busy_hold_minutes = 30
    bridge = Bridge(cfg)
    bridge.storage.uin_for_peer(555, kind="user", title="Мама", group_name="Личные")
    bridge.storage.uin_for_peer(-4001, kind="chat", title="Дача", group_name="Группы")
    # Заглушённый в Telegram чат: в «не беспокоить» он молчит.
    bridge.storage.uin_for_peer(-4002, kind="chat", title="Шумная", group_name="Группы",
                                muted=1)
    bridge.storage.uin_for_peer(-100200, kind="channel", title="Новости",
                                group_name="Каналы", favourite=1)
    bridge._roster = bridge.storage.contacts()
    return bridge


def uin_of(bridge: Bridge, peer_id: int) -> int:
    return bridge.storage.contact_by_peer(peer_id).uin


async def main() -> None:
    # --- «занят»: групповое придерживается, личное проходит ---------------
    bridge = make_bridge()
    await bridge.on_owner_status(C.STATUS_OCCUPIED)
    assert bridge.mode == policy.BUSY

    now = int(time.time())
    await bridge.on_telegram_message(-4001, "Вася", "в группе", now)
    await bridge.on_telegram_message(555, "", "личное", now)

    assert bridge.storage.held_count() == 1, "групповое должно было придержаться"
    assert bridge.storage.pending_count() == 1, "личное должно было пойти на телефон"

    # Придержанное постарше окна — уже не отдаём.
    old = now - 45 * 60
    bridge.storage.hold(uin_of(bridge, -4001), "старое", old, 30)
    assert bridge.storage.held_count() == 2

    # --- возврат в сеть: приходит только свежее ---------------------------
    await bridge.on_owner_status(C.STATUS_ONLINE)
    assert bridge.storage.held_count() == 0, "придержанное должно было разобраться"
    assert bridge.storage.pending_count() == 2, \
        f"ждали личное и свежее групповое, вышло {bridge.storage.pending_count()}"
    texts = [row[2] for row in bridge.storage.peek_pending()]
    assert any("в группе" in t for t in texts), texts
    assert not any("старое" in t for t in texts), texts
    bridge.storage.close()

    # --- «не беспокоить»: молчит то, что заглушено в Telegram -------------
    bridge = make_bridge()
    await bridge.on_owner_status(C.STATUS_DND)
    assert bridge.mode == policy.PERSONAL

    await bridge.on_telegram_message(-4002, "Вася", "из заглушённой", int(time.time()))
    assert bridge.storage.held_count() == 0, "«не беспокоить» ничего не копит"
    assert bridge.storage.pending_count() == 0, "заглушённый чат не должен доходить"

    # Незаглушённая группа проходит: так настроено в самом Telegram.
    await bridge.on_telegram_message(-4001, "Вася", "из обычной", int(time.time()))
    assert bridge.storage.pending_count() == 1, "незаглушённый чат должен доходить"

    await bridge.on_owner_status(C.STATUS_ONLINE)
    assert bridge.storage.pending_count() == 1, "пропущенное не догоняет"
    bridge.storage.close()

    # --- из «занят» сразу в «не беспокоить»: придержанное не всплывает -----
    bridge = make_bridge()
    await bridge.on_owner_status(C.STATUS_OCCUPIED)
    await bridge.on_telegram_message(-4001, "Вася", "в группе", int(time.time()))
    assert bridge.storage.held_count() == 1
    await bridge.on_owner_status(C.STATUS_DND)
    assert bridge.storage.pending_count() == 0, "в тишину придержанное отдавать нельзя"
    assert bridge.storage.held_count() == 0, "и копить дальше тоже незачем"
    bridge.storage.close()

    # --- команда !fav: чат становится избранным и остаётся им -------------
    bridge = make_bridge()
    group = bridge.storage.contact_by_peer(-4001)
    assert not group.favourite

    await bridge.run_command(group, history.parse("!fav"))
    assert bridge.storage.contact_by_peer(-4001).favourite == 1, "!fav не пометил чат"
    assert bridge.storage.pending_count() == 1, "ответ на команду не пришёл"

    # Обновление списка диалогов не должно сбивать ручной выбор.
    bridge.storage.uin_for_peer(-4001, kind="chat", title="Дача",
                                group_name="Группы", favourite=0)
    assert bridge.storage.contact_by_peer(-4001).favourite == 1, \
        "обновление списка стёрло ручную отметку"

    # В обычном «в сети» избранная группа теперь проходит фильтр.
    await bridge.on_owner_status(C.STATUS_ONLINE)
    bridge._roster = bridge.storage.contacts()
    before = bridge.storage.pending_count()
    await bridge.on_telegram_message(-4001, "Вася", "привет", int(time.time()))
    assert bridge.storage.pending_count() == before + 1, "избранная группа не прошла"

    # Повторный !fav снимает отметку, и группа снова отсеивается.
    group = bridge.storage.contact_by_peer(-4001)
    await bridge.run_command(group, history.parse("!fav"))
    assert bridge.storage.contact_by_peer(-4001).favourite == 0
    before = bridge.storage.pending_count()
    await bridge.on_telegram_message(-4001, "Вася", "ещё раз", int(time.time()))
    assert bridge.storage.pending_count() == before, "неизбранная группа прошла фильтр"
    bridge.storage.close()

    # --- накопленное в очереди тоже проходит через фильтр статуса ---------
    bridge = make_bridge()
    now = int(time.time())
    group = bridge.storage.contact_by_peer(-4001)
    mom = bridge.storage.contact_by_peer(555)

    # Телефон был не в сети: в очередь попало и групповое, и личное.
    bridge.storage.queue(group.uin, "из группы", 30)
    bridge.storage.queue(mom.uin, "личное", 30)
    assert bridge.storage.pending_count() == 2

    # Владелец входит в «не беспокоить»: групповое доставлять нельзя.
    await bridge.on_owner_status(C.STATUS_DND)
    muted = bridge.storage.contact_by_peer(-4002)
    assert bridge.verdict_for(muted.uin) == "drop", "заглушённое должно отсеиваться"
    assert bridge.verdict_for(group.uin) == "send", "незаглушённое должно доходить"
    assert bridge.verdict_for(mom.uin) == "send", "личное должно доходить"

    # В «занят» то же самое, но с сохранением до смены статуса.
    await bridge.on_owner_status(C.STATUS_OCCUPIED)
    assert bridge.verdict_for(group.uin) == "hold", "в «занят» надо придержать"

    # В «свободен для беседы» проходит всё.
    await bridge.on_owner_status(C.STATUS_FREE_FOR_CHAT)
    assert bridge.verdict_for(group.uin) == "send"
    bridge.storage.close()

    # --- ответ на команду доходит и в «не беспокоить» ---------------------
    bridge = make_bridge()
    group = bridge.storage.contact_by_peer(-4001)
    await bridge.on_owner_status(C.STATUS_DND)

    await bridge.reply(bridge.storage.contact_by_peer(-4002), "ответ на команду")
    rows = bridge.storage.peek_pending()
    assert len(rows) == 1 and rows[0][4] is True, \
        "ответ на команду должен быть помечен как обязательный"

    # Обычное сообщение из заглушённого чата в тишине доставляться не должно.
    silent = bridge.storage.contact_by_peer(-4002)
    await bridge.oscar.deliver(silent.uin, "обычное из заглушённой")
    rows = bridge.storage.peek_pending()
    assert [r[4] for r in rows] == [True, False], [r[4] for r in rows]

    # Отправитель обязан пропустить помеченное и отсеять обычное.
    server = bridge.oscar
    sent: list[str] = []

    class Phone:
        ready, closed = True, False

        async def deliver(self, uin, text, wait_ack=False, row_id=None):
            sent.append(text)
            return True

        async def notify_status(self, uin, status): pass

    server.session = Phone()
    server.use_ack = False
    await server.drain_queue()
    assert sent == ["ответ на команду"], sent
    assert bridge.storage.pending_count() == 0, "очередь должна разобраться"
    bridge.storage.close()

    print("  ответ на команду: доходит даже в «не беспокоить» — ок")
    print("  очередь при смене статуса: ок (групповое не прорывается в тишину)")
    print("  «занят»: придерживает и отдаёт свежее — ок")
    print("  «не беспокоить»: не копит и не догоняет — ок")
    print("  команда !fav: переключает избранное и переживает обновление списка — ок")
    print("ПРИДЕРЖАНИЕ ПРОВЕРЕНО")


if __name__ == "__main__":
    asyncio.run(main())
