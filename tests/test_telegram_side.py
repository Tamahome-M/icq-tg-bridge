"""Проверка пометок для вложений и раскладки чатов по папкам Telegram."""

from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon import types

from bridge.config import Config
from bridge.tg.client import TelegramSide, describe_message

NOW = dt.datetime.now(dt.timezone.utc)


def msg(message="", media=None, action=None):
    m = types.Message(id=1, peer_id=types.PeerUser(1), date=NOW, message=message)
    m.media = media
    m.action = action
    return m


def document(attributes, size=1234, mime="application/octet-stream"):
    return types.Document(id=1, access_hash=1, file_reference=b"", date=NOW,
                          mime_type=mime, size=size, dc_id=2, attributes=attributes)


def photo():
    return types.MessageMediaPhoto(photo=types.Photo(
        id=1, access_hash=1, file_reference=b"", date=NOW,
        sizes=[], dc_id=2, has_stickers=False))


def check_media():
    cases = [
        (msg("привет"), "привет"),
        (msg("подпись", photo()), "[фото] подпись"),
        (msg("", photo()), "[фото]"),
        (msg("", types.MessageMediaDocument(document=document(
            [types.DocumentAttributeAudio(duration=14, voice=True)]))), "[голосовое 0:14]"),
        (msg("", types.MessageMediaDocument(document=document(
            [types.DocumentAttributeSticker(alt="😀", stickerset=types.InputStickerSetEmpty())]))),
         "[стикер 😀]"),
        (msg("", types.MessageMediaDocument(document=document(
            [types.DocumentAttributeVideo(duration=95, w=640, h=480)]))), "[видео 1:35]"),
        (msg("", types.MessageMediaDocument(document=document(
            [types.DocumentAttributeFilename(file_name="отчёт.pdf")], size=2 * 1024 * 1024))),
         "[файл отчёт.pdf, 2.0 МБ]"),
        (msg("", types.MessageMediaGeo(geo=types.GeoPoint(long=1, lat=2, access_hash=1))),
         "[геопозиция]"),
        (msg("", types.MessageMediaContact(phone_number="+79990000000", first_name="Вася",
                                           last_name="", vcard="", user_id=0)),
         "[контакт Вася +79990000000]"),
        # Служебные — пометкой с именем действия.
        (msg("", action=types.MessageActionChatMigrateTo(channel_id=1)), "[ChatMigrateTo]"),
    ]
    for message, expected in cases:
        got = describe_message(message)
        assert got == expected, f"ожидали {expected!r}, получили {got!r}"
    print(f"  пометки вложений: ок ({len(cases)} случаев)")


class Filter:
    """Заглушка папки Telegram."""
    def __init__(self, title, include=(), exclude=(), **flags):
        self.title = title
        self.pinned_peers = []
        self.include_peers = list(include)
        self.exclude_peers = list(exclude)
        for k, v in flags.items():
            setattr(self, k, v)
        for k in ("contacts", "non_contacts", "groups", "broadcasts", "bots"):
            setattr(self, k, flags.get(k, False))


def check_folders():
    cfg = Config(tg_api_id=1, tg_api_hash="x", other_group="Прочее")
    side = TelegramSide.__new__(TelegramSide)   # без подключения к сети
    side.cfg = cfg

    mom = types.User(id=777001, first_name="Мама", contact=True)
    channel = types.Channel(id=200300, title="Новости", photo=None, date=NOW,
                            broadcast=True, megagroup=False)
    bot = types.User(id=999, first_name="Бот", bot=True)

    folders = [
        ("Семья", Filter("Семья", include=[types.InputPeerUser(user_id=777001, access_hash=0)])),
        ("Каналы", Filter("Каналы", broadcasts=True)),
    ]
    assert side._folder_for(folders, mom, "user") == "Семья"
    assert side._folder_for(folders, channel, "channel") == "Каналы"
    assert side._folder_for(folders, bot, "bot") == "Прочее"
    assert side._folder_for([], mom, "user") is None    # без папок — группировка по типу

    # Галочки папки: заглушённый, прочитанный и архивный чат папка может
    # исключить — но только попавший в неё по типу, не добавленный явно.
    strict = [("Каналы", Filter("Каналы", broadcasts=True, exclude_muted=True,
                                exclude_read=True, exclude_archived=True)),
              ("Семья", Filter("Семья", include=[types.InputPeerUser(user_id=777001,
                                                                     access_hash=0)],
                               exclude_muted=True))]
    assert side._folder_for(strict, channel, "channel", muted=False, unread=3) == "Каналы"
    assert side._folder_for(strict, channel, "channel", muted=True, unread=3) == "Прочее"
    assert side._folder_for(strict, channel, "channel", muted=False, unread=0) == "Прочее"
    assert side._folder_for(strict, channel, "channel", unread=3, archived=True) == "Архив"
    assert side._folder_for(strict, mom, "user", muted=True) == "Семья", \
        "явно добавленный чат остаётся в папке при любых галочках"

    # Архив без своей папки — в группу «Архив», а если её имя пустое — как все.
    assert side._folder_for(folders, bot, "bot", archived=True) == "Архив"
    cfg.archive_group = ""
    assert side._folder_for(folders, bot, "bot", archived=True) == "Прочее"
    print("  раскладка по папкам: ок (галочки папок и архив)")


class FakeEvent:
    """Ровно те поля событий Telethon, на которые смотрит мост."""

    def __init__(self, **fields):
        self.__dict__.update(fields)


def check_events() -> None:
    """Набор текста относится к чату, где печатают; прочтение — только показанному."""
    import asyncio
    import tempfile

    cfg = Config(tg_api_id=1, tg_api_hash="x")
    cfg.tg_session = os.path.join(tempfile.mkdtemp(), "t.session")
    cfg.mark_read = True
    seen: list[tuple] = []

    async def on_message(peer_id, sender, text, ts, topic_id=0, attach=""):
        seen.append(("msg", peer_id, text))
        return "покажем" in text            # мост говорит, показал ли телефону

    async def on_status(peer_id, status):
        seen.append(("status", peer_id, status))

    async def on_typing(peer_id, active):
        seen.append(("typing", peer_id, active))

    side = TelegramSide(cfg, on_message, on_status, on_typing)

    # Печатают в группе: индикатор у группы, а не у личного чата человека.
    group = -1001234
    asyncio.run(side._on_user_update(FakeEvent(user_id=555, chat_id=group,
                                               typing=True, cancel=False, status=None)))
    assert seen[-1] == ("typing", group, True), seen[-1]
    # В личном чате chat_id совпадает с человеком.
    asyncio.run(side._on_user_update(FakeEvent(user_id=555, chat_id=555,
                                               typing=True, cancel=False, status=None)))
    assert seen[-1] == ("typing", 555, True), seen[-1]
    # Статус всегда относится к человеку.
    asyncio.run(side._on_user_update(FakeEvent(user_id=555, chat_id=group, typing=False,
                                               cancel=False,
                                               status=types.UserStatusOffline(dt.datetime.now(dt.timezone.utc)))))
    assert seen[-1][:2] == ("status", 555), seen[-1]

    # Прочитанным помечается только то, что телефон увидел.
    reads: list[str] = []

    class Msg:
        def __init__(self, text):
            self.peer_id = types.PeerUser(555)
            self.message = text
            self.date = dt.datetime.now(dt.timezone.utc)
            self.reply_to = None
            self.media = None
            self.action = None

        async def mark_read(self):
            reads.append(self.message)

    for text in ("это покажем", "это отсеяно"):
        event = FakeEvent(message=Msg(text), is_private=True)
        asyncio.run(side._on_new_message(event))
    assert reads == ["это покажем"], f"прочитанным помечено лишнее: {reads}"

    # Сообщение без заголовка темы: в форуме это тема «General» (1),
    # в обычной супергруппе — просто чат (0).
    topics: list[int] = []

    async def on_message_topic(peer_id, sender, text, ts, topic_id=0, attach=""):
        topics.append(topic_id)
        return False

    side.on_message = on_message_topic
    forum = -1001234
    forum_msg = Msg("покажем в общем")
    forum_msg.peer_id = types.PeerChannel(1234)
    forum_chat = FakeEvent(forum=True)

    async def fetch_forum():
        return forum_chat

    asyncio.run(side._on_new_message(FakeEvent(message=forum_msg, is_private=False,
                                               chat=None, get_chat=fetch_forum)))
    asyncio.run(side._on_new_message(FakeEvent(message=forum_msg, is_private=False,
                                               chat=FakeEvent(forum=False))))
    assert topics == [1, 0], topics
    side.on_message = on_message

    # Свои сообщения с других устройств приходят как «Я», а отправленное
    # самим мостом обратно не возвращается.
    seen.clear()
    side._own_ids[(555, 41)] = __import__("time").time()
    own = Msg("написал с десктопа")
    own.id = 42
    asyncio.run(side._on_own_message(FakeEvent(message=own)))
    assert seen == [("msg", 555, "написал с десктопа")], seen
    bridge_sent = Msg("ушло с телефона")
    bridge_sent.id = 41
    seen.clear()
    asyncio.run(side._on_own_message(FakeEvent(message=bridge_sent)))
    assert seen == [], "отправленное мостом не должно возвращаться на телефон"
    side._sending[555] = 1                    # отправка в этот чат прямо сейчас идёт
    asyncio.run(side._on_own_message(FakeEvent(message=own)))
    assert seen == [], "во время отправки мостом исходящее в тот же чат не зеркалим"
    print("  события: ок (набор в группе, прочтение только показанного, "
          "General форума, зеркало своих)")


if __name__ == "__main__":
    check_media()
    check_folders()
    check_events()
    print("СТОРОНА TELEGRAM ПРОВЕРЕНА")
