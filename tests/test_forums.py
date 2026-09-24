"""Проверка форумов: темы становятся отдельными собеседниками."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.bridge import Bridge
from bridge.config import Config
from bridge.tg.client import GENERAL_TOPIC, reply_target, topic_of

FORUM = -1001234567890


class Reply:
    def __init__(self, forum_topic, top=None, msg=None):
        self.forum_topic = forum_topic
        self.reply_to_top_id = top
        self.reply_to_msg_id = msg


class Message:
    def __init__(self, reply=None):
        self.reply_to = reply


def make_bridge() -> Bridge:
    cfg = Config(tg_api_id=1, tg_api_hash="x")
    work = tempfile.mkdtemp()
    cfg.db = os.path.join(work, "test.db")
    # Telethon заводит файл сессии сразу при создании клиента — уводим его
    # во временный каталог, чтобы тесты не оставляли следов в проекте.
    cfg.tg_session = os.path.join(work, "test.session")
    cfg.photos_enabled = True
    cfg.photos_dir = tempfile.mkdtemp()
    bridge = Bridge(cfg)

    sent: list[tuple[int, str, int]] = []

    async def send(peer_id, text, topic_id=0):
        sent.append((peer_id, text, topic_id))
        return len(sent)

    async def title_for(peer_id):
        return "Рабочий форум", "chat"

    asked: list[tuple] = []

    async def history(peer_id, count, since, cap, topic_id=0):
        asked.append(("history", peer_id, topic_id))
        return []

    async def last_photos(peer_id, count, topic_id=0):
        asked.append(("photos", peer_id, topic_id))
        return []

    bridge.telegram.send = send
    bridge.telegram.title_for = title_for
    bridge.telegram.history = history
    bridge.telegram.last_photos = last_photos
    bridge.sent = sent
    bridge.asked = asked
    return bridge


def test_topic_detection() -> None:
    assert topic_of(Message(None)) == 0                                # обычный чат
    assert topic_of(Message(Reply(True, top=42, msg=100))) == 42        # ответ в теме
    assert topic_of(Message(Reply(True, msg=7))) == 7                   # первое в теме
    assert topic_of(Message(Reply(False, msg=5))) == 0                  # ответ вне форума
    # В General пишут как в обычную группу; в остальные темы — ответом на корень.
    assert reply_target(0) is None
    assert reply_target(GENERAL_TOPIC) is None
    assert reply_target(42) == 42
    print("  определение темы: ок")


async def main() -> None:
    test_topic_detection()
    bridge = make_bridge()

    # Темы одного форума — разные собеседники с разными UIN.
    general = bridge.storage.uin_for_peer(FORUM, kind="chat", title="Общее",
                                          group_name="Рабочий форум", topic_id=1)
    dev = bridge.storage.uin_for_peer(FORUM, kind="chat", title="Разработка",
                                      group_name="Рабочий форум", topic_id=42)
    assert general != dev, "у тем должны быть разные UIN"
    assert len({c.uin for c in bridge.storage.contacts()}) == 2
    assert {c.group_name for c in bridge.storage.contacts()} == {"Рабочий форум"}

    # Сообщение из темы попадает именно в неё.
    # Темы — групповые чаты, поэтому для проверки берём статус, который
    # пропускает всё; фильтрация по статусу проверяется отдельно.
    from bridge import policy
    bridge.mode = policy.ALL
    now = int(time.time())
    await bridge.on_telegram_message(FORUM, "Вася", "по разработке", now, 42)
    rows = bridge.storage.peek_pending()
    assert len(rows) == 1 and rows[0][1] == dev, f"сообщение ушло не в ту тему: {rows}"

    # Ответ с телефона уходит в ту же тему.
    contact = bridge.storage.contact_by_uin(dev)
    await bridge.on_phone_message(dev, "принял")
    assert bridge.sent == [(FORUM, "принял", 42)], bridge.sent

    # Ответ в обычном чате уходит без темы.
    plain = bridge.storage.uin_for_peer(555, kind="user", title="Мама", group_name="Личные")
    await bridge.on_phone_message(plain, "привет")
    assert bridge.sent[-1] == (555, "привет", 0), bridge.sent[-1]

    # Незнакомая тема заводится на лету, форум становится группой,
    # название темы берётся из Telegram.
    async def topic_title(peer_id, topic_id):
        return "Дежурство" if topic_id == 77 else ""

    bridge.telegram.topic_title = topic_title
    await bridge.on_telegram_message(FORUM, "Петя", "в новой теме", now, 77)
    fresh = bridge.storage.contact_by_peer(FORUM, 77)
    assert fresh is not None, "новая тема не завелась"
    assert fresh.group_name == "Рабочий форум", fresh.group_name
    assert fresh.title == "Дежурство", fresh.title
    assert fresh.uin not in (general, dev)
    await bridge.on_telegram_message(FORUM, "Петя", "ещё тема", now, 78)
    assert bridge.storage.contact_by_peer(FORUM, 78).title == "Тема 78"

    # Сообщение из General приходит без темы — оно должно попасть в тему 1,
    # а не завести форуму второй контакт.
    before = {c.uin for c in bridge.storage.contacts()}
    await bridge.on_telegram_message(FORUM, "Вася", "в общем", now, 0)
    rows = bridge.storage.peek_pending()
    assert rows[-1][1] == general, f"сообщение General ушло не туда: {rows[-1]}"
    assert bridge.storage.contact_by_peer(FORUM, 0) is None, "лишний контакт форума"
    assert {c.uin for c in bridge.storage.contacts()} == before
    assert bridge.storage.contact_by_uin(general).last_ts == now
    # Ответ из General уходит без темы — как в обычную группу.
    await bridge.on_phone_message(general, "ответ в общее")
    assert bridge.sent[-1] == (FORUM, "ответ в общее", GENERAL_TOPIC), bridge.sent[-1]

    # Отметка о доставке ведётся по теме, а не по чату целиком.
    bridge.storage.note_delivered(FORUM, now + 10, 42)
    assert bridge.storage.contact_by_peer(FORUM, 42).last_ts == now + 10
    assert bridge.storage.contact_by_peer(FORUM, 1).last_ts == now
    assert bridge.storage.contact_by_peer(FORUM, 78).last_ts == now

    # Команды в теме спрашивают только эту тему, а не весь форум.
    from bridge import history as history_mod
    await bridge.run_command(bridge.storage.contact_by_uin(dev),
                             history_mod.parse("!last 5"))
    await bridge.run_command(bridge.storage.contact_by_uin(dev),
                             history_mod.parse("!lastfoto"))
    assert bridge.asked == [("history", FORUM, 42), ("photos", FORUM, 42)], bridge.asked

    # В обычном чате тема не подставляется.
    bridge.asked.clear()
    await bridge.run_command(bridge.storage.contact_by_uin(plain),
                             history_mod.parse("!last"))
    assert bridge.asked == [("history", 555, 0)], bridge.asked

    bridge.storage.close()
    print("  история и фото в теме: ок (спрашиваем только свою тему)")
    print("  темы форума: ок (свои UIN, маршрутизация в обе стороны)")

    # --- догрузка при старте: отметка «доставлено» ставится своей теме -----
    bridge = make_bridge()
    dev = bridge.storage.uin_for_peer(FORUM, kind="chat", title="Разработка",
                                      group_name="Рабочий форум", topic_id=42)
    bridge.storage.note_delivered(FORUM, 1_000, 42)       # что-то уже доставляли
    bridge._reload_roster()
    bridge._unread[(FORUM, 42)] = 1

    calls: list[tuple] = []

    async def missed(peer_id, since_ts, cap, topic_id=0):
        calls.append((peer_id, since_ts, topic_id))
        return [(1_500, "Вася", "новое в теме")] if since_ts < 1_500 else []

    bridge.telegram.missed = missed
    await bridge.catch_up()
    assert calls == [(FORUM, 1_000, 42)], calls
    assert bridge.storage.pending_count() == 1, "новое должно встать в очередь"
    rows = bridge.storage.peek_pending()
    assert rows[0][3] == 1_500, "в очереди должно быть настоящее время сообщения"
    assert bridge.storage.contact_by_uin(dev).last_ts == 1_500, \
        "отметка «доставлено» должна встать у самой темы"

    # Второй запуск: та же тема больше ничего не догружает.
    calls.clear()
    await bridge.catch_up()
    assert calls == [(FORUM, 1_500, 42)], calls
    assert bridge.storage.pending_count() == 1, "повторной догрузки быть не должно"
    bridge.storage.close()
    print("  догрузка тем: ок (отметка у темы, без повторов)")

    # --- лишний контакт «всего форума» уходит при обновлении списка --------
    bridge = make_bridge()
    shell = bridge.storage.uin_for_peer(FORUM, kind="chat", title="Рабочий форум",
                                        group_name="Группы", position=9999)
    general = bridge.storage.uin_for_peer(FORUM, kind="chat", title="Общее",
                                          group_name="Рабочий форум", topic_id=1)
    plain = bridge.storage.uin_for_peer(555, kind="user", title="Мама", group_name="Личные")
    marked = bridge.storage.mark_forum_shells({FORUM})
    assert [c.uin for c in marked] == [shell], marked
    alive = {c.uin for c in bridge.storage.contacts()}
    assert alive == {general, plain}, alive
    assert bridge.storage.mark_forum_shells({FORUM}) == [], "повторно помечать нечего"
    # Сообщение без темы после этого идёт в General, а не воскрешает оболочку.
    bridge.mode = policy.ALL
    await bridge.on_telegram_message(FORUM, "Вася", "снова в общем", now, 0)
    assert bridge.storage.peek_pending()[-1][1] == general
    assert bridge.storage.contact_by_uin(shell).gone == 1
    bridge.storage.close()
    print("  оболочка форума: ок (убрана, General идёт в тему 1)")
    print("ФОРУМЫ ПРОВЕРЕНЫ")


if __name__ == "__main__":
    asyncio.run(main())
