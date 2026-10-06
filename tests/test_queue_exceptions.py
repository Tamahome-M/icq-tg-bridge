"""Исключения фильтра доставки сохраняются в очереди до отправки телефону."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge import policy
from bridge.bridge import Bridge
from bridge.config import Config

PEER = -4001


class Phone:
    ready, closed = True, False

    def __init__(self):
        self.sent = []

    async def deliver(self, uin, text, **kwargs):
        self.sent.append((uin, text, kwargs.get("url", ""), kwargs.get("attach", "")))
        return True


def make_bridge(path=":memory:"):
    cfg = Config(tg_api_id=1, tg_api_hash="x", tg_session="", db=path,
                 photos_enabled=False, render_enabled=False)
    bridge = Bridge(cfg)
    bridge.storage.uin_for_peer(PEER, kind="chat", title="Группа", group_name="Группы",
                                muted=1)
    return bridge


async def drain(bridge):
    phone = Phone()
    bridge.oscar.session = phone
    bridge.oscar.use_ack = False
    await bridge.oscar.drain_queue()
    return phone.sent


async def run_mentions_and_calls():
    for mode in (policy.UNMUTED, policy.BUSY, policy.QUIET):
        bridge = make_bridge()
        try:
            contact = bridge.storage.contact_by_peer(PEER)
            # Обычное было принято раньше, когда разрешалось всё: при
            # отправке оно по-прежнему должно пройти текущий фильтр.
            bridge.mode = policy.ALL
            await bridge.on_telegram_message(PEER, "", "обычное")
            bridge.mode = mode
            assert await bridge.on_telegram_message(PEER, "", "упоминание", mention=True,
                                                     attach="photo:123")
            assert await bridge.on_telegram_message(PEER, "", "звонок", always=True)
            await bridge.reply(contact, "ответ", url="http://example.test/r/1")
            sent = await drain(bridge)
            assert [row[1] for row in sent] == ["упоминание", "звонок", "ответ"], (mode, sent)
            assert sent[0][3] == "photo:123", "вложение упоминания потерялось"
            assert sent[2][2] == "http://example.test/r/1", "ссылка ответа потерялась"
            assert bridge.storage.pending_count() == 0
            assert bridge.storage.held_count() == (1 if mode == policy.BUSY else 0)
        finally:
            bridge.storage.close()
    print("  очередь: упоминания, звонки и ответы доходят; обычное фильтруется — ок")


async def run_status_changes():
    for mode in (policy.FAVOURITES, policy.INVISIBLE):
        for favourite in (False, True):
            bridge = make_bridge()
            try:
                contact = bridge.storage.contact_by_peer(PEER)
                bridge.mode = policy.UNMUTED
                assert await bridge.on_telegram_message(PEER, "", "упоминание", mention=True)
                assert await bridge.on_telegram_message(PEER, "", "звонок", always=True)
                if favourite:
                    bridge.storage.toggle_favourite(contact.uin)
                bridge.mode = mode
                sent = await drain(bridge)
                expected = ["упоминание", "звонок"] if favourite else ["звонок"]
                assert [row[1] for row in sent] == expected, (mode, favourite, sent)
            finally:
                bridge.storage.close()
    print("  смена статуса: упоминание требует избранного, звонок приходит всегда — ок")


async def run_disabled_mentions():
    bridge = make_bridge()
    try:
        bridge.mode = policy.QUIET
        bridge.cfg.mentions_through = False
        assert not await bridge.on_telegram_message(PEER, "", "выключенное", mention=True)
        assert bridge.storage.pending_count() == 0
        # Выключатель учитывается и для уже накопленного упоминания.
        bridge.cfg.mentions_through = True
        assert await bridge.on_telegram_message(PEER, "", "накопленное", mention=True)
        bridge.cfg.mentions_through = False
        assert await bridge.on_telegram_message(PEER, "", "звонок", mention=True, always=True)
        assert [row[1] for row in await drain(bridge)] == ["звонок"]
    finally:
        bridge.storage.close()
    print("  отключение упоминаний не отключает звонки — ок")


async def run_restart():
    with tempfile.TemporaryDirectory() as work:
        path = os.path.join(work, "bridge.db")
        bridge = make_bridge(path)
        bridge.mode = policy.QUIET
        try:
            assert await bridge.on_telegram_message(PEER, "", "упоминание", mention=True)
            assert await bridge.on_telegram_message(PEER, "", "звонок", always=True)
        finally:
            bridge.storage.close()
        restarted = make_bridge(path)
        try:
            restarted.mode = policy.QUIET
            assert [row[1] for row in await drain(restarted)] == ["упоминание", "звонок"]
            assert restarted.storage.pending_count() == 0
        finally:
            restarted.storage.close()
    print("  перезапуск: очередь сохраняет исключения фильтра — ок")


async def run_retry():
    bridge = make_bridge()
    try:
        bridge.mode = policy.QUIET
        assert await bridge.on_telegram_message(PEER, "", "упоминание", mention=True)
        assert await bridge.on_telegram_message(PEER, "", "звонок", always=True)
        phone = Phone()
        bridge.oscar.session = phone
        bridge.oscar.use_ack = bridge.oscar.ack_works = True
        await bridge.oscar.drain_queue()
        assert bridge.storage.in_flight_count() == 2, "оба сообщения должны ждать подтверждения"
        bridge.oscar.session_gone(phone)
        assert bridge.storage.in_flight_count() == 0
        assert [row[1] for row in await drain(bridge)] == ["упоминание", "звонок"]
        assert bridge.storage.pending_count() == 0
    finally:
        bridge.storage.close()
    print("  обрыв до подтверждения: исключения действуют и при повторной отправке — ок")


async def run_migration():
    with tempfile.TemporaryDirectory() as work:
        path = os.path.join(work, "legacy.db")
        with sqlite3.connect(path) as conn:
            conn.executescript("""
                CREATE TABLE pending (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uin INTEGER NOT NULL, text TEXT NOT NULL, ts INTEGER NOT NULL,
                    sent_at INTEGER NOT NULL DEFAULT 0, forced INTEGER NOT NULL DEFAULT 0,
                    url TEXT NOT NULL DEFAULT '', attach TEXT NOT NULL DEFAULT ''
                );
                INSERT INTO pending (uin, text, ts, forced) VALUES
                    (1000001, 'обычное', 0, 0), (1000001, 'ответ', 0, 1);
            """)
        bridge = make_bridge(path)
        try:
            bridge.mode = policy.QUIET
            # Старые записи сохраняются; миграция не делает обычное
            # сообщение обязательным и не теряет обязательный ответ.
            assert bridge.storage.pending_count() == 2
            sent = await drain(bridge)
            assert len(sent) == 1 and sent[0][1].endswith("ответ"), sent
            assert bridge.storage.pending_count() == 0
        finally:
            bridge.storage.close()
    print("  старая база: сообщения сохранены, прежние правила доставки действуют — ок")


async def main():
    await run_mentions_and_calls()
    await run_status_changes()
    await run_disabled_mentions()
    await run_restart()
    await run_retry()
    await run_migration()
    print("ИСКЛЮЧЕНИЯ ФИЛЬТРА В ОЧЕРЕДИ ПРОВЕРЕНЫ")


if __name__ == "__main__":
    asyncio.run(main())
