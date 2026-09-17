"""Проверка того, что «занят» придерживает сообщения, а «не беспокоить» — нет."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge import history, policy
from bridge.bridge import Bridge
from bridge.config import Config
from bridge.oscar import const as C


def make_bridge() -> Bridge:
    cfg = Config(tg_api_id=1, tg_api_hash="x")
    work = tempfile.mkdtemp()
    cfg.db = os.path.join(work, "test.db")
    # Telethon заводит файл сессии сразу при создании клиента — уводим его
    # во временный каталог, чтобы тесты не оставляли следов в проекте.
    cfg.tg_session = os.path.join(work, "test.session")
    cfg.photos_enabled = False
    cfg.busy_hold_minutes = 30
    bridge = Bridge(cfg)
    bridge.storage.uin_for_peer(555, kind="user", title="Мама", group_name="Личные")
    bridge.storage.uin_for_peer(-4001, kind="chat", title="Дача", group_name="Группы")
    # Заглушённый в Telegram чат: в «не беспокоить» он молчит.
    bridge.storage.uin_for_peer(-4002, kind="chat", title="Шумная", group_name="Группы",
                                muted=1)
    bridge.storage.uin_for_peer(-100200, kind="channel", title="Новости",
                                group_name="Каналы", favourite=1)
    bridge._roster = bridge.storage.contacts()
    return bridge


def uin_of(bridge: Bridge, peer_id: int) -> int:
    return bridge.storage.contact_by_peer(peer_id).uin


async def main() -> None:
    # --- «занят»: групповое придерживается, личное проходит ---------------
    bridge = make_bridge()
    await bridge.on_owner_status(C.STATUS_OCCUPIED)
    assert bridge.mode == policy.BUSY

    now = int(time.time())
    await bridge.on_telegram_message(-4001, "Вася", "в группе", now)
    await bridge.on_telegram_message(555, "", "личное", now)

    assert bridge.storage.held_count() == 1, "групповое должно было придержаться"
    assert bridge.storage.pending_count() == 1, "личное должно было пойти на телефон"

    # Придержанное постарше окна — уже не отдаём.
    old = now - 45 * 60
    bridge.storage.hold(uin_of(bridge, -4001), "старое", old, 30)
    assert bridge.storage.held_count() == 2

    # --- возврат в сеть: приходит только свежее ---------------------------
    await bridge.on_owner_status(C.STATUS_ONLINE)
    assert bridge.storage.held_count() == 0, "придержанное должно было разобраться"
    assert bridge.storage.pending_count() == 2, \
        f"ждали личное и свежее групповое, вышло {bridge.storage.pending_count()}"
    texts = [row[2] for row in bridge.storage.peek_pending()]
    assert any("в группе" in t for t in texts), texts
    assert not any("старое" in t for t in texts), texts
    bridge.storage.close()

    # --- заглушённое придерживается, но при возврате в сеть не всплывает ---
    bridge = make_bridge()
    await bridge.on_owner_status(C.STATUS_OCCUPIED)
    now = int(time.time())
    await bridge.on_telegram_message(-4002, "Вася", "из заглушённой", now)
    await bridge.on_telegram_message(555, "", "личное", now)
    assert bridge.storage.held_count() == 1, "заглушённое личное должно придержаться"
    assert bridge.storage.pending_count() == 1, "незаглушённое личное должно пройти"

    await bridge.on_owner_status(C.STATUS_ONLINE)
    assert bridge.storage.pending_count() == 1, \
        "заглушённый чат не должен прорываться вместе с придержанным"

    # А в «свободен для беседы» доходит и оно.
    await bridge.on_owner_status(C.STATUS_OCCUPIED)
    await bridge.on_telegram_message(-4002, "Вася", "ещё из заглушённой", int(time.time()))
    assert bridge.storage.held_count() == 1
    await bridge.on_owner_status(C.STATUS_FREE_FOR_CHAT)
    assert bridge.storage.pending_count() == 2, "тут заглушённое должно дойти"
    print("  заглушённое: придерживается и не всплывает при возврате — ок")
    bridge.storage.close()

    # --- «не беспокоить»: молчит то, что заглушено в Telegram -------------
    bridge = make_bridge()
    await bridge.on_owner_status(C.STATUS_DND)
    assert bridge.mode == policy.QUIET

    await bridge.on_telegram_message(-4002, "Вася", "из заглушённой", int(time.time()))
    assert bridge.storage.held_count() == 0, "«не беспокоить» ничего не копит"
    assert bridge.storage.pending_count() == 0, "заглушённый чат не должен доходить"

    # Обычная группа в «не беспокоить» тоже не доходит — только личные и избранные.
    await bridge.on_telegram_message(-4001, "Вася", "из обычной", int(time.time()))
    assert bridge.storage.pending_count() == 0, "группа не должна доходить"

    # Личное и избранное проходят, если не заглушены.
    await bridge.on_telegram_message(555, "", "личное", int(time.time()))
    await bridge.on_telegram_message(-100200, "", "из избранного", int(time.time()))
    assert bridge.storage.pending_count() == 2, "личное и избранное должны доходить"

    await bridge.on_owner_status(C.STATUS_ONLINE)
    assert bridge.storage.pending_count() == 2, "пропущенное не догоняет"
    bridge.storage.close()

    # --- из «занят» сразу в «не беспокоить»: придержанное не всплывает -----
    bridge = make_bridge()
    await bridge.on_owner_status(C.STATUS_OCCUPIED)
    await bridge.on_telegram_message(-4001, "Вася", "в группе", int(time.time()))
    assert bridge.storage.held_count() == 1
    await bridge.on_owner_status(C.STATUS_DND)
    assert bridge.storage.pending_count() == 0, "в тишину придержанное отдавать нельзя"
    assert bridge.storage.held_count() == 0, "и копить дальше тоже незачем"
    bridge.storage.close()

    # --- «невидимый»: только избранные собеседники ------------------------
    bridge = make_bridge()
    await bridge.on_owner_status(C.STATUS_OCCUPIED)
    now = int(time.time())
    await bridge.on_telegram_message(-4001, "Вася", "в группе", now)
    assert bridge.storage.held_count() == 1

    await bridge.on_owner_status(policy.STATUS_INVISIBLE)
    assert bridge.mode == policy.INVISIBLE
    assert bridge.storage.pending_count() == 0, "в невидимость придержанное не отдаём"

    await bridge.on_telegram_message(-100200, "", "из избранного канала", now)
    await bridge.on_telegram_message(555, "", "от мамы", now)
    assert bridge.storage.pending_count() == 0, \
        "неизбранный собеседник и канал в невидимости молчат"
    assert bridge.storage.held_count() == 0, "невидимость ничего не копит"

    mom = bridge.storage.contact_by_peer(555)
    bridge.storage.toggle_favourite(mom.uin)
    await bridge.on_telegram_message(555, "", "снова от мамы", now)
    assert bridge.storage.pending_count() == 1, "избранный собеседник должен доходить"
    print("  «невидимый»: доходят только избранные собеседники — ок")
    bridge.storage.close()

    # --- команда !fav: чат становится избранным и остаётся им -------------
    bridge = make_bridge()
    group = bridge.storage.contact_by_peer(-4001)
    assert not group.favourite

    await bridge.run_command(group, history.parse("!fav"))
    assert bridge.storage.contact_by_peer(-4001).favourite == 1, "!fav не пометил чат"
    assert bridge.storage.pending_count() == 1, "ответ на команду не пришёл"

    # Обновление списка диалогов не должно сбивать ручной выбор.
    bridge.storage.uin_for_peer(-4001, kind="chat", title="Дача",
                                group_name="Группы", favourite=0)
    assert bridge.storage.contact_by_peer(-4001).favourite == 1, \
        "обновление списка стёрло ручную отметку"

    # В «не беспокоить» избранная группа проходит фильтр, обычная — нет.
    await bridge.on_owner_status(C.STATUS_DND)
    bridge._roster = bridge.storage.contacts()
    before = bridge.storage.pending_count()
    await bridge.on_telegram_message(-4001, "Вася", "привет", int(time.time()))
    assert bridge.storage.pending_count() == before + 1, "избранная группа не прошла"

    # Повторный !fav снимает отметку, и группа снова отсеивается.
    group = bridge.storage.contact_by_peer(-4001)
    await bridge.run_command(group, history.parse("!fav"))
    assert bridge.storage.contact_by_peer(-4001).favourite == 0
    before = bridge.storage.pending_count()
    await bridge.on_telegram_message(-4001, "Вася", "ещё раз", int(time.time()))
    assert bridge.storage.pending_count() == before, "неизбранная группа прошла фильтр"
    bridge.storage.close()

    # --- накопленное в очереди тоже проходит через фильтр статуса ---------
    bridge = make_bridge()
    now = int(time.time())
    group = bridge.storage.contact_by_peer(-4001)
    mom = bridge.storage.contact_by_peer(555)

    # Телефон был не в сети: в очередь попало и групповое, и личное.
    bridge.storage.queue(group.uin, "из группы", 30)
    bridge.storage.queue(mom.uin, "личное", 30)
    assert bridge.storage.pending_count() == 2

    # Владелец входит в «не беспокоить»: групповое доставлять нельзя.
    await bridge.on_owner_status(C.STATUS_DND)
    muted = bridge.storage.contact_by_peer(-4002)
    favourite = bridge.storage.contact_by_peer(-100200)
    assert bridge.verdict_for(muted.uin) == "drop", "заглушённое должно отсеиваться"
    assert bridge.verdict_for(group.uin) == "drop", "групповое должно отсеиваться"
    assert bridge.verdict_for(favourite.uin) == "send", "избранное должно доходить"
    assert bridge.verdict_for(mom.uin) == "send", "личное должно доходить"

    # В «занят» то же самое, но с сохранением до смены статуса.
    await bridge.on_owner_status(C.STATUS_OCCUPIED)
    assert bridge.verdict_for(group.uin) == "hold", "в «занят» надо придержать"
    assert bridge.verdict_for(favourite.uin) == "send", "избранное доходит и в «занят»"

    # В «недоступен» остаётся только избранное.
    await bridge.on_owner_status(C.STATUS_NA)
    assert bridge.verdict_for(favourite.uin) == "send", "избранное доходит всегда"
    assert bridge.verdict_for(mom.uin) == "drop", "в «недоступен» молчат и личные"

    # В «свободен для беседы» проходит всё.
    await bridge.on_owner_status(C.STATUS_FREE_FOR_CHAT)
    assert bridge.verdict_for(group.uin) == "send"
    bridge.storage.close()

    # --- ответ на команду доходит и в «не беспокоить» ---------------------
    bridge = make_bridge()
    group = bridge.storage.contact_by_peer(-4001)
    await bridge.on_owner_status(C.STATUS_DND)

    await bridge.reply(bridge.storage.contact_by_peer(-4002), "ответ на команду")
    rows = bridge.storage.peek_pending()
    assert len(rows) == 1 and rows[0][4] is True, \
        "ответ на команду должен быть помечен как обязательный"

    # Обычное сообщение из заглушённого чата в тишине доставляться не должно.
    silent = bridge.storage.contact_by_peer(-4002)
    await bridge.oscar.deliver(silent.uin, "обычное из заглушённой")
    rows = bridge.storage.peek_pending()
    assert [r[4] for r in rows] == [True, False], [r[4] for r in rows]

    # Отправитель обязан пропустить помеченное и отсеять обычное.
    server = bridge.oscar
    sent: list[str] = []

    class Phone:
        ready, closed = True, False

        async def deliver(self, uin, text, wait_ack=False, row_id=None, url="", attach=""):
            sent.append(text)
            return True

        async def notify_status(self, uin, status): pass

    server.session = Phone()
    server.use_ack = False
    await server.drain_queue()
    assert sent == ["ответ на команду"], sent
    assert bridge.storage.pending_count() == 0, "очередь должна разобраться"
    bridge.storage.close()

    print("  ответ на команду: доходит даже в «не беспокоить» — ок")
    print("  очередь при смене статуса: ок (групповое не прорывается в тишину)")
    print("  «занят»: придерживает и отдаёт свежее — ок")
    print("  «не беспокоить»: не копит и не догоняет — ок")
    print("  команда !fav: переключает избранное и переживает обновление списка — ок")

    # --- roster_limit переживает !fav и прочие перечитывания списка ----------
    bridge = make_bridge()
    bridge.cfg.roster_limit = 2
    bridge._reload_roster()
    assert len(bridge.roster()) == 2, "ограничение списка должно действовать"

    group = bridge.storage.contact_by_peer(-4001)
    await bridge.run_command(group, history.parse("!fav"))
    assert len(bridge.roster()) == 2, \
        f"после !fav список раздулся до {len(bridge.roster())} — ограничение потеряно"
    assert bridge._by_uin[group.uin].favourite == 1, \
        "индекс по UIN должен обновляться вместе со списком"
    assert any(c.uin == group.uin for c in bridge.roster()), \
        "избранный чат остаётся в ограниченном списке"

    await bridge.search_chats("дач")
    assert len(bridge.roster()) == 2, "поиск тоже не должен снимать ограничение"

    # Поиск по Telegram не затирает группу и мьют уже известного чата.
    async def search_chats(query, limit):
        return [{"peer_id": -4002, "kind": "chat", "title": "Шумная", "username": "@noisy"}]

    bridge.telegram.search_chats = search_chats
    before = bridge.storage.contact_by_peer(-4002)
    found = await bridge.search_chats("noisy")
    after = bridge.storage.contact_by_peer(-4002)
    assert found and found[0]["uin"] == before.uin, found
    assert (after.group_name, after.muted, after.position) == \
        (before.group_name, before.muted, before.position), \
        "известный чат после поиска не должен менять группу, мьют и позицию"
    bridge.storage.close()
    print("  roster_limit: ок (не слетает после !fav и поиска)")

    # --- весь список чатов и возвращение вытесненного -----------------------
    bridge = make_bridge()
    bridge.cfg.roster_limit = 2
    bridge._reload_roster()
    in_roster = {c.uin for c in bridge.roster()}
    rows = await bridge.chat_list()
    assert len(rows) == 4, f"в списке должны быть все чаты, а не {len(rows)}"
    assert [r[1] for r in rows] == sorted([r[1] for r in rows], key=str.lower), \
        "список идёт по алфавиту — его листают глазами"
    assert {r[0] for r in rows if r[4]} == in_roster, \
        "пометка «в контакт-листе» должна совпадать с самим списком"
    assert any(not r[4] for r in rows), "вытесненные чаты тоже должны быть в списке"

    # Поиск без запроса отдаёт то же самое, но с пометками сети в названии.
    found = await bridge.search_chats("")
    assert len(found) == 4, found
    assert all(f["title"][:3] in ("[T]", "[M]") for f in found), found
    assert found == await bridge.search_chats("*"), "«*» — тот же «покажи всё»"

    # Убранный чат возвращается на телефон вместе с последним сообщением.
    lost = bridge.storage.contact_by_peer(-4002)
    bridge.storage.set_hidden(lost.uin)
    bridge._reload_roster()
    assert lost.uin not in {c.uin for c in bridge.roster()}

    said: list[str] = []

    async def deliver(uin, text, wait_ack=False, row_id=None, url="", attach="", forced=False):
        said.append(text)
        return True

    async def fetch_history(uin, count, offset=0):
        return [("[16.09 12:00] Вася: последнее", "")], False

    bridge.oscar.deliver = deliver
    bridge.fetch_history = fetch_history
    assert await bridge.open_chat(lost.uin) is True
    assert bridge.storage.contact_by_uin(lost.uin).hidden == 0, "скрытие должно сняться"
    assert lost.uin in {c.uin for c in bridge.roster()}, "чат должен вернуться в список"
    assert said and "последнее" in said[-1], said
    assert await bridge.open_chat(999999) is False, "чужой UIN — отказ"

    # Отправленное с телефона видно в самой переписке: своё голосовое и свой
    # снимок телефон в окно чата не кладёт, это делает мост.
    said.clear()
    mom = bridge.storage.contact_by_peer(555)

    async def send_voice(peer_id, data, seconds=0, voice=True, topic_id=0):
        return 42

    async def send_photo(peer_id, data, caption="", topic_id=0):
        return 43

    bridge.telegram.send_voice = send_voice
    bridge.telegram.send_photo = send_photo
    bridge.cfg.render_ffmpeg = "ffmpeg-которого-нет"
    assert await bridge.send_voice_message(mom.uin, b"#!AMR\n" + b"x" * 100, 75) is True
    assert said and said[-1].startswith("[голосовое 1:15] отправлено"), said
    assert "файлом" in said[-1], "без opus честно говорим, что ушло вложением"
    assert await bridge.send_camera_photo(mom.uin, b"\xff\xd8\xff" + b"x" * 100) is True
    assert said[-1] == "[фото] отправлено", said

    # История пачками: вторая пачка — то, что старее первой.
    del bridge.fetch_history          # выше он был подменён ради open_chat
    import datetime as dt
    from bridge.history import HistoryItem
    when = dt.datetime(2026, 9, 17, 9, 0, tzinfo=dt.timezone.utc)
    whole = [HistoryItem(when, "Вася", f"строка {n}") for n in range(1, 8)]
    wanted: list[int] = []

    async def last_messages(peer_id, count, since, cap, topic_id=0):
        wanted.append(count)
        return whole[-count:] if count else list(whole)

    bridge.telegram.history = last_messages
    rows, more = await bridge.fetch_history(mom.uin, 3)
    assert [r[0].split(": ", 1)[1] for r in rows] == ["строка 5", "строка 6", "строка 7"], rows
    assert more is True, more
    assert wanted[-1] == 4, "берём на одно сообщение больше, чтобы знать про «ещё»"

    rows, more = await bridge.fetch_history(mom.uin, 3, offset=3)
    assert [r[0].split(": ", 1)[1] for r in rows] == ["строка 2", "строка 3", "строка 4"], rows
    assert more is True, "перед ними осталась ещё одна строка"

    rows, more = await bridge.fetch_history(mom.uin, 3, offset=6)
    assert [r[0].split(": ", 1)[1] for r in rows] == ["строка 1"], rows
    assert more is False, "дальше истории нет"
    print("  история пачками: ок (окно по смещению и признак «есть ещё»)")
    bridge.storage.close()
    print("  все чаты: ок (список целиком, пометки сети, возвращение убранного)")
    print("ПРИДЕРЖАНИЕ ПРОВЕРЕНО")


if __name__ == "__main__":
    asyncio.run(main())
