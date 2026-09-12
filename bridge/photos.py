"""Хранилище фотографий для телефона: перекодирование под маленький экран
и раздача по короткой ссылке."""

from __future__ import annotations

import io
import logging
import re
import os
import secrets
import time
from dataclasses import dataclass

from PIL import Image, ImageOps

log = logging.getLogger("photos")

# Размер по умолчанию — под экран телефона вроде Motorola V3 (176x220).
# Больше отдавать смысла нет, а трафика на GPRS уходит заметно больше.
DEFAULT_WIDTH = 176
DEFAULT_HEIGHT = 220
# Потолок размера файла: на GPRS каждый лишний килобайт заметен.
DEFAULT_MAX_BYTES = 40 * 1024
QUALITY_STEPS = (75, 65, 55, 45, 35, 25)
# Имя файла в ссылке — только латиница и цифры: ничего, что уводит из каталога.
TOKEN_RE = re.compile(r"\A[A-Za-z0-9]{1,32}\Z")
# Потолок для входной картинки: и по весу, и по числу точек, чтобы
# распаковка не съела память.
MAX_SOURCE_BYTES = 12 * 1024 * 1024
MAX_SOURCE_PIXELS = 40_000_000


@dataclass
class Photo:
    token: str
    path: str
    size: int
    width: int
    height: int
    caption: str


def shrink(raw: bytes, width: int = DEFAULT_WIDTH, height: int = DEFAULT_HEIGHT,
           max_bytes: int = DEFAULT_MAX_BYTES) -> tuple[bytes, int, int] | None:
    """Ужимает картинку под экран телефона: данные, ширина, высота."""
    if not raw:
        log.warning("картинка пустая, пропускаю")
        return None
    if len(raw) > MAX_SOURCE_BYTES:
        log.warning("картинка %d КБ слишком велика, пропускаю", len(raw) // 1024)
        return None
    try:
        Image.MAX_IMAGE_PIXELS = MAX_SOURCE_PIXELS
        image = Image.open(io.BytesIO(raw))
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
    except Exception:
        log.warning("не удалось прочитать картинку (%d байт)", len(raw))
        return None

    image.thumbnail((width, height), Image.LANCZOS)
    data = b""
    for quality in QUALITY_STEPS:
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True,
                   progressive=False)      # старые браузеры не любят прогрессивный JPEG
        data = buffer.getvalue()
        if len(data) <= max_bytes:
            break
    return data, image.width, image.height


class PhotoStore:
    def __init__(self, directory: str, width: int = DEFAULT_WIDTH,
                 height: int = DEFAULT_HEIGHT, max_bytes: int = DEFAULT_MAX_BYTES,
                 keep_hours: int = 48):
        self.directory = directory
        self.width = width
        self.height = height
        self.max_bytes = max_bytes
        self.keep_hours = keep_hours
        os.makedirs(directory, exist_ok=True)

    def convert(self, raw: bytes, caption: str = "") -> Photo | None:
        """Ужимает картинку под экран телефона и кладёт в хранилище."""
        got = shrink(raw, self.width, self.height, self.max_bytes)
        if got is None:
            return None
        data, width, height = got

        token = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8]
        path = os.path.join(self.directory, f"{token}.jpg")
        with open(path, "wb") as fh:
            fh.write(data)
        log.info("картинка ужата до %dx%d, %d КБ", width, height, len(data) // 1024)
        return Photo(token, path, len(data), width, height, caption)

    def path_for(self, token: str) -> str | None:
        """Путь к файлу по токену из ссылки."""
        if not TOKEN_RE.match(token or ""):
            return None
        path = os.path.join(self.directory, f"{token}.jpg")
        return path if os.path.isfile(path) else None

    def cleanup(self) -> int:
        """Убирает старые файлы, чтобы каталог не рос бесконечно."""
        if self.keep_hours <= 0:
            return 0
        deadline = time.time() - self.keep_hours * 3600
        removed = kept = 0
        for name in os.listdir(self.directory):
            path = os.path.join(self.directory, name)
            try:
                if not os.path.isfile(path):
                    continue
                if os.path.getmtime(path) < deadline:
                    os.unlink(path)
                    removed += 1
                else:
                    kept += 1
            except OSError:
                continue
        if removed:
            log.info("уборка снимков: удалено %d старше %d ч, осталось %d",
                     removed, self.keep_hours, kept)
        else:
            log.debug("уборка снимков: убирать нечего, файлов %d", kept)
        return removed
