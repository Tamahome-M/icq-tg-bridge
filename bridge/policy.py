"""Что доставлять на телефон в зависимости от статуса в Jimm."""

from __future__ import annotations

from .oscar import const as C

# Режимы доставки, от самого разговорчивого к самому тихому
ALL = "all"                    # всё подряд, даже заглушённое в Telegram
UNMUTED = "unmuted"            # всё, что не заглушено в Telegram
BUSY = "busy"                  # личные и избранные, остальное придерживаем
QUIET = "quiet"                # то же, но остальное просто отбрасываем
FAVOURITES = "favourites"      # только избранное

# Статус в Jimm — режим доставки. Проверяем по битам, начиная с самого
# «разговорчивого»: клиенты любят слать статусы комбинациями вроде DND|OCCUPIED.
STATUS_RULES = (
    (C.STATUS_FREE_FOR_CHAT, ALL),        # «свободен для беседы»
    (C.STATUS_DND, QUIET),                # «не беспокоить» — пропущенное не вернётся
    (C.STATUS_NA, FAVOURITES),            # «недоступен»
    (C.STATUS_OCCUPIED, BUSY),            # «занят» — придержим и отдадим свежее
    (0x0100, UNMUTED),                    # «невидимый»
    (C.STATUS_AWAY, UNMUTED),             # «отошёл» — как обычный онлайн
)

MODE_NAMES = {
    ALL: "принимаю все чаты",
    UNMUTED: "принимаю всё, кроме заглушённого в Telegram",
    BUSY: "принимаю личные и избранные, остальное придержу",
    QUIET: "принимаю только личные и избранные",
    FAVOURITES: "принимаю только избранное",
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
    return UNMUTED             # обычный «в сети»


def status_name(status: int) -> str:
    for bit, _ in STATUS_RULES:
        if status & bit:
            return STATUS_NAMES.get(bit, f"0x{status:04x}")
    return STATUS_NAMES.get(status, f"0x{status:04x}")


def allows(mode: str, kind: str, favourite: bool, muted: bool = False) -> bool:
    """Пропускать ли сообщение из чата такого рода при таком режиме.

    Про то, что важно, а что нет, мост не гадает: он смотрит на настройки
    уведомлений в самом Telegram. Заглушённый там чат молчит и на телефоне —
    во всех режимах, кроме «свободен для беседы», где проходит вообще всё.
    «Недоступен» — обратный случай: там пометка «избранное» перевешивает
    и мьют, потому что её ставят руками и ради этого статуса.
    """
    if mode == ALL:
        return True
    if mode == FAVOURITES:
        return favourite
    if muted:
        return False
    if mode == UNMUTED:
        return True
    return kind in ("user", "bot") or favourite


def holds(mode: str) -> bool:
    """Нужно ли придержать то, что не прошло фильтр, до смены статуса."""
    return mode == BUSY


def releases(mode: str) -> bool:
    """Отдавать ли придержанное, когда «занят» сменился на этот режим."""
    return mode in (ALL, UNMUTED)
