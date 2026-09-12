"""Команда !render: страница переписки для браузера телефона."""

from __future__ import annotations

import asyncio
import io
import os
import stat
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge import history, render
from bridge.access import AccessControl
from bridge.bridge import Bridge
from bridge.config import Config
from bridge.photos import PhotoStore
from bridge.webserver import PhotoServer

PORT = 15700


def picture() -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (800, 600), (30, 60, 90)).save(out, format="PNG")
    return out.getvalue()


def fake_ffmpeg(directory: str) -> str:
    """Поддельный ffmpeg: пишет заглушку в файл назначения, а ключи — рядом с собой.

    Настоящего в сборочной машине может не быть, а проверить надо и разбор
    ключей, и то, что мост кладёт результат куда следует.
    """
    path = os.path.join(directory, "ffmpeg-fake")
    with open(path, "w") as fh:
        fh.write(
            "#!/bin/sh\n"
            "out=\"\"\n"
            "prev=\"\"\n"
            "for arg in \"$@\"; do\n"
            "  out=\"$arg\"\n"
            "  prev=\"$prev $arg\"\n"
            "done\n"
            "echo \"$prev\" > \"$0.args\"\n"
            "printf 'FAKEMEDIA' > \"$out\"\n"
        )
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


async def run_transcoder() -> None:
    work = tempfile.mkdtemp()
    coder = render.Transcoder(fake_ffmpeg(work), video_seconds=30, audio_seconds=90,
                              workdir=work)
    assert coder.available, "поддельный ffmpeg должен находиться"

    args = coder.video_args("in.mp4", "out.3gp")
    assert "h263" in args, args
    assert "libopencore_amrnb" in args, args
    assert f"{render.VIDEO_WIDTH}:{render.VIDEO_HEIGHT}" in " ".join(args), args
    assert args[args.index("-t") + 1] == "30", "ограничение по времени видео"
    # Плеер RAZR V3: H.263 Level 10 — не больше 64 кбит/с и 15 кадров в секунду.
    assert args[args.index("-b:v") + 1] == "64k" and args[args.index("-r") + 1] == "15", args
    assert "-maxrate" in args and "+faststart" in args, args
    mp4 = render.Transcoder("x", video_codec="mpeg4").video_args("in", "out")
    assert "mpeg4" in mp4 and "mp4v" in mp4 and "h263" not in mp4, mp4
    assert render.Transcoder("x", video_codec="чушь").video_codec == "h263", "неизвестный кодек — h263"

    args = coder.audio_args("in.ogg", "out.amr")
    assert args[args.index("-t") + 1] == "90", "ограничение по времени звука"
    assert args[args.index("-ar") + 1] == "8000", "AMR-NB — это 8 кГц"

    got = await coder.convert(b"raw video", "video")
    assert got == b"FAKEMEDIA", got
    assert not [n for n in os.listdir(work) if n.startswith(("in-", "out-"))], \
        "временные файлы должны убираться за собой"

    # Без ffmpeg мост не падает, просто ничего не отдаёт.
    missing = render.Transcoder("ffmpeg-которого-нет", workdir=work)
    assert not missing.available
    assert await missing.convert(b"raw", "voice") is None
    print("  перекодирование: ок (ключи, результат, отсутствие ffmpeg)")


async def run_page() -> None:
    work = tempfile.mkdtemp()
    store = render.RenderStore(os.path.join(work, "render"),
                               render.Transcoder(fake_ffmpeg(work), workdir=work),
                               ttl_minutes=30)

    items = [
        render.Item(when="10:00", who="Вася", text="Привет!"),
        render.Item(when="10:01", who="Я", text="Смотри", mine=True,
                    kind="photo", raw=picture()),
        render.Item(when="10:02", who="Вася", kind="video", raw=b"video",
                    seconds=75),
        render.Item(when="10:03", who="Вася", kind="voice", raw=b"voice",
                    seconds=8),
    ]
    page = await store.build("Дача 2026", items)
    assert page is not None
    text = page.body.decode("utf-8")

    assert "Дача 2026" in text, "в шапке должно быть название чата"
    assert "Привет!" in text and "Смотри" in text
    assert render.COLOR_MINE in text and render.COLOR_THEIRS in text, \
        "свои и чужие сообщения красятся по-разному"
    assert text.startswith("<?xml"), "страница должна быть XHTML Mobile Profile"
    assert "xhtml-mobile10.dtd" in text, text[:200]

    assert len(page.assets) == 3, page.assets
    assert '<img src="/m/' in text, "фото вставляется прямо в страницу"
    assert ".3gp\">" in text and "видео 1:15" in text, "видео — ссылкой с длительностью"
    assert ".amr\">" in text and "голосовое 0:08" in text, "голосовое — ссылкой"

    # Файлы лежат на диске и отдаются по токенам.
    for token in page.assets:
        asset = store.asset_for(token)
        assert asset is not None and os.path.isfile(asset.path), token
    assert store.page_for(page.token) == page.body
    assert store.page_for("нетакого") is None

    kinds = sorted(store.asset_for(t).ext for t in page.assets)
    assert kinds == ["3gp", "amr", "jpg"], kinds
    assert store.asset_for(page.assets[0]).mime in render.MIME.values()

    # Экранирование: разметка из сообщения не должна попадать в страницу.
    page2 = await store.build("Чат", [render.Item(when="11:00", who="<b>Хакер</b>",
                                                  text="<script>alert(1)</script>")])
    body = page2.body.decode("utf-8")
    assert "<script>" not in body and "&lt;script&gt;" in body, "текст должен экранироваться"
    assert "<b>Хакер</b>" not in body, "имя тоже"

    print("  страница: ок (вёрстка, вложения, экранирование)")


async def run_lazy_and_progress() -> None:
    """Вложения тянутся по одному, а о ходе дела сообщается."""
    work = tempfile.mkdtemp()
    store = render.RenderStore(os.path.join(work, "render"),
                               render.Transcoder(fake_ffmpeg(work), workdir=work),
                               ttl_minutes=30)
    order: list[str] = []
    ticks: list[tuple[int, int]] = []

    def loader(name: str, data: bytes):
        async def fetch():
            order.append(name)
            return data
        return fetch

    async def progress(done: int, total: int) -> None:
        ticks.append((done, total))

    items = [
        render.Item(when="10:00", who="Вася", text="без вложения"),
        render.Item(when="10:01", who="Вася", kind="photo", fetch=loader("фото", picture())),
        render.Item(when="10:02", who="Вася", kind="voice", fetch=loader("голос", b"v"),
                    seconds=3),
        render.Item(when="10:03", who="Вася", kind="video", fetch=loader("видео", b"m"),
                    thumb=loader("превью", picture()), seconds=9),
    ]
    page = await store.build("Чат", items, progress)
    assert order == ["фото", "голос", "превью", "видео"], "вложения должны тянуться по очереди"
    assert ticks == [(1, 3), (2, 3), (3, 3)], ticks
    assert len(page.assets) == 4, "у видео два файла: превью и ролик"
    text = page.body.decode("utf-8")
    assert 'alt="видео"' in text and "смотреть: видео 0:09" in text, \
        "видео — картинкой-превью и ссылкой под ней"
    assert "слушать: голосовое 0:03" in text

    # Без превью и без ffmpeg: остаётся пометка, страница цела.
    async def no_thumb():
        return None
    silent = render.RenderStore(os.path.join(work, "render2"),
                                render.Transcoder("нет", workdir=work))
    page3 = await silent.build("Чат", [render.Item(when="10:05", who="Вася", kind="video",
                                                    fetch=loader("в", b"m"), thumb=no_thumb,
                                                    seconds=5)])
    assert "[видео 0:05 — перекодировать не вышло]" in page3.body.decode("utf-8")

    # Сломавшийся загрузчик не роняет страницу — остаётся пометка.
    async def broken():
        raise RuntimeError("сеть упала")

    page2 = await store.build("Чат", [render.Item(when="10:04", who="Вася",
                                                  kind="photo", fetch=broken)])
    assert "не открылось" in page2.body.decode("utf-8")
    print("  ленивые вложения и прогресс: ок")


async def run_expiry() -> None:
    work = tempfile.mkdtemp()
    store = render.RenderStore(os.path.join(work, "render"),
                               render.Transcoder("нет-такого", workdir=work),
                               ttl_minutes=30)
    page = await store.build("Чат", [render.Item(when="10:00", who="Вася",
                                                 kind="photo", raw=picture())])
    token = page.assets[0]
    assert store.page_for(page.token) is not None
    assert store.asset_for(token) is not None

    # Отматываем время: срок вышел.
    store._pages[page.token].made = time.time() - 31 * 60
    assert store.page_for(page.token) is None, "просроченная страница не отдаётся"
    assert store.asset_for(token) is None, "и вложения к ней тоже"

    path = store._assets[token].path
    assert store.cleanup() == 1, "уборка должна удалить файл"
    assert not os.path.exists(path), "файл должен исчезнуть с диска"
    assert store.page_for(page.token) is None

    # Сироты после перезапуска: файлы есть, страниц в памяти нет.
    orphan = os.path.join(store.directory, "zzzzzzzzzz.3gp")
    fresh = os.path.join(store.directory, "yyyyyyyyyy.jpg")
    with open(orphan, "wb") as fh:
        fh.write(b"old")
    with open(fresh, "wb") as fh:
        fh.write(b"new")
    os.utime(orphan, (time.time() - 3600, time.time() - 3600))
    assert store.cleanup() == 1, "старый сирота должен уйти, свежий — остаться"
    assert not os.path.exists(orphan) and os.path.exists(fresh)
    print("  срок жизни: ок (ссылка перестаёт работать, файлы и сироты убираются)")


async def run_web() -> None:
    work = tempfile.mkdtemp()
    store = render.RenderStore(os.path.join(work, "render"),
                               render.Transcoder(fake_ffmpeg(work), workdir=work),
                               ttl_minutes=30)
    page = await store.build("Дача", [
        render.Item(when="10:00", who="Вася", text="Привет"),
        render.Item(when="10:01", who="Вася", kind="photo", raw=picture()),
        render.Item(when="10:02", who="Вася", kind="voice", raw=b"voice", seconds=5),
    ])

    photos = PhotoStore(os.path.join(work, "photos"))
    server = PhotoServer(photos, "127.0.0.1", PORT, AccessControl(), render=store)
    await server.start()

    async def get(path: str, extra: str = "") -> tuple[str, bytes]:
        reader, writer = await asyncio.open_connection("127.0.0.1", PORT)
        writer.write(f"GET {path} HTTP/1.1\r\nHost: phone\r\n{extra}\r\n".encode())
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(200000), timeout=5)
        writer.close()
        head, _, body = raw.partition(b"\r\n\r\n")
        return head.decode("latin-1"), body

    head, body = await get(f"/r/{page.token}")
    assert "200 OK" in head, head
    assert "vnd.wap.xhtml+xml" in head, head
    assert "no-cache" in head, "страница не должна кэшироваться дольше своего срока"
    assert "Дача".encode("utf-8") in body

    jpg = [t for t in page.assets if store.asset_for(t).ext == "jpg"][0]
    head, body = await get(f"/m/{jpg}.jpg")
    assert "200 OK" in head and "image/jpeg" in head, head
    assert body[:3] == b"\xff\xd8\xff", "ждали JPEG"

    amr = [t for t in page.assets if store.asset_for(t).ext == "amr"][0]
    head, body = await get(f"/m/{amr}.amr")
    assert "audio/amr" in head, head
    assert body == b"FAKEMEDIA", body
    assert "Accept-Ranges: bytes" in head, "качалка телефона должна знать, что диапазоны можно"
    assert f'filename="{amr}.amr"' in head, "имя файла с расширением — подсказка телефону"

    # Диапазоны: качалка после обрыва просит хвост — отдаём 206 и ровно его.
    head, body = await get(f"/m/{amr}.amr", "Range: bytes=4-\r\n")
    assert head.startswith("HTTP/1.1 206"), head
    assert "Content-Range: bytes 4-8/9" in head, head
    assert body == b"MEDIA", body
    head, body = await get(f"/m/{amr}.amr", "Range: bytes=0-3\r\n")
    assert head.startswith("HTTP/1.1 206") and body == b"FAKE", (head, body)
    head, body = await get(f"/m/{amr}.amr", "Range: bytes=500-\r\n")
    assert head.startswith("HTTP/1.1 200") and body == b"FAKEMEDIA", "негодный диапазон — целиком"

    head, _ = await get("/r/чужое")
    assert "404" in head, head
    head, _ = await get("/m/aaaaaaaaaa.3gp")
    assert "404" in head, "неизвестное вложение отдавать нельзя"

    await server.stop()
    print("  раздача: ок (страница, вложения, чужие ссылки)")


async def run_url_message() -> None:
    """Ссылка доезжает до клиента отдельным полем URL-сообщения."""
    from bridge.access import AccessControl        # noqa: F401  (уже импортирован)
    from bridge.db import Storage
    from bridge.oscar.server import OscarServer
    from tests.fake_jimm import FakeJimm

    cfg = Config()
    cfg.oscar_host, cfg.oscar_port = "127.0.0.1", PORT + 1
    cfg.oscar_uin, cfg.oscar_password = "1", "s3cret"
    cfg.bos_host = "127.0.0.1"
    storage = Storage(":memory:")
    uin = storage.uin_for_peer(555, kind="user", title="Мама", group_name="Личные")

    async def on_outgoing(*_):
        return 1

    server = OscarServer(cfg, storage, on_outgoing, storage.contacts)
    await server.start()

    client = FakeJimm("127.0.0.1", cfg.oscar_port, cfg.oscar_uin, cfg.oscar_password)
    await client.connect()
    await client.bos(await client.login_md5_jimm())
    await client.drain_for(0.5)

    link = "http://10.0.0.1:8080/r/k7m3qb2xta"
    await server.deliver(uin, f"{link}\n12 сообщений", forced=True, url=link)
    await client.drain_for(0.6)

    assert (uin, link) in client.urls, client.urls
    got = [text for sender, text in client.received if "сообщений" in text]
    assert got and got[0].startswith(link), \
        "ссылка должна остаться и в тексте — иначе не будет пункта «Открыть ссылку»"

    # Обычное сообщение остаётся обычным.
    before = len(client.urls)
    await server.deliver(uin, "просто текст")
    await client.drain_for(0.5)
    assert len(client.urls) == before, client.urls

    await client.close()
    server._server.close()
    storage.close()
    print("  URL-сообщение: ок (ссылка отдельным полем и в тексте)")


async def run_paths_and_index() -> None:
    """Адрес страницы по формату из настроек и список страниц."""
    work = tempfile.mkdtemp()
    coder = render.Transcoder("нет", workdir=work)
    item = [render.Item(when="10:00", who="Вася", text="привет")]

    store = render.RenderStore(os.path.join(work, "a"), coder, path_format="/r/{n}")
    first = await store.build("Дача 2026", list(item))
    second = await store.build("Мама", list(item))
    assert (first.path, second.path) == ("/r/1", "/r/2"), (first.path, second.path)
    assert store.page_by_path("/r/2") == second.body
    assert store.page_by_path("/r/2/") == second.body, "хвостовая косая не мешает"
    assert store.page_by_path("/r/" + first.token) == first.body, "по токену — тоже"
    assert store.page_by_path("/r/9") is None

    store = render.RenderStore(os.path.join(work, "b"), coder, path_format="{chat}/{n}")
    page = await store.build("Дача 2026", list(item))
    assert page.path == "/dacha-2026/1", page.path
    assert store.page_by_path("/dacha-2026/1") is not None

    store = render.RenderStore(os.path.join(work, "c"), coder, path_format="/{chat}")
    old = await store.build("Мама", list(item))
    new = await store.build("Мама", list(item))
    assert store.page_by_path("/mama") == new.body, "занятый адрес переходит новой странице"
    assert store.page_for(old.token) is not None, "а старая остаётся по токену"

    # Список страниц: выключен по умолчанию, включённый показывает живые.
    assert not store.is_index("/r/")
    store.index_enabled = True
    assert store.is_index("/r/") and store.is_index("/r") and store.is_index("/r/index")
    listing = store.index_html().decode("utf-8")
    assert 'href="/mama"' in listing and "Мама" in listing, listing[-400:]
    store._pages[new.token].made -= 3600
    store._pages[old.token].made -= 3600
    assert "Страниц пока нет" in store.index_html().decode("utf-8")
    print("  адреса и список: ок (номер, название, токен, индекс)")


async def run_password() -> None:
    """Пароль: Basic, форма с cookie, ключ в адресе — и бан за перебор."""
    import base64
    from bridge.access import AccessControl
    from bridge.photos import PhotoStore
    from bridge.webserver import PhotoServer

    work = tempfile.mkdtemp()
    store = render.RenderStore(os.path.join(work, "render"),
                               render.Transcoder("нет", workdir=work), index=True)
    page = await store.build("Мама", [render.Item(when="10:00", who="Мама", text="секрет")])
    port = PORT + 2
    access = AccessControl(max_failures=3, ban_seconds=60)
    server = PhotoServer(PhotoStore(os.path.join(work, "photos")), "127.0.0.1", port,
                         access, render=store, password="s3cret")
    await server.start()

    async def http(method: str, path: str, headers: dict | None = None,
                   body: bytes = b"") -> tuple[int, dict, bytes]:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        lines = [f"{method} {path} HTTP/1.1", "Host: phone"]
        for k, v in (headers or {}).items():
            lines.append(f"{k}: {v}")
        if body:
            lines.append(f"Content-Length: {len(body)}")
        writer.write(("\r\n".join(lines) + "\r\n\r\n").encode() + body)
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(200000), timeout=5)
        writer.close()
        head, _, data = raw.partition(b"\r\n\r\n")
        head_lines = head.decode("latin-1").split("\r\n")
        status = int(head_lines[0].split()[1])
        hdrs = {}
        for line in head_lines[1:]:
            k, _, v = line.partition(":")
            hdrs[k.strip().lower()] = v.strip()
        return status, hdrs, data

    # Без пароля — 401 с вызовом Basic и формой в теле.
    status, hdrs, data = await http("GET", page.path)
    assert status == 401, status
    assert "basic" in hdrs.get("www-authenticate", "").lower(), hdrs
    assert b"<form" in data and "секрет".encode() not in data

    # Basic с верным паролем — страница.
    token = base64.b64encode(b"icq:s3cret").decode()
    status, _, data = await http("GET", page.path, {"Authorization": f"Basic {token}"})
    assert status == 200 and "секрет".encode() in data

    # Ключ в адресе — страница и cookie на будущее.
    status, hdrs, data = await http("GET", page.path + "?key=s3cret")
    assert status == 200 and "секрет".encode() in data
    cookie = hdrs.get("set-cookie", "").split(";")[0]
    assert cookie.startswith("bridge_auth="), hdrs
    status, _, data = await http("GET", "/r/", {"Cookie": cookie})
    assert status == 200 and "Мама".encode() in data, "cookie должна открывать и список"

    # Браузер без cookie: после входа по ключу ссылки страницы несут токен
    # сеанса, по которому пускают дальше — и сам пароль в них не гуляет.
    status, hdrs, data = await http("GET", "/r/?key=s3cret")
    assert status == 200
    import re
    tokens = set(re.findall(rb'"/s/([A-Za-z0-9_-]+)/', data))
    assert len(tokens) == 1, f"в ссылках списка должен быть один токен сеанса: {data[-300:]}"
    token_s = tokens.pop().decode()
    assert b"s3cret" not in data, "пароль в ссылки попадать не должен"
    assert f'href="/s/{token_s}{page.path}"'.encode() in data, data[-300:]
    # Токен — в начале пути: адрес по-прежнему кончается расширением, и
    # старый браузер понимает, что за файл качает.
    status, _, data = await http("GET", f"/s/{token_s}{page.path}")
    assert status == 200 and "секрет".encode() in data, "по токену из ссылки должны пускать"
    status, _, data = await http("GET", f"/s/{token_s}/r/")
    assert b'"/s/' + token_s.encode() in data, "ссылки страницы проносят токен дальше"
    assert b"?s=" not in data, "хвост ?s= больше не используется"
    status, _, _ = await http("GET", f"{page.path}?s={token_s}")
    assert status == 200, "старая форма ?s= тоже пускает"
    status, _, _ = await http("GET", f"/s/nonsense{page.path}")
    assert status == 401, "чужой токен не пускает"
    # Вход по cookie или Basic ссылки не трогает.
    status, _, data = await http("GET", "/r/", {"Cookie": cookie})
    assert b'"/s/' not in data, "с cookie токен в ссылках не нужен"

    # Форма: неверный пароль — снова форма, верный — переход с cookie.
    status, _, data = await http("POST", "/login", {"Content-Type": "application/x-www-form-urlencoded"},
                                 b"p=wrong&next=" + page.path.encode())
    assert status == 200 and "не подошёл".encode() in data
    status, hdrs, _ = await http("POST", "/login", {"Content-Type": "application/x-www-form-urlencoded"},
                                 b"p=s3cret&next=" + page.path.encode())
    assert status == 302 and hdrs.get("location") == page.path, hdrs
    assert hdrs.get("set-cookie", "").startswith("bridge_auth=")

    # Перебор: после трёх неверных попыток подряд адрес отключается
    # (удачный вход выше счётчик обнулил).
    for _ in range(3):
        await http("GET", page.path + "?key=nope")
    try:
        status, _, _ = await http("GET", page.path + "?key=s3cret")
        assert status != 200, "после бана даже верный пароль не должен проходить"
    except (ConnectionError, asyncio.IncompleteReadError, OSError):
        pass                                      # соединение просто закрыли — тоже отказ

    await server.stop()
    print("  пароль: ок (Basic, ключ в адресе, форма с cookie, бан за перебор)")


async def run_downloads() -> None:
    """Раздел «Загрузки»: список каталога и файлы с правильными типами."""
    from bridge.access import AccessControl
    from bridge.photos import PhotoStore
    from bridge.webserver import PhotoServer

    work = tempfile.mkdtemp()
    files = os.path.join(work, "files")
    os.makedirs(files)
    with open(os.path.join(files, "jimm.jad"), "w") as fh:
        fh.write("MIDlet-Name: Jimm\nMIDlet-Jar-URL: jimm.jar\n")
    with open(os.path.join(files, "jimm.jar"), "wb") as fh:
        fh.write(b"PK\x03\x04" + b"0" * 2000)
    with open(os.path.join(files, ".secret"), "w") as fh:
        fh.write("нельзя")
    os.makedirs(os.path.join(files, "sub"))
    with open(os.path.join(work, "outside.txt"), "w") as fh:
        fh.write("снаружи")

    port = PORT + 3
    server = PhotoServer(PhotoStore(os.path.join(work, "photos")), "127.0.0.1", port,
                         AccessControl(), password="s3cret", downloads_dir=files)
    await server.start()

    async def get(path: str) -> tuple[int, str, bytes]:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(f"GET {path} HTTP/1.1\r\nHost: phone\r\n\r\n".encode())
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(200000), timeout=5)
        writer.close()
        head, _, body = raw.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        mime = next((l.split(":", 1)[1].strip() for l in lines if l.lower().startswith("content-type")), "")
        return int(lines[0].split()[1]), mime, body

    # Список: без пароля (установщик телефона его спросить не умеет), скрытых
    # файлов и подкаталогов в нём нет.
    status, mime, body = await get("/d/")
    assert status == 200 and "vnd.wap.xhtml" in mime, (status, mime)
    text = body.decode("utf-8")
    assert 'href="/d/jimm.jad"' in text and 'href="/d/jimm.jar"' in text, text
    assert ".secret" not in text and "sub" not in text, text

    status, mime, body = await get("/d/jimm.jad")
    assert status == 200 and mime == "text/vnd.sun.j2me.app-descriptor", (status, mime)
    assert b"MIDlet-Jar-URL" in body
    status, mime, body = await get("/d/jimm.jar")
    assert status == 200 and mime == "application/java-archive" and len(body) == 2004

    # Обходные пути и скрытое — мимо.
    for bad in ("/d/../outside.txt", "/d/.secret", "/d/sub", "/d/%2e%2e/outside.txt"):
        status, _, _ = await get(bad)
        assert status == 404, f"{bad} не должен отдаваться: {status}"

    # А остальное под паролем по-прежнему.
    status, _, _ = await get("/r/")
    assert status == 401, status

    # protected = true закрывает и загрузки.
    server.downloads_protected = True
    status, _, _ = await get("/d/jimm.jar")
    assert status == 401, "с protected загрузки должны спрашивать пароль"

    await server.stop()
    print("  загрузки: ок (список, типы jad/jar, без обходных путей, пароль по желанию)")


async def run_command() -> None:
    """Команда целиком: от разбора до ссылки в ответе."""
    assert history.parse("!render").name == "render"
    assert history.parse("!render 5").count == 5
    assert history.parse("!render x").error

    cfg = Config(tg_api_id=1, tg_api_hash="x")
    work = tempfile.mkdtemp()
    cfg.db = os.path.join(work, "test.db")
    cfg.tg_session = os.path.join(work, "test.session")
    cfg.photos_enabled = True
    cfg.photos_dir = os.path.join(work, "photos")
    cfg.render_dir = os.path.join(work, "render")
    cfg.render_ffmpeg = fake_ffmpeg(work)
    cfg.photos_public_host = "10.0.0.1"
    cfg.photos_port = 8080
    bridge = Bridge(cfg)
    bridge.photo_server = object()          # запускать сервер тут незачем

    uin = bridge.storage.uin_for_peer(-4001, kind="chat", title="Дача",
                                      group_name="Группы")
    contact = bridge.storage.contact_by_uin(uin)

    asked: list[tuple] = []

    async def render_items(peer_id, count, since, cap, topic_id=0, max_media_bytes=0):
        asked.append((peer_id, count, since is not None, cap, topic_id, max_media_bytes))
        return [
            {"when": "10:00", "who": "Вася", "text": "Привет", "mine": False,
             "kind": "", "raw": None, "seconds": 0, "name": ""},
            {"when": "10:01", "who": "Вася", "text": "", "mine": False,
             "kind": "photo", "raw": picture(), "seconds": 0, "name": ""},
        ]

    bridge.telegram.render_items = render_items

    sent: list[str] = []
    links: list[str] = []

    async def deliver(target, text, forced=False, url=""):
        links.append(url)
        sent.append(text)
        return True

    bridge.oscar.deliver = deliver

    await bridge.run_command(contact, history.parse("!render"))
    assert asked and asked[0][2] is True, "без числа берём сегодняшние сообщения"
    assert asked[0][5] == cfg.render_source_max_mb * 1024 * 1024, asked

    link = [t for t in sent if "/r/" in t]
    assert link, sent
    assert link[0].startswith("http://10.0.0.1:8080/r/"), link
    assert "2 сообщений, 1 вложений" in link[0], link
    assert "30 мин" in link[0], "срок жизни ссылки должен быть в ответе"
    assert link[0].split("\n")[0] in links, \
        "ссылка должна уйти и отдельным полем — URL-сообщением"

    # По умолчанию адрес — сквозной номер: его можно набрать на кнопках.
    path = "/r/" + link[0].split("/r/")[1].split("\n")[0]
    assert path == "/r/1", path
    body = bridge.render.page_by_path(path)
    assert body is not None and "Привет".encode("utf-8") in body

    # С числом — столько последних сообщений, и не больше потолка.
    asked.clear()
    await bridge.run_command(contact, history.parse("!render 5"))
    assert asked[0][1] == 5 and asked[0][2] is False, asked

    sent.clear()
    asked.clear()
    await bridge.run_command(contact, history.parse("!render 500"))
    assert asked[0][1] == cfg.render_messages, "больше потолка не просим"
    assert any("не соберу" in t for t in sent), sent

    # Выключенная сборка отвечает понятным отказом.
    bridge.render = None
    sent.clear()
    await bridge.run_command(contact, history.parse("!render"))
    assert any("выключена" in t for t in sent), sent

    bridge.storage.close()
    print("  команда !render: ок (разбор, ссылка, потолок, отказ)")


async def main() -> None:
    await run_transcoder()
    await run_page()
    await run_lazy_and_progress()
    await run_expiry()
    await run_web()
    await run_paths_and_index()
    await run_password()
    await run_downloads()
    await run_command()
    await run_url_message()
    print("СТРАНИЦА ПЕРЕПИСКИ ПРОВЕРЕНА")


if __name__ == "__main__":
    asyncio.run(main())
