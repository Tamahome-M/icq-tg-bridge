"""Bounded chat pages and correlated media chunks, including legacy clients."""
import asyncio
from pathlib import Path
import struct
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bridge.config import Config
from bridge.db import Storage
from bridge.oscar import blocks, const as C
from bridge.oscar.proto import Snac, pstr8
from bridge.oscar.server import OscarServer, Session


async def run():
    storage = Storage(':memory:')
    async def outgoing(*_): return 1
    server = OscarServer(Config(oscar_uin='100500', oscar_password='test'), storage, outgoing, storage.contacts)
    session = Session(server, None, SimpleNamespace(get_extra_info=lambda _: ('127.0.0.1', 1)))
    session.tmm_version = (1, 15)
    rows = [(1000001+i, 'Чат '+str(i), i % 3, i, True) for i in range(85)]
    async def chats(): return rows
    server.chat_list = chats
    replies = []
    async def parts(target, token, data, kind, request): replies.append((data, request))
    session._send_bart_parts = parts
    def query(token):
        body = pstr8(b'100500') + b'\1' + struct.pack('>H', C.BART_CHATS) + b'\1\20' + token
        return Snac(C.SSBI, 6, 0, 72, body)
    try:
        await session.on_icon_request(query(bytes(16)))
        assert replies[-1] == (blocks.chat_records(rows, C.CHATS_MAX_BYTES), 72)
        for offset in (0, 20, 80, 200):
            token = b'P1'+struct.pack('>H', offset)+b'\24'+bytes(11)
            await session.on_icon_request(query(token))
            expected = b'CP1'+bytes([offset+20 < len(rows)])+blocks.chat_records(rows[offset:offset+20], C.CHATS_MAX_BYTES)
            assert replies[-1] == (expected, 72), offset
        token = b'P1'+bytes(2)+b'\xff'+bytes(11)
        await session.on_icon_request(query(token))
        assert replies[-1][0] == b'CP1\1'+blocks.chat_records(rows[:30], C.CHATS_MAX_BYTES)

        sent, acks = [], []
        async def photo(uin, data): sent.append(('photo', uin, data)); return True
        async def voice(uin, data, seconds): sent.append(('voice', uin, data)); return True
        async def capture(family, subtype, data=b'', **kw): acks.append((subtype, data, kw.get('request_id'))); return True
        server.on_photo = photo; server.on_voice = voice; session.send_snac = capture
        def chunk(kind, request, part, total, data):
            body = pstr8(b'1000001')+struct.pack('>HH', part, total)
            if kind == C.SSBI_UPLOAD_VOICE: body += struct.pack('>H', 2)
            body += struct.pack('>H', len(data))+data
            return Snac(C.SSBI, kind, 0, request, body)
        for reference in (0, 91):
            sent.clear(); acks.clear()
            await session.on_photo_upload(chunk(C.SSBI_UPLOAD, reference, 1, 2, b'a'))
            await session.on_photo_upload(chunk(C.SSBI_UPLOAD, reference+1, 2, 2, b'old'))
            await session.on_photo_upload(chunk(C.SSBI_UPLOAD, reference, 2, 2, b'b'))
            assert sent == [('photo', 1000001, b'ab')]
            assert acks[-1][2] == reference
        sent.clear()
        await session.on_voice_upload(chunk(C.SSBI_UPLOAD_VOICE, 100, 1, 3, b'a'))
        await session.on_voice_upload(chunk(C.SSBI_UPLOAD_VOICE, 100, 3, 3, b'early'))
        await session.on_voice_upload(chunk(C.SSBI_UPLOAD_VOICE, 100, 2, 3, b'b'))
        await session.on_voice_upload(chunk(C.SSBI_UPLOAD_VOICE, 100, 3, 3, b'c'))
        assert sent == [('voice', 1000001, b'abc')]
        assert acks[-1][2] == 100
        print('PASS: bounded chat pages, old full-list requests, correlated chunks/ACKs, legacy reference zero and out-of-order rejection')
    finally:
        storage.close()


if __name__ == '__main__':
    asyncio.run(run())
