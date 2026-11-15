"""V8 quiet-chat protocol: opt-in, client-owned selection, multipart delivery and retry."""

from __future__ import annotations

import os
import struct
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.config import Config
from bridge.db import Storage
from bridge.oscar import const as C
from bridge.oscar.proto import Reader, Snac, pstr8, tlv
from bridge.oscar.server import OscarServer, Session


class QuietProtocolTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.storage = Storage(":memory:")
        self.uin = self.storage.uin_for_peer(123, title="Chat", kind="chat", group_name="TG")
        self.other = self.storage.uin_for_peer(456, title="Other", kind="chat", group_name="TG")

        async def outgoing(*args):
            return True

        self.server = OscarServer(Config(), self.storage, outgoing, self.storage.contacts)
        self.session = self.make_session()
        self.server.session = self.session

    async def asyncTearDown(self):
        self.storage.close()

    def make_session(self):
        session = Session(self.server, None, SimpleNamespace(get_extra_info=lambda _: None))
        session.authorized = session.ready = True
        session.packets = []

        async def capture(family, subtype, data=b"", **kwargs):
            session.packets.append((family, subtype, data, kwargs))
            return True

        session.send_snac = capture
        return session

    async def advertise(self, version=(1, 28), flags=1, session=None):
        session = session or self.session
        cap = C.CAP_TMM_PREFIX + bytes((*version, flags)) + bytes(9)
        await session.handle_snac(Snac(C.LOCATE, C.LOCATE_SET_INFO, 0, 1,
                                      tlv(C.LOCATE_TLV_CAPS, cap)))

    async def sync(self, uins=(), data=None, session=None):
        session = session or self.session
        if data is None:
            data = struct.pack(">H", len(uins)) + b"".join(struct.pack(">I", uin) for uin in uins)
        await session.handle_snac(Snac(C.OSERVICE, C.CLIENT_QUIET_CHATS, 0, 77, data))

    def assert_protocol_error(self, session=None):
        packet = (session or self.session).packets[-1]
        self.assertEqual(packet[:2], (C.OSERVICE, 1))
        self.assertEqual(packet[3]["request_id"], 77)
        self.assertEqual(packet[2][:2], b"\0\1")
        self.assertTrue(Reader(packet[2][2:]).tlvs().get(C.TLV_TMM_ERROR_TEXT).decode())

    def incoming(self):
        result = []
        for family, subtype, data, _ in self.session.packets:
            if (family, subtype) != (C.ICBM, C.ICBM_INCOMING):
                continue
            reader = Reader(data)
            cookie, channel = reader.read(8), reader.u16()
            uin = int(reader.pstr8())
            reader.u16()  # warning
            reader.tlvs(reader.u16())  # user-info TLVs
            result.append((cookie, channel, uin, reader.tlvs()))
        return result

    async def test_capability_requires_both_version_and_explicit_bit(self):
        self.assertFalse(self.session.quiet_delivery)
        for version, flags, expected in [((1, 27), 1, False), ((1, 28), 0, False),
                                         ((1, 28), 2, False), ((1, 28), 1, True),
                                         ((1, 29), 1, True)]:
            await self.advertise(version, flags)
            self.assertEqual(self.session.quiet_delivery, expected)
        await self.sync([self.uin])
        await self.advertise(flags=0)
        self.assertFalse(self.session.quiet_synced)
        self.assertFalse(self.session.quiet_uins)

    async def test_whitelist_is_atomic_bounded_and_client_owned(self):
        await self.sync([self.uin])
        self.assert_protocol_error()
        self.assertFalse(self.session.quiet_synced)
        await self.advertise()
        changes = []

        async def changed():
            changes.append(set(self.session.quiet_uins))

        self.server.on_quiet_chats = changed
        await self.sync([self.uin, self.other, self.uin])
        self.assertTrue(self.session.quiet_synced)
        self.assertEqual(self.session.quiet_uins, {self.uin, self.other})
        self.assertEqual(changes, [{self.uin, self.other}])
        for data in (b"", b"\0", b"\0\1", b"\0\0extra", b"\0\1" + bytes(4),
                     struct.pack(">H", 257) + struct.pack(">I", self.uin) * 257):
            await self.sync(data=data)
            self.assert_protocol_error()
            self.assertEqual(self.session.quiet_uins, {self.uin, self.other})
        self.assertEqual(len(changes), 1)
        await self.sync([self.other])
        self.assertEqual(self.session.quiet_uins, {self.other}, "full sync replaces, not merges")
        await self.sync()
        self.assertEqual(self.session.quiet_uins, set())
        self.assertTrue(self.session.quiet_synced)
        fresh = self.make_session()
        self.assertFalse(fresh.quiet_uins, "selection must not persist in bridge storage")
        self.assertFalse(fresh.quiet_synced)

    async def test_bart_uses_live_owner_and_cannot_modify_list(self):
        await self.advertise()
        await self.sync([self.uin])
        bart = self.make_session()
        bart.service_only = True
        self.assertTrue(bart.quiet_delivery)
        await self.sync([], session=bart)
        self.assert_protocol_error(bart)
        self.assertEqual(self.session.quiet_uins, {self.uin})
        bart.tmm_version = (1, 28)
        bart._quiet_delivery = True
        self.server.session = self.make_session()
        self.assertFalse(bart.quiet_delivery, "cached BART capability must not survive owner change")
        self.server.session = self.session
        self.session.closed = True
        self.assertFalse(bart.quiet_delivery)
        self.server.session = None
        self.assertFalse(bart.quiet_delivery)

    async def test_every_part_in_both_channels_has_exact_silent_tlv(self):
        await self.advertise()
        await self.sync([self.uin])
        self.server.max_message_chars = 12
        text = "one two three four five six seven eight nine ten eleven twelve"
        for wait_ack in (False, True):
            self.session.packets.clear()
            await self.session.deliver(self.uin, text, wait_ack=wait_ack, silent=True)
            incoming = self.incoming()
            self.assertGreater(len(incoming), 1)
            for _, channel, _, values in incoming:
                self.assertEqual(channel, 2 if wait_ack else 1)
                self.assertEqual(values.get_all(C.TLV_TMM_SILENT), [b"\x01"])
        for version, flags in [((1, 28), 0), ((1, 27), 1)]:
            await self.advertise(version, flags)
            self.session.packets.clear()
            await self.session.deliver(self.uin, text, silent=True)
            self.assertTrue(all(not item[3].has(C.TLV_TMM_SILENT) for item in self.incoming()))

    async def test_unsynced_queue_is_preserved_until_full_selection(self):
        await self.advertise()
        await self.server.deliver(self.uin, "muted backlog")
        self.server.verdict_for = lambda *args: "drop"
        self.assertEqual(self.server.sift_pending(), [])
        self.assertEqual(self.storage.pending_count(), 1)
        await self.session.send_offline_messages(100500, 12)
        self.assertEqual(self.storage.pending_count(), 1)
        self.assertFalse(self.session.offline_ids)
        await self.sync()
        self.assertEqual(self.server.sift_pending(), [])
        self.assertEqual(self.storage.pending_count(), 0)

    async def test_offline_ack_retry_rechecks_selection_and_preserves_exceptions(self):
        await self.advertise()
        await self.sync([self.uin])
        for text, kwargs in [("quiet", {}), ("command", {"forced": True}),
                             ("mention", {"mention": True})]:
            await self.server.deliver(self.uin, text, **kwargs)
        rows = self.storage.peek_pending()
        quiet, command, mention = (row[0] for row in rows)
        self.assertTrue(self.session.silent_for(self.uin, quiet))
        self.assertFalse(self.session.silent_for(self.uin, command))
        self.assertFalse(self.session.silent_for(self.uin, mention))
        self.assertFalse(self.session.silent_for(self.other, quiet))
        self.assertFalse(self.session.silent_for(self.uin, None))
        self.assertFalse(self.session.silent_for(self.uin, 999999))
        await self.session.send_offline_messages(100500, 12)
        self.assertEqual(self.session.offline_ids, [command, mention])
        self.session.offline_acknowledged()
        self.assertEqual(self.storage.pending_count(), 1, "offline ACK must retain quiet row")
        self.server.ack_works = True
        await self.server.push(self.uin, "quiet", quiet)
        self.assertEqual(self.incoming()[-1][3].get(C.TLV_TMM_SILENT), b"\x01")
        self.storage.reset_sent()
        await self.sync()
        await self.server.push(self.uin, "quiet", quiet)
        self.assertFalse(self.incoming()[-1][3].has(C.TLV_TMM_SILENT), "retry uses current selection")
        self.storage.reset_sent()
        await self.sync([self.uin])
        await self.server.push(self.uin, "quiet", quiet)
        cookie, _, _, values = self.incoming()[-1]
        self.assertEqual(values.get(C.TLV_TMM_SILENT), b"\x01")
        body = cookie + struct.pack(">H", 2) + pstr8(str(self.uin).encode())
        await self.session.on_icbm_client_ack(Snac(C.ICBM, C.ICBM_CLIENT_ACK, 0, 0, body))
        self.assertEqual(self.storage.pending_count(), 0)

    async def test_classic_offline_delivery_does_not_wait_for_sync(self):
        await self.server.deliver(self.uin, "regular backlog")
        row_id = self.storage.peek_pending()[0][0]
        await self.session.send_offline_messages(100500, 12)
        self.assertEqual(self.session.offline_ids, [row_id])
        self.session.offline_acknowledged()
        self.assertEqual(self.storage.pending_count(), 0)

    async def test_selection_change_during_send_refilters_remaining_rows(self):
        await self.advertise()
        self.server.ack_works = False
        self.server.verdict_for = lambda uin, mention=False: (
            "send" if uin == self.other or uin in self.session.quiet_uins else "drop")
        capture = self.session.send_snac
        for offline in (False, True):
            await self.sync([self.uin])
            await self.server.deliver(self.other, "first")
            await self.server.deliver(self.uin, "muted second")
            first, second = (row[0] for row in self.storage.peek_pending())
            changed = False

            async def change_during_send(family, subtype, data=b"", **kwargs):
                nonlocal changed
                result = await capture(family, subtype, data, **kwargs)
                if not changed and family in (C.ICBM, C.ICQ):
                    changed = True
                    await self.sync()
                return result

            self.session.send_snac = change_during_send
            self.session.packets.clear()
            if offline:
                await self.session.send_offline_messages(100500, 12)
                self.assertEqual(self.session.offline_ids, [first])
                self.session.offline_acknowledged()
            else:
                await self.server.drain_queue()
                self.assertEqual([row[2] for row in self.incoming()], [self.other])
            self.assertTrue(changed)
            self.assertEqual([row[0] for row in self.storage.peek_pending()], [second])
            self.session.send_snac = capture
            self.session.packets.clear()
            await self.server.drain_queue()
            self.assertFalse(self.incoming(), "removed muted chat must not arrive audibly")
            self.assertEqual(self.storage.pending_count(), 0)

    async def test_status_refresh_failure_does_not_lose_valid_selection(self):
        await self.advertise()

        async def failed_refresh():
            raise ConnectionError("status connection interrupted")

        self.server.on_quiet_chats = failed_refresh
        with self.assertLogs("oscar", level="WARNING"):
            await self.sync([self.uin])
        self.assertEqual(self.session.quiet_uins, {self.uin})
        self.assertTrue(self.session.quiet_synced)
        self.assertFalse(self.session.closed)
        self.assertTrue(self.server._wake.is_set())


if __name__ == "__main__":
    unittest.main()
