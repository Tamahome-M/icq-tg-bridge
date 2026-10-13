"""Own-device reads must remove only read offline deliveries, never newer messages."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from telethon import events, types, utils
from bridge.bridge import Bridge
from bridge.config import Config
from bridge.db import Storage
from bridge.history import MissedMessage
from bridge.max.client import MaxSide, to_peer
from bridge.tg.client import TelegramSide, Dialog
from bridge.express.client import ExpressSide, chat_peer, thread_topic
from bridge.express.web import JS_WATCH, ExpressClient
from tests.test_express import FakeExpress, GROUP, THREAD, PERSONAL, BOSS, raw_event
from tests.test_max import FakeMax, DIALOG_ID, ME, MOM, message

STAMP = 1_800_000_000


def contact(store, peer=555, topic=0):
    return store.uin_for_peer(peer, topic_id=topic, kind="chat", title="chat", group_name="group")


def texts(store):
    return [r[2] for r in store.peek_pending()]


class StorageReads(unittest.TestCase):
    def setUp(self):
        self.store = Storage(":memory:")
        self.addCleanup(self.store.close)

    def test_telegram_prefix_media_other_chat_and_forced_replies(self):
        uin, other = contact(self.store), contact(self.store, 556)
        for mid in (99, 100, 101):
            self.store.queue(uin, str(mid), 30, ts=STAMP, message_id=mid, attach=f"photo:{mid}")
        self.store.queue(other, "other chat", 30, message_id=99)
        self.store.queue(uin, "command reply", 30, forced=True, message_id=1)
        self.store.queue(uin, "no source ID", 30)
        self.assertEqual(self.store.drop_read_inbox(555, 100, by_id=True), (2, 0))
        self.assertEqual(texts(self.store), ["101", "other chat", "command reply", "no source ID"])
        self.assertFalse(self.store.queue(uin, "replayed read photo", 30, message_id=100))
        self.assertEqual(self.store.peek_pending()[0][6], "photo:101")

    def test_topic_read_does_not_clear_other_topics(self):
        for topic, mid in ((0, 40), (42, 45), (42, 51), (43, 46)):
            self.store.queue(contact(self.store, topic=topic), f"{topic}:{mid}", 30, message_id=mid)
        self.assertEqual(self.store.drop_read_inbox(555, 50, by_id=True, topic_id=42), (1, 0))
        self.assertEqual(texts(self.store), ["0:40", "42:51", "43:46"])
        self.assertEqual(self.store.drop_read_inbox(555, 50, by_id=True), (2, 0))
        self.assertEqual(texts(self.store), ["42:51"])

    def test_read_before_slow_message_or_new_contact_and_held_release(self):
        self.store.drop_read_inbox(555, 100, by_id=True, topic_id=42)
        uin = contact(self.store, topic=42)
        self.assertFalse(self.store.queue(uin, "slow event", 30, message_id=99, ts=STAMP))
        self.assertTrue(self.store.message_processed(uin, 99))
        self.assertEqual(self.store.contact_by_uin(uin).last_ts, STAMP)
        self.store.hold(uin, "read held", STAMP, 30, message_id=98)
        self.assertEqual(self.store.held_count(), 0)
        self.store.hold(uin, "new held", STAMP, 30, message_id=101)
        self.assertEqual(self.store.drop_read_inbox(555, 101, by_id=True, topic_id=42), (0, 1))
        self.assertFalse(self.store.queue(uin, "already taken held", 30, source_message_id=101))

    def test_millisecond_boundary_and_legacy_second_are_conservative(self):
        for peer, ident in ((to_peer(10), 999999999999999), (chat_peer(GROUP), GROUP)):
            uin = contact(self.store, peer)
            for suffix, offset in (("read", 900), ("unread", 901)):
                self.store.queue(uin, suffix, 30, ts=STAMP, message_id=f"{ident}{suffix}",
                                 source_ts=STAMP * 1000 + offset, attach="video:123")
            self.store.queue(uin, "legacy boundary", 30, ts=STAMP, message_id="old-id")
            self.store.queue(uin, "legacy older", 30, ts=STAMP-1, message_id="older-id")
            self.assertEqual(self.store.drop_read_inbox(peer, STAMP*1000+900, by_id=False), (2, 0))
            self.assertFalse(self.store.queue(uin, "slow read", 30, ts=STAMP,
                                             message_id="delayed", source_ts=STAMP*1000+899))
        self.assertEqual(texts(self.store), ["unread", "legacy boundary"] * 2)

    def test_marks_survive_restart_and_never_move_backwards(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "bridge.db")
            store = Storage(path)
            uin = contact(store)
            store.drop_read_inbox(555, 100, by_id=True)
            store.close()
            store = Storage(path)
            try:
                store.drop_read_inbox(555, 90, by_id=True)
                self.assertFalse(store.queue(uin, "read catch-up", 30, message_id=95))
                self.assertTrue(store.queue(uin, "new catch-up", 30, message_id=101))
                self.assertEqual(texts(store), ["new catch-up"])
            finally:
                store.close()

    def test_failed_pruning_rolls_back_queue_held_and_read_marker(self):
        uin = contact(self.store)
        self.store.queue(uin, "pending", 30, message_id=99)
        self.store.hold(uin, "held", STAMP, 30, message_id=98)
        self.store.conn.execute("CREATE TEMP TRIGGER fail_read BEFORE DELETE ON held "
                                "BEGIN SELECT RAISE(ABORT, 'test deletion failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.drop_read_inbox(555, 100, by_id=True)
        self.assertEqual(texts(self.store), ["pending"])
        self.assertEqual(self.store.held_count(), 1)
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM inbox_reads").fetchone()[0], 0)
        self.store.conn.execute("DROP TRIGGER fail_read")
        self.assertEqual(self.store.drop_read_inbox(555, 100, by_id=True), (1, 1))

    def test_migration_keeps_unknown_sources_and_bad_marks_do_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "bridge.db")
            with sqlite3.connect(path) as conn:
                conn.executescript("""CREATE TABLE pending (id INTEGER PRIMARY KEY,
                    uin INTEGER NOT NULL, text TEXT NOT NULL, ts INTEGER NOT NULL);
                    INSERT INTO pending VALUES (1,1000001,'legacy unknown',1800000000);""")
            store = Storage(path)
            try:
                contact(store)
                store.drop_read_inbox(555, 999999, by_id=True)
                self.assertEqual(texts(store), ["legacy unknown"])
                for mark in (0, -1):
                    self.assertEqual(store.drop_read_inbox(555, mark, by_id=True), (0, 0))
            finally:
                store.close()

    def test_timestamp_survives_queue_busy_hold_and_release(self):
        uin = contact(self.store, to_peer(10))
        self.store.queue(uin, "photo", 30, message_id=123, ts=STAMP,
                         attach="photo:123", source_ts=STAMP*1000+901)
        row = self.store.peek_pending()[0]
        mid, exact = self.store.pending_source(row[0])
        self.store.drop_pending(row[0])
        self.store.hold(uin, "photo", STAMP, 30, mid, "photo:123", exact)
        taken = self.store.take_held(with_source=True)[0]
        self.assertEqual(taken[3:], ("123", "photo:123", STAMP*1000+901))
        self.store.drop_read_inbox(to_peer(10), STAMP*1000+900, by_id=False)
        self.assertTrue(self.store.queue(uin, taken[1], 30, ts=taken[2],
                                         source_message_id=taken[3], source_ts=taken[5]))


class AdapterReads(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.cfg = Config(tg_api_id=1, tg_api_hash="test", db=":memory:", photos_enabled=False,
                          tg_session=str(Path(self.folder.name)/"tg.session"))
        self.bridge = Bridge(self.cfg)
        self.addCleanup(self.bridge.storage.close)
        self.addAsyncCleanup(self.bridge.telegram.stop)

    async def test_telegram_own_reads_contents_and_topic_events(self):
        side = self.bridge.telegram
        uin, topic, other = [contact(self.bridge.storage, topic=t) for t in (0, 42, 43)]
        for u in (uin, topic, other):
            self.bridge.storage.queue(u, str(u), 30, message_id=99)
        await side._on_inbox_read(events.MessageRead.Event(types.PeerUser(555), message_ids=[99], contents=True))
        self.assertEqual(self.bridge.storage.pending_count(), 3)
        update = types.UpdateReadChannelDiscussionInbox(channel_id=123, top_msg_id=42, read_max_id=100)
        peer = utils.get_peer_id(types.PeerChannel(123))
        for t in (42, 43):
            self.bridge.storage.queue(contact(self.bridge.storage, peer, t), f"channel:{t}", 30, message_id=99)
        await side._on_topic_read(update)
        self.assertNotIn("channel:42", texts(self.bridge.storage))
        self.assertIn("channel:43", texts(self.bridge.storage))
        await side._on_inbox_read(events.MessageRead.Event(types.PeerUser(555), max_id=100))
        self.assertEqual(texts(self.bridge.storage), ["channel:43"])

    async def test_telegram_registers_both_read_directions_once(self):
        side = self.bridge.telegram
        await side.stop()
        handlers = []
        side.client = NS(connect=AsyncMock(), is_user_authorized=AsyncMock(return_value=True),
                         get_me=AsyncMock(return_value=types.User(1, first_name="owner")),
                         disconnect=AsyncMock(), add_event_handler=lambda cb, builder: handlers.append((cb, builder)))
        await side.start()
        await side.start()
        readers = [builder for _, builder in handlers if isinstance(builder, events.MessageRead)]
        self.assertEqual(sorted(builder.inbox for builder in readers), [False, True])
        self.assertEqual(sum(isinstance(builder, events.Raw) for _, builder in handlers), 1)

    async def test_native_dialog_snapshot_uses_owner_marker(self):
        self.cfg.max_contacts = False
        maximum = MaxSide(self.cfg, None, client=FakeMax())
        maximum.me_id = ME
        for c in maximum.client.chats:
            c.participants = {ME: STAMP*1000+900, MOM: STAMP*1000+999}
        rows = await maximum.dialogs()
        self.assertTrue(rows)
        self.assertTrue(all(d.read_inbox == STAMP*1000+900 for d in rows))
        side = self.bridge.telegram
        side.cfg.grouping = "type"
        raw = NS(entity=types.User(555, first_name="chat"), name="chat", unread_count=2,
                 dialog=NS(read_inbox_max_id=100))
        async def dialogs(**_):
            yield raw
        side.client.iter_dialogs = dialogs
        self.assertEqual((await side.dialogs())[0].read_inbox, 100)

    async def test_busy_sift_keeps_exact_time_and_prunes_only_read_held_media(self):
        peer = to_peer(10)
        uin = contact(self.bridge.storage, peer)
        for mid, exact in ((123, 901), (124, 902)):
            self.bridge.storage.queue(uin, str(mid), 30, ts=STAMP, message_id=mid,
                                      attach=f"photo:{mid}", source_ts=STAMP*1000+exact)
        self.bridge.oscar.verdict_for = lambda *_: "hold"
        self.assertEqual(self.bridge.oscar.sift_pending(), [])
        self.assertEqual(self.bridge.storage.held_count(), 2)
        await self.bridge.on_inbox_read(peer, STAMP*1000+901)
        remaining = self.bridge.storage.take_held(with_source=True)
        self.assertEqual(remaining[0][3:], ("124", "photo:124", STAMP*1000+902))

    async def test_read_after_disconnect_also_clears_unconfirmed_message(self):
        uin = contact(self.bridge.storage)
        self.bridge.storage.queue(uin, "unconfirmed", 30, message_id=99)
        self.bridge.storage.mark_sent(self.bridge.storage.peek_pending()[0][0])
        await self.bridge.on_inbox_read(555, 100)
        self.assertEqual(self.bridge.storage.pending_count(), 0)

    async def test_max_self_read_is_not_a_peer_read_receipt(self):
        from pymax.types.events import MessageReadEvent
        peer = to_peer(10)
        uin = contact(self.bridge.storage, peer)
        side = MaxSide(self.cfg, None, on_read=AsyncMock(), on_inbox_read=self.bridge.on_inbox_read)
        side.me_id = 1
        self.bridge.storage.queue(uin, "MAX incoming", 30, message_id=999999999999,
                                  ts=STAMP, source_ts=STAMP*1000+901)
        def event(user, unread=False):
            return MessageReadEvent.model_validate(dict(chatId=10, userId=user,
                                                        mark=STAMP*1000+901, setAsUnread=unread))
        await side._on_read(event(2))
        side.on_read.assert_awaited_once_with(peer, STAMP*1000+901)
        self.assertEqual(self.bridge.storage.pending_count(), 1)
        await side._on_read(event(1, True))
        self.assertEqual(self.bridge.storage.pending_count(), 1)
        await side._on_read(event(1))
        self.assertEqual(self.bridge.storage.pending_count(), 0)
        self.assertEqual(side.on_read.await_count, 1)

    async def test_express_thread_read_is_scoped_and_web_dispatch_routes_it(self):
        side = ExpressSide(self.cfg, None, client=FakeExpress(), on_inbox_read=self.bridge.on_inbox_read)
        await side.dialogs()
        peer, topic = chat_peer(GROUP), thread_topic(THREAD)
        for t in (0, topic):
            self.bridge.storage.queue(contact(self.bridge.storage, peer, t), str(t), 30,
                                      message_id=GROUP, ts=STAMP, source_ts=STAMP*1000+901)
        client = ExpressClient("unused", on_inbox_read=side._on_inbox_read)
        client._on_emit(None, json.dumps(dict(watch="inbox-read", chat=THREAD, at=STAMP*1000+901)))
        await asyncio.gather(*client._tasks)
        self.assertEqual(texts(self.bridge.storage), ["0"])
        await side._on_inbox_read(GROUP, STAMP*1000+901)
        self.assertEqual(self.bridge.storage.pending_count(), 0)

    async def test_online_phone_keeps_live_deliveries(self):
        uin = contact(self.bridge.storage)
        self.bridge.storage.queue(uin, "live delivery awaiting ACK", 30, message_id=99)
        self.bridge.oscar.session = NS(ready=True, closed=False)
        await self.bridge.on_inbox_read(555, 100)
        self.assertEqual(texts(self.bridge.storage), ["live delivery awaiting ACK"])
        self.assertEqual(self.bridge.storage.conn.execute("SELECT COUNT(*) FROM inbox_reads").fetchone()[0], 0)

    async def test_snapshot_and_slow_catch_up_do_not_restore_read_messages(self):
        await self.bridge._apply_roster({"telegram": [Dialog(555, "chat", "chat", "group", 0,
                                                             unread=2, read_inbox=100)]})
        uin = self.bridge.storage.contact_by_peer(555).uin
        self.bridge.storage.note_delivered(555, STAMP-1)
        self.bridge.telegram.missed = AsyncMock(return_value=[
            MissedMessage(STAMP, "", "read old photo", 99, "photo:99"),
            MissedMessage(STAMP+1, "", "new message", 101)])
        await self.bridge.catch_up("telegram")
        self.assertEqual(texts(self.bridge.storage), ["new message"])
        self.assertTrue(self.bridge.storage.message_processed(uin, 99))

    async def test_autoread_does_not_consume_offline_queue(self):
        self.cfg.mark_read = True
        online = False
        received = AsyncMock(return_value=True)
        side = TelegramSide(self.cfg, received, phone_online=lambda: online)
        self.addAsyncCleanup(side.stop)
        msg = NS(peer_id=types.PeerUser(555), id=99, date=dt.datetime.now(dt.timezone.utc),
                 reply_to=None, media=None, action=None, message="incoming", mark_read=AsyncMock())
        event = NS(message=msg, is_private=True)
        await side._on_new_message(event)
        msg.mark_read.assert_not_awaited()
        maximum = MaxSide(self.cfg, received, client=FakeMax(), phone_online=lambda: online)
        maximum.me_id = ME
        await maximum._on_new_message(message(99, DIALOG_ID, MOM, "incoming", STAMP*1000+901))
        self.assertEqual(maximum.client.read, [])
        express = ExpressSide(self.cfg, received, client=FakeExpress(), phone_online=lambda: online)
        await express.dialogs()
        await express._on_new_message(express.client.message(raw_event(99, PERSONAL, BOSS, "incoming")))
        self.assertEqual(express.client.read, [])
        online = True
        await side._on_new_message(event)
        msg.mark_read.assert_awaited_once()
        await maximum._on_new_message(message(100, DIALOG_ID, MOM, "incoming", STAMP*1000+902))
        self.assertEqual(len(maximum.client.read), 1)
        await express._on_new_message(express.client.message(raw_event(100, PERSONAL, BOSS, "incoming")))
        self.assertEqual(len(express.client.read), 1)


class ExpressWatch(unittest.TestCase):
    def test_native_js_read_positions_and_local_history_reads(self):
        import playwright
        node = Path(playwright.__file__).parent/"driver/node"
        source = r'''const assert=require('assert'),fs=require('fs');
const watch=eval('('+JSON.parse(fs.readFileSync(0,'utf8'))+')'),subscribers=[],emitted=[];
const initial={groupChatId:'chat',readPositionAt:50,positionEventInsertedAt:50};
let state={chats:[initial],user:{huid:'me'},typing:new Map(),groupCall:{},presences:{userPresences:new Map()}};
global.location={hash:'#/chats'};
global.window={__store:{getState:()=>state,subscribe:f=>subscribers.push(f)},__expressEmit:s=>emitted.push(JSON.parse(s))};
watch();watch();const count=subscribers.length;
function update(values){state={...state,chats:[{...state.chats[0],...values}]};for(const f of subscribers)f();}
update({readPositionAt:100});assert.deepEqual(emitted,[{watch:'read',chat:'chat',at:100}]);
emitted.length=0;update({positionEventInsertedAt:90});assert.deepEqual(emitted,[{watch:'inbox-read',chat:'chat',at:90}]);
assert.equal(window.__exInboxReads.get('chat'),90);
emitted.length=0;location.hash='#/chats/chat';update({positionEventInsertedAt:150});
assert.deepEqual(emitted,[]);assert.equal(window.__exInboxReads.get('chat'),90);
location.hash='#/chats';update({positionEventInsertedAt:150});assert.deepEqual(emitted,[]);
update({positionEventInsertedAt:170});assert.deepEqual(emitted,[{watch:'inbox-read',chat:'chat',at:170}]);
assert.equal(window.__exInboxReads.get('chat'),170);
emitted.length=0;update({positionEventInsertedAt:160});assert.deepEqual(emitted,[]);
assert.equal(window.__exInboxReads.get('chat'),170);assert.equal(subscribers.length,count);
console.log('PASS: own/peer read positions stay separate; bridge history reads do not emit own-read events or change snapshot read positions');'''
        subprocess.run([str(node), "-e", source], input=json.dumps(JS_WATCH), text=True,
                       check=True, timeout=20)


if __name__ == "__main__":
    unittest.main()
