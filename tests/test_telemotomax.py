"""TeleMotoMax — расширенный клиент: мост узнаёт его по способности."""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.config import Config
from bridge.db import Storage
from bridge.oscar import const as C
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

    # Сам ролик: приходит частями по 30 КБ, клиент склеивает.
    clip = bytes(range(256)) * 300                     # 76 800 байт «3GP»
    videos: list[str] = []

    async def fetch_video(target: int, attach: str):
        videos.append(attach)
        return clip

    server.fetch_video = fetch_video
    client.parts_seen.clear()
    got_clip = await client.request_video(uin, client.attachments[-1][1])
    assert videos == ["video:4343"], videos
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

    async def fetch_history(target: int, count: int):
        asked.append((target, count))
        when = dt.datetime(2026, 9, 16, 10, 0, tzinfo=dt.timezone.utc)
        items = [HistoryItem(when, "Мама", "привет"), HistoryItem(when, "Я", "и тебе"),
                 HistoryItem(when, "Мама", "[фото] закат", 4242, "photo")]
        return [(f"[{i.when:%d.%m %H:%M}] {i.who}: {i.text}",
                 f"photo:{i.msg_id}" if i.kind == "photo" else "") for i in items[:count]]

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

    rows = await client.request_history(uin, 30)
    assert asked == [(uin, 30)], asked
    assert [t.split("] ", 1)[1] for t, _ in rows] == ["Мама: привет", "Я: и тебе", "Мама: [фото] закат"], rows
    assert rows[0][1] is None and rows[2][1] is not None, "у сообщения с фото должен быть токен"
    # Фото из истории открывается тем же запросом, что и из чата.
    got = await client.request_photo(uin, rows[2][1])
    assert fetched == ["photo:4242"] and got["image"][:3] == b"\xff\xd8\xff"
    await client.close()
    server._server.close()
    print("  история: ок (текст последних сообщений по службе 0x10)")


async def main() -> None:
    await run_detection()
    await run_photos()
    await run_history()
    print("TELEMOTOMAX ПРОВЕРЕН")


if __name__ == "__main__":
    asyncio.run(main())
