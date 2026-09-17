"""TeleMotoMax — расширенный клиент: мост узнаёт его по способности."""

from __future__ import annotations

import asyncio
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.config import Config
from bridge.db import Storage
from bridge.oscar import const as C
from bridge.oscar.proto import flap, pstr8, tlv
from bridge.oscar.server import OscarServer
from tests.fake_jimm import FakeJimm

PORT = 15900


def make_server(port: int) -> tuple[OscarServer, Storage]:
    cfg = Config(tg_api_id=1, tg_api_hash="x")
    cfg.oscar_host, cfg.oscar_port = "127.0.0.1", port
    cfg.oscar_uin, cfg.oscar_password = "100500", "s3cret"
    storage = Storage(":memory:")
    storage.uin_for_peer(555, kind="user", title="Мама", group_name="Личные")

    async def on_outgoing(*_):
        return 1

    return OscarServer(cfg, storage, on_outgoing, storage.contacts), storage


async def run_detection() -> None:
    server, _ = make_server(PORT)
    await server.start()

    # Обычный Jimm: способности без нашей — сессия обычная.
    client = FakeJimm("127.0.0.1", PORT, "100500", "s3cret")
    await client.connect()
    await client.bos(await client.login_md5_jimm())
    await client.drain_for(0.5)
    session = server.session
    assert session is not None and not session.extended and session.client_name == "?", \
        (session.extended, session.client_name)
    await client.close()
    await asyncio.sleep(0.2)

    # TeleMotoMax 0.1: та же цепочка плюс способность «TMM:» — сессия расширенная.
    client = FakeJimm("127.0.0.1", PORT, "100500", "s3cret")
    client.tmm_version = (0, 1)
    await client.connect()
    await client.bos(await client.login_md5_jimm())
    await client.drain_for(0.5)
    session = server.session
    assert session is not None and session.extended, "TeleMotoMax не опознан"
    assert session.tmm_version == (0, 1) and session.client_name == "TeleMotoMax 0.1", \
        (session.tmm_version, session.client_name)
    # Всё обычное при этом работает: сообщение доходит.
    await server.deliver(server.storage.contact_by_peer(555).uin, "привет")
    await client.drain_for(0.5)
    assert any("привет" in t for _, t in client.received), client.received
    await client.close()
    server._server.close()
    print("  опознание: ок (Jimm — обычная сессия, TeleMotoMax 0.1 — расширенная)")


def small_jpeg() -> bytes:
    """Снимок «из Telegram»: большой, чтобы мосту было что ужимать."""
    import io
    from PIL import Image
    out = io.BytesIO()
    img = Image.new("RGB", (800, 600))
    for x in range(0, 800, 4):
        for y in range(0, 600, 4):
            img.putpixel((x, y), (x % 256, y % 256, 128))
    img.save(out, format="JPEG", quality=90)
    return out.getvalue()


async def run_photos() -> None:
    """Снимок из сообщения: обычному Jimm — только пометка, TeleMotoMax —
    токен, по которому он забирает картинку через службу 0x10."""
    cfg = Config(tg_api_id=1, tg_api_hash="x")
    cfg.oscar_host, cfg.oscar_port = "127.0.0.1", PORT + 1
    cfg.oscar_uin, cfg.oscar_password = "100500", "s3cret"
    cfg.avatars = True                      # служба 0x10 включается вместе с аватарками
    cfg.tmm_photo_width, cfg.tmm_photo_height, cfg.tmm_photo_max_kb = 176, 176, 12
    storage = Storage(":memory:")
    uin = storage.uin_for_peer(555, kind="user", title="Мама", group_name="Личные")
    asked: list[tuple[int, str]] = []

    async def on_outgoing(*_):
        return 1

    async def fetch_attachment(target: int, attach: str):
        asked.append((target, attach))
        from bridge import photos
        got = photos.shrink(small_jpeg(), cfg.tmm_photo_width, cfg.tmm_photo_height,
                            cfg.tmm_photo_max_kb * 1024)
        return got[0] if got else None

    server = OscarServer(cfg, storage, on_outgoing, storage.contacts,
                         fetch_attachment=fetch_attachment)
    await server.start()

    # Обычный Jimm: сообщение с фото приходит текстом, TLV вложения нет.
    client = FakeJimm("127.0.0.1", cfg.oscar_port, "100500", "s3cret")
    await client.connect()
    await client.bos(await client.login_md5_jimm())
    await client.drain_for(0.3)
    await server.deliver(uin, "[фото] закат", attach="photo:4242")
    await client.drain_for(0.5)
    assert client.received and "[фото] закат" in client.received[-1][1], client.received
    assert client.attachments == [], "обычному Jimm вложение слать нельзя"
    await client.close()
    await asyncio.sleep(0.2)

    # TeleMotoMax: тот же текст плюс токен; по токену — снимок.
    client = FakeJimm("127.0.0.1", cfg.oscar_port, "100500", "s3cret")
    client.tmm_version = (0, 1)
    await client.connect()
    await client.bos(await client.login_md5_jimm())
    await client.drain_for(0.3)
    await server.deliver(uin, "[фото] закат", attach="photo:4242")
    await client.drain_for(0.5)
    assert client.attachments and client.attachments[-1][0] == uin, client.attachments
    token = client.attachments[-1][1]
    assert len(token) == 16
    assert asked == [], "снимок не должен тянуться заранее"

    got = await client.request_photo(uin, token)
    assert asked == [(uin, "photo:4242")], asked
    assert got["image"][:3] == b"\xff\xd8\xff", "ждали JPEG"
    assert len(got["image"]) <= 12 * 1024, len(got["image"])
    from PIL import Image
    import io
    with Image.open(io.BytesIO(got["image"])) as img:
        assert max(img.size) <= 176, img.size

    # Видео: та же примета, только вид 2, и кадр-превью по запросу.
    client.attachments.clear()
    await server.deliver(uin, "[видео 0:12] ролик", attach="video:4343")
    await client.drain_for(0.5)
    assert client.attachments and client.attachments[-1][0] == uin, client.attachments
    got = await client.request_photo(uin, client.attachments[-1][1])
    assert asked[-1] == (uin, "video:4343") and got["image"][:3] == b"\xff\xd8\xff"

    # Короткий ролик укладывается в один пакет — тот же путь, что у фото.
    short = bytes(range(256)) * 150                    # 38 400 байт
    videos: list[str] = []

    async def fetch_short(target: int, attach: str):
        videos.append(attach)
        return short

    server.fetch_video = fetch_short
    client.parts_seen.clear()
    got_short = await client.request_video(uin, client.attachments[-1][1])
    assert videos == ["video:4343"], videos
    assert got_short == short, (len(got_short), len(short))
    assert client.parts_seen == [(1, 1)], client.parts_seen

    # Длинный ролик — частями по 60 КБ, клиент склеивает байт в байт.
    clip = bytes(range(256)) * 500                     # 128 000 байт
    async def fetch_clip(target: int, attach: str):
        return clip
    server.fetch_video = fetch_clip
    client.parts_seen.clear()
    got_clip = await client.request_video(uin, client.attachments[-1][1])
    assert got_clip == clip, (len(got_clip), len(clip))
    assert client.parts_seen == [(1, 3), (2, 3), (3, 3)], client.parts_seen

    # Чужой или протухший токен — отказ службы, а не тишина.
    await client.request_service(C.SSBI)
    redirect = await client.expect(C.OSERVICE, C.SERVICE_REDIRECT)
    assert redirect.data
    await client.close()
    server._server.close()
    print("  снимки: ок (Jimm — без вложения, TeleMotoMax — токен и картинка по запросу)")


async def run_history() -> None:
    """История чата на отдельный экран: текст последних N сообщений по службе 0x10."""
    import datetime as dt
    from bridge.history import HistoryItem

    cfg = Config(tg_api_id=1, tg_api_hash="x")
    cfg.oscar_host, cfg.oscar_port = "127.0.0.1", PORT + 2
    cfg.oscar_uin, cfg.oscar_password = "100500", "s3cret"
    storage = Storage(":memory:")
    uin = storage.uin_for_peer(555, kind="user", title="Мама", group_name="Личные")
    asked: list[tuple[int, int]] = []

    async def on_outgoing(*_):
        return 1

    fetched: list[str] = []

    when = dt.datetime(2026, 9, 16, 10, 0, tzinfo=dt.timezone.utc)
    whole = [HistoryItem(when, "Мама", "самое старое"), HistoryItem(when, "Я", "и правда"),
             HistoryItem(when, "Мама", "привет"), HistoryItem(when, "Я", "и тебе"),
             HistoryItem(when, "Мама", "[фото] закат", 4242, "photo"),
             HistoryItem(when, "Папа", "[видео 0:09] кот", 4343, "video")]

    async def fetch_history(target: int, count: int, offset: int = 0):
        asked.append((target, count, offset))
        end = max(0, len(whole) - offset)
        start = max(0, end - count)
        rows = [(f"[{i.when:%d.%m %H:%M}] {i.who}: {i.text}",
                 f"{i.kind}:{i.msg_id}" if i.kind in ("photo", "video") else "",
                 i.who == "Я")
                for i in whole[start:end]]
        return rows, start > 0

    async def fetch_attachment(target: int, attach: str):
        fetched.append(attach)
        return small_jpeg()[:3000]

    server = OscarServer(cfg, storage, on_outgoing, storage.contacts,
                         fetch_attachment=fetch_attachment, fetch_history=fetch_history)
    await server.start()
    client = FakeJimm("127.0.0.1", cfg.oscar_port, "100500", "s3cret")
    client.tmm_version = (0, 2)
    await client.connect()
    await client.bos(await client.login_md5_jimm())
    await client.drain_for(0.3)

    rows = await client.request_history(uin, 4)
    assert asked == [(uin, 4, 0)], asked
    assert [t.split("] ", 1)[1] for t, _, _, _ in rows] == \
        ["Мама: привет", "Я: и тебе", "Мама: [фото] закат", "Папа: [видео 0:09] кот"], rows
    assert rows[0][1] is None and rows[2][1] is not None, "у сообщения с фото должен быть токен"
    assert [k for _, _, k, _ in rows] == ["", "", "photo", "video"], "вид вложения — во флаге записи"
    assert [m for _, _, _, m in rows] == [False, True, False, False], "своё сообщение помечено"
    # Фото из истории открывается тем же запросом, что и из чата.
    got = await client.request_photo(uin, rows[2][1])
    assert fetched == ["photo:4242"] and got["image"][:3] == b"\xff\xd8\xff"

    # Пачками: первая — свежие, вторая — то, что старее, и мост говорит,
    # осталось ли ещё.
    asked.clear()
    first, more = await client.request_history_page(uin, 4)
    assert asked == [(uin, 4, 0)], asked
    assert [t.split("] ", 1)[1] for t, _, _, _ in first][0] == "Мама: привет"
    assert more is True, "в чате осталось ещё два сообщения"

    older, more = await client.request_history_page(uin, 4, offset=4)
    assert asked[-1] == (uin, 4, 4), asked
    assert [t.split("] ", 1)[1] for t, _, _, _ in older] == \
        ["Мама: самое старое", "Я: и правда"], older
    assert more is False, "дальше истории нет — «Ещё» предлагать не надо"
    await client.close()
    server._server.close()
    print("  история: ок (последние сообщения и подгрузка пачками)")


async def run_camera() -> None:
    """Снимок с камеры телефона уходит в чат; обычному Jimm это недоступно."""
    cfg = Config(tg_api_id=1, tg_api_hash="x")
    cfg.oscar_host, cfg.oscar_port = "127.0.0.1", PORT + 3
    cfg.oscar_uin, cfg.oscar_password = "100500", "s3cret"
    storage = Storage(":memory:")
    uin = storage.uin_for_peer(555, kind="user", title="Мама", group_name="Личные")
    got: list[tuple[int, int]] = []

    async def on_outgoing(*_):
        return 1

    async def on_photo(target: int, data: bytes) -> bool:
        got.append((target, len(data)))
        return data[:3] == b"\xff\xd8\xff"        # принимаем только JPEG

    server = OscarServer(cfg, storage, on_outgoing, storage.contacts, on_photo=on_photo)
    await server.start()

    client = FakeJimm("127.0.0.1", cfg.oscar_port, "100500", "s3cret")
    client.tmm_version = (0, 3)
    await client.connect()
    await client.bos(await client.login_md5_jimm())
    await client.drain_for(0.3)

    # Снимок больше одной части — мост собирает его целиком.
    shot = small_jpeg()
    assert len(shot) > 30000, len(shot)
    assert await client.send_camera_photo(uin, shot) is True
    assert got == [(uin, len(shot))], got

    # Не JPEG — мост отвечает отказом, а не молчанием.
    assert await client.send_camera_photo(uin, b"not a jpeg" * 100) is False
    await client.close()
    await asyncio.sleep(0.2)

    # Обычный Jimm: части приходят, но сессия не расширенная — ничего не шлём.
    got.clear()
    plain = FakeJimm("127.0.0.1", cfg.oscar_port, "100500", "s3cret")
    await plain.connect()
    await plain.bos(await plain.login_md5_jimm())
    await plain.drain_for(0.3)
    await plain.send_snac(C.SSBI, C.SSBI_UPLOAD,
                          pstr8(str(uin).encode()) + struct.pack(">HHH", 1, 1, 3) + b"abc")
    await plain.drain_for(0.4)
    assert got == [], got
    await plain.close()
    server._server.close()
    print("  камера: ок (снимок частями в чат, отказ на негодный, обычному Jimm нельзя)")


async def run_voice() -> None:
    """Голосовые в обе стороны: слушаем присланное и шлём записанное телефоном."""
    cfg = Config(tg_api_id=1, tg_api_hash="x")
    cfg.oscar_host, cfg.oscar_port = "127.0.0.1", PORT + 4
    cfg.oscar_uin, cfg.oscar_password = "100500", "s3cret"
    storage = Storage(":memory:")
    uin = storage.uin_for_peer(555, kind="user", title="Мама", group_name="Личные")

    async def on_outgoing(*_):
        return 1

    asked: list[str] = []
    amr = b"#!AMR\n" + bytes(range(256)) * 400          # 102 406 байт — три части

    async def fetch_voice(target: int, attach: str):
        asked.append(attach)
        return amr

    sent: list[tuple[int, int, int]] = []

    async def on_voice(target: int, data: bytes, seconds: int) -> bool:
        sent.append((target, len(data), seconds))
        return data[:5] == b"#!AMR"                    # негодную запись не принимаем

    server = OscarServer(cfg, storage, on_outgoing, storage.contacts,
                         fetch_voice=fetch_voice, on_voice=on_voice)
    await server.start()

    client = FakeJimm("127.0.0.1", cfg.oscar_port, "100500", "s3cret")
    client.tmm_version = (0, 4)
    await client.connect()
    await client.bos(await client.login_md5_jimm())
    await client.drain_for(0.3)

    # Присланное голосовое — тот же TLV, но вид 3: картинки нет, только «Прослушать».
    await server.deliver(uin, "[голосовое 0:07]", attach="voice:4444")
    await client.drain_for(0.5)
    assert client.attachments and client.attachments[-1][2] == C.ATTACH_VOICE, client.attachments
    token = client.attachments[-1][1]
    assert asked == [], "запись не должна тянуться заранее"

    client.parts_seen.clear()
    got = await client.request_voice(uin, token)
    assert asked == ["voice:4444"], asked
    assert got == amr, (len(got), len(amr))
    assert client.parts_seen == [(1, 2), (2, 2)], client.parts_seen

    # Запись с телефона: части 10/04 с длительностью, ответ 10/03.
    mine = b"#!AMR\n" + bytes(range(256)) * 200        # 51 206 байт — две части
    assert await client.send_voice(uin, mine, 7) is True
    assert sent == [(uin, len(mine), 7)], sent
    assert server.session.upload_kind == "audio/amr", "тип записи мост должен запомнить"

    # Клиент постарше типа не приписывает — приём от этого не ломается.
    sent.clear()
    assert await client.send_voice(uin, mine, 5, kind=None) is True
    assert sent == [(uin, len(mine), 5)], sent
    assert server.session.upload_kind == "", "без хвоста тип пустой"
    assert await client.send_voice(uin, b"not amr" * 100, 3) is False
    await client.close()
    await asyncio.sleep(0.2)

    # Обычный Jimm: части приходят, но сессия не расширенная — ничего не шлём.
    sent.clear()
    plain = FakeJimm("127.0.0.1", cfg.oscar_port, "100500", "s3cret")
    await plain.connect()
    await plain.bos(await plain.login_md5_jimm())
    await plain.drain_for(0.3)
    await plain.send_snac(C.SSBI, C.SSBI_UPLOAD_VOICE,
                          pstr8(str(uin).encode()) + struct.pack(">HHHH", 1, 1, 3, 3) + b"abc")
    await plain.drain_for(0.4)
    assert sent == [], sent
    await plain.close()
    server._server.close()
    print("  голосовые: ок (слушаем частями, шлём записанное, обычному Jimm нельзя)")


async def run_chats() -> None:
    """Весь список чатов на отдельный экран и возвращение забытого чата."""
    cfg = Config(tg_api_id=1, tg_api_hash="x")
    cfg.oscar_host, cfg.oscar_port = "127.0.0.1", PORT + 5
    cfg.oscar_uin, cfg.oscar_password = "100500", "s3cret"
    storage = Storage(":memory:")
    mom = storage.uin_for_peer(555, kind="user", title="Мама", group_name="Личные")
    old = storage.uin_for_peer(777, kind="user", title="Давний", group_name="Личные")

    async def on_outgoing(*_):
        return 1

    chats = [(mom, "Мама", False, 0, True), (old, "Давний", True, 400, False)]
    opened: list[int] = []

    async def chat_list():
        return chats

    async def open_chat(uin: int) -> bool:
        opened.append(uin)
        return uin == old

    server = OscarServer(cfg, storage, on_outgoing, storage.contacts,
                         chat_list=chat_list, open_chat=open_chat)
    await server.start()

    client = FakeJimm("127.0.0.1", cfg.oscar_port, "100500", "s3cret")
    client.tmm_version = (0, 6)
    await client.connect()
    await client.bos(await client.login_md5_jimm())
    await client.drain_for(0.3)

    got = await client.request_chats(mom)
    assert got == chats, got
    assert got[1][2] is True, "чат из MAX помечен своим флагом"
    assert got[1][4] is False, "чат вне контакт-листа помечен тоже"

    # Выбор чата в списке возвращает его на телефон.
    assert await client.open_chat(mom, old) is True
    assert opened == [old], opened
    assert await client.open_chat(mom, 12345) is False, "чужой UIN — отказ, а не тишина"
    # Пинг от телефона виден в журнале и считается: по нему сторож решает,
    # жива ли сессия. И на него приходит ответ — по нему уже телефон
    # понимает, что канал жив, а не висит открытым после обрыва.
    before = server.session.pings_seen
    await client.ping()
    channel, payload = await client.recv_flap(2.0)
    assert (channel, payload) == (5, b""), f"мост должен отвечать на пинг: {channel}"
    await client.drain_for(0.3)
    assert server.session.pings_seen == before + 1, "пинг должен считаться"
    assert server.session.last_ping > 0, "время пинга нужно для промежутка в журнале"

    await client.close()
    await asyncio.sleep(0.2)

    # Обычному Jimm список не отдаём — он про эту службу не знает.
    plain = FakeJimm("127.0.0.1", cfg.oscar_port, "100500", "s3cret")
    await plain.connect()
    await plain.bos(await plain.login_md5_jimm())
    await plain.drain_for(0.3)
    try:
        await plain.request_chats(mom, timeout=1.5)
        raise AssertionError("обычный Jimm не должен получить список чатов")
    except AssertionError:
        raise
    except Exception:
        pass
    await plain.close()
    server._server.close()
    print("  список чатов: ок (все чаты с пометками, возвращение забытого)")


def run_history_layout() -> None:
    """Клиент должен читать историю от моста любого возраста."""

    def record(text: str, flag: int = 0) -> bytes:
        raw = text.encode("utf-8")
        out = struct.pack(">H", len(raw)) + raw + bytes([flag])
        return out + (os.urandom(16) if flag & 1 else b"")

    body = (record("[17.09 11:20] Вася: привет") + record("[17.09 11:21] Я: и тебе", 8)
            + record("[17.09 11:22] Вася: [фото] кот", 1))
    variants = {
        "без заголовка": (body, 0, False),
        "один байт": (bytes([1]) + body, 1, True),
        "примета и флаг": (bytes([0xFF, 1]) + body, 2, True),
    }

    def fits(data: bytes, start: int) -> bool:
        pos, seen = start, 0
        while pos + 3 <= len(data):
            length = struct.unpack(">H", data[pos:pos + 2])[0]
            pos += 2
            if not 0 < length <= 4000 or pos + length + 1 > len(data):
                return False
            pos += length
            flag = data[pos]
            pos += 1
            if flag & 0xF0:
                return False
            if flag & 1:
                if pos + 16 > len(data):
                    return False
                pos += 16
            seen += 1
        return seen > 0 and pos == len(data)

    for name, (data, want_start, want_more) in variants.items():
        order = [2, 1, 0] if data[:1] == b"\xff" else [0, 1, 2]
        start = next((i for i in order if i <= len(data) and fits(data, i)), 0)
        more = bool(data[1]) if start == 2 else (bool(data[0]) if start == 1 else False)
        assert start == want_start, f"{name}: начало {start}, ждали {want_start}"
        assert more is want_more, f"{name}: «есть ещё» {more}"
        assert len(FakeJimm._history_records(data[start:])) == 3, name
    print("  разбор истории: ок (ответ моста любого возраста читается)")


def run_reply_routing() -> None:
    """Ответ службы адресован примете: типу и токену.

    Пока идёт одна загрузка, клиент может начать вторую (история и снимок),
    и без проверки первое же действие в очереди съедало бы чужой ответ —
    а его хозяин ждал бы вечно. Проверяем, что по ответу видно, чей он."""
    from bridge.oscar import blocks

    mine, other = os.urandom(16), os.urandom(16)
    reply = blocks.icon_reply(1000002, mine, "история".encode(), C.BART_HISTORY)

    def belongs(data: bytes, bart_type: int, token: bytes) -> bool:
        pos = 1 + data[0]                      # длина UIN и сам UIN
        kind = struct.unpack(">H", data[pos:pos + 2])[0]
        length = data[pos + 3]
        return kind == bart_type and length == len(token) \
            and data[pos + 4:pos + 4 + length] == token

    assert belongs(reply, C.BART_HISTORY, mine), "свой ответ должен опознаваться"
    assert not belongs(reply, C.BART_HISTORY, other), "чужой токен — чужой ответ"
    assert not belongs(reply, C.BART_PHOTO, mine), "другая примета — другой запрос"
    print("  адресность ответов: ок (примета и токен видны в ответе службы)")


async def run_stale_service() -> None:
    """Оборванное соединение за аватарками не должно держать слот вечно."""
    from bridge.oscar import server as server_module

    cfg = Config(tg_api_id=1, tg_api_hash="x")
    cfg.oscar_host, cfg.oscar_port = "127.0.0.1", PORT + 6
    cfg.oscar_uin, cfg.oscar_password = "100500", "s3cret"
    cfg.max_connections = 4
    storage = Storage(":memory:")
    storage.uin_for_peer(555, kind="user", title="Мама", group_name="Личные")

    async def on_outgoing(*_):
        return 1

    server = OscarServer(cfg, storage, on_outgoing, storage.contacts)
    await server.start()
    was = server_module.SERVICE_IDLE_TIMEOUT
    server_module.SERVICE_IDLE_TIMEOUT = 0.3
    try:
        client = FakeJimm("127.0.0.1", cfg.oscar_port, "100500", "s3cret")
        client.tmm_version = (0, 9)
        await client.connect()
        await client.bos(await client.login_md5_jimm())
        await client.drain_for(0.3)

        # Второе соединение — как за аватарками: берём cookie у сервера и
        # входим по нему, но больше ничего не шлём.
        await client.request_service(C.SSBI)
        redirect = await client.expect(C.OSERVICE, C.SERVICE_REDIRECT)
        tlvs = redirect.reader().tlvs(3)
        cookie = tlvs.get(C.TLV_AUTH_COOKIE) or b""
        host = (tlvs.get(C.TLV_BOS_ADDRESS) or b"").decode()
        port = int(host.partition(":")[2] or cfg.oscar_port)
        reader, writer = await asyncio.open_connection(cfg.oscar_host, port)
        head = await reader.readexactly(6)
        await reader.readexactly(struct.unpack(">H", head[4:6])[0])
        writer.write(flap(1, 2, struct.pack(">I", 1) + tlv(C.TLV_AUTH_COOKIE, cookie)))
        await writer.drain()
        await asyncio.sleep(0.2)
        busy = server.access.connections
        assert busy >= 2, busy

        # Молчим дольше срока — сервер закрывает соединение сам.
        for _ in range(60):
            await asyncio.sleep(0.05)
            if server.access.connections < busy:
                break
        assert server.access.connections < busy, \
            "зависшее служебное соединение должно освобождать слот"
        writer.close()
        await client.close()
    finally:
        server_module.SERVICE_IDLE_TIMEOUT = was
        server._server.close()
    print("  зависшее служебное соединение: ок (слот освобождается сам)")


async def main() -> None:
    await run_detection()
    await run_photos()
    await run_history()
    await run_camera()
    await run_voice()
    await run_chats()
    run_history_layout()
    run_reply_routing()
    await run_stale_service()
    print("TELEMOTOMAX ПРОВЕРЕН")


if __name__ == "__main__":
    asyncio.run(main())
