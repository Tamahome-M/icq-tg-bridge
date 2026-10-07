"""Native quote routing and OSCAR references, with network calls replaced by spies."""
from __future__ import annotations
import asyncio
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
from types import SimpleNamespace as NS
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bridge.bridge import Bridge
from bridge.config import Config
from bridge.db import Storage
from bridge.history import SentMessage
from bridge.oscar import blocks, const as C
from bridge.oscar.proto import Reader, Snac, pstr8, tlv
from bridge.oscar.server import Session
from bridge.max.client import MaxSide, to_peer
from bridge.express.client import chat_peer as express_peer
from bridge.tg.client import TelegramSide

BIG_ID = 2**63 + 12345

class Network:
    def __init__(self): self.calls = []
    async def quote(self, *args): self.calls.append(args); return 99

async def run():
    with tempfile.TemporaryDirectory() as work:
        cfg = Config(tg_api_id=1, tg_api_hash="x", db=os.path.join(work,"bridge.db"),
                     tg_session=os.path.join(work,"tg.session"), photos_enabled=False)
        # Simulate a database written by 0.84, including existing pending rows.
        old = Storage(cfg.db)
        old.queue(1000001,"old queue",10)
        for table,column in [("pending","message_id"),("held","message_id"),("held","attach")]:
            old.conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        old.close()
        migrated = Storage(cfg.db)
        assert migrated.peek_pending()[0][2]=="old queue" and migrated.pending_message_id(1)==""
        migrated.drop_pending(1);migrated.close()
        bridge = Bridge(cfg)
        telegram = Network(); maximum = Network()
        bridge.telegram = telegram; bridge.max = maximum; bridge.active["max"] = True
        def chat(peer, title, topic=0):
            return bridge.storage.uin_for_peer(peer, kind="chat", title=title, group_name="Chats",topic_id=topic)
        src, dst, topic = chat(-100111,"Source"), chat(222,"Destination"), chat(-100333,"Topic",77)
        ms, md = chat(to_peer(10),"MAX source"),chat(to_peer(20),"MAX destination")
        ex = chat(express_peer("00000000-0000-0000-0000-000000000003"),"Express")
        assert not await bridge.on_phone_quote(topic, src, 123)
        assert telegram.calls == [(-100333, -100111, 123, 77)]
        assert not await bridge.on_phone_quote(md, ms, BIG_ID)
        assert maximum.calls == [(to_peer(20),to_peer(10),BIG_ID,0)]
        assert await bridge.on_phone_quote(md, src, 123) and len(maximum.calls)==1
        assert await bridge.on_phone_quote(dst, ex, 123) and len(telegram.calls)==1
        assert not bridge.quote_supported(ex)
        bridge.active["max"] = False
        assert await bridge.on_phone_quote(md, ms, BIG_ID) and len(maximum.calls)==1
        bridge.active["max"] = True

        class Writer:
            def get_extra_info(self, _): return ("127.0.0.1",1)
        session = Session(bridge.oscar,None,Writer())
        session.tmm_version=(0,85); session.ready=True
        bridge.oscar.session=session
        packets=[]
        async def capture(family, subtype, data=b"", **kw):
            packets.append((family,subtype,data,kw));return True
        session.send_snac=capture
        body=pstr8(str(md).encode())+pstr8(str(ms).encode())+blocks.message_ref(BIG_ID)
        request=Snac(C.SSBI,C.SSBI_QUOTE,0,77,body)
        entered, finish = asyncio.Event(), asyncio.Event()
        original = bridge.oscar.on_quote
        async def delayed(*args):
            entered.set(); await finish.wait(); return await original(*args)
        bridge.oscar.on_quote = delayed
        session.authorized = True
        await session.handle_snac(request)  # quote dispatch must not block the OSCAR reader
        await entered.wait()
        await session.handle_snac(request)
        await asyncio.sleep(0)
        finish.set()
        await asyncio.gather(*session._tasks)
        bridge.oscar.on_quote = original
        await session.on_quote(request)
        assert len(maximum.calls)==2,maximum.calls
        assert packets[-1][1:3]==(C.SSBI_QUOTE_ACK,b"\0") and packets[-1][3]["request_id"]==77
        await session.on_quote(Snac(C.SSBI,C.SSBI_QUOTE,0,78,body[:-1]))
        assert packets[-1][1]==1 and len(maximum.calls)==2
        await session.on_quote(Snac(C.SSBI,C.SSBI_QUOTE,0,79,pstr8(str(dst).encode())+pstr8(str(ms).encode())+blocks.message_ref(BIG_ID)))
        assert packets[-1][2][0]==1 and len(maximum.calls)==2

        # References survive SQLite reopening and reach every split ICBM part.
        bridge.storage.queue(ms,"long message across parts",10,message_id=BIG_ID)
        row=bridge.storage.peek_pending()[0][0]
        bridge.storage.close();bridge.storage=Storage(cfg.db);bridge.oscar.storage=bridge.storage
        assert bridge.storage.pending_message_id(row)==str(BIG_ID)
        session.server.max_message_chars=8
        packets.clear();await session.deliver(ms,"long message across parts",row_id=row)
        assert len(packets)>1
        for family,subtype,data,_ in packets:
            assert (family,subtype)==(C.ICBM,C.ICBM_INCOMING)
            r=Reader(data);r.read(8);r.u16();r.pstr8();r.u16();count=r.u16();r.tlvs(count)
            assert r.tlvs().get(C.TLV_TMM_MESSAGE_REF)==blocks.message_ref(BIG_ID)
        session.tmm_version=(0,84)
        packets.clear();await session.deliver(ms,"old",message_id=BIG_ID)
        assert tlv(C.TLV_TMM_MESSAGE_REF,blocks.message_ref(BIG_ID)) not in packets[0][2]
        session.tmm_version=(0,85)

        # A held message has already passed de-duplication; release still carries its original ID.
        await bridge.on_owner_status(C.STATUS_OCCUPIED)
        now=int(time.time())
        await bridge.on_telegram_message(-100111,"Author","held",now,message_id=456)
        assert bridge.storage.held_count()==1
        await bridge.on_owner_status(C.STATUS_ONLINE)
        held=next(r for r in bridge.storage.peek_pending() if "held" in r[2])
        assert bridge.storage.pending_message_id(held[0])=="456"
        assert not bridge.storage.queue(src,"duplicate",10,message_id=456)

        # IDs are returned independently of read markers for our own phone messages.
        async def outgoing(*_): return SentMessage(1700000000000,BIG_ID)
        bridge.oscar.on_outgoing=outgoing
        cookie=bytes(range(8));packets.clear()
        await session.on_icbm_send(Snac(4,6,0,1,cookie+struct.pack(">H",1)+pstr8(str(md).encode())+tlv(2,blocks.message_fragments("mine"))))
        assert packets[0][0:3]==(4,C.TMM_MESSAGE_REF,cookie+pstr8(str(md).encode())+blocks.message_ref(BIG_ID))

        rows=[("first","",False,0,BIG_ID),("photo","photo:5",True,123,44)]
        data=blocks.history_records(rows,1000,lambda _:bytes(16),threads=True,quotes=True)
        assert data.endswith(struct.pack(">I",123)+blocks.message_ref(44)) and b"\x20"+blocks.message_ref(BIG_ID) in data
        old=blocks.history_records(rows,1000,lambda _:bytes(16),threads=True)
        assert blocks.message_ref(BIG_ID) not in old
        assert blocks.message_ref("bad")==blocks.message_ref(0)==blocks.message_ref(2**64)==b""
        bridge.storage.close()

    # Adapter calls use native forward APIs, retaining source and target topic.
    class TG:
        async def get_input_entity(self,peer): return peer
        async def __call__(self,req): self.request=req; return object()
        def _get_response_message(self,req,result,peer): return [NS(id=987)]
    tg=TelegramSide.__new__(TelegramSide);tg.client=TG()
    assert await tg.quote(-100333,-100111,123,77)==987
    req=tg.client.request
    assert req.id==[123] and req.from_peer==-100111 and req.to_peer==-100333 and req.top_msg_id==77
    assert not req.drop_author and not req.drop_media_captions
    class MAX:
        async def forward_message(self,**kw): self.request=kw;return NS(id=321)
    maximum=MaxSide.__new__(MaxSide);maximum.client=MAX()
    assert await maximum.quote(to_peer(20),to_peer(10),BIG_ID)==321
    assert maximum.client.request==dict(chat_id=20,message_id=BIG_ID,source_chat_id=10)
    print("PASS: native Telegram/MAX APIs, topic routing, source IDs, queue/restart/held delivery, OSCAR refs, duplicate requests, legacy clients and unsupported networks")

if __name__=="__main__":asyncio.run(run())
