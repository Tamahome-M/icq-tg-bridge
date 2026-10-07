"""Видео по клику: отдельная страница, подготовка в фоне и старый клиент."""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.bridge import Bridge
from bridge.config import Config
from bridge.photos import PhotoStore
from bridge.render import Transcoder
from bridge.videos import ENCODING_VERSION, VideoSpec, VideoStore, link_text
from bridge.webserver import PhotoServer
from tests.fake_jimm import FakeJimm
from tests.test_render import fake_ffmpeg


def ffmpeg(directory: Path) -> str:
    encoder = fake_ffmpeg(str(directory))
    probe = directory / "ffprobe"
    probe.write_text("#!/bin/sh\nprintf '125\\n'\n")
    probe.chmod(0o755)
    return encoder


async def request(port: int, path: str, method: str = "GET", headers: str = ""):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"{method} {path} HTTP/1.0\r\nHost: localhost\r\n{headers}\r\n".encode())
    await writer.drain()
    response = await asyncio.wait_for(reader.read(), 5)
    writer.close()
    await writer.wait_closed()
    head, _, body = response.partition(b"\r\n\r\n")
    return int(head.split()[1]), head.decode("latin-1"), body


async def run_pages() -> None:
    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        calls = []
        release = asyncio.Event()

        async def fetch(uin, attach):
            calls.append((uin, attach))
            await release.wait()
            return b"original-video"

        spec = VideoSpec(ffmpeg(directory), seconds=60)
        store = VideoStore(str(directory / "videos"), fetch)
        path = store.register(100500, "video:42", "Чат <&>", spec)
        assert store.register(100500, "video:42", "Чат", spec) == path
        assert store.register(100500, "photo:42", "Чат", spec) == ""
        assert calls == [], "создание ссылки не должно скачивать видео"
        photo = PhotoStore(str(directory / "photos"))
        server = PhotoServer(photo, "127.0.0.1", 0, password="secret", videos=store)
        await server.start()
        port = server._server.sockets[0].getsockname()[1]
        session = server.session_token()
        protected = f"/s/{session}{path}"
        try:
            assert (await request(port, path))[0] == 401
            assert calls == [], "неавторизованный запрос не запускает загрузку"
            assert (await request(port, protected, "HEAD"))[0] == 200
            assert calls == [], "HEAD не запускает перекодирование"
            assert (await request(port, protected + "/0.3gp"))[0] == 404
            code, head, body = await request(port, protected)
            assert code == 200 and "no-cache" in head and "xhtml" in head
            assert "Видео готовится" in body.decode()
            assert f'href="{protected}/0"'.encode() in body
            ET.fromstring(body)
            await asyncio.sleep(0)
            assert calls == [(100500, "video:42")]
            await request(port, protected)
            assert len(calls) == 1, "параллельные открытия запускают одну подготовку"
            assert (await request(port, "/"))[0] == 200, "подготовка не держит HTTP-запрос"
            page = store.pages[path.split("/")[-1]]
            release.set()
            await asyncio.gather(*list(page.jobs.values()))
            code, _, body = await request(port, protected)
            asset_url = protected + f"/0-v{ENCODING_VERSION}.3gp"
            assert code == 200 and f'href="{asset_url}"'.encode() in body
            assert f'href="{protected}/1"'.encode() in body
            assert "Обновить" not in body.decode()
            assert "&lt;&amp;&gt;" in body.decode()
            code, head, body = await request(port, asset_url, headers="Range: bytes=1-3\r\n")
            assert code == 206 and body == b"AKE"
            assert "video/3gpp" in head and f'filename="0-v{ENCODING_VERSION}.3gp"' in head
            assert (await request(port, protected + "/0.3gp"))[2] == b"FAKEMEDIA", "старый адрес файла остаётся доступен"
            assert (await request(port, protected + f"/0-v{ENCODING_VERSION - 1}.3gp"))[0] == 404
            await request(port, protected + "/2")
            await asyncio.gather(*list(page.jobs.values()))
            _, _, body = await request(port, protected + "/2")
            assert "Дальше" not in body.decode(), "последняя часть не предлагает следующую"
            assert len(calls) == 1, "исходник повторно не скачивается"
            assert "-ss 120" in Path(spec.ffmpeg + ".args").read_text()
            _, _, body = await request(port, protected + "/3")
            assert "Конец видео" in body.decode() and not page.jobs
            for bad in (f"/s/{session}/v/../../etc/passwd", protected + "/-1", protected + "/10001"):
                assert (await request(port, bad))[0] == 404
        finally:
            release.set()
            await server.stop()

        # Метаданные и готовое видео доступны после перезапуска хранилища.
        restored = VideoStore(str(directory / "videos"), fetch)
        assert f"/0-v{ENCODING_VERSION}.3gp".encode() in restored.resolve(path, start=False)[0]
        assert restored.resolve(path + "/0.3gp")[0] == b"FAKEMEDIA"
        metadata = directory / "videos" / f"{page.token}.json"
        # И последний формат с fiel/pasp (v3), и старые записи без версии
        # должны перейти на новый формат с сохранением исходника и ссылки.
        for version in (3, None):
            old = json.loads(metadata.read_text())
            if version is None:
                old["spec"].pop("encoding_version")
            else:
                old["spec"]["encoding_version"] = version
            metadata.write_text(json.dumps(old))
            legacy = VideoStore(str(directory / "videos"), fetch)
            assert legacy.register(100500, "video:42", "Чат", spec) == path, "старые ссылки должны продолжать работать"
            assert legacy.resolve(path + "/0.3gp") is None, "старый 3GP должен быть удалён"
            assert (directory / "videos" / f"{page.token}.source").is_file(), "исходник нельзя удалять при смене формата"
            assert json.loads(metadata.read_text())["spec"]["encoding_version"] == ENCODING_VERSION
            legacy.resolve(path)
            await asyncio.gather(*list(legacy.pages[page.token].jobs.values()))
            assert legacy.resolve(path + "/0.3gp")[0] == b"FAKEMEDIA"
            assert f"/0-v{ENCODING_VERSION}.3gp".encode() in legacy.resolve(path)[0]
            assert legacy.resolve(path + "/0-v3.3gp") is None, "прежний адрес файла не должен отдавать кеш браузера"
            assert len(calls) == 1, "смена формата не должна повторно скачивать исходник"
            await legacy.stop()
        restored.pages[page.token].made = time.time() - 49 * 3600
        restored.cleanup()
        assert restored.resolve(path) is None
        assert not list((directory / "videos").glob(page.token + ".*"))
        assert "-t" not in Transcoder("ffmpeg", video_seconds=0).video_args("in", "out")
        assert link_text("Подпись [видео 1:23]", "http://host/v/token") == \
            "[видео](http://host/v/token) 1:23\nПодпись"
    print("  страницы видео: ок (ленивая подготовка, пароль, Range, кеш, части, перезапуск, TTL)")


async def run_retry_and_cancel() -> None:
    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        good = False

        async def fetch(*_):
            return b"original" if good else None

        store = VideoStore(str(directory / "videos"), fetch)
        path = store.register(1, "video:1", "Чат", VideoSpec(ffmpeg(directory)))
        page = store.pages[path.split("/")[-1]]
        store.resolve(path)
        await asyncio.gather(*list(page.jobs.values()))
        assert "Попробовать снова" in store.resolve(path)[0].decode()
        assert not page.jobs
        good = True
        store.resolve(path + "/0/retry")
        await asyncio.gather(*list(page.jobs.values()))
        assert f"/0-v{ENCODING_VERSION}.3gp".encode() in store.resolve(path)[0]

        # Остановка сервера должна завершить ffmpeg, а не оставить процесс.
        slow = directory / "ffmpeg-slow"
        slow.write_text("#!/usr/bin/python3\nimport os,time\nfrom pathlib import Path\n"
                        f"Path({str(directory / 'pid')!r}).write_text(str(os.getpid()))\ntime.sleep(30)\n")
        slow.chmod(0o755)
        path = store.register(1, "video:2", "Чат", VideoSpec(str(slow)))
        store.resolve(path)
        for _ in range(150):
            if (directory / "pid").exists():
                break
            await asyncio.sleep(0.02)
        assert (directory / "pid").exists(), "ffmpeg должен начать работу"
        pid = int((directory / "pid").read_text())
        await asyncio.wait_for(store.stop(), 3)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            pass
        else:
            raise AssertionError("отмена оставила работающий ffmpeg")
        assert not list((directory / "videos").glob("in-*"))
        assert not list((directory / "videos").glob("out-*"))
    print("  повтор и остановка: ок (ошибка, явный повтор, отмена ffmpeg)")


async def run_delivery() -> None:
    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        cfg = Config(tg_api_id=1, tg_api_hash="x", db=":memory:", oscar_host="127.0.0.1",
                     oscar_port=0, oscar_uin="100500", oscar_password="test", render_enabled=False,
                     photos_dir=str(directory / "photos"), render_dir=str(directory / "render"),
                     render_ffmpeg=ffmpeg(directory), photos_public_url="http://host:8080")
        bridge = Bridge(cfg)
        assert bridge.render is None and bridge.videos is not None
        uin = bridge.storage.uin_for_peer(555, kind="user", title="Чат", group_name="Личные")

        async def history(*_):
            return [("[06.10 12:00] Я: подпись [видео 2:05]", "video:42", True)], False

        bridge.oscar.fetch_history = history
        native_requests = []

        async def native_video(target, attach, rotate="auto", segment=0):
            native_requests.append((target, attach, segment))
            return b"native-3gp-video"

        bridge.oscar.fetch_video = native_video
        await bridge.oscar.start()
        port = bridge.oscar._server.sockets[0].getsockname()[1]
        cfg.oscar_port = port
        try:
            cases = [
                ((0, 76), 176, None, False),
                ((0, 77), 240, None, False),  # установленная 0.77 на V8
                ((0, 78), 240, 2, False),
                ((0, 78), 176, 2, False),    # V8-сборка: режим важнее размера экрана
                ((0, 78), 240, None, False), # без режима — безопасный выбор по профилю
                ((0, 78), 0, None, False),   # неизвестный телефон: встроенный плеер
                ((0, 79), 240, 2, False),   # явно только встроенный плеер
                ((0, 77), 176, None, True),
                ((0, 78), 176, 1, True),
                ((0, 78), 240, 1, True),    # V3/Light-сборка: явный режим
                ((0, 79), 176, 3, True),    # оба действия на V3/Light
                ((0, 79), 240, 3, True),    # оба действия на V8
            ]
            for version, width, mode, browser in cases:
                client = FakeJimm("127.0.0.1", port, "100500", "test")
                client.tmm_version = version
                client.device = ("j2me", width, 320 if width == 240 else 182, 8192 if width == 240 else 781)
                client.media = {"video_mode": mode} if mode is not None else None
                try:
                    # Видео, сохранённое до входа, уходит обычным потоком после офлайн-пачки.
                    await bridge.oscar.deliver(uin, "подпись [видео 2:05]", attach="video:42")
                    await client.connect()
                    await client.bos(await client.login_md5_jimm())
                    await client.drain_for(0.3)
                    text = "\n".join(row[1] for row in client.received)
                    rows = await client.request_history(uin, 1)
                    if not browser:
                        assert "[видео](" not in text and "[видео](" not in rows[0][0]
                        assert not bridge.videos.pages
                        assert client.attachments, "встроенный плеер должен получить токен видео"
                        assert not native_requests, "видео не должно скачиваться до команды плеера"
                        token = client.attachments[-1][1]
                        got = await client.request_video(uin, token)
                        assert got == b"native-3gp-video", got
                        assert native_requests == [(uin, "video:42", 0)], native_requests
                        native_requests.clear()
                    else:
                        assert "[видео](http://host:8080/v/" in text, text
                        assert "[видео](http://host:8080/v/" in rows[0][0], rows
                        assert re.search(r"\[видео\]\(([^)]+)\)", text)[1] == re.search(
                            r"\[видео\]\(([^)]+)\)", rows[0][0])[1], "очередь и история должны использовать одну страницу"
                        assert not any(page.jobs for page in bridge.videos.pages.values())
                        assert not list((directory / "photos/videos").glob("*.source"))
                        if mode == 3:
                            assert client.attachments, "для выбора плеера нужен токен"
                            got = await client.request_video(uin, client.attachments[-1][1])
                            assert got == b"native-3gp-video", got
                            assert native_requests == [(uin, "video:42", 0)], native_requests
                            native_requests.clear()
                            client.received.clear()
                            client.attachments.clear()
                            await bridge.oscar.deliver(uin, "[видео 2:05] " + "подпись " * 400,
                                                       attach="video:42")
                            await client.drain_for(0.3)
                            assert len(client.received) > 1, "длинная подпись должна разбиться"
                            assert "[видео](" in client.received[0][1]
                            assert len(client.attachments) == 2, "токен нужен у ссылки и последней части"
                finally:
                    await client.close()
                    await asyncio.sleep(0.05)
        finally:
            await bridge.oscar.stop()
            await bridge.photo_server.stop()
            bridge.storage.close()
    print("  доставка: ок (оба действия на V3/V8, очередь, история, длинная подпись, 0.76–0.79)")


async def main() -> None:
    await run_pages()
    await run_retry_and_cancel()
    await run_delivery()
    print("ВИДЕО ПО КЛИКУ ПРОВЕРЕНЫ")


if __name__ == "__main__":
    asyncio.run(main())
