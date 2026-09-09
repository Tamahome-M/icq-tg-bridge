"""Прогон полного диалога Jimm <-> сервер без участия Telegram."""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.config import Config
from bridge.oscar import const as C
from bridge.db import Storage
from bridge.oscar.server import OscarServer
from tests.fake_jimm import FakeJimm

PORT = 15190
CHATS = [
    (777001, "user", "Мама", "Семья"),
    (777002, "user", "Вася Пупкин", "Друзья"),
    (-100200300, "channel", "Новости дня", "Каналы"),
    (-4001, "chat", "Дача 2026", "Семья"),
]


def make_config() -> Config:
    cfg = Config()
    cfg.oscar_host = "127.0.0.1"
    cfg.oscar_port = PORT
    cfg.oscar_uin = "1"
    cfg.oscar_password = "s3cret"
    cfg.bos_host = "127.0.0.1"
    cfg.max_message_chars = 900
    cfg.ack_timeout = 5
    return cfg


async def run_case(login_mode: str) -> None:
    cfg = make_config()
    storage = Storage(":memory:")
    uins = {}
    for pos, (peer, kind, title, group) in enumerate(CHATS):
        uins[title] = storage.uin_for_peer(peer, kind=kind, title=title,
                                           group_name=group, position=pos)

    sent_to_telegram: list[tuple[int, str]] = []

    async def on_outgoing(uin: int, text: str) -> int:
        sent_to_telegram.append((uin, text))
        return 1000 + len(sent_to_telegram)      # номер сообщения в Telegram

    # «Новости дня» офлайн, «Вася Пупкин» отошёл, остальные в сети
    statuses = {uins["Новости дня"]: C.STATUS_OFFLINE, uins["Вася Пупкин"]: C.STATUS_AWAY}
    server = OscarServer(cfg, storage, on_outgoing, storage.contacts,
                         lambda uin: statuses.get(uin, C.STATUS_ONLINE))
    await server.start()

    client = FakeJimm("127.0.0.1", PORT, cfg.oscar_uin, cfg.oscar_password)
    await client.connect()
    login = {"xor": client.login_xor, "md5": client.login_md5,
             "md5_jimm": client.login_md5_jimm}[login_mode]
    cookie = await login()
    assert cookie, "сервер не выдал cookie"
    await client.bos(cookie)
    await client.drain_for(0.7)          # ждём, пока сервер отработает «клиент готов»

    assert len(client.contacts) == len(CHATS), f"контактов {len(client.contacts)}"
    assert client.ssi_stamp, "метка времени списка не пришла"
    assert set(client.groups.values()) == {"Семья", "Друзья", "Каналы"}, client.groups
    assert client.aliases[uins["Новости дня"]] == "Новости дня", client.aliases

    # Повторный запрос списка с версией: клиент ждёт полный список.
    # Короткий ответ «не менялся» вешает Jimm на «checking roster».
    assert client.ssi_stamp and client.ssi_count, "версия контакт-листа не пришла"
    assert await client.check_roster() == "full", \
        "на запрос с версией нужно отдавать список целиком"

    # Запрос офлайн-сообщений: без ответа Jimm застревает на "Reading messages".
    answer = await client.offline_messages()
    assert answer == 0x0042, f"на запрос офлайн-сообщений пришло 0x{answer:04x}"

    # Telegram -> телефон, в том числе кириллица и длинный текст.
    # Отправка идёт фоном, клиент по ходу подтверждает получение.
    await server.deliver(uins["Мама"], "Привет! Как дела? ёжик")
    await server.deliver(uins["Новости дня"], "x" * 2000)
    await client.drain_for(2.0)

    texts = [t for _, t in client.received]
    assert set(client.channels) == {2}, f"ждали доставку каналом 2, было {client.channels}"
    assert "Привет! Как дела? ёжик" in texts, texts[:3]
    assert sum(1 for t in texts if t.startswith("xxx")) == 3, "длинное не разбилось на 3 части"
    assert uins["Мама"] in client.online_uins, "не пришло уведомление об онлайне"
    assert client.statuses[uins["Мама"]] == C.STATUS_ONLINE
    assert client.statuses[uins["Вася Пупкин"]] == C.STATUS_AWAY, "статус «отошёл» не доехал"
    assert client.offline_uins == [uins["Новости дня"]], client.offline_uins
    assert len(client.online_uins) == len(CHATS) - 1, client.online_uins

    # Смена статуса на лету
    await server.notify_status(uins["Мама"], C.STATUS_OFFLINE)
    await client.drain_for(0.5)
    assert uins["Мама"] in client.offline_uins, "уход контакта не доехал"

    # Телефон -> Telegram: сообщение уходит, а в ответ приходит подтверждение
    # с тем же cookie — по нему Jimm рисует галочку доставки.
    cookie = await client.say(uins["Вася Пупкин"], "Привет из Jimm")
    await client.drain_for(0.5)
    assert sent_to_telegram == [(uins["Вася Пупкин"], "Привет из Jimm")], sent_to_telegram
    assert client.acks == [], "галочка не должна появляться раньше прочтения"

    # Собеседник прочитал — вот теперь галочка.
    await server.confirm_read(uins["Вася Пупкин"], 1001)
    await client.drain_for(0.5)
    assert client.acks == [cookie], f"подтверждение не пришло или с чужим cookie: {client.acks}"

    # Контакты должны объявлять возможность «печатает», иначе Jimm
    # не станет присылать уведомления о наборе (JimmUI.hasCapability).
    from bridge.oscar.blocks import CAP_TYPING
    assert CAP_TYPING in client.capabilities.get(uins["Мама"], b""), \
        "в сведениях о контакте нет возможности «печатает»"

    # «Печатает» в обе стороны.
    typed: list[tuple[int, bool]] = []

    async def on_typing(uin: int, active: bool) -> None:
        typed.append((uin, active))

    server.on_typing = on_typing
    await client.send_typing(uins["Мама"], True)
    await asyncio.sleep(0.2)
    assert typed == [(uins["Мама"], True)], typed

    await server.notify_typing(uins["Мама"], True)
    await client.drain_for(0.4)
    assert (uins["Мама"], True) in client.typing, client.typing

    # Незнакомый дополнительный сервис: отвечаем отказом, а не молчанием.
    # За аватарками (0x10) отвечаем адресом службы — это проверяет test_avatars.
    await client.request_service(0x000D)
    await client.drain_for(0.4)
    assert any(family == C.OSERVICE for family, _ in client.errors), client.errors

    # Отключение телефона: сообщения копятся и досылаются при следующем входе.
    await client.close()
    await asyncio.sleep(0.3)
    await server.deliver(uins["Мама"], "Ты где?")
    await asyncio.sleep(0.2)
    assert storage.pending_count() == 1, "сообщение не встало в очередь"

    client2 = FakeJimm("127.0.0.1", PORT, cfg.oscar_uin, cfg.oscar_password)
    await client2.connect()
    cookie = await client2.login_xor()
    await client2.bos(cookie)
    await client2.drain_for(2.5)
    assert any("Ты где?" in t for _, t in client2.received), client2.received
    assert storage.pending_count() == 0

    await client2.close()
    server._server.close()
    await server._server.wait_closed()
    print(f"  вход по {login_mode}: ок ({len(client.contacts)} контактов, "
          f"{len(client.groups)} группы, {len(texts)} сообщений принято)")


async def run_bad_password() -> None:
    cfg = make_config()
    cfg.oscar_port = PORT + 1
    storage = Storage(":memory:")
    async def refuse(*_):
        return None

    server = OscarServer(cfg, storage, refuse, storage.contacts)
    await server.start()
    client = FakeJimm("127.0.0.1", cfg.oscar_port, "1", "wrong")
    await client.connect()
    try:
        await client.login_xor()
    except AssertionError as exc:
        print("  неверный пароль отклонён:", exc)
    else:
        raise AssertionError("сервер пустил с неверным паролем!")
    await client.close()
    server._server.close()


class BrokenSession:
    """Сессия, у которой связь рвётся после нескольких сообщений."""

    def __init__(self, fail_after: int):
        self.fail_after = fail_after
        self.sent = 0
        self.ready = True
        self.closed = False

    async def deliver(self, uin: int, text: str, wait_ack: bool = False,
                      row_id: int | None = None) -> bool:
        if self.sent >= self.fail_after:
            self.closed = True          # телефон отвалился
            return False
        self.sent += 1
        return True

    async def notify_status(self, uin: int, status: int) -> None:
        pass


async def run_queue_safety() -> None:
    """Обрыв посреди досылки не должен съедать сообщения."""
    cfg = make_config()
    cfg.oscar_port = PORT + 2
    storage = Storage(":memory:")
    uin = storage.uin_for_peer(555, kind="user", title="Мама", group_name="Личные")

    async def on_outgoing(*_):
        return 1

    server = OscarServer(cfg, storage, on_outgoing, storage.contacts)

    # Телефона нет: всё копится в очереди.
    for i in range(5):
        await server.deliver(uin, f"сообщение {i}")
    assert storage.pending_count() == 5, storage.pending_count()

    # Связь рвётся после двух доставленных: остальные остаются в очереди.
    server.use_ack = False          # заглушка подтверждений не шлёт
    server.session = BrokenSession(fail_after=2)
    await server.drain_queue()
    assert storage.pending_count() == 3, f"осталось {storage.pending_count()}, ждали 3"

    # Телефон вернулся — досылается остаток, и ничего не задваивается.
    good = BrokenSession(fail_after=99)
    server.session = good
    await server.drain_queue()
    assert storage.pending_count() == 0, storage.pending_count()
    assert good.sent == 3, f"дослано {good.sent}, ждали 3"

    # Сообщение в мёртвую сессию остаётся в очереди.
    server.session = BrokenSession(fail_after=0)
    await server.deliver(uin, "в никуда")
    await server.drain_queue()
    assert storage.pending_count() == 1

    print("  очередь при обрыве связи: ок (ничего не потеряно и не задвоено)")


async def run_without_acks() -> None:
    """Клиент, не присылающий подтверждений, должен получать обычные сообщения."""
    cfg = make_config()
    cfg.oscar_port = PORT + 3
    cfg.ack_timeout = 1
    storage = Storage(":memory:")
    uin = storage.uin_for_peer(555, kind="user", title="Мама", group_name="Личные")

    async def on_outgoing(*_):
        return 1

    server = OscarServer(cfg, storage, on_outgoing, storage.contacts)
    await server.start()

    client = FakeJimm("127.0.0.1", cfg.oscar_port, cfg.oscar_uin, cfg.oscar_password)
    client.send_acks = False
    await client.connect()
    await client.bos(await client.login_md5_jimm())
    await client.drain_for(0.7)

    await server.deliver(uin, "Привет без подтверждений")
    await client.drain_for(4.0)

    assert client.channels[0] == 2, "первая попытка должна идти каналом 2"
    assert 1 in client.channels, f"отката на канал 1 не случилось: {client.channels}"
    assert any("без подтверждений" in t for _, t in client.received), client.received
    assert storage.pending_count() == 0, "сообщение осталось в очереди"
    assert server.ack_works is False, "режим подтверждений должен был отключиться"

    await client.close()
    server._server.close()
    print("  клиент без подтверждений: ок (откат на обычные сообщения, ничего не потеряно)")


async def run_no_blocking() -> None:
    """Очередь не должна стоять, пока телефон молчит: сообщения уходят
    одно за другим, а подтверждения приходят когда придут."""
    cfg = make_config()
    cfg.oscar_port = PORT + 4
    cfg.ack_timeout = 30
    storage = Storage(":memory:")
    uin = storage.uin_for_peer(555, kind="user", title="Мама", group_name="Личные")

    async def on_outgoing(*_):
        return 1

    server = OscarServer(cfg, storage, on_outgoing, storage.contacts)
    await server.start()

    client = FakeJimm("127.0.0.1", cfg.oscar_port, cfg.oscar_uin, cfg.oscar_password)
    await client.connect()
    await client.bos(await client.login_md5_jimm())
    await client.drain_for(0.7)

    for i in range(3):
        await server.deliver(uin, f"сообщение {i}")
    await asyncio.sleep(0.8)          # телефон пока молчит, ничего не читает

    assert storage.in_flight_count() == 3, \
        f"отправлено {storage.in_flight_count()} из 3 — очередь встала в ожидании"
    assert not storage.peek_pending(), "часть сообщений так и не отправлена"

    await client.drain_for(1.5)       # телефон прочитал и подтвердил
    assert storage.pending_count() == 0, \
        f"после подтверждений в очереди осталось {storage.pending_count()}"
    assert len(client.received) == 3, client.received

    await client.close()
    server._server.close()
    print("  доставка не блокируется ожиданием подтверждений: ок")


async def run_status_modes() -> None:
    """Смена статуса в Jimm должна доходить до моста."""
    cfg = make_config()
    cfg.oscar_port = PORT + 6
    storage = Storage(":memory:")

    async def on_outgoing(*_):
        return 1

    server = OscarServer(cfg, storage, on_outgoing, storage.contacts)
    seen: list[int] = []

    async def on_status(status: int) -> None:
        seen.append(status)

    server.on_owner_status = on_status
    await server.start()

    client = FakeJimm("127.0.0.1", cfg.oscar_port, cfg.oscar_uin, cfg.oscar_password)
    await client.connect()
    await client.bos(await client.login_md5_jimm())
    await client.drain_for(0.5)

    for status in (C.STATUS_DND, C.STATUS_FREE_FOR_CHAT, C.STATUS_ONLINE):
        await client.set_status(status)
        await asyncio.sleep(0.2)

    assert seen == [C.STATUS_DND, C.STATUS_FREE_FOR_CHAT, C.STATUS_ONLINE], seen
    assert server.owner_status == C.STATUS_ONLINE, server.owner_status

    # Повтор того же статуса лишний раз мост не дёргает.
    await client.set_status(C.STATUS_ONLINE)
    await asyncio.sleep(0.2)
    assert len(seen) == 3, seen

    await client.close()
    server._server.close()
    print("  смена статуса: ок (доходит до моста, повторы не дёргают)")


async def run_contact_info() -> None:
    """Карточка контакта: сведения о чате Telegram в полях профиля ICQ."""
    cfg = make_config()
    cfg.oscar_port = PORT + 5
    storage = Storage(":memory:")
    uin = storage.uin_for_peer(-100200300, kind="channel", title="Новости дня",
                               group_name="Каналы")

    async def on_outgoing(*_):
        return 1

    async def chat_info(asked: int) -> dict | None:
        if asked != uin:
            return None
        return {"title": "Новости дня", "kind": "Канал", "username": "@news",
                "phone": "", "members": "участников: 1234",
                "about": "Всё самое важное", "bday": (15, 3, 1985),
                "marks": "Избранный, Заглушенный"}

    server = OscarServer(cfg, storage, on_outgoing, storage.contacts,
                         None, chat_info)
    await server.start()

    client = FakeJimm("127.0.0.1", cfg.oscar_port, cfg.oscar_uin, cfg.oscar_password)
    await client.connect()
    await client.bos(await client.login_md5_jimm())
    await client.drain_for(0.7)

    info = await client.request_info(uin)
    assert info["found"], "сервер ответил «контакт не найден»"
    assert info["packets"] >= 5, \
        f"пришло {info['packets']} пакетов — Jimm покажет карточку только с пяти"
    assert info["nick"] == "Новости дня", info
    assert info["kind" if "kind" in info else "first"] == "Канал", info
    assert info["email"] == "@news", info
    assert info["city"] == "участников: 1234", info
    assert info["about"] == "Всё самое важное", info
    assert info["homepage"] == "t.me/news", info
    assert info["company"] == "Telegram", info
    assert info["bday"] == "15.3.1985", info
    assert info["position"] == "Избранный, Заглушенный", \
        f"пометки чата должны приехать в «Должность», пришло {info.get('position')!r}"
    assert info["age"] > 0, "возраст должен считаться по году рождения"

    # Поиск чатов из окна поиска Jimm.
    async def search(query: str) -> list[dict]:
        if "нов" in query.lower():
            return [{"uin": uin, "title": "Новости дня", "kind": "Канал",
                     "username": "@news"}]
        return []

    server.search = search
    results = await client.search("Нов")
    assert len(results) == 1, results
    assert results[0]["uin"] == uin and results[0]["nick"] == "Новости дня", results
    assert results[0]["first"] == "Канал" and results[0]["email"] == "@news", results
    assert await client.search("такого нет") == [], "пустой поиск должен возвращать пусто"

    # Незнакомый UIN — честный ответ «не найдено», а не тишина.
    missing = await client.request_info(999999)
    assert missing.get("found") is False, missing

    await client.close()
    server._server.close()
    print("  карточка контакта и поиск: ок")


async def run_roster_changes() -> None:
    """Чат, удалённый в Telegram, должен уходить из контакт-листа."""
    storage = Storage(":memory:")
    channel = storage.uin_for_peer(-100200300, kind="channel", title="Новости",
                                   group_name="Каналы")
    mom = storage.uin_for_peer(555, kind="user", title="Мама", group_name="Личные")
    assert len(storage.contacts()) == 2

    # Канал пропал из списка диалогов.
    gone = storage.mark_missing([555])
    assert [c.uin for c in gone] == [channel], gone
    assert [c.uin for c in storage.contacts()] == [mom]

    # Пустой ответ Telegram — повод не трогать список, а не стереть его.
    assert storage.mark_missing([]) == []
    assert len(storage.contacts()) == 1

    # Канал вернулся: тот же UIN, значит история на телефоне не разъедется.
    again = storage.uin_for_peer(-100200300, kind="channel", title="Новости",
                                 group_name="Каналы")
    assert again == channel, f"UIN сменился: было {channel}, стало {again}"
    assert len(storage.contacts()) == 2

    print("  удаление и возврат чата: ок (UIN сохраняется)")


async def main() -> None:
    for mode in ("xor", "md5", "md5_jimm"):
        await run_case(mode)
    await run_bad_password()
    await run_queue_safety()
    await run_without_acks()
    await run_no_blocking()
    await run_status_modes()
    await run_contact_info()
    await run_roster_changes()
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")


if __name__ == "__main__":
    asyncio.run(main())
