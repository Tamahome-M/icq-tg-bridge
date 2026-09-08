"""Что доставлять на телефон в зависимости от статуса в Jimm."""

from __future__ import annotations

from .oscar import const as C

# Режимы доставки
ALL = "all"                    # всё подряд
FAVOURITES = "favourites"      # личные и избранные группы с каналами
PERSONAL = "personal"          # только личные, остальное проходит мимо
BUSY = "busy"                  # только личные, остальное придерживаем

# Статус в Jimm — режим доставки. Проверяем по битам, начиная с самого
# «разговорчивого»: клиенты любят слать статусы комбинациями вроде DND|OCCUPIED.
STATUS_RULES = (
    (C.STATUS_FREE_FOR_CHAT, ALL),        # «свободен для беседы»
    (C.STATUS_DND, PERSONAL),             # «не беспокоить» — пропущенное не вернётся
    (C.STATUS_NA, PERSONAL),              # «недоступен»
    (C.STATUS_OCCUPIED, BUSY),            # «занят» — придержим и отдадим свежее
    (0x0100, PERSONAL),                   # «невидимый»
    (C.STATUS_AWAY, FAVOURITES),          # «отошёл» — как обычный онлайн
)

MODE_NAMES = {
    ALL: "принимаю все чаты",
    FAVOURITES: "принимаю личные и избранные",
    PERSONAL: "принимаю только личные, остальное не вернётся",
    BUSY: "принимаю только личные, остальное придержу",
}

STATUS_NAMES = {
    C.STATUS_ONLINE: "в сети",
    C.STATUS_AWAY: "отошёл",
    C.STATUS_DND: "не беспокоить",
    C.STATUS_NA: "недоступен",
    C.STATUS_OCCUPIED: "занят",
    C.STATUS_FREE_FOR_CHAT: "свободен для беседы",
    0x0100: "невидимый",
}


def mode_for(status: int) -> str:
    """Режим доставки для статуса, выставленного в Jimm."""
    for bit, mode in STATUS_RULES:
        if status & bit:
            return mode
    return FAVOURITES          # обычный «в сети»


def status_name(status: int) -> str:
    for bit, _ in STATUS_RULES:
        if status & bit:
            return STATUS_NAMES.get(bit, f"0x{status:04x}")
    return STATUS_NAMES.get(status, f"0x{status:04x}")


def allows(mode: str, kind: str, favourite: bool) -> bool:
    """Пропускать ли сообщение из чата такого рода при таком режиме."""
    if mode == ALL:
        return True
    personal = kind in ("user", "bot")
    if mode in (PERSONAL, BUSY):
        return personal
    return personal or favourite


def holds(mode: str) -> bool:
    """Нужно ли придержать то, что не прошло фильтр, до смены статуса."""
    return mode == BUSY
