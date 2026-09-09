"""Проверка того, что статус в Jimm управляет доставкой."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge import policy
from bridge.oscar import const as C

# статус -> (личный чат, избранный канал, обычная группа, бот)
# Все чаты здесь не заглушены в Telegram; поведение с мьютом ниже отдельно.
MATRIX = {
    C.STATUS_FREE_FOR_CHAT: (True, True, True, True),      # свободен для беседы
    C.STATUS_ONLINE: (True, True, True, True),             # в сети: всё незаглушённое
    C.STATUS_AWAY: (True, True, True, True),               # отошёл: так же
    C.STATUS_DND: (True, True, False, True),               # не беспокоить
    C.STATUS_NA: (False, True, False, False),              # недоступен: только избранное
    C.STATUS_OCCUPIED: (True, True, False, True),          # занят
    policy.STATUS_INVISIBLE: (False, False, False, False),  # невидимый
    0x0013: (True, True, False, True),                     # DND в связке с другими
    0x0021: (True, True, True, True),                      # «свободен» с флагами
    0x0102: (False, False, False, False),                  # невидимый вместе с DND
}

def main() -> None:
    for status, (personal, favourite_channel, plain_group, bot) in MATRIX.items():
        mode = policy.mode_for(status)
        got = (
            policy.allows(mode, "user", False),
            policy.allows(mode, "channel", True),
            policy.allows(mode, "chat", False),
            policy.allows(mode, "bot", False),
        )
        want = (personal, favourite_channel, plain_group, bot)
        assert got == want, f"статус {policy.status_name(status)}: ждали {want}, вышло {got}"

    # Мьют в Telegram молчит везде, кроме «свободен для беседы».
    for mode in (policy.UNMUTED, policy.BUSY, policy.QUIET):
        assert policy.allows(mode, "user", False, muted=False)
        assert not policy.allows(mode, "user", False, muted=True), \
            f"заглушённый человек должен молчать в режиме {mode}"
        assert not policy.allows(mode, "channel", True, muted=True), \
            f"избранное не отменяет мьют в режиме {mode}"

    # «Свободен для беседы» пропускает и заглушённое.
    assert policy.allows(policy.ALL, "channel", False, muted=True)
    # «Недоступен» — только избранное, зато пометку не отменяет даже мьют.
    assert policy.allows(policy.FAVOURITES, "channel", True, muted=True)
    assert not policy.allows(policy.FAVOURITES, "user", False)
    # «Занят» и «не беспокоить» различаются судьбой непрошедшего, а не фильтром.
    assert policy.holds(policy.BUSY) and not policy.holds(policy.QUIET)
    # Придержанное отдаётся только в разговорчивых режимах.
    assert policy.releases(policy.ALL) and policy.releases(policy.UNMUTED)
    assert not policy.releases(policy.QUIET) and not policy.releases(policy.FAVOURITES)
    # «Невидимый» — только избранные собеседники, каналы и группы молчат.
    assert policy.allows(policy.INVISIBLE, "user", True)
    assert policy.allows(policy.INVISIBLE, "user", True, muted=True), \
        "пометку избранного мьют не отменяет"
    assert not policy.allows(policy.INVISIBLE, "user", False), "неизбранный молчит"
    assert not policy.allows(policy.INVISIBLE, "channel", True), "избранный канал молчит"
    assert not policy.allows(policy.INVISIBLE, "chat", True), "избранная группа молчит"
    assert not policy.releases(policy.INVISIBLE)

    # Незнакомый статус ведёт себя как обычный «в сети».
    assert policy.mode_for(0x0800) == policy.UNMUTED

    print(f"  режимы доставки: ок ({len(MATRIX)} статусов)")
    print("СТАТУСЫ ПРОВЕРЕНЫ")


if __name__ == "__main__":
    main()
