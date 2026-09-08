"""Проверка перевода эмодзи в смайлы Jimm и обратно."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.emoji import EMOJI_TEXT, EMOJI_WORDS, JIMM_SMILEYS, to_emoji, to_text

TO_TEXT = [
    ("Привет \U0001F600", "Привет :-D"),
    ("Привет\U0001F600", "Привет :-D"),                      # пробел добавляется
    ("\U0001F44D", "(y)"),                                   # палец вверх Jimm
    ("люблю \U00002764\U0000FE0F", "люблю *IN_LOVE*"),       # сердце → влюблён
    ("\U0001F602\U0001F602\U0001F602", ":-D"),               # повторы схлопываются
    ("\U0001F600\U0001F44D", ":-D (y)"),                     # соседние разделяются
    ("болею\U0001F912 сегодня", "болею :-! сегодня"),
    ("\U0001F339 тебе", "@}->-- тебе"),
    ("конец\U0001F600.", "конец :-D."),                      # перед точкой пробела нет
    ("\U0001F44B\U0001F3FD привет", "*привет* привет"),      # тон кожи убран
    ("флаг \U0001F1F7\U0001F1FA", "флаг [RU]"),
    ("\U0001FAE0", "[melting face]"),                        # редкий — по имени
    ("обычный текст", "обычный текст"),
    ("", ""),
]

TO_EMOJI = [
    (":) привет", "\U0001F642 привет"),
    ("класс (y)", "класс \U0001F44D"),
    ("вот *IN_LOVE*", "вот \U0001F60D"),
    ("роза @}->--", "роза \U0001F339"),
    ("ок :-D", "ок \U0001F603"),
    ("время 8:00", "время 8:00"),          # не смайл
    ("счёт 8-1", "счёт 8-1"),              # не смайл
    ("путь C:/temp", "путь C:/temp"),      # не смайл
]


def main() -> None:
    for src, want in TO_TEXT:
        got = to_text(src)
        assert got == want, f"to_text({src!r}): ожидали {want!r}, получили {got!r}"
    for src, want in TO_EMOJI:
        got = to_emoji(src)
        assert got == want, f"to_emoji({src!r}): ожидали {want!r}, получили {got!r}"

    # Каждый код, в который мы переводим эмодзи, должен быть смайлом Jimm —
    # иначе на телефоне вместо картинки будет непонятная строка.
    for emoji_char, code in EMOJI_TEXT.items():
        if emoji_char in EMOJI_WORDS:
            continue
        assert code in JIMM_SMILEYS, f"{code!r} нет в наборе смайлов Jimm"

    # После перевода не должно остаться символов вне базовой плоскости —
    # иначе телефон получит суррогатные пары и нарисует квадраты.
    hard = "тест \U0001F92F \U0001F9D1\U0000200D\U0001F4BB \U0001F1EF\U0001F1F5 \U0001F970"
    assert all(ord(c) <= 0xFFFF for c in to_text(hard)), to_text(hard)

    print(f"  эмодзи → смайлы Jimm: ок ({len(TO_TEXT)} случаев, "
          f"{len(EMOJI_TEXT) - len(EMOJI_WORDS)} эмодзи на {len(JIMM_SMILEYS)} картинок)")
    print(f"  смайлы Jimm → эмодзи: ок ({len(TO_EMOJI)} случаев)")
    print("СМАЙЛЫ ПРОВЕРЕНЫ")


if __name__ == "__main__":
    main()
