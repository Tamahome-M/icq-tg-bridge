"""Команды, набираемые прямо в окне чата на телефоне.

  !last       — сообщения за сегодня, с полуночи
  !last 10    — десять последних сообщений
  !lastfoto   — ссылка на последнее фото чата
  !lastfoto 3 — три последних фото
  !render     — страница переписки за сегодня: фото, видео и голосовые
  !render 20  — то же по двадцати последним сообщениям
  !fav        — добавить чат в избранное или убрать оттуда
  !help       — короткая справка
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

PREFIX = "!"

HELP = ("Команды: !last — история за сегодня; !last N — N последних сообщений; "
        "!lastfoto [N] — фото ссылкой; !render [N] — страница с фото, видео и "
        "голосовыми; !fav — избранное вкл/выкл; !help — эта справка.")


@dataclass
class Command:
    name: str
    count: int | None = None      # для !last: сколько сообщений просили
    error: str | None = None      # текст ошибки, если разобрать не вышло


@dataclass
class HistoryItem:
    when: dt.datetime
    who: str
    text: str
    msg_id: int = 0        # номер сообщения в сети — по нему достаётся вложение
    kind: str = ""         # photo, video, voice, audio — или пусто


def parse(text: str) -> Command | None:
    """Разбирает команду. None — это обычное сообщение, его надо отправить в чат."""
    stripped = text.strip()
    if not stripped.startswith(PREFIX):
        return None
    parts = stripped.split()
    name = parts[0].lower()

    if name == "!help":
        return Command("help")
    if name == "!fav":
        if len(parts) > 1:
            return Command("fav", error="Команда без аргументов: просто !fav")
        return Command("fav")
    if name in ("!lastfoto", "!photo"):
        kind = "photo"
    elif name == "!last":
        kind = "last"
    elif name == "!render":
        kind = "render"
    else:
        return None               # неизвестное — считаем обычным текстом

    sample = {"last": "!last 10", "photo": "!lastfoto 3",
              "render": "!render 20"}[kind]
    if len(parts) == 1:
        return Command(kind)
    if len(parts) > 2:
        return Command(kind, error=f"Лишние слова. Нужно: {name} или {sample}")
    try:
        count = int(parts[1])
    except ValueError:
        return Command(kind, error=f"«{parts[1]}» — не число. Нужно: {sample}")
    if count < 1:
        return Command(kind, error="Число должно быть больше нуля")
    return Command(kind, count=count)


def since_midnight(now: dt.datetime | None = None) -> dt.datetime:
    """Начало текущих суток по местному времени."""
    now = now or dt.datetime.now().astimezone()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def format_items(items: list[HistoryItem], max_chars: int) -> list[str]:
    """Складывает историю в блоки, влезающие в одно сообщение."""
    lines = [f"[{i.when.astimezone():%H:%M}] {i.who}: {i.text}" for i in items]
    blocks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        if current and size + len(line) + 1 > max_chars:
            blocks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        blocks.append("\n".join(current))
    return blocks
