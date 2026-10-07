"""Реальные модели Telegram/PyMax → фильтр моста → очередь/догрузка/телефон."""

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

from bridge import policy
from bridge.bridge import Bridge
from bridge.config import Config
from bridge.max.client import MaxSide, to_peer
from bridge.mentions import mentions_all, utf16_text
from bridge.tg.client import TelegramSide

ME = 1001
NOW = dt.datetime.now(dt.timezone.utc)
TG_PEER = -1000000001234
MAX_CHAT = -5678


def telegram(mid, text, *, entities=None, mentioned=False, out=False, topic=0, photo=False):
    media = types.MessageMediaPhoto(photo=types.Photo(
        id=1, access_hash=1, file_reference=b"", date=NOW, sizes=[], dc_id=2)) if photo else None
    reply = types.MessageReplyHeader(reply_to_msg_id=topic, forum_topic=True) if topic else None
    return types.Message(id=mid, peer_id=types.PeerChannel(1234), date=NOW, message=text,
                         out=out, mentioned=mentioned, entities=entities, media=media, reply_to=reply)


def maximum(mid, text, *, elements=None, mine=False, photo=False):
    return MaxMessage.model_validate(dict(id=mid, chatId=MAX_CHAT, sender=ME if mine else 2222,
        time=int(NOW.timestamp()) * 1000, type="USER", text=text, elements=elements or [],
        attaches=[dict(_type="PHOTO", photoId=42, baseUrl="http://files.test/p.jpg",
                       height=10, width=10, photoToken="test")] if photo else []))


def telegram_cases():
    return [
        telegram(1, "личное упоминание", mentioned=True),
        telegram(2, "Владелец", entities=[types.MessageEntityMentionName(0, 8, ME)]),
        telegram(3, "😀 @Owner", entities=[types.MessageEntityMention(3, 6)]),
        telegram(4, "@alias", entities=[types.MessageEntityMention(0, 6)]),
        telegram(5, "@other", entities=[types.MessageEntityMention(0, 6)]),
        telegram(6, "Другой", entities=[types.MessageEntityMentionName(0, 6, 2222)]),
        telegram(7, "😀 @ALL, внимание!"),
        telegram(8, "😀 @all", entities=[types.MessageEntityCode(3, 4)]),
        telegram(9, "@all", entities=[types.MessageEntityBlockquote(0, 4)]),
        telegram(10, "https://x/@all", entities=[types.MessageEntityUrl(0, 14)]),
        telegram(11, "name@all @alliance"),
        telegram(12, "@all", mentioned=True, out=True),
        telegram(13, "фото с упоминанием", mentioned=True, photo=True),
        telegram(14, "@inactive", entities=[types.MessageEntityMention(0, 9)]),
        telegram(15, "😀 @Owner", entities=[types.MessageEntityMention(2, 6)]),
        telegram(16, "@all", entities=[types.MessageEntityMentionName(0, 4, 2222)]),
        telegram(17, "https://example.test/?q=@all"),
    ]


def max_cases():
    return [
        maximum(1, "Владелец", elements=[dict(type="USER_MENTION", entityId=ME, **{"from": 0}, length=8)]),
        maximum(2, "Владелец", elements=[dict(type="USER_MENTION", entityId=str(ME))]),
        maximum(3, "Другой", elements=[dict(type="USER_MENTION", entityId=2222)]),
        maximum(4, "Владелец", elements=[dict(type="LINK", entityId=ME)]),
        maximum(5, "😀 @ALL, внимание!"),
        maximum(6, "😀 @all", elements=[dict(type="MONOSPACED", **{"from": 3}, length=4)]),
        maximum(7, "@all", elements=[dict(type="QUOTE", **{"from": 0}, length=4)]),
        maximum(8, "https://x/@all", elements=[dict(type="LINK", **{"from": 0}, length=14)]),
        maximum(9, "name@all @alliance"),
        maximum(10, "@all", mine=True),
        maximum(11, "фото", elements=[dict(type="USER_MENTION", entityId=ME)], photo=True),
        maximum(12, "@all", elements=[dict(type="CODE", **{"from": 0}, length=4)]),
        maximum(13, "@all", elements=[dict(type="USER_MENTION", entityId=2222, **{"from": 0}, length=4)]),
        maximum(14, "https://example.test/?q=@all"),
    ]


class TelegramClient:
    def __init__(self, messages): self.messages = messages
    async def get_entity(self, peer): return NS(forum=False)
    async def iter_messages(self, peer, limit, reply_to=None):
        for message in reversed(self.messages[-limit:]):
            yield message


class MaxClient:
    def __init__(self, messages): self.messages = messages
    async def get_chat(self, chat): return NS(id=chat, type="CHAT", title="MAX группа")
    async def get_user(self, user): return NS(names=[NS(name="Автор")])
    def get_cached_user(self, user): return None
    async def fetch_history(self, chat, backward): return self.messages[-backward:]


class Phone:
    ready, closed = True, False
    def __init__(self): self.sent = []
    async def deliver(self, uin, text, **kwargs):
        self.sent.append((uin, text, kwargs))
        return True


async def run_network(network, *, mode=policy.QUIET, disabled=False, catch_up=False):
    with tempfile.TemporaryDirectory() as work:
        cfg = Config(tg_api_id=1, tg_api_hash="x", db=str(Path(work)/"bridge.db"),
            tg_session="", photos_enabled=False, render_enabled=False,
            show_sender_in_groups=False, mirror_outgoing=True, offline_queue_per_chat=30,
            mentions_through=not disabled)
        bridge = Bridge(cfg)
        bridge.mode = mode
        try:
            if network == "telegram":
                side = bridge.telegram
                side.me = types.User(id=ME, username="owner", usernames=[
                    types.Username("alias", active=True), types.Username("inactive", active=False)])
                messages = telegram_cases()
                side.client = TelegramClient(messages)
                expected = {1, 2, 3, 4, 7, 13}
                peer = TG_PEER
            else:
                messages = max_cases()
                side = MaxSide(cfg, bridge.on_telegram_message, client=MaxClient(messages))
                side.me_id = ME
                bridge.max = side
                bridge.active["max"] = True
                expected = {1, 2, 5, 11}
                peer = to_peer(MAX_CHAT)
            uin = bridge.storage.uin_for_peer(peer, kind="chat", title="Группа",
                                              group_name="Группы", muted=1)
            if catch_up:
                missed = await side.missed(peer, int(NOW.timestamp())-1, 30)
                assert {m.message_id for m in missed if m.mention} == expected, missed
                bridge.storage.note_delivered(peer, int(NOW.timestamp())-1)
                bridge._unread[(peer, 0)] = len(messages)
                await bridge.catch_up()
            else:
                for message in messages:
                    if network == "telegram":
                        # Incoming handler only receives incoming events in Telethon.
                        if message.out: continue
                        await side._on_new_message(NS(message=message, is_private=False, chat=None))
                    else:
                        await side._on_new_message(message)
                rows = bridge.storage.peek_pending()
                assert {int(bridge.storage.pending_message_id(row[0])) for row in rows} == (
                    set() if disabled else expected), rows
                assert all(row[7] for row in rows)
            phone = Phone()
            bridge.oscar.session = phone
            bridge.oscar.use_ack = False
            await bridge.oscar.drain_queue()
            assert len(phone.sent) == (0 if disabled else len(expected)), (network, phone.sent)
            assert all(item[0] == uin for item in phone.sent), "упоминание попало в другой чат"
            if not disabled:
                photo_id = 13 if network == "telegram" else 11
                assert any(row[2].get("attach") == f"photo:{photo_id}" for row in phone.sent)
        finally:
            bridge.storage.close()


async def run_topic():
    bridge = Bridge(Config(tg_api_id=1, tg_api_hash="x", tg_session="", db=":memory:",
                           photos_enabled=False, show_sender_in_groups=False))
    try:
        bridge.mode = policy.QUIET
        general = bridge.storage.uin_for_peer(TG_PEER, title="Общее", kind="chat", group_name="Форум",
                                               topic_id=1, muted=1)
        topic = bridge.storage.uin_for_peer(TG_PEER, title="Работа", kind="chat", group_name="Форум",
                                             topic_id=77, muted=1)
        for mid, topic_id in [(101, 77), (102, 0)]:
            await bridge.telegram._on_new_message(NS(message=telegram(mid, "@all", topic=topic_id),
                                                      is_private=False, chat=NS(forum=True)))
        rows = bridge.storage.peek_pending()
        assert [row[1] for row in rows] == [topic, general], rows
    finally:
        bridge.storage.close()


async def main():
    assert utf16_text("😀 @owner", 3, 6) == "@owner"
    assert utf16_text("😀 @owner", 1, 1) == ""
    assert not mentions_all("@@all name@all @alliance https://x/@all")
    assert mentions_all("(@All), внимание")
    assert not mentions_all("www.example.test/?q=@all")
    for network in ("telegram", "max"):
        for mode in (policy.UNMUTED, policy.QUIET, policy.BUSY):
            await run_network(network, mode=mode)
        await run_network(network, disabled=True)
        await run_network(network, catch_up=True)
        await run_network(network, disabled=True, catch_up=True)
    await run_topic()
    print("PASS: Telegram/MAX own/all mentions, real PyMax entityId, UTF-16, exclusions, muted delivery, knob, queue, catch-up, attachments and forum routing")


if __name__ == "__main__":
    asyncio.run(main())
