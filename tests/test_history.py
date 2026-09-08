"""Проверка команд !last и !help: разбор и раскладка истории по сообщениям."""

from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.history import HistoryItem, format_items, parse, since_midnight

PARSE = [
    ("!last", ("last", None, None)),
    ("!last 10", ("last", 10, None)),
    ("  !LAST 5  ", ("last", 5, None)),
    ("!help", ("help", None, None)),
]
PARSE_ERRORS = ["!last abc", "!last 0", "!last -3", "!last 1 2"]
NOT_COMMANDS = ["привет", "!!!", "!что-то", "", "ну !last внутри строки"]


def main() -> None:
    for text, (name, count, err) in PARSE:
        cmd = parse(text)
        assert cmd is not None and cmd.name == name and cmd.count == count and cmd.error == err, \
            f"{text!r} -> {cmd}"
    for text in PARSE_ERRORS:
        cmd = parse(text)
        assert cmd is not None and cmd.error, f"{text!r} должно было дать ошибку, вышло {cmd}"
    for text in NOT_COMMANDS:
        assert parse(text) is None, f"{text!r} — не команда, а разобралось"

    midnight = since_midnight(dt.datetime(2026, 9, 6, 15, 30).astimezone())
    assert (midnight.hour, midnight.minute, midnight.day) == (0, 0, 6), midnight

    # Длинная история режется на сообщения, а короткая остаётся одним
    now = dt.datetime(2026, 9, 6, 12, 34).astimezone()
    few = [HistoryItem(now, "Вася", "привет"), HistoryItem(now, "Я", "ага")]
    blocks = format_items(few, 900)
    assert blocks == ["[12:34] Вася: привет\n[12:34] Я: ага"], blocks

    many = [HistoryItem(now, "Вася", "с" * 100) for _ in range(20)]
    blocks = format_items(many, 500)
    assert len(blocks) == 5, f"частей {len(blocks)}"
    assert all(len(b) <= 500 for b in blocks), [len(b) for b in blocks]
    assert sum(b.count("\n") + 1 for b in blocks) == 20, "потерялись строки"

    assert format_items([], 900) == []

    print(f"  разбор команд: ок ({len(PARSE) + len(PARSE_ERRORS) + len(NOT_COMMANDS)} случаев)")
    print("  раскладка истории по сообщениям: ок")
    print("КОМАНДЫ ПРОВЕРЕНЫ")


if __name__ == "__main__":
    main()
