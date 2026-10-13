"""Sender names outside the issued roster: live/offline, negotiated only."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bridge.config import Config
from bridge.db import Storage
from bridge.oscar import blocks, const as C
from bridge.oscar.proto import Reader
from bridge.oscar.server import OscarServer, Session


def make_session():
    cfg = Config(tg_api_id=1, tg_api_hash="x")
    storage = Storage(":memory:")
    known = storage.uin_for_peer(1, kind="user", title="В списке", group_name="Личные")
    outside = [storage.uin_for_peer(peer, kind="chat", title=name, group_name="Чаты")
               for peer, name in [(2, "Мама"), (3, "MAX: Друзья"), (4, "eXpress: Команда")]]

    async def outgoing(*args):
        return 1

    server = OscarServer(cfg, storage, outgoing, lambda: [storage.contact_by_uin(known)])
    class Writer:
        def get_extra_info(self, name): return ("127.0.0.1", 1)
    session = Session(server, None, Writer())
    session.tmm_version = (1, 20)
    session.ready = True
    session.build_ssi()
    packets = []
    async def capture(family, subtype, data=b"", **kw):
        packets.append((family, subtype, data))
        return True
    session.send_snac = capture
    return server, storage, session, packets, known, outside


def incoming_tlvs(data):
    reader = Reader(data)
    reader.read(8); reader.u16(); reader.pstr8(); reader.u16()
    reader.tlvs(reader.u16())
    return reader.tlvs()


class ContactNamesTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        (self.server, self.storage, self.session, self.packets,
         self.known, self.outside) = make_session()

    async def asyncTearDown(self):
        self.storage.close()

    async def test_live_channels_and_split(self):
        self.server.max_message_chars = 8
        for wait_ack in [False, True]:
            for uin, name in zip(self.outside, ["Мама", "MAX: Друзья", "eXpress: Команда"]):
                self.packets.clear()
                await self.session.deliver(uin, "длинное сообщение", wait_ack=wait_ack, url="https://example.org")
                self.assertGreater(len(self.packets), 1)
                self.assertEqual(incoming_tlvs(self.packets[0][2]).get(C.TLV_TMM_SENDER_NAME), name.encode())
                for _, _, data in self.packets[1:]:
                    self.assertIsNone(incoming_tlvs(data).get(C.TLV_TMM_SENDER_NAME))
                self.assertTrue(all((family, subtype) == (C.ICBM, C.ICBM_INCOMING)
                                    for family, subtype, _ in self.packets))

    async def test_issued_roster_and_legacy_clients(self):
        for version in [None, (0, 85), (1, 19)]:
            self.session.tmm_version = version
            await self.session.deliver(self.outside[0], "legacy")
            self.assertIsNone(incoming_tlvs(self.packets[-1][2]).get(C.TLV_TMM_SENDER_NAME))
        self.session.tmm_version = (1, 20)
        for uin in [self.known, 999999]:
            await self.session.deliver(uin, "known or unknown")
            self.assertIsNone(incoming_tlvs(self.packets[-1][2]).get(C.TLV_TMM_SENDER_NAME))

    async def test_offline_negotiation_and_ack(self):
        sender = self.outside[0]
        self.storage.queue(sender, "накопленное сообщение", 10, ts=1700000000)
        row = self.storage.peek_pending()[0][0]
        self.server.max_message_chars = 8
        for version in [None, (1, 19), (1, 20)]:
            self.storage.reset_sent()
            self.session.tmm_version = version
            records = []
            async def capture(uin, subtype, seq, body):
                if subtype == C.ICQ_OFFLINE_MSG: records.append(body)
            self.session.send_icq_reply = capture
            await self.session.send_offline_messages(100500, 1)
            self.assertGreater(len(records), 1)
            for index, record in enumerate(records):
                end = 14 + struct.unpack_from("<H", record, 12)[0]
                if version == (1, 20) and index == 0:
                    self.assertEqual(Reader(record[end:]).tlvs().get(C.TLV_TMM_SENDER_NAME), "Мама".encode())
                else:
                    self.assertEqual(len(record), end)
            self.assertEqual(self.storage.conn.execute("SELECT id FROM pending").fetchone()[0], row)
        self.session.offline_acknowledged()
        self.assertEqual(self.storage.peek_pending(), [])

    def test_alias_limits_unicode_and_missing_title(self):
        sender = self.outside[0]
        self.storage.conn.execute("UPDATE contacts SET title=? WHERE uin=?", ("😀"*200, sender))
        self.server.alias_max_chars = 1000
        name = Reader(self.session.sender_name_tlv(sender)).tlvs().get(C.TLV_TMM_SENDER_NAME)
        self.assertEqual(name.decode(), "😀"*64)
        self.assertEqual(len(name), 256)
        self.server.alias_max_chars = 3
        self.assertEqual(Reader(self.session.sender_name_tlv(sender)).tlvs().get(C.TLV_TMM_SENDER_NAME).decode(), "😀"*3)
        self.storage.conn.execute("UPDATE contacts SET title=? WHERE uin=?", (" \x00\r\n ", sender))
        self.assertEqual(self.session.sender_name_tlv(sender), b"")


if __name__ == "__main__":
    unittest.main()
