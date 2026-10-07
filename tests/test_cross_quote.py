"""Клиент 0.85 → запрос цитаты → реальные адаптеры → исходный текст другой сети."""

from __future__ import annotations

import asyncio
import datetime as dt
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from telethon import types
from pymax import Message as MaxMessage
from pymax.protocol import Opcode

from bridge.bridge import Bridge
from bridge.config import Config
from bridge.max.client import MaxSide, to_peer
from bridge.oscar import blocks, const as C
from bridge.oscar.proto import Snac, pstr8
from bridge.oscar.server import Session

NOW = dt.datetime.now(dt.timezone.utc)
BIG_ID = 2**63 + 12345
TEXT = "Полный исходный текст 😀\n**Звёздочки** _подчёркивания_ [ссылка](https://x/)\n> цитата\n!last 50"


class Telegram:
    def __init__(self):
        self.sent, self.fetched, self.forwards = [], [], []
        self.message = types.Message(id=123, peer_id=types.PeerChannel(1234), date=NOW, message=TEXT)
        self.protected = False
    async def get_messages(self, peer, ids):
        self.fetched.append((peer, ids))
        return self.message
    async def get_entity(self, peer): return NS(noforwards=self.protected)
    async def send_message(self, peer, text, **kwargs):
        self.sent.append((peer, text, kwargs))
        return NS(id=1000 + len(self.sent))
    async def get_input_entity(self, peer): return peer
    async def __call__(self, request):
        self.forwards.append(request)
        return object()
    def _get_response_message(self, request, result, peer): return [NS(id=456)]


class Maximum:
    def __init__(self):
        self.sent, self.fetched, self.forwards = [], [], []
        self.message = MaxMessage.model_validate(dict(id=BIG_ID, chatId=-5678, time=1800000000000,
                                                      type="USER", text=TEXT))
        self._app = NS(invoke=self.invoke, api=NS(messages=NS(_next_cid=self.next_cid)))
        self.cid = 1000
        self.fail = False
    def next_cid(self):
        self.cid += 1
        return self.cid
    async def get_message(self, chat, message_id):
        self.fetched.append((chat, message_id))
        return self.message
    async def invoke(self, opcode, payload):
        assert opcode == Opcode.MSG_SEND
        if self.fail: raise RuntimeError("send failed")
        self.sent.append(payload)
        return NS(payload=dict(chatId=payload["chatId"], message=dict(
            id=10000+len(self.sent), time=1800000000000, type="USER", text=payload["message"]["text"])))
    async def forward_message(self, **kwargs):
        self.forwards.append(kwargs)
        return NS(id=999)


async def main():
    with tempfile.TemporaryDirectory() as work:
        bridge = Bridge(Config(tg_api_id=1, tg_api_hash="x", tg_session="",
                               db=str(Path(work)/"bridge.db"), photos_enabled=False))
        try:
            tg, maximum = Telegram(), Maximum()
            bridge.telegram.client = tg
            bridge.max = MaxSide(bridge.cfg, bridge.on_telegram_message, client=maximum)
            bridge.active["max"] = True
            def chat(peer, title, topic=0):
                return bridge.storage.uin_for_peer(peer, kind="chat", title=title, group_name="Чаты", topic_id=topic)
            src = chat(-1000000001234, "Работа [тест]")
            dst = chat(-1000000002345, "Форум", 77)
            ms, md = chat(to_peer(-5678), "MAX источник"), chat(to_peer(-6789), "MAX цель")
            expected_tg = "Цитировано из Telegram, чат «Работа [тест]»:\n" + TEXT
            expected_max = "Цитировано из MAX, чат «MAX источник»:\n" + TEXT
            assert not await bridge.on_phone_quote(md, src, 123)
            assert tg.fetched == [(-1000000001234, 123)]
            payload = maximum.sent[-1]
            assert payload["chatId"] == -6789 and payload["message"]["text"] == expected_tg
            assert payload["message"]["elements"] == [] and payload["message"]["attaches"] == []
            assert payload["notify"] is True
            assert not await bridge.on_phone_quote(dst, ms, BIG_ID)
            assert maximum.fetched == [(-5678, BIG_ID)]
            assert tg.sent[-1] == (-1000000002345, expected_max, dict(reply_to=77, parse_mode=None))
            assert (-1000000002345, 1001) in bridge.telegram._own_ids
            assert (-6789, 10001) in bridge.max._own_ids
            assert not tg.forwards and not maximum.forwards

            # Long messages remain complete, including supplementary Unicode characters.
            tg.message.message = "😀" * 2500 + " конец"
            before = len(maximum.sent)
            assert not await bridge.on_phone_quote(md, src, 123)
            parts = [p["message"]["text"] for p in maximum.sent[before:]]
            header = expected_tg.split("\n", 1)[0] + "\n"
            assert len(parts) == 2 and all(len(p.encode("utf-16-le"))//2 <= 4000 for p in parts)
            assert "".join(p.removeprefix(header) for p in parts) == tg.message.message
            tg.message.message = TEXT

            # Deleted/wrong message or forum topic does not send under a misleading source name.
            before = len(maximum.sent)
            original = tg.message
            tg.message = types.MessageEmpty(123, None)
            assert await bridge.on_phone_quote(md, src, 123)
            tg.message = original
            original.noforwards = True
            assert await bridge.on_phone_quote(md, src, 123)
            original.noforwards = False
            tg.protected = True
            assert await bridge.on_phone_quote(md, src, 123)
            tg.protected = False
            assert await bridge.on_phone_quote(md, src, 999)
            wrong_topic = chat(-1000000001234, "Другая тема", 55)
            assert await bridge.on_phone_quote(md, wrong_topic, 123)
            assert len(maximum.sent) == before
            old_max = maximum.message
            maximum.message = None
            before_tg = len(tg.sent)
            assert await bridge.on_phone_quote(dst, ms, BIG_ID)
            assert len(tg.sent) == before_tg
            maximum.message = old_max

            # Unknown fields in PyMax 2.4 still expose the body of a native forward.
            maximum.message = MaxMessage.model_validate(dict(id=BIG_ID, chatId=-5678, time=1800000000000,
                type="USER", text="", link=dict(type="FORWARD", message=dict(text="Из пересылки"))))
            assert not await bridge.on_phone_quote(dst, ms, BIG_ID)
            assert tg.sent[-1][1].endswith("Из пересылки")
            maximum.message = old_max
            # Both source and destination networks must be enabled.
            for network in ("telegram", "max"):
                before = len(maximum.sent), len(tg.sent)
                bridge.active[network] = False
                assert await bridge.on_phone_quote(md, src, 123)
                assert await bridge.on_phone_quote(dst, ms, BIG_ID)
                assert before == (len(maximum.sent), len(tg.sent))
                bridge.active[network] = True

            # Native same-network forwarding remains native, including forum routing.
            assert not await bridge.on_phone_quote(dst, src, 123)
            assert tg.forwards[-1].top_msg_id == 77 and tg.forwards[-1].from_peer == -1000000001234
            assert not await bridge.on_phone_quote(md, ms, BIG_ID)
            assert maximum.forwards[-1] == dict(chat_id=-6789, source_chat_id=-5678, message_id=BIG_ID)

            # Existing 0.85 request/ACK also handles cross-network success/failure and deduplicates retries.
            session = Session(bridge.oscar, None, NS(get_extra_info=lambda _: ("127.0.0.1", 1)))
            session.tmm_version = (0, 85)
            packets = []
            async def capture(family, subtype, data=b"", **kwargs):
                packets.append((family, subtype, data, kwargs))
                return True
            session.send_snac = capture
            body = pstr8(str(md).encode()) + pstr8(str(src).encode()) + blocks.message_ref(123)
            request = Snac(C.SSBI, C.SSBI_QUOTE, 0, 201, body)
            before = len(maximum.sent)
            await session.on_quote(request)
            await session.on_quote(request)
            assert len(maximum.sent) == before + 1
            assert packets[-1][1:3] == (C.SSBI_QUOTE_ACK, b"\0")
            assert packets[-1][3]["request_id"] == 201
            maximum.fail = True
            await session.on_quote(Snac(C.SSBI, C.SSBI_QUOTE, 0, 202, body))
            assert packets[-1][1] == C.SSBI_QUOTE_ACK and packets[-1][2][0] == 1
            assert len(maximum.sent) == before + 1
        finally:
            bridge.storage.close()
    print("PASS: Telegram ↔ MAX full source text, provenance, literal Markdown, 64-bit IDs, forum destination, limits, deleted source, native forwards, legacy 0.85 protocol, ACK errors and duplicate requests")


if __name__ == "__main__":
    asyncio.run(main())
