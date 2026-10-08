"""Ручная история MAX не расходует фоновую квоту; ошибка не становится пустой пачкой."""

from __future__ import annotations

import asyncio
from pathlib import Path
import struct
import sys
import time
from types import SimpleNamespace as NS
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pymax.api.messages.service import MessageService
from pymax.exceptions import ApiError
from pymax.protocol import Opcode

from bridge.bridge import Bridge
from bridge.config import Config
from bridge.max.client import MaxSide, to_peer
from bridge.oscar import const as C
from bridge.oscar.proto import Reader, Snac, pstr8
from bridge.oscar.server import Session

CHAT, ME, SENDER = 225892684, 1001, 2002
NOW_MS = int(time.time() * 1000)
CHECK = unittest.TestCase()


class MaxTransport:
    """SDK настоящий; транспорт воспроизводит ошибку из журнала пользователя."""
    def __init__(self):
        self.calls = []
        self.background_left = 1
        self.fail_interactive = False
        self.messages = [dict(id=10000+i, time=NOW_MS-60000+i*1000, type="USER",
                             sender=ME if i % 7 == 0 else SENDER, text=f"Сообщение {i}")
                         for i in range(1, 46)]
        self.messages[-3]["attaches"] = [dict(_type="PHOTO", photoId=42,
            baseUrl="http://files.test/p.jpg", photoToken="test", height=176, width=144)]
        self.api = NS(messages=MessageService(self))

    async def invoke(self, opcode, payload):
        assert opcode == Opcode.CHAT_HISTORY
        self.calls.append(payload)
        assert payload["chatId"] == CHAT
        assert payload["getMessages"] is True and payload["forward"] == 0
        assert isinstance(payload["from"], int) and payload["from"] > NOW_MS-1000
        if payload["interactive"]:
            rejected = self.fail_interactive
        else:
            rejected = self.background_left == 0
            self.background_left = max(0, self.background_left-1)
        if rejected:
            raise ApiError(opcode=49, error="too.many.requests", title="Слишком много запросов",
                           message="Chat history noninteractive limit reached")
        return NS(payload=dict(messages=self.messages[-payload["backward"]:]))


class MaxClient:
    def __init__(self, transport): self.transport = transport
    async def fetch_history(self, *args, **kwargs):
        return await self.transport.api.messages.fetch_history(*args, **kwargs)
    async def get_chat(self, chat_id): return NS(id=chat_id, type="DIALOG", participants={ME: 1, SENDER: 1})
    def get_cached_user(self, user_id): return NS(id=user_id, names=[NS(name="Сергей")])
    async def get_user(self, user_id): return self.get_cached_user(user_id)


def history_data(packet):
    family, subtype, data, kwargs = packet
    assert (family, subtype) == (C.SSBI, C.SSBI_ICQ_REPLY)
    r = Reader(data)
    r.pstr8()
    for part in range(2):
        assert r.u16() == C.BART_HISTORY
        r.u8(); r.read(r.u8())
        if part == 0: r.u8()
    body = r.read(r.u16())
    assert not r.left
    return body


def records(data):
    r = Reader(data)
    result = []
    while r.left:
        text = r.read(r.u16()).decode("utf-8")
        flags = r.u8()
        token = r.read(16) if flags & 1 else None
        if flags & 0x10: r.u32()
        ident = int.from_bytes(r.read(8), "big") if flags & 0x20 else None
        result.append((text, token, ident))
    return result


async def main():
    bridge = Bridge(Config(tg_api_id=1, tg_api_hash="x", tg_session="", db=":memory:",
                           photos_enabled=False, render_enabled=False))
    try:
        transport = MaxTransport()
        bridge.max = MaxSide(bridge.cfg, bridge.on_telegram_message, client=MaxClient(transport))
        bridge.max.me_id = ME
        bridge.active["max"] = True
        uin = bridge.storage.uin_for_peer(to_peer(CHAT), title="Сергей", kind="user", group_name="MAX")
        session = Session(bridge.oscar, None, NS(get_extra_info=lambda _: ("127.0.0.1", 1)))
        session.tmm_version = (0, 85)
        packets = []
        async def capture(family, subtype, data=b"", **kwargs):
            packets.append((family, subtype, data, kwargs))
            return True
        session.send_snac = capture
        async def request(count, offset=0, paged=True):
            token = struct.pack(">HHB", count, offset, int(paged)) + bytes(11)
            body = pstr8(str(uin).encode()) + b"\x01" + struct.pack(">H", C.BART_HISTORY) + b"\x01\x10" + token
            await session.on_icon_request(Snac(C.SSBI, C.SSBI_ICQ_REQ, 0, 77, body))
            return packets[-1]

        # Opening a chat preloads one message; immediately opening history loads a full page.
        single = records(history_data(await request(1, paged=False)))
        assert len(single) == 1 and single[0][2] == 10045
        first = history_data(await request(10))
        assert first[:2] == b"\xff\x01"
        first_rows = records(first[2:])
        assert [row[2] for row in first_rows] == list(range(10036, 10046))
        assert any(row[1] for row in first_rows), "photo lost from history"
        older = history_data(await request(10, offset=10))
        assert [row[2] for row in records(older[2:])] == list(range(10026, 10036))
        assert all(call["interactive"] for call in transport.calls)
        assert transport.background_left == 1

        # Catch-up keeps the background flag and reports a real quota error without advancing the cursor.
        missed = await bridge.max.missed(to_peer(CHAT), NOW_MS//1000-60, 10)
        assert missed and transport.calls[-1]["interactive"] is False
        assert transport.background_left == 0
        anchor = NOW_MS//1000-60
        bridge.storage.note_delivered(to_peer(CHAT), anchor)
        bridge._unread[(to_peer(CHAT), 0)] = 10
        with CHECK.assertLogs(level="WARNING"):
            await bridge.catch_up()
        assert bridge.storage.contact_by_uin(uin).last_ts == anchor
        assert bridge.storage.pending_count() == 0
        assert transport.calls[-1]["interactive"] is False
        # Exhausting the background budget does not affect the open history, render or !lastfoto.
        assert len(records(history_data(await request(10))[2:])) == 10
        assert len(await bridge.max.render_items(to_peer(CHAT), 10, None, 20)) == 10
        async def download(url): return b"jpeg"
        bridge.max._download = download
        assert await bridge.max.last_photos(to_peer(CHAT), 1) == [(b"jpeg", "Сообщение 43")]
        assert all(call["interactive"] for call in transport.calls[-3:])

        transport.fail_interactive = True
        with CHECK.assertLogs(level="WARNING"):
            error = await request(10)
        assert error[0:2] == (C.SSBI, 1) and error[3]["request_id"] == 77
        assert error[2][:2] == b"\0\1"
        reason = Reader(error[2][2:]).tlvs().get(C.TLV_TMM_ERROR_TEXT).decode("utf-8")
        assert reason == "Слишком много запросов истории. Повторите позже."
        # Text commands also report failure, rather than "no messages" or closing the socket.
        replies = []
        async def reply(contact, text, **kwargs): replies.append(text)
        bridge.reply = reply
        with CHECK.assertLogs(level="WARNING"):
            assert await bridge.on_phone_message(uin, "!last 10") == -1
        assert replies[-1] == "Не получилось загрузить историю"
        bridge.photos = bridge.photo_server = object()
        with CHECK.assertLogs(level="WARNING"):
            assert await bridge.on_phone_message(uin, "!lastfoto") == -1
        assert replies[-1] == "Не получилось загрузить фотографии"
        # A genuinely empty chat still produces the valid empty page.
        transport.fail_interactive = False
        transport.messages = []
        assert history_data(await request(10)) == b"\xff\0"
    finally:
        bridge.storage.close()
    print("PASS: real PyMax history payload, chat preload → pages, native IDs/photo tokens, background quota, interactive render/photos, error SNAC, command failures and genuinely empty history")


if __name__ == "__main__":
    asyncio.run(main())
