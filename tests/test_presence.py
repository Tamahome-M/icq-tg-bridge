"""Initial presence batching, version fallback, bounded frames and cancellation."""
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bridge.config import Config
from bridge.db import Storage
from bridge.oscar import blocks, const as C
from bridge.oscar.proto import Reader
from bridge.oscar.server import OscarServer, Session, BUDDY_BATCH_BYTES, BUDDY_BURST
from tests.test_session_cleanup import BrokenWriter


def statuses():
    return {1000001 + i: C.STATUS_OFFLINE if i % 10 == 0 else C.STATUS_AWAY if i % 3 == 0 else C.STATUS_ONLINE
            for i in range(97)}


async def run():
    storage = Storage(":memory:")
    state = statuses()
    contacts = [NS(uin=uin) for uin in state]
    icon = lambda uin: bytes([uin % 251 + 1]) * 16 if uin % 2 else None
    server = OscarServer(Config(avatars=True), storage, None, lambda: contacts,
                         status_of=state.get, icon_hash=icon)
    server.typing_prime = False
    session = Session(server, None, BrokenWriter(None))
    replies = []
    async def capture(family, subtype, body=b"", **kw):
        replies.append((family, subtype, body))
        return True
    session.send_snac = capture
    pauses = []
    async def pause(delay):
        pauses.append(delay)
    with patch("bridge.oscar.server.asyncio.sleep", pause):
        for version in (None, (0, 93), (1, 6)):
            session.tmm_version = version
            replies.clear()
            await session.announce_buddies()
            assert len(replies) == 97
            for (family, command, data), (uin, status) in zip(replies, state.items()):
                r = Reader(data)
                assert int(r.pstr8()) == uin
                r.u16()
                count = r.u16()
                if status == C.STATUS_OFFLINE and not icon(uin):
                    assert command == C.BUDDY_DEPARTED and count == 0 and r.left == 0
                else:
                    assert command == C.BUDDY_ARRIVED
                    tlvs = r.tlvs(count)
                    wire = int.from_bytes(tlvs.get(C.UI_TLV_STATUS), "big")
                    assert wire == (C.STATUS_WIRE_OFFLINE if status == C.STATUS_OFFLINE else status)
        print("PASS: classic Jimm and TeleMotoMax through 1.6 retain one presence record per packet, offline and avatar semantics")
        session.tmm_version = (1, 7)
        replies.clear(); pauses.clear()
        await session.announce_buddies()
        assert len(replies) == 5 and pauses == [0.2] * 4
        got = []
        for family, command, data in replies:
            assert (family, command) == (C.BUDDY, C.BUDDY_ARRIVED)
            assert len(data) <= BUDDY_BATCH_BYTES
            r = Reader(data); count = 0
            while r.left:
                uin = int(r.pstr8()); r.u16(); fields = r.tlvs(r.u16())
                expected = state[uin]
                wire = int.from_bytes(fields.get(C.UI_TLV_STATUS), "big")
                assert wire == (C.STATUS_WIRE_OFFLINE if expected == C.STATUS_OFFLINE else expected)
                if icon(uin):
                    assert fields.get(C.UI_TLV_BART)[4:] == icon(uin)
                got.append(uin); count += 1
            assert count <= BUDDY_BURST
        assert got == list(state)
        print("PASS: 97 initial statuses use five <=4-KiB packets, exact order/status/avatar hashes, and four pacing pauses")
        server.typing_prime = True
        replies.clear()
        await session.announce_buddies()
        assert len(replies) == 5 and not any(family == C.ICBM for family, _, _ in replies)
        assert sum(command == C.BUDDY_ARRIVED and family == C.BUDDY for family, command, _ in replies) == 5
        server.typing_prime = False
        replies.clear()
        session.closed = True
        await session.announce_buddies()
        assert not replies
        session.closed = False
        async def failed(*args, **kw):
            replies.append(args); return False
        session.send_snac = failed
        await session.announce_buddies()
        assert len(replies) == 1
        print("PASS: modern client needs no typing-prime packets; closed session and failed send stop the initial burst")
    storage.close()


if __name__ == "__main__":
    asyncio.run(run())
