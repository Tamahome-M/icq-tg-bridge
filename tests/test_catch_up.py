"""Граничная секунда догрузки, повторы событий и сохранение ID в базе."""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import sqlite3
import sys
import tempfile
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon import types

from bridge.bridge import Bridge
from bridge.config import Config

PEER = 555
STAMP = 1_800_000_000


def message(number, stamp=STAMP, text="одинаковый текст", outgoing=False):
    return types.Message(id=number, peer_id=types.PeerUser(PEER),
                         date=dt.datetime.fromtimestamp(stamp, dt.timezone.utc),
                         message=text, out=outgoing)


class History:
    def __init__(self, rows):
        self.rows = rows
        self.during_fetch = None

    async def get_entity(self, peer):
        return types.User(id=peer, first_name="Друг")

    async def iter_messages(self, peer, **kwargs):
        if self.during_fetch is not None:
            callback, self.during_fetch = self.during_fetch, None
            await callback()
        for row in self.rows[:kwargs["limit"]]:
            yield row


def make_bridge(path=":memory:"):
    cfg = Config(tg_api_id=1, tg_api_hash="x", tg_session="", db=path,
                 photos_enabled=False, render_enabled=False)
    bridge = Bridge(cfg)
    bridge.storage.uin_for_peer(PEER, kind="user", title="Друг", group_name="Личные")
    bridge._unread[(PEER, 0)] = 3
    return bridge


async def receive(bridge, msg):
    await bridge.telegram._on_new_message(NS(message=msg, is_private=True))


async def seed(bridge):
    await receive(bridge, message(1, text="уже доставлено"))
    for row in bridge.storage.peek_pending():
        bridge.storage.drop_pending(row[0])
    assert bridge.storage.contact_by_peer(PEER).last_ts == STAMP


def pending_texts(bridge):
    return [row[2] for row in bridge.storage.peek_pending()]


async def run_boundary_and_restart():
    with tempfile.TemporaryDirectory() as work:
        path = os.path.join(work, "bridge.db")
        rows = [message(4, STAMP + 1, outgoing=True), message(3), message(2),
                message(1, text="уже доставлено"), message(9, STAMP - 1, "старое")]
        bridge = make_bridge(path)
        bridge.telegram.client = History(rows)
        try:
            await seed(bridge)
            await bridge.catch_up()
            assert pending_texts(bridge) == ["одинаковый текст", "одинаковый текст"], pending_texts(bridge)
            await bridge.catch_up()
            await receive(bridge, message(3))
            assert bridge.storage.pending_count() == 2, "повтор догрузки или события продублировал сообщение"
        finally:
            bridge.storage.close()
        restarted = make_bridge(path)
        restarted.telegram.client = History(rows)
        try:
            await restarted.catch_up()
            assert restarted.storage.pending_count() == 2, "после перезапуска забылись ID сообщений"
        finally:
            restarted.storage.close()
    print("  одна секунда: два одинаковых текста с разными ID доходят без повторов, включая перезапуск — ок")


async def run_live_race():
    bridge = make_bridge()
    source = History([message(3, STAMP + 1, "новое пропущенное"),
                      message(2, STAMP + 1, "текущее"),
                      message(4, STAMP, "пропущенное в граничной секунде"),
                      message(1, text="уже доставлено")])
    bridge.telegram.client = source
    try:
        await seed(bridge)

        async def live():
            await receive(bridge, message(2, STAMP + 1, "текущее"))
        source.during_fetch = live
        await bridge.catch_up()
        assert pending_texts(bridge) == ["текущее", "пропущенное в граничной секунде", "новое пропущенное"], \
            pending_texts(bridge)
        await bridge.catch_up()
        assert bridge.storage.pending_count() == 3
        assert bridge.storage.contact_by_peer(PEER).last_ts == STAMP + 1
    finally:
        bridge.storage.close()
    print("  события во время догрузки: новые не теряются, уже принятые не повторяются — ок")


async def run_topic_ids():
    bridge = make_bridge()
    try:
        other = bridge.storage.uin_for_peer(PEER, kind="chat", title="Тема", group_name="Темы", topic_id=42)
        assert await bridge.on_telegram_message(PEER, "", "личное", STAMP, message_id=1)
        assert await bridge.on_telegram_message(PEER, "", "в теме", STAMP, 42, message_id=1)
        assert bridge.storage.pending_count() == 2
        assert bridge.storage.message_processed(other, 1)
    finally:
        bridge.storage.close()
    print("  ID учитывается отдельно для каждого чата и темы — ок")


async def run_atomic_queue():
    bridge = make_bridge()
    try:
        uin = bridge.storage.contact_by_peer(PEER).uin
        bridge.storage.conn.execute("""
            CREATE TEMP TRIGGER fail_pending BEFORE INSERT ON pending
            BEGIN SELECT RAISE(ABORT, 'test queue failure'); END
        """)
        try:
            bridge.storage.queue(uin, "первое", 30, ts=STAMP, message_id=1)
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("ошибка вставки должна была сработать")
        assert not bridge.storage.message_processed(uin, 1), "неудачная запись сохранила ID"
        assert bridge.storage.contact_by_peer(PEER).last_ts == 0, "неудачная запись продвинула отметку времени"
        bridge.storage.conn.execute("DROP TRIGGER fail_pending")
        assert bridge.storage.queue(uin, "первое", 30, ts=STAMP, message_id=1)
        assert not bridge.storage.queue(uin, "повтор", 30, ts=STAMP, message_id=1)
        assert pending_texts(bridge) == ["первое"]
    finally:
        bridge.storage.close()
    print("  ошибка БД: очередь, ID и отметка времени откатываются вместе — ок")


async def run_legacy_database():
    with tempfile.TemporaryDirectory() as work:
        path = os.path.join(work, "bridge.db")
        bridge = make_bridge(path)
        bridge.telegram.client = History([])
        await seed(bridge)
        # В прежних базах были время и очередь, но ещё не было ID.
        bridge.storage.conn.execute("DROP TABLE processed_messages")
        bridge.storage.close()
        migrated = make_bridge(path)
        migrated.telegram.client = History([message(2, text="новое в ту же секунду"),
                                              message(1, text="уже доставлено")])
        try:
            await migrated.catch_up()
            # Без старых ID граница перечитывается один раз целиком:
            # лучше повтор старого, чем потеря нового в той же секунде.
            assert pending_texts(migrated) == ["уже доставлено", "новое в ту же секунду"]
            await migrated.catch_up()
            assert migrated.storage.pending_count() == 2
        finally:
            migrated.storage.close()
    print("  старая база: граничная секунда перечитывается один раз, новые сообщения не теряются — ок")


async def main():
    await run_boundary_and_restart()
    await run_live_race()
    await run_topic_ids()
    await run_atomic_queue()
    await run_legacy_database()
    print("ДОГРУЗКА ПО ID СООБЩЕНИЙ ПРОВЕРЕНА")


if __name__ == "__main__":
    asyncio.run(main())
