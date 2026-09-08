"""Проверка того, что статус в Jimm управляет доставкой."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge import policy
from bridge.oscar import const as C

# статус -> (личный чат, избранный канал, обычная группа, бот)
MATRIX = {
    C.STATUS_FREE_FOR_CHAT: (True, True, True, True),      # свободен для беседы
    C.STATUS_ONLINE: (True, True, False, True),            # в сети
    C.STATUS_AWAY: (True, True, False, True),              # отошёл
    C.STATUS_DND: (True, False, False, True),              # не беспокоить
    C.STATUS_NA: (True, False, False, True),               # недоступен
    C.STATUS_OCCUPIED: (True, False, False, True),         # занят
    0x0013: (True, False, False, True),                    # DND в связке с другими
    0x0021: (True, True, True, True),                      # «свободен» с флагами
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

    # «Не беспокоить» не пропускает даже закреплённую группу.
    assert not policy.allows(policy.PERSONAL, "chat", True)
    # «Свободен для беседы» пропускает и заглушённую.
    assert policy.allows(policy.ALL, "channel", False)
    # Незнакомый статус ведёт себя как обычный «в сети».
    assert policy.mode_for(0x0800) == policy.FAVOURITES

    print(f"  режимы доставки: ок ({len(MATRIX)} статусов)")
    print("СТАТУСЫ ПРОВЕРЕНЫ")


if __name__ == "__main__":
    main()
