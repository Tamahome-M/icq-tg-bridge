"""Сторона MAX: чаты одной группой, сообщения в обе стороны, события."""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import sys
import tempfile
import time
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.bridge import Bridge
from bridge.config import Config
from bridge.max import client as maxside
from bridge.max.client import MaxSide, describe_message, from_peer, is_max_peer, to_peer
from bridge.oscar import const as C
from bridge.tg.client import Dialog

ME = 1001
MOM = 2002
BOSS = 3003
AUNT = 4004
DIALOG_ID = ME ^ MOM
GROUP_ID = -72_056_572_839_294       # группы в MAX нумеруются отрицательными числами
NOW_MS = 1_800_000_000_000


def user(uid: int, name: str, **extra):
    # Как у MAX: первое имя — короткое, из профиля; второе — из адресной книги.
    names = [NS(name=name.split()[0], first_name=None, last_name=None),
             NS(name=None, first_name=name.split()[0], last_name=" ".join(name.split()[1:]) or None)]
    return NS(id=uid, names=names,
              photo_id=extra.get("photo_id", 0), base_url=extra.get("base_url", ""),
              phone=extra.get("phone"), description=extra.get("about", ""))


def message(mid: int, chat_id: int, sender: int, text: str = "", when: int = NOW_MS,
            attaches: list | None = None):
    return NS(id=mid, chat_id=chat_id, sender=sender, text=text, time=when,
              attaches=attaches or [], type="TEXT")


class FakeMax:
    """Подделка клиента PyMax: ровно те методы, которыми пользуется мост."""

    def __init__(self):
        self.me = NS(contact=user(ME, "Я сам"))
        self.users = {MOM: user(MOM, "Мама Петровна", phone=79990001122, about="мама"),
                      BOSS: user(BOSS, "Шеф"), AUNT: user(AUNT, "Тётя Валя")}
        # Адресная книга: мама (переписка есть) и тётя (переписки нет).
        self.contacts = [self.users[MOM], None, self.users[AUNT], self.me.contact]
        self.chats = [
            NS(id=0, type="DIALOG", participants={ME: 1}, title=None,
               last_event_time=NOW_MS - 5000, new_messages=0, base_icon_url="",
               description="", participants_count=1, link=None),
            NS(id=DIALOG_ID, type="DIALOG", participants={ME: 1, MOM: 1}, title=None,
               last_event_time=NOW_MS - 1000, new_messages=2, base_icon_url="",
               description="", participants_count=2, link=None),
            NS(id=GROUP_ID, type="CHAT", participants={ME: 1, BOSS: 1}, title="Работа",
               last_event_time=NOW_MS, new_messages=0, base_icon_url="http://x/icon",
               description="рабочий чат", participants_count=12, link="https://max.ru/join/abc"),
        ]
        self.history = {
            DIALOG_ID: [message(1, DIALOG_ID, MOM, "привет", NOW_MS - 30_000),
                        message(2, DIALOG_ID, ME, "и тебе", NOW_MS - 20_000),
                        message(3, DIALOG_ID, MOM, "", NOW_MS - 10_000,
                                [NS(type="PHOTO", base_url="http://x/p.jpg", photo_id=5,
                                    height=10, width=10, photo_token="t")])],
            GROUP_ID: [message(10, GROUP_ID, BOSS, "план на завтра", NOW_MS - 5_000)],
        }
        self.sent: list[tuple[int, str]] = []
        self.fetched: list = []
        self.invoked: list = []
        self._app = self                      # client._app.invoke — как у PyMax
        self.read: list[tuple[int, int]] = []
        self.handlers: dict[str, object] = {}
        self.next_id = 100

    # регистрация обработчиков — как декораторы PyMax
    def _reg(self, name):
        def deco(*_filters):
            def wrap(fn):
                self.handlers[name] = fn
                return fn
            return wrap
        return deco

    def on_start(self): return self._reg("start")()
    def on_message(self, *f): return self._reg("message")()
    def on_typing(self, *f): return self._reg("typing")()
    def on_presence(self, *f): return self._reg("presence")()
    def on_message_read(self, *f): return self._reg("read")()
    def on_disconnect(self): return self._reg("disconnect")()
    def on_raw(self, *f): return self._reg("raw")()

    async def start(self):
        # Ответ на вход: сервер прикладывает присутствие контактов.
        await self.handlers["raw"](NS(opcode=19, cmd=1, seq=1, payload={
            "presence": {str(MOM): {"seen": int(time.time() * 1000) - 3_600_000, "status": 1},
                         str(BOSS): {"seen": 0, "status": 1}}}), self)
        # Настройки профиля по чатам в ответе на вход: группа заглушена навсегда.
        await self.handlers["raw"](NS(opcode=19, cmd=1, seq=2, payload={
            "config": {"hash": "x", "chats": {str(GROUP_ID): {"dontDisturbUntil": -1, "favIndex": 0},
                                              str(DIALOG_ID): {"dontDisturbUntil": 0}}}}), self)
        await self.handlers["start"](self)
        await asyncio.Event().wait()          # живём, пока не отменят

    async def connect(self):
        await self.handlers["start"](self)

    async def close(self): pass

    async def fetch_chats(self, marker=None):
        self.fetched.append(marker)
        # Страницами по одному чату, как сервер: маркер — старше самого старого.
        older = [c for c in self.chats if marker is None or c.last_event_time <= marker]
        older.sort(key=lambda c: -c.last_event_time)
        return older[:1]
    async def get_chat(self, chat_id):
        for c in self.chats:
            if c.id == chat_id:
                return c
        raise KeyError(chat_id)
    def get_cached_user(self, uid): return self.users.get(uid)
    async def get_user(self, uid): return self.users.get(uid)

    async def fetch_history(self, chat_id, backward=40, **kw):
        return list(self.history.get(chat_id, []))[-backward:]

    async def send_message(self, chat_id, text=None, reply_to=None, attachments=None, **kw):
        self.sent.append((chat_id, text))
        self.next_id += 1
        return message(self.next_id, chat_id, ME, text, NOW_MS + self.next_id * 1000)

    async def invoke(self, opcode, payload, **kw):
        self.invoked.append((opcode, payload))
        return NS(opcode=opcode, payload={"hash": "y"})

    async def read_message(self, message_id, chat_id):
        self.read.append((chat_id, message_id))
        return NS(unread=0, mark=NOW_MS)


def make_cfg(work: str) -> Config:
    cfg = Config(tg_api_id=1, tg_api_hash="x")
    cfg.db = os.path.join(work, "test.db")
    cfg.tg_session = os.path.join(work, "test.session")
    cfg.photos_enabled = False
    cfg.max_enabled = True
    cfg.max_phone = "+79990000000"
    cfg.max_session = os.path.join(work, "max.session")
    return cfg


def run_pure() -> None:
    assert from_peer(to_peer(5)) == 5 and is_max_peer(to_peer(5))
    assert from_peer(to_peer(GROUP_ID)) == GROUP_ID and is_max_peer(to_peer(GROUP_ID))
    assert not is_max_peer(555) and not is_max_peer(-1001234567890) and not is_max_peer(-999_999_999_999_999)
    try:
        to_peer(10 ** 16)
    except ValueError:
        pass
    else:
        raise AssertionError("слишком большой номер должен отвергаться")
    assert describe_message(message(1, 1, 1, "текст")) == "текст"
    photo = NS(type="PHOTO")
    assert describe_message(message(1, 1, 1, "", attaches=[photo])) == "[фото]"
    assert describe_message(message(1, 1, 1, "гляди", attaches=[photo])) == "[фото] гляди"
    assert describe_message(message(1, 1, 1, "", attaches=[NS(type="FILE", name="a.pdf")])) == "[файл a.pdf]"
    assert describe_message(message(1, 1, 1, "", attaches=[NS(type="SHARE")])) == ""
    assert maxside._seconds(NOW_MS) == NOW_MS // 1000 and maxside._seconds(1_800_000_000) == 1_800_000_000
    import time
    assert maxside.presence_name(NS(seen=int(time.time() * 1000) - 5000, status=1)) == "online"
    assert maxside.presence_name(NS(seen=int(time.time() * 1000) - 300_000, status=1)) == "away"
    assert maxside.presence_name(NS(seen=int(time.time() * 1000) - 3_600_000, status=1)) == "offline"
    print("  чистые функции: ок (номера, пометки вложений, время, присутствие)")


async def run_side() -> None:
    work = tempfile.mkdtemp()
    cfg = make_cfg(work)
    got: list = []
    statuses: list = []
    typing: list = []
    reads: list = []

    async def on_message(peer, sender, text, ts, topic):
        got.append((peer, sender, text, ts, topic))
        return True

    async def on_status(peer, status): statuses.append((peer, status))
    async def on_typing(peer, active): typing.append((peer, active))
    async def on_read(peer, mark): reads.append((peer, mark))

    fake = FakeMax()
    side = MaxSide(cfg, on_message, on_status, on_typing, on_read, client=fake)
    await side.start()
    assert side.me_id == ME

    # Список чатов: одна группа, личный чат назван по собеседнику, свежие первыми.
    fake.chats_on_login = None
    dialogs = await side.dialogs()
    assert [d.title for d in dialogs] == ["Работа", "Мама Петровна", "Я", "Тётя Валя"], dialogs
    # Контакт без переписки: свой чат с вычисленным номером, писать можно сразу.
    aunt = dialogs[3]
    assert aunt.peer_id == to_peer(ME ^ AUNT) and aunt.kind == "user"
    assert await side.title_for(aunt.peer_id) == ("Тётя Валя", "user")
    assert (await side.chat_info(aunt.peer_id))["kind"] == "Личный чат"
    assert await side.history(aunt.peer_id, 10, None, 50) == []
    await side.send(aunt.peer_id, "привет, тётя")
    assert fake.sent[-1] == (ME ^ AUNT, "привет, тётя")
    fake.sent.clear()
    assert len(fake.fetched) >= 2, "список собирается страницами, пока сервер отдаёт новое"
    assert all(d.group_name == "MAX" for d in dialogs)
    assert [d.kind for d in dialogs] == ["chat", "user", "user", "user"]
    assert dialogs[1].peer_id == to_peer(DIALOG_ID) and dialogs[1].unread == 2
    assert dialogs[0].photo_id and not dialogs[1].photo_id
    assert dialogs[2].peer_id == to_peer(0), "чат с собой — номер 0"
    # «Не беспокоить» — из сырого описания чата: у группы есть, у личного нет.
    assert dialogs[0].muted and not dialogs[1].muted, dialogs
    assert side.is_muted(GROUP_ID) and not side.is_muted(DIALOG_ID) and not side.is_muted(12345)
    # Статусы: у группы «online» по соглашению, у человека — по присутствию из входа.
    assert dialogs[0].status == "online" and dialogs[1].status == "offline", dialogs

    # Входящее: личное — без отправителя, групповое — с именем; своё — не возвращается.
    await side._on_new_message(message(50, DIALOG_ID, MOM, "ты где?"))
    await side._on_new_message(message(51, GROUP_ID, BOSS, "созвон в 10"))
    await side._on_new_message(message(52, GROUP_ID, ME, "ок"))
    assert got == [(to_peer(DIALOG_ID), "", "ты где?", NOW_MS // 1000, 0),
                   (to_peer(GROUP_ID), "Шеф", "созвон в 10", NOW_MS // 1000, 0)], got
    assert fake.read == [], "без mark_read прочитанным не отмечаем"

    # Отправка: возвращается время сообщения — по нему приходит отметка прочтения.
    stamp = await side.send(to_peer(DIALOG_ID), "иду")
    assert fake.sent == [(DIALOG_ID, "иду")]
    assert stamp == NOW_MS + fake.next_id * 1000
    await side._on_new_message(message(fake.next_id, DIALOG_ID, ME, "иду"))
    assert len(got) == 2, "отправленное мостом не должно вернуться на телефон"
    await side._on_read(NS(chat_id=DIALOG_ID, user_id=MOM, mark=stamp, set_as_unread=False))
    assert reads == [(to_peer(DIALOG_ID), stamp)]

    # Присутствие человека — статус личного чата с ним; набор — «печатает».
    import time
    await side._on_presence(NS(user_id=MOM, presence=NS(seen=int(time.time() * 1000), status=1)))
    assert statuses == [(to_peer(DIALOG_ID), "online")], statuses
    await side._on_typing(NS(chat_id=GROUP_ID, user_id=BOSS))
    assert typing == [(to_peer(GROUP_ID), True)]

    # История и пропущенное.
    items = await side.history(to_peer(DIALOG_ID), 10, None, 50)
    assert [(i.who, i.text) for i in items] == [("Мама Петровна", "привет"), ("Я", "и тебе"), ("Мама Петровна", "[фото]")], items
    missed = await side.missed(to_peer(DIALOG_ID), (NOW_MS - 25_000) // 1000, 50)
    assert [(s, t) for _, s, t in missed] == [("", "[фото]")], missed

    # Страница: фото с загрузчиком, своё помечено.
    rows = await side.render_items(to_peer(DIALOG_ID), 10, None, 50)
    assert [r["kind"] for r in rows] == ["", "", "photo"] and rows[1]["mine"]
    assert rows[2]["fetch"] is not None

    # Поиск по своим чатам, карточка, название нового чата.
    found = await side.search_chats("раб", 5)
    assert found and found[0]["peer_id"] == to_peer(GROUP_ID)
    info = await side.chat_info(to_peer(GROUP_ID))
    assert info["kind"] == "Группа" and info["members"] == "участников: 12"
    info = await side.chat_info(to_peer(DIALOG_ID))
    assert info["title"] == "Мама Петровна" and info["phone"] == "+79990001122"
    assert await side.title_for(to_peer(DIALOG_ID)) == ("Мама Петровна", "user")

    # Заглушение: настройка профиля опкодом CONFIG, -1 — навсегда, 0 — снять.
    assert await side.set_muted(to_peer(DIALOG_ID), True) is True
    assert fake.invoked[-1] == (22, {"settings": {"chats": {str(DIALOG_ID): {"dontDisturbUntil": -1}}}})
    assert side.is_muted(DIALOG_ID)
    assert await side.set_muted(to_peer(DIALOG_ID), False) is True
    assert fake.invoked[-1][1]["settings"]["chats"][str(DIALOG_ID)]["dontDisturbUntil"] == 0
    assert not side.is_muted(DIALOG_ID)
    # Заглушили на десктопе — уведомление с настройкой, срок истёк — не заглушён.
    await fake.handlers["raw"](NS(opcode=134, cmd=0, seq=0, payload={
        "settings": {"chats": {str(DIALOG_ID): {"dontDisturbUntil": 1}}}}), fake)
    assert not side.is_muted(DIALOG_ID), "истёкший срок — уже не заглушён"
    await fake.handlers["raw"](NS(opcode=134, cmd=0, seq=0, payload={
        "settings": {"chats": {str(DIALOG_ID): {"dontDisturbUntil": int(time.time() * 1000) + 3_600_000}}}}), fake)
    assert side.is_muted(DIALOG_ID), "срок в будущем — заглушён"

    await side.stop()
    print("  сторона MAX: ок (список, сообщения, отправка, события, история, карточка)")


async def run_bridge() -> None:
    work = tempfile.mkdtemp()
    cfg = make_cfg(work)
    cfg.mark_read = True
    bridge = Bridge(cfg)
    assert bridge.max is not None
    fake = FakeMax()
    bridge.max.client = fake

    async def tg_dialogs():
        return [Dialog(555, "user", "Папа", "Личные", 0, "online")]

    tg_sent: list = []

    async def tg_send(peer, text, topic=0):
        tg_sent.append((peer, text))
        return 7

    bridge.telegram.dialogs = tg_dialogs
    bridge.telegram.send = tg_send
    await bridge.max.start()
    await bridge.refresh_roster()

    # Оба списка в одном контакт-листе; группы MAX — своя.
    titles = {c.title: c for c in bridge.roster()}
    assert set(titles) == {"Папа", "Работа", "Мама Петровна", "Я", "Тётя Валя"}, titles
    assert titles["Мама Петровна"].group_name == "MAX" and titles["Папа"].group_name == "Личные"
    assert titles["Работа"].position < titles["Папа"].position, "чаты MAX идут перед Telegram"
    # У каждой сети своё ограничение: roster_limit Telegram не трогает MAX и наоборот.
    cfg.roster_limit = 1
    bridge._reload_roster()
    assert {c.title for c in bridge.roster()} == {"Папа", "Работа", "Мама Петровна", "Я", "Тётя Валя"}
    cfg.max_roster_limit = 1
    bridge._reload_roster()
    assert {c.title for c in bridge.roster()} == {"Папа", "Работа"}, "самый свежий чат MAX"
    cfg.roster_limit = cfg.max_roster_limit = 0
    bridge._reload_roster()

    # Сообщение с телефона уходит в нужную сеть.
    await bridge.on_phone_message(titles["Мама Петровна"].uin, "привет, мам")
    await bridge.on_phone_message(titles["Папа"].uin, "привет, пап")
    assert fake.sent == [(DIALOG_ID, "привет, мам")] and tg_sent == [(555, "привет, пап")]

    # Входящее из MAX — в очередь телефону под нужным UIN и отмечено прочитанным.
    queued: list = []

    async def deliver(uin, text, forced=False, url="", ts=0):
        queued.append((uin, text))
        return True

    bridge.oscar.deliver = deliver
    await fake.handlers["message"](message(60, DIALOG_ID, MOM, "ужин в семь"), fake)
    assert queued == [(titles["Мама Петровна"].uin, "ужин в семь")], queued
    assert fake.read == [(DIALOG_ID, 60)]

    # Новый чат MAX, которого не было в списке, заводится в группе MAX.
    fake.chats.append(NS(id=4242, type="CHANNEL", participants={}, title="Новости MAX",
                         last_event_time=NOW_MS, new_messages=0, base_icon_url="",
                         description="", participants_count=0, link=None))
    await fake.handlers["message"](message(61, 4242, 0, "выпуск"), fake)
    fresh = bridge.storage.contact_by_peer(to_peer(4242))
    assert fresh is not None and fresh.group_name == "MAX" and fresh.kind == "channel"

    # Карточка и статус — через сторону MAX.
    info = await bridge.chat_info(titles["Мама Петровна"].uin)
    assert info["kind"] == "Личный чат"

    # Сторона не ответила — карточка всё равно не пустая.
    async def no_info(peer):
        raise RuntimeError("поле пропало")
    bridge.max.chat_info = no_info
    info = await bridge.chat_info(titles["Мама Петровна"].uin)
    assert info["title"] == "Мама Петровна" and info["kind"] == "Личные", info
    await bridge.on_telegram_status(to_peer(DIALOG_ID), "offline")
    assert bridge.status_of(titles["Мама Петровна"].uin) == C.STATUS_OFFLINE

    # MAX не ответил на обновление списка — его чаты не считаются пропавшими.
    async def broken():
        raise RuntimeError("сеть")
    bridge.max.dialogs = broken
    await bridge.refresh_roster()
    assert bridge.storage.contact_by_peer(to_peer(DIALOG_ID)).gone == 0

    await bridge.max.stop()
    bridge.storage.close()
    print("  мост с двумя сетями: ок (общий список, маршрутизация, новый чат, статусы)")


async def main() -> None:
    run_pure()
    await run_side()
    await run_bridge()
    print("MAX ПРОВЕРЕН")


if __name__ == "__main__":
    asyncio.run(main())
