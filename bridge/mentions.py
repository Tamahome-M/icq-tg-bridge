"""Обращение ко всем через @all; позиции разметки сетей считаются в UTF-16."""

from __future__ import annotations

import re
from collections.abc import Iterable

ALL = re.compile(r"(?<![\w@/])@all(?![\w@])", re.IGNORECASE)
URL = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)


def utf16_text(text: str, offset: int, length: int) -> str:
    if offset < 0 or length <= 0:
        return ""
    data = text.encode("utf-16-le")
    if (offset + length) * 2 > len(data):
        return ""
    try:
        return data[offset * 2:(offset + length) * 2].decode("utf-16-le")
    except UnicodeDecodeError:
        return ""


def mentions_all(text: str, blocked: Iterable[tuple[int, int]] = ()) -> bool:
    """Отдельный @all вне ссылок, кода и цитат — соглашение моста."""
    spans = list(blocked)
    urls = [(match.start(), match.end()) for match in URL.finditer(text)]
    for match in ALL.finditer(text):
        if any(start < match.end() and end > match.start() for start, end in urls):
            continue
        start = len(text[:match.start()].encode("utf-16-le")) // 2
        end = start + len(match.group())
        if not any(offset < end and offset + length > start for offset, length in spans):
            return True
    return False
