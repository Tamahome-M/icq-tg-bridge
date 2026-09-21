"""Профили телефонов: какие снимок, ролик и голосовое отдавать этому аппарату.

TeleMotoMax при входе присылает платформу (`microedition.platform`), размер
экрана и объём кучи. По ним выбирается профиль — набор настроек вместо
общих `[telemotomax]`: у V3 экран 176×220 и куча меньше мегабайта, у V8 —
240×320 и десять мегабайт, и одинаковые 176×176 при 20 КБ на снимок для
обоих — либо мыло на V8, либо перебор для V3.

Встроенные профили — для двух известных телефонов; в `config.toml` их можно
подправить или добавить свои (`[telemotomax.profile.<имя>]`). Профиль
подходит, если платформа содержит `match` (без учёта регистра) или экран
не уже `min_width`; первый подошедший — по порядку: сначала из конфига,
потом встроенные. Без сведений от телефона (обычный Jimm или старый
TeleMotoMax) действуют общие настройки.
"""

from __future__ import annotations

from dataclasses import dataclass

# Что можно переопределить в профиле, и как ключ называется в Config.
KEYS = {
    "photo_width": "tmm_photo_width",
    "photo_height": "tmm_photo_height",
    "photo_max_kb": "tmm_photo_max_kb",
    "photo_quality": "tmm_photo_quality",
    "video_seconds": "tmm_video_seconds",
    "voice_seconds": "tmm_voice_seconds",
    "voice_kbps": "tmm_voice_kbps",
    "history_max": "tmm_history_max",
    # Ограничение контакт-листа тоже своё у каждого телефона: V3 сотни
    # контактов не тянет, V8 — тянет. Пишется в профиле как roster_limit,
    # а общее значение — [bridge] roster_limit.
    "roster_limit": "roster_limit",
}

BUILTIN: dict[str, dict] = {
    # Motorola V3: маленький экран, меньше мегабайта кучи, MMAPI без видео.
    "v3": {"match": "V3", "photo_width": 176, "photo_height": 176, "photo_max_kb": 20,
           "photo_quality": 0, "video_seconds": 10, "voice_kbps": 12.2, "history_max": 200},
    # Motorola V8: 240×320, кучи хватает на снимок побольше и получше, ролик
    # подлиннее и список без ограничения (0 — все чаты).
    "v8": {"match": "V8", "min_width": 240, "photo_width": 240, "photo_height": 320,
           "photo_max_kb": 60, "photo_quality": 85, "video_seconds": 30, "voice_kbps": 12.2,
           "history_max": 400, "roster_limit": 0},
}


@dataclass
class Device:
    platform: str = ""
    width: int = 0
    height: int = 0
    memory_kb: int = 0

    def __str__(self) -> str:
        bits = [self.platform or "платформа не названа"]
        if self.width and self.height:
            bits.append(f"экран {self.width}×{self.height}")
        if self.memory_kb:
            bits.append(f"куча {self.memory_kb // 1024} МБ" if self.memory_kb >= 2048
                        else f"куча {self.memory_kb} КБ")
        return ", ".join(bits)


def matches(profile: dict, device: Device) -> bool:
    match = str(profile.get("match", "") or "")
    if match and match.lower() in device.platform.lower():
        return True
    min_width = int(profile.get("min_width", 0) or 0)
    if min_width and device.width and device.width >= min_width:
        return True
    return False


def choose(device: Device, configured: dict[str, dict]) -> tuple[str, dict] | None:
    """Имя и настройки подошедшего профиля. Профиль из конфига с тем же
    именем, что встроенный, дополняет его: неуказанное берётся из
    встроенного."""
    merged: dict[str, dict] = {}
    for name, prof in configured.items():
        merged[name] = {**BUILTIN.get(name, {}), **prof}
    for name, prof in BUILTIN.items():
        merged.setdefault(name, prof)
    for name, prof in merged.items():
        if matches(prof, device):
            return name, prof
    return None
