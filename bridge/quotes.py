"""Original text and downloadable media for a quote between networks."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable


class QuoteError(Exception):
    """An actionable quote failure that can be shown on the phone."""


@dataclass
class QuoteMedia:
    kind: str
    name: str
    size: int
    save: Callable[[str, int], Awaitable[None]]


@dataclass
class QuoteContent:
    text: str
    media: list[QuoteMedia] = field(default_factory=list)


def utf16_size(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def text_parts(text: str, header: str, limit: int = 4000):
    capacity = limit - utf16_size(header)
    while text:
        size = units = 0
        for char in text:
            width = 2 if ord(char) > 0xFFFF else 1
            if units + width > capacity:
                break
            units += width
            size += 1
        if not size:
            raise QuoteError("Название исходного чата слишком длинное для цитирования.")
        yield header + text[:size]
        text = text[size:]


def check_size(size: int, maximum: int) -> None:
    if maximum <= 0 or size > maximum:
        raise QuoteError("Вложение цитаты больше лимита [render].source_max_mb.")


async def save_bytes(fetch: Callable[[], Awaitable[bytes | None]], path: str, maximum: int) -> None:
    data = await fetch()
    if not data:
        raise QuoteError("Не удалось скачать вложение цитаты. Ничего не отправлено.")
    check_size(len(data), maximum)
    Path(path).write_bytes(data)


def filename(name: str, fallback: str = "file.bin") -> str:
    name = name.replace("\\", "/").rsplit("/", 1)[-1].replace("\0", "")
    return name if name and name not in (".", "..") else fallback
