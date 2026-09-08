#!/usr/bin/env python3
"""Раздача установочных файлов Jimm для телефона.

Ставить нужно именно с JAD: только так в описании приложения доезжают
Background и FlipInsensitive, от которых зависит работа в фоне и с закрытой
раскладушкой. Поэтому дескриптор отдаётся с MIME-типом
text/vnd.sun.j2me.app-descriptor — иначе телефон просто покажет его текстом.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

# Каталог со сборками: в нём подкаталоги, где лежат Jimm.jad и Jimm.jar.
# Путь задаётся переменной JIMM_DIR или вторым аргументом.
JIMM_DIR = os.environ.get("JIMM_DIR", os.path.expanduser("~/jimm"))


def find_builds(root: str) -> dict[str, tuple[str, str]]:
    builds: dict[str, tuple[str, str]] = {}
    if not os.path.isdir(root):
        return builds
    for name in sorted(os.listdir(root)):
        directory = os.path.join(root, name)
        if os.path.isfile(os.path.join(directory, "Jimm.jad")):
            key = "".join(c for c in name.lower() if c.isalnum())[:16] or f"b{len(builds)}"
            builds[key] = (directory, name)
    return builds


BUILDS: dict[str, tuple[str, str]] = {}

MIME = {
    ".jad": "text/vnd.sun.j2me.app-descriptor",
    ".jar": "application/java-archive",
}

log = logging.getLogger("jimm-web")


def page() -> bytes:
    """Страница со ссылками.

    Простой HTML в UTF-8, а не XHTML MP: браузер старой Motorola не распознаёт
    тип application/xhtml+xml и берёт кодировку по своему усмотрению — из-за
    этого кириллица приезжает мусором.
    """
    rows = []
    for key, (directory, title) in BUILDS.items():
        jar = os.path.join(directory, "Jimm.jar")
        size = os.path.getsize(jar) // 1024 if os.path.exists(jar) else 0
        rows.append(f'<p><a href="/{key}/Jimm.jad">{title}</a><br>{size} KB</p>')
    body = (
        "<html><head>"
        '<meta http-equiv="Content-Type" content="text/html; charset=utf-8">'
        "<title>Jimm</title></head><body>"
        "<p><b>Установка Jimm</b></p>"
        + "".join(rows) +
        "<p><small>Ставить по ссылке на JAD — иначе не будет работы в фоне.</small></p>"
        "</body></html>"
    )
    return body.encode("utf-8")


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    peer = writer.get_extra_info("peername")
    try:
        line = await asyncio.wait_for(reader.readline(), timeout=15)
        if not line:
            return
        parts = line.decode("latin-1", "replace").split()
        if len(parts) < 2:
            return
        method, path = parts[0], parts[1].split("?", 1)[0]
        while True:                       # дочитываем заголовки
            header = await asyncio.wait_for(reader.readline(), timeout=15)
            if header in (b"\r\n", b"\n", b""):
                break
        log.info("%s %s %s", peer[0] if peer else "?", method, path)

        body, mime = resolve(path)
        if body is None:
            writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n"
                         b"Connection: close\r\n\r\n")
        else:
            head = (f"HTTP/1.1 200 OK\r\nContent-Type: {mime}\r\n"
                    f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n")
            writer.write(head.encode("ascii") + (b"" if method == "HEAD" else body))
        await writer.drain()
    except (asyncio.TimeoutError, ConnectionError, OSError):
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass


def resolve(path: str) -> tuple[bytes | None, str]:
    if path in ("/", "/index.html", "/index.wml"):
        return page(), "text/html; charset=utf-8"

    chunks = [c for c in path.split("/") if c]
    if len(chunks) != 2 or chunks[0] not in BUILDS:
        return None, ""
    directory = BUILDS[chunks[0]][0]
    name = os.path.basename(chunks[1])
    if name not in ("Jimm.jad", "Jimm.jar"):
        return None, ""
    full = os.path.join(directory, name)
    if not os.path.isfile(full):
        return None, ""
    with open(full, "rb") as fh:
        return fh.read(), MIME[os.path.splitext(name)[1].lower()]


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S")
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5190
    root = sys.argv[2] if len(sys.argv) > 2 else JIMM_DIR
    BUILDS.update(find_builds(root))
    if not BUILDS:
        log.error("в каталоге %s не нашлось ни одной сборки с Jimm.jad", root)
        return
    server = await asyncio.start_server(handle, "0.0.0.0", port)
    log.info("раздача Jimm на порту %d", port)
    log.info("сборки из каталога %s:", root)
    for key, (directory, title) in BUILDS.items():
        log.info("  /%s/Jimm.jad — %s", key, title)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
