"""Outgoing delivery/read receipts, legacy ACK policy and adapter routing."""
from __future__ import annotations

import asyncio
from pathlib import Path
import struct
import sys
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bridge.bridge import Bridge
from bridge.config import Config
from bridge.db import Storage
from bridge.history import SentMessage
from bridge.oscar import blocks, const as C
from bridge.oscar.proto import Snac, pstr8, tlv
from bridge.oscar.server import OscarServer, Session, SENT_MEMORY
from bridge.tg.client import TelegramSide
from bridge.max.client import MaxSide, to_peer
from bridge.express.client import ExpressSide, chat_peer
from tests.fake_jimm import FakeJimm
from tests.test_secure import SecureDialer
from bridge.oscar.secure import parse_psk


def setup(version=(1, 11), policy="read"):
    cfg = Config(oscar_uin="100500", oscar_password="test", ack_on=policy)
    storage = Storage(":memory:")
    async def outgoing(*_):
        return 100
    server = OscarServer(cfg, storage, outgoing, storage.contacts, lambda _: C.STATUS_ONLINE)
    session = Session(server, None, NS(get_extra_info=lambda _: ("127.0.0.1", 1)))
    session.tmm_version = version; session.ready = True; server.session = session
    captured = []
    async def capture(family, subtype, data=b"", **_):
        captured.append((family, subtype, data)); return True
    session.send_snac = capture
    return server, session, storage, captured


def request(uin=1000001, ident=71, acknowledge=True, text="hello"):
    cookie = struct.pack(">II", ident, 1)
    body = cookie + struct.pack(">H", 1) + pstr8(str(uin).encode())
    body += tlv(2, blocks.message_fragments(text)) + (tlv(3, b"") if acknowledge else b"")
    return cookie, Snac(C.ICBM, C.ICBM_SEND, 0, 1, body)


async def policies():
    for version in (None, (0, 85), (1, 10), (1, 11)):
        for policy in ("sent", "read"):
            server, session, storage, packets = setup(version, policy)
            try:
                cookie, outgoing = request(); await session.on_icbm_send(outgoing)
                modern = version == (1, 11)
                immediate = modern or policy == "sent"
                ack = (C.ICBM, C.ICBM_ACK, cookie+b"\0\1"+pstr8(b"1000001"))
                assert packets == ([ack] if immediate else []), (version, policy, packets)
                await server.confirm_read(1000001, 99)
                assert len(packets) == int(immediate)
                assert await server.confirm_read(1000001, 100) == (1 if modern or policy == "read" else 0)
                if modern:
                    assert packets == [ack, (C.ICBM, C.TMM_MESSAGE_READ, cookie+pstr8(b"1000001"))]
                else:
                    assert packets == [ack] and all(p[1] != C.TMM_MESSAGE_READ for p in packets)
                assert await server.confirm_read(1000001, 100) == 0
                assert await server.confirm_read(1000001, 90) == 0
                assert server._read_marks[1000001] == 100 and not server._sent
            finally:
                storage.close()
    server, session, storage, packets = setup()
    try:
        _, outgoing = request(acknowledge=False); await session.on_icbm_send(outgoing)
        assert not packets and not server._sent
        for result in (None, 0, -1):
            async def send(*_, result=result): return result
            server.on_outgoing = send; packets.clear()
            _, outgoing = request(); await session.on_icbm_send(outgoing)
            assert [p[1] for p in packets] == ([C.ICBM_ACK] if result == -1 else [])
            assert not server._sent  # bridge commands have no peer read receipt
    finally:
        storage.close()
    print("PASS: 1.11 gets delivery then read under both ack_on policies; Jimm/old TMM keep one configured ACK; exact cookies/recipients, no duplicates, failures/commands/disabled requests")


async def early_and_reconnect():
    server, session, storage, packets = setup()
    try:
        async def early(*_):
            assert await server.confirm_read(1000001, 100) == 0
            return 100
        server.on_outgoing = early
        cookie, outgoing = request(); await session.on_icbm_send(outgoing)
        assert [p[1] for p in packets] == [C.ICBM_ACK, C.TMM_MESSAGE_READ] and not server._sent
        # Read reports for one recipient must not confirm another's message.
        second, _ = request(1000002, 72)
        server.remember_sent(1000002, 200, second, 1)
        server.remember_sent(1000001, 101, cookie, 1)
        server.session = None
        assert await server.confirm_read(1000001, 101) == 0 and len(server._sent) == 2
        server.session = session; packets.clear(); await server.replay_read_receipts()
        assert packets == [(C.ICBM, C.TMM_MESSAGE_READ, cookie+pstr8(b"1000001"))]
        assert len(server._sent) == 1 and server._sent[0][0] == 1000002
        # Failed writes retain the receipt for reconnect rather than losing it.
        original = session.send_read_receipt
        async def failed(*_): return False
        session.send_read_receipt = failed
        assert await server.confirm_read(1000002, 200) == 0 and len(server._sent) == 1
        async def cancelled(*_): raise asyncio.CancelledError
        session.send_read_receipt = cancelled
        try:
            await server.confirm_read(1000002, 200)
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("receipt cancellation swallowed")
        assert len(server._sent) == 1
        session.send_read_receipt = original
        assert await server.confirm_read(1000002, 200) == 1 and not server._sent
        # Both pending cookies and watermarks have a fixed server bound.
        for i in range(SENT_MEMORY+20):
            server.remember_sent(2000000+i, i+1, cookie, 1)
            await server.confirm_read(3000000+i, i+1)
        assert len(server._sent) == len(server._read_marks) == SENT_MEMORY
    finally:
        storage.close()
    print("PASS: read before send RPC result, per-recipient isolation, offline/reconnect replay, failed/cancelled sends retained, monotonic watermarks and fixed bounds")


async def adapters():
    cfg = Config(tg_api_id=1, tg_api_hash="x", db=":memory:", photos_enabled=False)
    bridge = Bridge(cfg)
    session = Session(bridge.oscar, None, NS(get_extra_info=lambda _: ("127.0.0.1", 1)))
    session.tmm_version=(1,11); session.ready=True; bridge.oscar.session=session
    packets=[]
    async def capture(family, subtype, data=b"", **_): packets.append((family,subtype,data)); return True
    session.send_snac=capture
    try:
        telegram_peer=-100987
        tg=TelegramSide.__new__(TelegramSide); tg.on_read=bridge.on_telegram_read
        maximum=MaxSide(cfg,None,on_read=bridge.on_telegram_read); maximum.me_id=1
        express=ExpressSide(cfg,None,on_read=bridge.on_telegram_read)
        express_chat="00000000-0000-0000-0000-000000000031"
        express._chats[chat_peer(express_chat)]=NS()
        peers=[telegram_peer,to_peer(10),chat_peer(express_chat)]
        markers=[105,1800000000000,1800000000001]
        uins=[]
        for peer, mark in zip(peers,markers):
            uin=bridge.storage.uin_for_peer(peer,kind="chat",title="chat",group_name="group"); uins.append(uin)
            bridge.oscar.remember_sent(uin,mark,struct.pack(">II",uin,1),1)
        topic=bridge.storage.uin_for_peer(telegram_peer,topic_id=77,kind="chat",title="topic",group_name="group")
        bridge.oscar.remember_sent(topic,104,struct.pack(">II",topic,1),1)
        await tg._on_read(NS(chat_id=telegram_peer,max_id=105))
        await maximum._on_read(NS(chat_id=10,user_id=2,mark=markers[1],set_as_unread=False))
        await express._on_read(express_chat,markers[2])
        assert len(packets)==4 and not bridge.oscar._sent
        assert all(p[:2]==(C.ICBM,C.TMM_MESSAGE_READ) for p in packets)
        recipients={int(p[2][9:]) for p in packets}
        assert recipients==set([*uins,topic])
        before=len(packets)
        await maximum._on_read(NS(chat_id=10,user_id=1,mark=markers[1]+1,set_as_unread=False))
        await maximum._on_read(NS(chat_id=10,user_id=2,mark=markers[1]+1,set_as_unread=True))
        assert len(packets)==before
    finally:
        bridge.storage.close()
    print("PASS: actual Telegram/MAX/eXpress read callbacks route native message IDs/timestamps to phone receipts, including forum topics; own/MAX unread markers ignored")


async def sockets():
    class Client(FakeJimm):
        def __init__(self, *args): super().__init__(*args); self.reads=[]
        def _absorb(self, packet):
            if (packet.family, packet.subtype)==(C.ICBM,C.TMM_MESSAGE_READ):
                assert len(packet.data)==9+packet.data[8]
                self.reads.append((packet.data[:8],int(packet.data[9:])))
            super()._absorb(packet)
    for secure in (False,True):
        for version in (None,(1,10),(1,11)):
            for policy in ("read","sent"):
                cfg=Config(oscar_host="127.0.0.1",oscar_port=0,oscar_uin="100500",
                           oscar_password="test",bos_host="127.0.0.1",ack_on=policy,
                           oscar_psk="1234")
                storage=Storage(":memory:");uin=storage.uin_for_peer(555,kind="user",title="peer",group_name="test")
                async def outgoing(*_): return 101
                server=OscarServer(cfg,storage,outgoing,storage.contacts,lambda _:C.STATUS_ONLINE)
                await server.start();port=server._server.sockets[0].getsockname()[1]
                client=Client("127.0.0.1",port,cfg.oscar_uin,cfg.oscar_password);client.tmm_version=version
                if secure:client.open_transport=SecureDialer(parse_psk("1234"))
                try:
                    await client.connect();await client.bos(await client.login_md5_jimm());await client.drain_for(.04)
                    cookie=await client.say(uin,"real socket");await client.drain_for(.04)
                    modern=version==(1,11)
                    assert client.acks==([cookie] if modern or policy=="sent" else [])
                    assert client.reads==[]
                    await server.confirm_read(uin,101);await client.drain_for(.04)
                    assert client.acks==[cookie]
                    assert client.reads==([(cookie,uin)] if modern else [])
                finally:
                    await client.close();await server.stop();storage.close()
    print("PASS: real cleartext/encrypted OSCAR login and sockets; both ack_on policies; Jimm/1.10 receive one ACK and 1.11 separately receives delivery/read with original cookies")


async def run():
    await policies(); await early_and_reconnect(); await adapters(); await sockets()


if __name__ == "__main__":
    asyncio.run(run())
