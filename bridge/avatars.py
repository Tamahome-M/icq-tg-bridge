"""Аватарки контактов: квадратик под контакт-лист телефона.

Телефон получает картинку одним пакетом, поэтому она должна быть маленькой —
и по числу точек, и по весу. Хеш, которым клиент опознаёт картинку, считается
из идентификатора фотографии в Telegram: пока человек не сменил фото, хеш тот
же, а сменил — клиент сам придёт за новой.
"""

from __future__ import annotations

import hashlib
import io
import logging

log = logging.getLogger("avatars")

DEFAULT_SIZE = 64
# Потолок веса: картинка едет одним SNAC, а на GPRS каждый килобайт заметен.
DEFAULT_MAX_BYTES = 4 * 1024
QUALITY_STEPS = (70, 60, 50, 40, 30)
# Защита от «архивных бомб»: аватарка приходит из Telegram, но проверить дёшево.
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_SOURCE_PIXELS = 40_000_000


def hash_for(photo_id: int) -> bytes:
    """Ярлык картинки: 16 байт, как ждёт клиент."""
    return hashlib.md5(str(photo_id).encode("ascii")).digest()


def convert(raw: bytes, size: int = DEFAULT_SIZE,
            max_bytes: int = DEFAULT_MAX_BYTES) -> bytes | None:
    """Обрезает аватарку в квадрат и ужимает под телефон."""
    if not raw or len(raw) > MAX_SOURCE_BYTES:
        return None
    try:
        from PIL import Image, ImageOps
    except ImportError:
        log.warning("нет Pillow — аватарки не отдаю")
        return None

    try:
        Image.MAX_IMAGE_PIXELS = MAX_SOURCE_PIXELS
        with Image.open(io.BytesIO(raw)) as img:
            img = ImageOps.exif_transpose(img)
            # Квадрат по центру: в списке контактов аватарка всё равно квадратная.
            img = ImageOps.fit(img.convert("RGB"), (size, size))
            for quality in QUALITY_STEPS:
                out = io.BytesIO()
                img.save(out, format="JPEG", quality=quality, optimize=True)
                if out.tell() <= max_bytes:
                    return out.getvalue()
        log.info("аватарка не ужалась до %d байт — пропускаю", max_bytes)
    except Exception as exc:
        log.warning("не смог перекодировать аватарку: %s", exc)
    return None


class AvatarStore:
    """Готовые картинки по UIN. Держим в памяти: их немного и они крошечные."""

    def __init__(self, size: int = DEFAULT_SIZE, max_bytes: int = DEFAULT_MAX_BYTES,
                 keep: int = 200):
        self.size = size
        self.max_bytes = max_bytes
        self.keep = keep
        self._hashes: dict[int, bytes] = {}
        self._images: dict[int, tuple[bytes, bytes]] = {}   # uin -> (хеш, jpeg)

    def remember(self, uin: int, photo_id: int) -> None:
        """Запоминает, какая картинка у контакта сейчас."""
        if not photo_id:
            self.forget(uin)
            return
        digest = hash_for(photo_id)
        if self._hashes.get(uin) != digest:
            self._hashes[uin] = digest
            self._images.pop(uin, None)     # фото сменилось — старое больше не нужно

    def forget(self, uin: int) -> None:
        self._hashes.pop(uin, None)
        self._images.pop(uin, None)

    def hash_of(self, uin: int) -> bytes | None:
        return self._hashes.get(uin)

    def cached(self, uin: int) -> tuple[bytes, bytes] | None:
        got = self._images.get(uin)
        if got is None or got[0] != self._hashes.get(uin):
            return None
        return got

    def store(self, uin: int, raw: bytes) -> tuple[bytes, bytes] | None:
        """Перекодирует и кладёт в кэш. Возвращает пару «хеш, картинка»."""
        digest = self._hashes.get(uin)
        if digest is None:
            return None
        image = convert(raw, self.size, self.max_bytes)
        if image is None:
            return None
        if len(self._images) >= self.keep:
            self._images.pop(next(iter(self._images)))
        self._images[uin] = (digest, image)
        return self._images[uin]
