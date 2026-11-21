"""Telegram updates, persistent queue, paged history and per-photo BART requests."""
import asyncio
import datetime as dt
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from telethon import types, utils
from bridge.bridge import Bridge
from bridge.config import Config
from bridge.oscar import blocks, const as C
from bridge.oscar.proto import Snac, pstr8
from bridge.oscar.server import Session
from tests.test_contact_names import incoming_tlvs

PEER = types.PeerChannel(42)
CHAT = utils.get_peer_id(PEER)
NOW = dt.datetime.now(dt.timezone.utc)


def photo(i, group=None, caption="", topic=0):
    media = types.MessageMediaPhoto(photo=types.Photo(i, 1, b"", NOW, [], 1))
    return NS(id=i, peer_id=PEER, grouped_id=group, message=caption, date=NOW,
              get_sender=AsyncMock(return_value=types.User(7, first_name="Анна")),
              mark_read=AsyncMock(), sender_id=7, photo=media.photo, media=media, action=None,
              out=False, mentioned=False, reply_to=NS(forum_topic=True, reply_to_msg_id=topic)
              if topic else None)


def event(msg):
    return NS(message=msg, chat=NS(forum=False), get_sender=msg.get_sender, is_private=False)


class Telegram:
    def __init__(self, messages):
        self.messages = messages
        self.lookups = 0
        self.history_requests = []

    async def get_entity(self, _):
        return types.ChatEmpty(42)

    async def get_messages(self, peer, *, limit, offset_id, add_offset):
        self.lookups += 1
        await asyncio.sleep(0)
        assert peer == CHAT and limit == 20 and add_offset == -10
        return self.messages

    async def iter_messages(self, peer, *, limit, reply_to=None, offset_id=0):
        self.history_requests.append((limit, offset_id))
        visible = [m for m in self.messages if utils.get_peer_id(m.peer_id) == peer
                   and (not offset_id or m.id < offset_id)
                   and (m.reply_to.reply_to_msg_id if m.reply_to else None) == reply_to]
        for msg in sorted(visible, key=lambda m: -m.id)[:limit]:
            yield msg


class Albums(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.bridge = Bridge(Config(tg_api_id=1, tg_api_hash="x", tg_session=str(root/"tg"),
                                    db=str(root/"bridge.db")))
        self.addCleanup(self.bridge.storage.close)
        self.side = self.bridge.telegram
        self.real_client = self.side.client
        self.addCleanup(self.real_client.session.close)
        self.group = [photo(11, 90, "Первый"), photo(15, 90, "Второй"), photo(22, 90)]
        self.group[-1].mentioned = True
        self.previous = photo(1)
        self.telegram = Telegram([self.previous] + self.group)
        self.side.client = self.telegram
        self.uin = self.bridge.storage.uin_for_peer(CHAT, kind="chat", title="Группа", group_name="Telegram")
        self.server = self.bridge.oscar
        self.session = Session(self.server, None, NS(get_extra_info=lambda _: None))
        self.session.tmm_version = (1, 32)
        self.session.send_snac = AsyncMock(return_value=True)

    async def test_live_offline_and_selective_download(self):
        # A single update arrives first; Telegram already holds the complete album.
        await self.side._on_new_message(event(self.group[1]))
        await self.side._on_new_message(event(self.group[0]))
        await self.side._on_new_message(event(self.group[2]))
        self.assertEqual(self.telegram.lookups, 1)
        row, = self.bridge.storage.peek_pending()
        self.assertEqual((row[2], row[6], row[7]), ("Анна: [фото: 3] Первый\nВторой", "album:11,15,22", True))
        self.assertEqual(self.bridge.storage.pending_message_id(row[0]), "22")
        self.server.session = self.session
        self.session.ready = True
        self.server.fetch_attachment = AsyncMock(return_value=b"jpeg")
        await self.server.push(self.uin, row[2], row_id=row[0], attach=row[6])
        call, = self.session.send_snac.await_args_list
        tail = incoming_tlvs(call.args[2])
        tokens = tail.get(C.TLV_TMM_ATTACH)
        self.assertEqual((tokens[0], len(tokens)), (1, 49))
        self.assertEqual(tail.get(C.TLV_TMM_MESSAGE_REF), blocks.message_ref(11))
        self.assertEqual(len(self.server.awaiting), 1)
        self.server.fetch_attachment.assert_not_awaited()
        for n in (2, 0, 1):
            token = tokens[1+n*16:17+n*16]
            request = pstr8(str(self.uin).encode()) + b"\x01" + struct.pack(">HBB", C.BART_PHOTO, 1, 16) + token
            await self.session.on_icon_request(Snac(C.SSBI, 6, 0, n+1, request))
            self.server.fetch_attachment.assert_awaited_with(self.uin, "photo:"+str(self.group[n].id), "auto")

    async def test_pages_catchup_and_legacy(self):
        self.server.session = self.session
        rows, more = await self.bridge.fetch_history(self.uin, 1)
        self.assertTrue(more)
        self.assertEqual([(r[1], r[4]) for r in rows], [("album:11,15,22", 11)])
        older, more = await self.bridge.fetch_history(self.uin, 1, 1)
        self.assertFalse(more)
        self.assertEqual(older[0][1], "photo:1")
        missed = await self.side.missed(CHAT, int(NOW.timestamp()), 1)
        self.assertEqual([(m.message_id, m.attach, m.mention) for m in missed], [(22, rows[0][1], True)])
        self.session.tmm_version = (1, 31)
        for n in range(3):
            individual, more = await self.bridge.fetch_history(self.uin, 1, n)
            self.assertEqual(individual[0][1], "photo:"+str(self.group[2-n].id))
        await self.session.deliver(self.uin, rows[0][0], wait_ack=True, row_id=7, attach=rows[0][1])
        frames = self.session.send_snac.await_args_list
        self.assertEqual(len(frames), 3)
        for i, call in enumerate(frames):
            token = incoming_tlvs(call.args[2]).get(C.TLV_TMM_ATTACH)[1:]
            self.assertEqual(self.server.attachments[token][1], "photo:"+str(self.group[i].id))
        self.assertEqual(self.server.awaiting, {frames[-1].args[2][:8]: 7})

    async def test_order_identity_and_fallback(self):
        self.side.on_message = AsyncMock(return_value=True)
        self.side.cfg.mark_read = True
        self.side.phone_online = lambda: True
        wrong_chat = photo(99, 90); wrong_chat.peer_id = types.PeerChannel(123)
        other_topic = photo(23, 90, topic=77)
        following = photo(25, caption="отдельно")
        self.telegram.messages += [wrong_chat, other_topic, following]
        await asyncio.gather(*(self.side._on_new_message(event(m)) for m in [*self.group, following]))
        calls = self.side.on_message.await_args_list
        self.assertEqual([c.kwargs["attach"] for c in calls], ["album:11,15,22", "photo:25"])
        self.group[-1].mark_read.assert_awaited_once()
        self.group[0].mark_read.assert_not_awaited()
        # Own albums use the same path. Groups mixed with video retain their media actions.
        self.side.client.get_messages = AsyncMock(side_effect=ConnectionError())
        a, b = photo(40, 91), photo(41, 91)
        a.out = b.out = True
        await asyncio.gather(self.side._on_own_message(event(b)), self.side._on_own_message(event(a)))
        self.assertEqual(self.side.on_message.await_args.args[1], "Я")
        self.assertEqual(self.side.on_message.await_args.kwargs["attach"], "album:40,41")
        c, d = photo(42, 92), photo(43, 92)
        d.photo, d.video, d.media = None, True, types.MessageMediaDocument()
        await asyncio.gather(self.side._on_new_message(event(c)), self.side._on_new_message(event(d)))
        self.assertEqual([x.kwargs["attach"] for x in self.side.on_message.await_args_list[-2:]], ["photo:42","video:43"])
        self.telegram.messages = [a]
        partial = await self.side.history(CHAT, 1, None, 5)
        self.assertEqual((partial[0].msg_id, partial[0].attach), (40, ""))
        self.telegram.messages = [following, self.previous]
        independent = await self.side.history(CHAT, 2, None, 10)
        self.assertEqual([m.msg_id for m in independent], [1, 25])
        interleaved = photo(17, caption="отдельный снимок")
        self.telegram.messages = [*self.group, interleaved]
        page = await self.side.history(CHAT, 2, None, 10)
        self.assertEqual([(m.msg_id, m.attach) for m in page], [(17, ""), (11, "album:11,15,22")])

    def test_byte_limited_page_keeps_album_whole_and_offers_older_posts(self):
        rows = [("old", ""), ("album", "album:11,15,22")]
        data = blocks.history_records(rows, 57, lambda _: bytes(16), albums=True, page_more=False)
        self.assertEqual(data, bytes([255, 1, 0, 5]) + b"album" + bytes([0x41, 3]) + bytes(48))



if __name__ == "__main__":
    unittest.main()
