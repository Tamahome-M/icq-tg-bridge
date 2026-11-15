"""Real session races and cache/auth validity found during the 1.29 audit."""
from __future__ import annotations
import asyncio
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bridge.config import Config
from bridge.db import Storage
from bridge.oscar.server import OscarServer, Session
from tests.test_session_cleanup import BrokenWriter

class PausedWriter(BrokenWriter):
    def __init__(self):
        super().__init__(None)
        self.entered, self.release = asyncio.Event(), asyncio.Event()
    async def drain(self):
        self.entered.set()
        await self.release.wait()

class DeliveryOwnership(unittest.IsolatedAsyncioTestCase):
    async def test_queued_send_does_not_write_after_session_closed(self):
        store = Storage(':memory:')
        server = OscarServer(Config(), store, None, store.contacts)
        writer = BrokenWriter(None)
        writes = []
        writer.write = writes.append
        session = Session(server, asyncio.StreamReader(), writer)
        await session._lock.acquire()
        task = asyncio.create_task(session.send_flap(5, b''))
        try:
            await asyncio.sleep(0)
            await session.close()
            session._lock.release()
            self.assertFalse(await task)
            self.assertEqual(writes, [], 'waiting sender wrote to an already closed socket')
        finally:
            if session._lock.locked():
                session._lock.release()
            await asyncio.gather(task, return_exceptions=True)
            await server.stop()
            store.close()

    async def test_failed_offline_batch_stays_ready_for_retry(self):
        for failure in ('write', 'drain', 'replacement'):
            with self.subTest(failure=failure):
                store = Storage(':memory:')
                server = OscarServer(Config(), store, None, store.contacts)
                writer = PausedWriter() if failure == 'replacement' else BrokenWriter(failure)
                old = Session(server, asyncio.StreamReader(), writer)
                old.authorized = old.ready = True
                server.session = old
                store.queue(1000001, 'Keep offline batch after interrupted write', 10)
                task = asyncio.create_task(old.send_offline_messages(100500, 1))
                try:
                    if failure == 'replacement':
                        await asyncio.wait_for(writer.entered.wait(), 1)
                        new = Session(server, asyncio.StreamReader(), BrokenWriter(None))
                        new.authorized = new.ready = True
                        server.session_arrived(new)
                        writer.release.set()
                    await asyncio.wait_for(task, 1)
                    self.assertEqual(store.pending_count(), 1)
                    self.assertEqual(store.in_flight_count(), 0,
                                     'failed batch marked a row sent after disconnect cleanup')
                    self.assertFalse(old.offline_ids)
                finally:
                    if isinstance(writer, PausedWriter):
                        writer.release.set()
                    await asyncio.gather(task, return_exceptions=True)
                    await old.close()
                    await server.stop()
                    store.close()

    async def test_late_send_cannot_remove_or_mark_replacement_sessions_queue(self):
        for with_ack in (False, True):
            for replace in (False, True):
                with self.subTest(ack=with_ack, replacement=replace):
                    store = Storage(':memory:')
                    server = OscarServer(Config(), store, None, store.contacts)
                    server.use_ack = with_ack
                    writer = PausedWriter()
                    old = Session(server, asyncio.StreamReader(), writer)
                    old.authorized = old.ready = True
                    server.session = old
                    store.queue(1000001, 'Keep until current phone receives it', 10)
                    row = store.peek_pending()[0][0]
                    pending = asyncio.create_task(server.push(1000001, 'Keep until current phone receives it', row))
                    await asyncio.wait_for(writer.entered.wait(), 1)
                    replacement = None
                    try:
                        if replace:
                            replacement = Session(server, asyncio.StreamReader(), BrokenWriter(None))
                            replacement.authorized = replacement.ready = True
                            server.session_arrived(replacement)
                            await asyncio.sleep(0)
                        else:
                            await old.close('test disconnect during write')
                        writer.release.set()
                        self.assertFalse(await asyncio.wait_for(pending, 1), 'old socket reported a current delivery')
                        self.assertEqual(store.pending_count(), 1, 'old socket lost a queued message')
                        self.assertEqual(store.in_flight_count(), 0, 'old socket stranded a message awaiting an impossible ACK')
                        self.assertFalse(server.awaiting)
                        if replacement is None:
                            replacement = Session(server, asyncio.StreamReader(), BrokenWriter(None))
                            replacement.authorized = replacement.ready = True
                            server.session_arrived(replacement)
                        self.assertTrue(await server.push(1000001, 'Retry to current phone', row))
                        self.assertEqual(store.in_flight_count(), int(with_ack))
                        self.assertEqual(store.pending_count(), int(with_ack))
                    finally:
                        writer.release.set()
                        await asyncio.gather(pending, return_exceptions=True)
                        await old.close()
                        await server.stop()
                        store.close()

class CacheAndCookieValidity(unittest.TestCase):
    def setUp(self):
        self.store = Storage(':memory:')
        self.server = OscarServer(Config(), self.store, None, self.store.contacts)
    def tearDown(self):
        self.store.close()
    def test_expired_cookie_rejected_without_another_login(self):
        for kind in ('bos', 'bart'):
            with self.subTest(kind=kind):
                with patch('bridge.oscar.server.time.time', return_value=1000), patch('bridge.oscar.server.time.monotonic', return_value=1000):
                    cookie = self.server.new_cookie(kind, 'client')
                with patch('bridge.oscar.server.time.time', return_value=1120), patch('bridge.oscar.server.time.monotonic', return_value=1120):
                    self.assertIsNone(self.server.consume_cookie(cookie))
                self.assertIsNone(self.server.consume_cookie(cookie))
    def test_cookie_before_deadline_is_single_use(self):
        with patch('bridge.oscar.server.time.time', return_value=1000), patch('bridge.oscar.server.time.monotonic', return_value=1000):
            cookie = self.server.new_cookie('bart', 'client')
        with patch('bridge.oscar.server.time.time', return_value=1119.9), patch('bridge.oscar.server.time.monotonic', return_value=1119.9):
            self.assertEqual(self.server.consume_cookie(cookie), ('bart', 'client'))
            self.assertIsNone(self.server.consume_cookie(cookie))
    def test_roster_version_changes_within_second_and_after_clock_rollback(self):
        key = [(1000001, 'Chats', 'First name', False)]
        with patch('bridge.oscar.server.time.time', return_value=1000):
            initial = self.server.ssi_version(key, 2)
            self.assertEqual(initial, self.server.ssi_version(list(key), 2))
            changed = self.server.ssi_version([(1000001, 'Chats', 'New name', False)], 2)
            self.assertGreater(changed[0], initial[0], 'same-size renamed roster kept cached version')
        with patch('bridge.oscar.server.time.time', return_value=900):
            third = self.server.ssi_version([(1000001, 'Other group', 'New name', False)], 2)
            self.assertGreater(third[0], changed[0], 'clock rollback reused an old roster stamp')
            self.assertEqual(third, self.server.ssi_version([(1000001, 'Other group', 'New name', False)], 2))

if __name__ == '__main__':
    unittest.main()
