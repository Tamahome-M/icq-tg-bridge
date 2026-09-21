"""Проверка перекодирования фотографий под маленький экран и их раздачи."""

from __future__ import annotations

import asyncio
import io
import os
import random
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from bridge.history import parse
from bridge.photos import PhotoStore
from bridge.webserver import PhotoServer

PORT = 18081


def noisy_jpeg(width: int, height: int) -> bytes:
    """Шумный снимок: такой хуже всего жмётся, на нём и проверяем потолок веса."""
    image = Image.new("RGB", (width, height))
    rnd = random.Random(42)
    image.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
                   for _ in range(width * height)])
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def fetch(url: str) -> tuple[int, str | None, int]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.headers.get("Content-Type"), len(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, None, 0


async def main() -> None:
    directory = tempfile.mkdtemp()
    store = PhotoStore(directory, width=176, height=220, max_bytes=40 * 1024,
                       keep_hours=48)

    # Снимок с телефона ужимается под экран и укладывается в потолок веса.
    original = noisy_jpeg(1600, 1200)
    photo = store.convert(original, "подпись")
    assert photo is not None
    assert photo.width <= 176 and photo.height <= 220, (photo.width, photo.height)
    assert photo.size <= 40 * 1024, f"{photo.size} байт — больше потолка"
    assert len(original) > photo.size * 5, "картинка почти не ужалась"

    # Пропорции сохраняются: широкий кадр не растягивается.
    wide = store.convert(noisy_jpeg(1000, 250))
    assert wide.width == 176 and wide.height < 100, (wide.width, wide.height)

    # Не картинка — не падаем, а честно возвращаем «не вышло».
    assert store.convert("\x00\x01 это не картинка".encode("utf-8")) is None

    # Токен из ссылки не должен выводить за пределы каталога.
    for bad in ("../../etc/passwd", "..", "a/b", ""):
        assert store.path_for(bad) is None, bad
    assert store.path_for(photo.token) is not None

    server = PhotoServer(store, "127.0.0.1", PORT)
    await server.start()
    loop = asyncio.get_running_loop()

    status, mime, length = await loop.run_in_executor(
        None, fetch, f"http://127.0.0.1:{PORT}/p/{photo.token}.jpg")
    assert (status, mime) == (200, "image/jpeg"), (status, mime)
    assert length == photo.size, (length, photo.size)

    for bad_url in (f"http://127.0.0.1:{PORT}/p/zzzzzz.jpg",
                    f"http://127.0.0.1:{PORT}/etc/passwd"):
        status, _, _ = await loop.run_in_executor(None, fetch, bad_url)
        assert status == 404, f"{bad_url} -> {status}"
    # Корень — главная со ссылками на разделы.
    status, _, _ = await loop.run_in_executor(None, fetch, f"http://127.0.0.1:{PORT}/")
    assert status == 200, status

    await server.stop()

    # Старые снимки убираются, свежие остаются.
    old_path = os.path.join(directory, "oldfile.jpg")
    with open(old_path, "wb") as fh:
        fh.write(b"x")
    os.utime(old_path, (time.time() - 72 * 3600, time.time() - 72 * 3600))
    assert store.cleanup() == 1
    assert not os.path.exists(old_path)
    assert os.path.exists(photo.path), "свежий снимок удалять нельзя"

    # Разбор команды
    assert parse("!lastfoto").name == "photo"
    assert parse("!lastfoto 3").count == 3
    assert parse("!lastfoto abc").error

    print(f"  перекодирование: ок ({len(original) // 1024} КБ -> {photo.size // 1024} КБ, "
          f"{photo.width}x{photo.height})")
    print("  раздача по ссылке и очистка: ок")
    print("ФОТО ПРОВЕРЕНЫ")


if __name__ == "__main__":
    asyncio.run(main())
