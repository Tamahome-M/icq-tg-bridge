"""Чтение config.toml."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass

from .db import UIN_BASE


@dataclass
class Config:
    oscar_host: str = "0.0.0.0"
    oscar_port: int = 5190
    oscar_uin: str = "1"
    oscar_password: str = "changeme"
    bos_host: str = ""
    bos_port: int = 0
    ssi_encoding: str = "cp1251"
    allow_from: tuple[str, ...] = ()
    max_connections: int = 8
    login_attempts: int = 5
    login_ban_seconds: int = 300

    tg_api_id: int = 0
    tg_api_hash: str = ""
    tg_session: str = "tg.session"
    mark_read: bool = False
    tg_device_model: str = "PC"
    tg_system_version: str = "Linux"
    tg_app_version: str = "Telegram-cli 1.4.1"
    tg_lang_code: str = "en"

    db: str = "bridge.db"
    grouping: str = "folders"
    other_group: str = "Прочее"
    show_sender_in_groups: bool = True
    max_message_chars: int = 900
    history_limit: int = 100
    idle_timeout: int = 360
    delivery_ack: bool = True
    ack_on: str = "read"
    ack_timeout: int = 30
    catch_up: bool = True
    roster_limit: int = 0
    alias_max_chars: int = 40
    topics_limit: int = 50
    favourites: tuple[str, ...] = ()
    busy_hold_minutes: int = 30
    photos_enabled: bool = True
    photos_host: str = "0.0.0.0"
    photos_port: int = 8080
    photos_public_host: str = ""
    photos_dir: str = "photos"
    photo_width: int = 176
    photo_height: int = 220
    photo_max_kb: int = 40
    photo_keep_hours: int = 48
    photos_per_request: int = 5
    emoji_to_text: bool = True
    text_to_emoji: bool = True
    offline_queue_per_chat: int = 30

    @classmethod
    def load(cls, path: str) -> "Config":
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
        oscar = raw.get("oscar", {})
        ph = raw.get("photos", {})
        tg = raw.get("telegram", {})
        br = raw.get("bridge", {})
        base = os.path.dirname(os.path.abspath(path))

        cfg = cls(
            oscar_host=oscar.get("host", cls.oscar_host),
            oscar_port=int(oscar.get("port", cls.oscar_port)),
            oscar_uin=str(oscar.get("uin", cls.oscar_uin)),
            oscar_password=str(oscar.get("password", cls.oscar_password)),
            bos_host=oscar.get("bos_host", ""),
            bos_port=int(oscar.get("bos_port", 0)),
            ssi_encoding=oscar.get("ssi_encoding", cls.ssi_encoding),
            allow_from=tuple(str(x) for x in oscar.get("allow_from", [])),
            max_connections=int(oscar.get("max_connections", cls.max_connections)),
            login_attempts=int(oscar.get("login_attempts", cls.login_attempts)),
            login_ban_seconds=int(oscar.get("login_ban_seconds", cls.login_ban_seconds)),
            tg_api_id=int(tg.get("api_id", 0)),
            tg_api_hash=str(tg.get("api_hash", "")),
            tg_session=_resolve(base, tg.get("session", cls.tg_session)),
            mark_read=bool(tg.get("mark_read", False)),
            tg_device_model=tg.get("device_model", cls.tg_device_model),
            tg_system_version=tg.get("system_version", cls.tg_system_version),
            tg_app_version=tg.get("app_version", cls.tg_app_version),
            tg_lang_code=tg.get("lang_code", cls.tg_lang_code),
            db=_resolve(base, br.get("db", cls.db)),
            grouping=br.get("grouping", cls.grouping),
            other_group=br.get("other_group", cls.other_group),
            show_sender_in_groups=bool(br.get("show_sender_in_groups", True)),
            max_message_chars=int(br.get("max_message_chars", cls.max_message_chars)),
            history_limit=int(br.get("history_limit", cls.history_limit)),
            idle_timeout=int(br.get("idle_timeout", cls.idle_timeout)),
            delivery_ack=bool(br.get("delivery_ack", True)),
            ack_on=str(br.get("ack_on", cls.ack_on)),
            ack_timeout=int(br.get("ack_timeout", cls.ack_timeout)),
            catch_up=bool(br.get("catch_up", True)),
            roster_limit=int(br.get("roster_limit", cls.roster_limit)),
            alias_max_chars=int(br.get("alias_max_chars", cls.alias_max_chars)),
            topics_limit=int(br.get("topics_limit", cls.topics_limit)),
            favourites=tuple(str(x).strip().lower() for x in br.get("favourites", [])),
            busy_hold_minutes=int(br.get("busy_hold_minutes", cls.busy_hold_minutes)),
            photos_enabled=bool(ph.get("enabled", True)),
            photos_host=ph.get("host", cls.photos_host),
            photos_port=int(ph.get("port", cls.photos_port)),
            photos_public_host=ph.get("public_host", ""),
            photos_dir=_resolve(base, ph.get("dir", cls.photos_dir)),
            photo_width=int(ph.get("width", cls.photo_width)),
            photo_height=int(ph.get("height", cls.photo_height)),
            photo_max_kb=int(ph.get("max_kb", cls.photo_max_kb)),
            photo_keep_hours=int(ph.get("keep_hours", cls.photo_keep_hours)),
            photos_per_request=int(ph.get("per_request", cls.photos_per_request)),
            emoji_to_text=bool(br.get("emoji_to_text", True)),
            text_to_emoji=bool(br.get("text_to_emoji", True)),
            offline_queue_per_chat=int(br.get("offline_queue_per_chat", cls.offline_queue_per_chat)),
        )
        if not cfg.oscar_uin.isdigit():
            raise ValueError("oscar.uin должен состоять из цифр — Jimm принимает только числовой UIN")
        if len(cfg.oscar_uin) < 5:
            raise ValueError("oscar.uin короче пяти цифр — Jimm не примет такой номер")
        if int(cfg.oscar_uin) >= UIN_BASE:
            raise ValueError(f"oscar.uin должен быть меньше {UIN_BASE} — с этого числа "
                             f"начинаются UIN чатов Telegram")
        if not cfg.tg_api_id or not cfg.tg_api_hash:
            raise ValueError("Заполните telegram.api_id и telegram.api_hash (my.telegram.org)")
        return cfg


def warn_about_permissions(paths: list[str]) -> list[str]:
    """Файлы с паролем и сессией не должны быть доступны посторонним."""
    loose = []
    for path in paths:
        try:
            mode = os.stat(path).st_mode
        except OSError:
            continue
        if mode & 0o077:
            loose.append(path)
    return loose


def _resolve(base: str, path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(base, path)
