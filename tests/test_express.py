"""Сторона eXpress: чаты одной группой, сообщения, вложения, упоминания, мьют."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge import policy
from bridge.bridge import Bridge
from bridge.config import Config
from bridge.express.client import (ExpressSide, chat_peer, describe_message, is_express_peer,
                                   media_kind, message_number)
from bridge.express.web import Chat, ExpressClient
from bridge.max.client import is_max_peer
from bridge.oscar import blocks
from bridge.tg.client import Dialog

ME = "11111111-aaaa-5bbb-8ccc-000000000001"
BOSS = "22222222-aaaa-5bbb-8ccc-000000000002"
PERSONAL = "33333333-aaaa-5bbb-8ccc-000000000003"
GROUP = "44444444-aaaa-5bbb-8ccc-000000000004"
MENTION = "55555555-aaaa-5bbb-8ccc-000000000005"
NOW_MS = 1_790_967_000_000
NAMES = {ME: "Вася", BOSS: "Шеф"}


def raw_event(number: int, chat: str, sender: str, body: str = "", when: int = NOW_MS,
              kind: str = "text", **payload) -> dict:
    """Событие в том виде, в каком его отдаёт страница веб-клиента."""
    return {"syncId": f"{number:08d}-0000-5000-8000-000000000000", "groupChatId": chat,
            "eventType": "message_new", "sender": sender, "insertedAt": when,
            "editedAt": None, "deletedAt": None,
            "payload": {"type": kind, "body": body, **payload}}


def mention(kind: str, huid: str = "", name: str = "") -> dict:
    return {"mentions": [{"mentionType": kind, "mentionId": MENTION,
                          "mentionData": {"userHuid": huid, "name": name}}]}


class FakeExpress:
    """Подделка веб-клиента: ровно те методы, которыми пользуется сторона."""

    def __init__(self):
        self.name = "Вася"
        self.parser = ExpressClient("нет-такого-профиля")
        self.parser.huid = ME
        self.on_message = None
        self.sent: list = []
        self.read: list = []
        self.muted: dict[str, bool] = {GROUP: True}
        self.rows: dict[str, list[dict]] = {
            PERSONAL: [
                raw_event(1, PERSONAL, ME, "123", NOW_MS - 3000),
                raw_event(2, PERSONAL, BOSS, "Фото сервера", NOW_MS - 2000, "image",
                          payload={"file": "/uploads/x.jpg", "fileName": "x.jpg", "fileSize": 5,
                                   "fileMimeType": "image/jpeg"}),
                raw_event(3, PERSONAL, BOSS, "", NOW_MS - 1000, "voice",
                          payload={"file": "/uploads/v", "fileName": "record.mp3", "fileSize": 3,
                                   "fileMimeType": "audio/mp3", "duration": 11}),
            ],
            GROUP: [raw_event(10, GROUP, BOSS, "общий сбор", NOW_MS - 500)],
        }

    def message(self, raw: dict):
        return self.parser._message(raw, NAMES)

    async def start(self): pass
    async def stop(self): pass

    async def chats(self):
        def chat(chat_id, kind, title, opponent, unread):
            rows = self.rows[chat_id]
            return Chat(id=chat_id, type=kind, title=title, opponent=opponent, unread=unread,
                        status="offline" if opponent else "",
                        muted=self.muted.get(chat_id, False), pinned=False, members=[ME, BOSS],
                        left=False, members_count=2, updated=rows[-1]["insertedAt"] / 1000,
                        last=self.message(rows[-1]))
        return [chat(GROUP, "group_chat", "Работа", None, 0),
                chat(PERSONAL, "chat", "Шеф", BOSS, 2)]

    async def history(self, chat_id, count=50):
        return [self.message(r) for r in self.rows[chat_id]][-count:]

    async def send(self, chat_id, text):
        raw = raw_event(100 + len(self.sent), chat_id, ME, text)
        self.sent.append((chat_id, text))
        # Страница показывает своё сообщение раньше, чем отправка вернётся.
        await self.on_message(self.message(raw))
        return self.message(raw)

    async def send_file(self, chat_id, path, caption="", as_document=False):
        with open(path, "rb") as source:
            self.sent.append((chat_id, os.path.basename(path), source.read(), caption, as_document))
        return self.message(raw_event(200 + len(self.sent), chat_id, ME, caption))

    async def download(self, message):
        return b"x" * message.attachment.size

    async def mark_read(self, chat_id):
        self.read.append(chat_id)

    async def set_muted(self, chat_id, muted):
        self.muted[chat_id] = muted
        return True


def make_cfg(work: str) -> Config:
    cfg = Config(tg_api_id=1, tg_api_hash="x")
    cfg.db = os.path.join(work, "test.db")
    cfg.tg_session = os.path.join(work, "test.session")
    cfg.express_enabled = True
    cfg.express_session = os.path.join(work, "express.session")
    return cfg


def run_pure() -> None:
    # Номера чатов eXpress — в своём окне, не пересекаются с MAX и Telegram.
    peer = chat_peer(PERSONAL)
    assert is_express_peer(peer) and not is_max_peer(peer)
    assert not is_express_peer(555) and not is_express_peer(-1001234567890)
    assert chat_peer(GROUP) != peer and message_number(MENTION) > 0

    fake = FakeExpress()
    photo, voice = fake.message(fake.rows[PERSONAL][1]), fake.message(fake.rows[PERSONAL][2])
    assert media_kind(photo) == "photo" and describe_message(photo) == "[фото] Фото сервера"
    assert media_kind(voice) == "voice" and describe_message(voice) == "[голосовое]"
    video = fake.message(raw_event(4, PERSONAL, BOSS, "", kind="document",
                                   payload={"file": "/f", "fileName": "a.webm", "fileSize": 1,
                                            "fileMimeType": "video/webm"}))
    assert media_kind(video) == "video" and describe_message(video) == "[видео]"
    doc = fake.message(raw_event(5, PERSONAL, BOSS, "", kind="document",
                                 payload={"file": "/f", "fileName": "отчёт.pdf", "fileSize": 1,
                                          "fileMimeType": "application/pdf"}))
    assert media_kind(doc) == "file" and describe_message(doc) == "[файл отчёт.pdf]"
    sticker = fake.message(raw_event(6, PERSONAL, BOSS, "😀", sticker={"link": "/s.png"}))
    assert media_kind(sticker) == "" and describe_message(sticker) == "[стикер] 😀"

    # Упоминания: заглушка в тексте меняется на имя, «меня» и «всех» видно.
    body = "глянь @{mention:%s} срочно" % MENTION
    mine = fake.message(raw_event(7, GROUP, BOSS, body, **mention("user", ME, "Вася")))
    assert mine.text == "глянь @Вася срочно" and mine.mentions_me and mine.mentions == [ME]
    other = fake.message(raw_event(8, GROUP, BOSS, body, **mention("user", BOSS, "Шеф")))
    assert other.text == "глянь @Шеф срочно" and not other.mentions_me
    everyone = fake.message(raw_event(9, GROUP, BOSS, body, **mention("all", "", "all")))
    assert everyone.text == "глянь @all срочно" and everyone.mentions_me
    chat = fake.message(raw_event(9, GROUP, BOSS, "см. ##{mention:%s}" % MENTION,
                                  **mention("chat", "", "Работа")))
    assert chat.text == "см. #Работа" and not chat.mentions_me

    # Упоминание идёт как личное: мьют ему не мешает, тихие статусы — мешают.
    assert not policy.allows(policy.UNMUTED, "chat", False, True)
    assert policy.allows(policy.UNMUTED, "chat", False, True, mention=True)
    assert policy.allows(policy.QUIET, "chat", False, True, mention=True)
    assert policy.allows(policy.BUSY, "channel", False, True, mention=True)
    assert not policy.allows(policy.FAVOURITES, "chat", False, True, mention=True)
    assert not policy.allows(policy.INVISIBLE, "chat", False, False, mention=True)
    assert policy.allows(policy.INVISIBLE, "chat", True, True, mention=True)

    # Список чатов для TeleMotoMax: у eXpress свой бит сети.
    data = blocks.chat_records([(1, "a", 0, 0, True), (2, "b", 1, 0, False), (3, "c", 2, 0, True)], 4096)
    assert [data[4], data[14], data[24]] == [0x02, 0x01, 0x06], list(data)
    print("  номера, пометки вложений, упоминания, бит сети: ок")


async def run_side() -> None:
    work = tempfile.mkdtemp()
    cfg = make_cfg(work)
    got: list = []

    async def on_message(peer, sender, text, ts=0, topic=0, attach="", mention=False):
        got.append((peer, sender, text, attach, mention))
        return True

    fake = FakeExpress()
    side = ExpressSide(cfg, on_message, client=fake)
    fake.on_message = side._on_new_message
    await side.start()

    dialogs = await side.dialogs()
    assert [(d.title, d.kind, d.group_name, d.muted, d.unread) for d in dialogs] == [
        ("Работа", "chat", "eXpress", True, 0), ("Шеф", "user", "eXpress", False, 2)], dialogs
    personal, group = chat_peer(PERSONAL), chat_peer(GROUP)
    assert await side.title_for(personal) == ("Шеф", "user")
    assert (await side.chat_info(group))["members"] == "участников: 2"
    assert [f["title"] for f in await side.search_chats("раб", 5)] == ["Работа"]

    # История и пропущенное: свои — «Я», в личном чате имя собеседника.
    items = await side.history(personal, None, None, 50)
    assert [(i.who, i.text, i.kind) for i in items] == [
        ("Я", "123", ""), ("Шеф", "[фото] Фото сервера", "photo"), ("Шеф", "[голосовое]", "voice")]
    missed = await side.missed(personal, (NOW_MS - 2500) // 1000, 30)
    assert [text for _, _, text in missed] == ["[фото] Фото сервера", "[голосовое]"], missed
    assert [m[1] for m in await side.missed(group, 0, 30)] == ["Шеф"]

    # Вложение достаётся по номеру сообщения — и после перезапуска, когда
    # в памяти его нет.
    side._messages.clear()
    assert await side.photo_bytes(personal, items[1].msg_id) == b"xxxxx"
    assert await side.voice_bytes(personal, items[2].msg_id, 0) == b"xxx"
    assert await side.voice_bytes(personal, items[2].msg_id, 2) is None, "больше потолка"
    assert await side.photo_bytes(personal, items[2].msg_id) is None, "это не фото"
    rows = await side.render_items(personal, None, None, 50)
    assert [(r["kind"], r["text"], r["mine"]) for r in rows] == [
        ("", "123", True), ("photo", "Фото сервера", False), ("voice", "", False)]
    assert await rows[1]["fetch"]() == b"xxxxx" and rows[2]["seconds"] == 11

    # Отправка: своё сообщение эхом не возвращается.
    assert await side.send(personal, "привет")
    assert fake.sent == [(PERSONAL, "привет")] and got == [], got
    await side.send_photo(group, b"\xff\xd8\xff", "подпись")
    assert fake.sent[-1] == (GROUP, "camera.jpg", b"\xff\xd8\xff", "подпись", False)
    await side.send_voice(personal, b"ogg", 3)
    assert fake.sent[-1][1:] == ("voice.ogg", b"ogg", "", True), "голосовое уходит файлом"

    # Входящие: в группе — с автором, упоминание помечено, своё с другого
    # устройства — только с mirror_outgoing.
    body = "зайди @{mention:%s}" % MENTION
    await side._on_new_message(fake.message(raw_event(20, PERSONAL, BOSS, "ужин в семь")))
    await side._on_new_message(fake.message(raw_event(21, GROUP, BOSS, body,
                                                      **mention("user", ME, "Вася"))))
    await side._on_new_message(fake.message(raw_event(22, PERSONAL, ME, "с ноутбука")))
    edited = raw_event(23, PERSONAL, BOSS, "правка")
    edited["editedAt"] = NOW_MS
    await side._on_new_message(fake.message(edited))
    assert got == [(personal, "", "ужин в семь", "", False),
                   (group, "Шеф", "зайди @Вася", "", True)], got
    cfg.mirror_outgoing = True
    await side._on_new_message(fake.message(raw_event(24, PERSONAL, ME, "с ноутбука")))
    assert got[-1] == (personal, "Я", "с ноутбука", "", False)

    # «Печатает» и присутствие собеседника доходят до моста по номеру чата.
    seen: list = []

    async def on_status(peer, status): seen.append(("status", peer, status))
    async def on_typing(peer, active): seen.append(("typing", peer, active))
    side.on_status, side.on_typing = on_status, on_typing
    await side._on_typing(GROUP, True)
    await side._on_typing(GROUP, False)
    await side._on_presence(BOSS, "online", NOW_MS / 1000)
    await side._on_presence(BOSS, "offline", time.time() - 30)
    await side._on_presence(BOSS, "offline", time.time() - 86400)
    assert seen == [("typing", group, True), ("typing", group, False), ("status", personal, "online"),
                    ("status", personal, "away"), ("status", personal, "offline")], seen
    assert [d.status for d in await side.dialogs()] == ["online", "offline"], "у группы статуса нет"

    # Мьют с телефона.
    assert await side.set_muted(personal, True) and fake.muted[PERSONAL]
    assert [d.muted for d in await side.dialogs()] == [True, True]
    await side.stop()
    print("  сторона eXpress: ок (список, история, вложения, отправка, упоминания, мьют)")


async def run_bridge() -> None:
    work = tempfile.mkdtemp()
    cfg = make_cfg(work)
    bridge = Bridge(cfg)
    assert bridge.express is not None
    fake = FakeExpress()
    bridge.express.client = fake
    fake.on_message = bridge.express._on_new_message

    async def tg_dialogs():
        return [Dialog(555, "user", "Папа", "Личные", 0, "online")]

    bridge.telegram.dialogs = tg_dialogs
    await bridge.express.start()
    await bridge.refresh_roster()

    titles = {c.title: c for c in bridge.roster()}
    assert set(titles) == {"Папа", "Работа", "Шеф"}, titles
    assert titles["Шеф"].group_name == "eXpress" and titles["Работа"].muted
    assert titles["Работа"].position < titles["Папа"].position, "чаты eXpress идут перед Telegram"
    assert bridge.network_of(titles["Шеф"].peer_id) == "eXpress"
    assert bridge._mark(titles["Шеф"]) == "[E] Шеф" and bridge._mark(titles["Папа"]) == "[T] Папа"
    rows = {title: net for _, title, net, _, _ in await bridge.chat_list()}
    assert rows == {"Папа": 0, "Работа": 2, "Шеф": 2}, rows

    await bridge.on_phone_message(titles["Шеф"].uin, "буду в десять")
    assert fake.sent == [(PERSONAL, "буду в десять")]

    queued: list = []

    async def deliver(uin, text, forced=False, url="", ts=0, attach=""):
        queued.append((uin, text))
        return True

    bridge.oscar.deliver = deliver
    # Заглушённая группа молчит, но упоминание из неё доходит.
    body = "ответь @{mention:%s}" % MENTION
    await fake.on_message(fake.message(raw_event(30, GROUP, BOSS, "болтовня")))
    assert queued == [], queued
    await fake.on_message(fake.message(raw_event(31, GROUP, BOSS, body,
                                                 **mention("user", ME, "Вася"))))
    await fake.on_message(fake.message(raw_event(32, GROUP, BOSS, "все сюда @{mention:%s}" % MENTION,
                                                 **mention("all", "", "all"))))
    uin = titles["Работа"].uin
    assert queued == [(uin, "Шеф: ответь @Вася"), (uin, "Шеф: все сюда @all")], queued
    # Чужое упоминание мьют не пробивает; выключенная настройка — тоже.
    await fake.on_message(fake.message(raw_event(33, GROUP, BOSS, body, **mention("user", BOSS, "Шеф"))))
    cfg.mentions_through = False
    await fake.on_message(fake.message(raw_event(34, GROUP, BOSS, body,
                                                 **mention("user", ME, "Вася"))))
    assert len(queued) == 2, queued

    # Мост был выключен: при старте догружается всё непрочитанное, в том
    # числе из заглушённой группы — и упоминание вместе с остальным.
    cfg.mentions_through = True
    before = bridge.storage.pending_count()
    later = NOW_MS + 60_000
    fake.rows[GROUP] += [
        raw_event(40, GROUP, BOSS, "пока тебя не было", later),
        raw_event(41, GROUP, BOSS, "и тебя звали @{mention:%s}" % MENTION, later + 1000,
                  **mention("user", ME, "Вася"))]
    bridge._unread[(chat_peer(GROUP), 0)] = 2
    await bridge.catch_up()
    texts = [row[2] for row in bridge.storage.peek_pending()][before:]
    assert texts == ["Шеф: пока тебя не было", "Шеф: и тебя звали @Вася"], texts

    # eXpress не ответил на обновление списка — его чаты не считаются пропавшими.
    async def broken():
        raise RuntimeError("сеть")
    bridge.express.dialogs = broken
    await bridge.refresh_roster()
    assert bridge.storage.contact_by_peer(chat_peer(PERSONAL)).gone == 0
    await bridge.close()
    print("  мост с eXpress: ок (группа, пометка [E], упоминание из заглушённого чата)")


async def main() -> None:
    run_pure()
    await run_side()
    await run_bridge()
    print("EXPRESS ПРОВЕРЕН")


if __name__ == "__main__":
    asyncio.run(main())
