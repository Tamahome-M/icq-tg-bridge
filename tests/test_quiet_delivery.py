"""Client-owned quiet lists must bypass mute without bypassing owner policy."""
from __future__ import annotations

import asyncio
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bridge import policy
from bridge.bridge import Bridge
from bridge.config import Config
from bridge.db import Storage
from bridge.express.client import chat_peer
from bridge.history import MissedMessage
from bridge.max.client import to_peer
from bridge.oscar import const as C
from bridge.oscar.server import Session


class Phone(SimpleNamespace):
    """A connected phone; real server queue/filter code remains under test."""

    def __init__(self, server, quiet=(), *, capable=True, synced=True, closed=False):
        super().__init__(ready=True, closed=closed, quiet_delivery=capable,
                         quiet_synced=synced, quiet_uins=set(quiet), offline_phase=False,
                         profile={}, media={}, server=server, service_only=False)
        self.sent = []
        self.statuses = []
        self.typing = []

    def silent_for(self, uin, row_id):
        return Session.silent_for(self, uin, row_id)

    async def deliver(self, uin, text, **kwargs):
        self.sent.append((uin, text, kwargs))
        return True

    async def notify_status(self, uin, status):
        self.statuses.append((uin, status))

    async def notify_typing(self, uin, active):
        self.typing.append((uin, active))


class QuietDelivery(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.bridge = Bridge(Config(tg_api_id=1, tg_api_hash="test",
                                    tg_session=str(Path(self.folder.name) / "telegram.session"),
                                    db=":memory:", photos_enabled=False,
                                    render_enabled=False, show_sender_in_groups=False,
                                    offline_queue_per_chat=10, busy_hold_minutes=30))
        self.store = self.bridge.storage
        self.bridge.oscar.use_ack = False
        self.phone = Phone(self.bridge.oscar)
        self.bridge.oscar.session = self.phone
        self.now = int(time.time())
        self.next_peer = 500
        self.next_message = 1

    async def asyncTearDown(self):
        tasks = list(self.bridge._typing.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.bridge.telegram.stop()
        self.bridge.telegram.client.session.close()
        self.store.close()

    def chat(self, *, muted=True, kind="chat", favourite=False, topic=0, peer=None):
        if peer is None:
            self.next_peer += 1
            peer = self.next_peer
        uin = self.store.uin_for_peer(peer, topic_id=topic, kind=kind,
                                      title="Chat " + str(peer), group_name="Chats",
                                      muted=int(muted), favourite=int(favourite))
        self.bridge._reload_roster()
        return uin

    async def receive(self, uin, text="message", **kwargs):
        contact = self.store.contact_by_uin(uin)
        kwargs.setdefault("message_id", self.next_message)
        self.next_message += 1
        return await self.bridge.on_telegram_message(
            contact.peer_id, "", text, self.now, topic_id=contact.topic_id, **kwargs)

    def pending_uins(self):
        return [row[1] for row in self.store.peek_pending()]

    async def test_live_whitelist_is_per_chat_and_does_not_unmute_network(self):
        selected = self.chat()
        other = self.chat()
        ordinary = self.chat(muted=False)
        self.phone.quiet_uins.add(selected)
        self.bridge.telegram.set_muted = AsyncMock(return_value=True)
        await self.bridge.on_phone_quiet_chats()
        self.assertTrue(await self.receive(selected))
        self.assertFalse(await self.receive(other))
        self.assertTrue(await self.receive(ordinary))
        self.assertEqual(self.pending_uins(), [selected, ordinary])
        self.assertEqual(self.bridge.verdict_for(selected), "send")
        self.assertEqual(self.bridge.verdict_for(other), "drop")
        self.assertEqual(self.bridge.status_of(selected), C.STATUS_ONLINE)
        self.assertEqual(self.bridge.status_of(other), C.STATUS_DND)
        self.assertEqual(self.store.contact_by_uin(selected).muted, 1)
        self.bridge.telegram.set_muted.assert_not_awaited()

    async def test_v3_classic_keeps_mute_and_unsynced_v8_defers_candidates(self):
        selected = self.chat()
        self.bridge.oscar.session = Phone(self.bridge.oscar, [selected], capable=False)
        self.assertFalse(await self.receive(selected))
        self.assertEqual(self.bridge.verdict_for(selected), "drop")
        self.assertEqual(self.bridge.status_of(selected), C.STATUS_DND)
        self.assertEqual(self.store.pending_count(), 0)
        self.phone = Phone(self.bridge.oscar, [selected], synced=False)
        self.bridge.oscar.session = self.phone
        self.assertFalse(await self.receive(selected, "during sync"))
        self.assertEqual(self.pending_uins(), [selected])
        await self.bridge.oscar.drain_queue()
        self.assertEqual(self.phone.sent, [])
        self.assertEqual(self.pending_uins(), [selected])
        self.phone.quiet_synced = True
        await self.bridge.on_phone_quiet_chats()
        await self.bridge.oscar.drain_queue()
        self.assertEqual([row[1] for row in self.phone.sent], ["during sync"])

    async def test_whitelist_keeps_busy_dnd_favourites_and_invisible_rules(self):
        # Quiet is an exception to the network mute, not to owner status.
        for mode in (policy.UNMUTED, policy.ALL, policy.BUSY, policy.QUIET,
                     policy.FAVOURITES, policy.INVISIBLE):
            for kind in ("user", "chat", "channel"):
                for favourite in (False, True):
                    with self.subTest(mode=mode, kind=kind, favourite=favourite):
                        uin = self.chat(kind=kind, favourite=favourite)
                        self.phone.quiet_uins.add(uin)
                        self.bridge.mode = mode
                        allowed = policy.allows(mode, kind, favourite, muted=False)
                        accepted = await self.receive(uin)
                        self.assertEqual(accepted, allowed)
                        expected = "send" if allowed else "hold" if mode == policy.BUSY else "drop"
                        self.assertEqual(self.bridge.verdict_for(uin), expected)
                        expected_status = C.STATUS_ONLINE if allowed else (
                            C.STATUS_NA if mode == policy.BUSY else C.STATUS_DND)
                        self.assertEqual(self.bridge.status_of(uin), expected_status)

    async def test_mentions_and_forced_messages_remain_audible(self):
        uin = self.chat()
        self.phone.quiet_uins.add(uin)
        self.bridge.mode = policy.QUIET
        self.assertFalse(await self.receive(uin, "ordinary DND"))
        self.assertTrue(await self.receive(uin, "mention", mention=True))
        self.bridge.mode = policy.INVISIBLE
        self.assertFalse(await self.receive(uin, "invisible mention", mention=True))
        self.assertTrue(await self.receive(uin, "forced", always=True))
        rows = self.store.peek_pending()
        self.assertEqual([row[2] for row in rows], ["mention", "forced"])
        self.assertTrue(all(not self.store.pending_can_be_silent(row[0]) for row in rows))
        self.bridge.mode = policy.UNMUTED
        self.assertTrue(await self.receive(uin, "ordinary quiet", attach="photo:123"))
        row = self.store.peek_pending()[-1]
        self.assertTrue(self.store.pending_can_be_silent(row[0]))
        self.assertEqual(row[6], "photo:123")

    async def test_offline_unknown_list_keeps_bounded_candidates_then_filters_for_v8(self):
        selected, other = self.chat(), self.chat()
        self.bridge.cfg.offline_queue_per_chat = 2
        self.bridge.oscar.session = None
        for number in range(4):
            # A retained candidate is not yet source-network read/delivered.
            self.assertFalse(await self.receive(selected, str(number)))
        self.assertFalse(await self.receive(other, "not selected"))
        self.assertEqual([row[2] for row in self.store.peek_pending()], ["2", "3", "not selected"])
        # No saved server whitelist is needed: this is the first list received.
        self.phone = Phone(self.bridge.oscar, [selected])
        self.bridge.oscar.session = self.phone
        await self.bridge.oscar.drain_queue()
        self.assertEqual([(uin, text) for uin, text, _ in self.phone.sent],
                         [(selected, "2"), (selected, "3")])
        self.assertTrue(all(kwargs.get("silent") for _, _, kwargs in self.phone.sent))
        self.assertEqual(self.store.pending_count(), 0)

    async def test_offline_muted_candidates_never_leak_to_classic_client(self):
        muted = self.chat()
        ordinary = self.chat(muted=False)
        self.bridge.oscar.session = Phone(self.bridge.oscar, closed=True, capable=False)
        self.assertFalse(await self.receive(muted, "muted"))
        self.assertTrue(await self.receive(ordinary, "ordinary"))
        legacy = Phone(self.bridge.oscar, capable=False)
        self.bridge.oscar.session = legacy
        await self.bridge.oscar.drain_queue()
        self.assertEqual([row[1] for row in legacy.sent], ["ordinary"])
        self.assertEqual(self.store.pending_count(), 0)

    async def test_offline_deferral_keeps_owner_filters_and_does_not_mark_read(self):
        group = self.chat()
        person = self.chat(kind="user")
        self.bridge.oscar.session = None
        self.bridge.mode = policy.QUIET
        self.assertFalse(await self.receive(group, "DND group"))
        self.assertFalse(await self.receive(person, "DND personal candidate"))
        self.assertEqual(self.pending_uins(), [person])
        self.bridge.mode = policy.INVISIBLE
        self.assertFalse(await self.receive(person, "not favourite"))
        self.assertEqual(self.pending_uins(), [person])

    async def test_initial_login_keeps_muted_candidate_until_ready(self):
        selected = self.chat()
        logging_in = Phone(self.bridge.oscar, capable=False)
        logging_in.ready = False
        self.bridge.oscar.session = logging_in
        self.assertFalse(await self.receive(selected, "during login"))
        self.assertEqual(self.pending_uins(), [selected])
        self.bridge.oscar.session = Phone(self.bridge.oscar, [selected])
        await self.bridge.oscar.drain_queue()
        self.assertEqual([row[1] for row in self.bridge.oscar.session.sent], ["during login"])

    async def test_busy_release_offline_defers_selection_until_client_connects(self):
        selected, other = self.chat(), self.chat()
        self.bridge.oscar.session = None
        self.bridge.mode = policy.BUSY
        self.assertFalse(await self.receive(selected, "selected", attach="video:17"))
        self.assertFalse(await self.receive(other, "other"))
        self.assertEqual(self.store.held_count(), 2)
        await self.bridge.on_owner_status(C.STATUS_ONLINE)
        self.assertEqual(self.store.held_count(), 0)
        self.assertEqual(self.pending_uins(), [selected, other])
        self.phone = Phone(self.bridge.oscar, [selected])
        self.bridge.oscar.session = self.phone
        await self.bridge.oscar.drain_queue()
        self.assertEqual(len(self.phone.sent), 1)
        self.assertEqual(self.phone.sent[0][:2], (selected, "selected"))
        self.assertEqual(self.phone.sent[0][2]["attach"], "video:17")

    async def test_disabling_list_reapplies_policy_and_updates_status(self):
        uin = self.chat()
        self.phone.quiet_uins.add(uin)
        await self.bridge.on_phone_quiet_chats()
        self.assertTrue(await self.receive(uin))
        self.phone.quiet_uins.clear()
        await self.bridge.on_phone_quiet_chats()
        self.assertIn((uin, C.STATUS_DND), self.phone.statuses)
        self.assertEqual(self.bridge.verdict_for(uin), "drop")
        await self.bridge.oscar.drain_queue()
        self.assertEqual(self.phone.sent, [])
        self.assertEqual(self.store.pending_count(), 0)
        self.assertEqual(self.store.contact_by_uin(uin).muted, 1)

    async def test_reconnect_uses_new_client_list_instead_of_previous_session(self):
        uin = self.chat()
        self.phone.quiet_uins.add(uin)
        self.assertTrue(await self.receive(uin, "queued on old connection"))
        self.phone.closed = True
        replacement = Phone(self.bridge.oscar)
        self.bridge.oscar.session = replacement
        await self.bridge.on_phone_quiet_chats()
        self.assertEqual(self.bridge.verdict_for(uin), "drop")
        await self.bridge.oscar.drain_queue()
        self.assertEqual(replacement.sent, [])
        self.assertEqual(self.store.pending_count(), 0)

    async def test_quiet_chat_stops_existing_typing_and_does_not_restart_it(self):
        uin = self.chat(muted=False, kind="user")
        peer = self.store.contact_by_uin(uin).peer_id
        await self.bridge.on_telegram_typing(peer, True)
        self.assertEqual(self.phone.typing, [(uin, True)])
        self.phone.quiet_uins.add(uin)
        await self.bridge.on_phone_quiet_chats()
        self.assertEqual(self.phone.typing, [(uin, True), (uin, False)])
        await self.bridge.on_telegram_typing(peer, True)
        self.assertNotIn(uin, self.bridge._typing)
        self.assertEqual(self.phone.typing, [(uin, True), (uin, False)])
        self.phone.quiet_uins.clear()
        await self.bridge.on_phone_quiet_chats()
        await self.bridge.on_telegram_typing(peer, True)
        self.assertEqual(self.phone.typing[-1], (uin, True))

    async def test_reads_elsewhere_remove_offline_candidates_before_quiet_delivery(self):
        uin = self.chat()
        peer = self.store.contact_by_uin(uin).peer_id
        self.bridge.oscar.session = None
        await self.receive(uin, "read", message_id=100)
        await self.receive(uin, "new", message_id=101)
        await self.bridge.on_inbox_read(peer, 100)
        self.assertEqual([row[2] for row in self.store.peek_pending()], ["new"])
        self.phone = Phone(self.bridge.oscar, [uin])
        self.bridge.oscar.session = self.phone
        await self.bridge.oscar.drain_queue()
        self.assertEqual([row[1] for row in self.phone.sent], ["new"])

    async def test_catch_up_rechecks_current_client_list_and_preserves_special_messages(self):
        selected, other = self.chat(), self.chat()
        self.bridge.oscar.session = None
        for uin in (selected, other):
            c = self.store.contact_by_uin(uin)
            self.store.note_delivered(c.peer_id, self.now - 10)
            self.bridge._unread[(c.peer_id, 0)] = 3

        async def missed(peer, since, limit, topic):
            return [MissedMessage(self.now - 1, "", "ordinary", 100),
                    MissedMessage(self.now - 1, "", "mention", 101, mention=True),
                    MissedMessage(self.now - 1, "", "forced", 102, always=True)]

        self.bridge.telegram.missed = missed
        await self.bridge.catch_up()
        rows = self.store.peek_pending()
        self.assertEqual(len(rows), 6)
        for row in rows:
            self.assertEqual(self.store.pending_can_be_silent(row[0]), row[2] == "ordinary")
        self.phone = Phone(self.bridge.oscar, [selected])
        self.bridge.oscar.session = self.phone
        await self.bridge.oscar.drain_queue()
        self.assertEqual([(uin, text) for uin, text, _ in self.phone.sent],
                         [(selected, "ordinary"), (selected, "mention"), (selected, "forced"),
                          (other, "mention"), (other, "forced")])
        self.assertEqual([bool(kwargs.get("silent")) for _, _, kwargs in self.phone.sent],
                         [True, False, False, False, False])

    async def test_forum_topics_have_independent_quiet_selection(self):
        first = self.chat(peer=-1000123, topic=10)
        second = self.chat(peer=-1000123, topic=20)
        self.phone.quiet_uins.add(first)
        self.assertTrue(await self.receive(first))
        self.assertFalse(await self.receive(second))
        self.assertEqual(self.pending_uins(), [first])

    async def test_selection_applies_to_telegram_max_and_express(self):
        self.bridge.max = SimpleNamespace()
        self.bridge.express = SimpleNamespace()
        self.bridge.active.update(max=True, express=True)
        peers = (555, to_peer(-12345), chat_peer("c7e28353-1424-4a5b-82cf-365a0a2dd62a"))
        selected = []
        for peer in peers:
            uin = self.chat(peer=peer)
            selected.append(uin)
            self.phone.quiet_uins.add(uin)
            self.assertTrue(await self.receive(uin))
            self.assertEqual(self.bridge.status_of(uin), C.STATUS_ONLINE)
        self.assertEqual(self.pending_uins(), selected)
        await self.bridge.oscar.drain_queue()
        self.assertTrue(all(kwargs.get("silent") for _, _, kwargs in self.phone.sent))


class QuietEligibility(unittest.TestCase):
    def test_old_pending_schema_migrates_without_changing_forced_semantics(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "bridge.db")
            with sqlite3.connect(path) as db:
                db.executescript("""CREATE TABLE pending (
                    id INTEGER PRIMARY KEY, uin INTEGER NOT NULL, text TEXT NOT NULL,
                    ts INTEGER NOT NULL, forced INTEGER NOT NULL DEFAULT 0);
                    INSERT INTO pending VALUES (1,1000001,'normal',1800000000,0);
                    INSERT INTO pending VALUES (2,1000001,'forced',1800000000,1);""")
            store = Storage(path)
            try:
                self.assertTrue(store.pending_can_be_silent(1))
                self.assertFalse(store.pending_can_be_silent(2))
                self.assertFalse(store.pending_can_be_silent(999))
                store.drop_pending(1)
                self.assertFalse(store.pending_can_be_silent(1))
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
