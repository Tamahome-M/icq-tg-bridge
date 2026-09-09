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
    print("  срок жизни: ок (ссылка перестаёт работать, файлы убираются)")


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

    async def get(path: str) -> tuple[str, bytes]:
        reader, writer = await asyncio.open_connection("127.0.0.1", PORT)
        writer.write(f"GET {path} HTTP/1.1\r\nHost: phone\r\n\r\n".encode())
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

    head, _ = await get("/r/чужое")
    assert "404" in head, head
    head, _ = await get("/m/aaaaaaaaaa.3gp")
    assert "404" in head, "неизвестное вложение отдавать нельзя"

    await server.stop()
    print("  раздача: ок (страница, вложения, чужие ссылки)")


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

    async def deliver(target, text, forced=False):
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

    token = link[0].split("/r/")[1].split("\n")[0]
    body = bridge.render.page_for(token)
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
    await run_expiry()
    await run_web()
    await run_command()
    print("СТРАНИЦА ПЕРЕПИСКИ ПРОВЕРЕНА")


if __name__ == "__main__":
    asyncio.run(main())
