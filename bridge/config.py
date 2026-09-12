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
    tg_device_model: str = "PC 64bit"
    tg_system_version: str = "Linux"
    tg_app_version: str = "4.16.8"
    tg_lang_code: str = "en"

    db: str = "bridge.db"
    grouping: str = "folders"
    other_group: str = "Прочее"
    archive_group: str = "Архив"
    mirror_outgoing: bool = False
    show_sender_in_groups: bool = True
    max_message_chars: int = 900
    history_limit: int = 100
    idle_timeout: int = 360
    delivery_ack: bool = True
    ack_on: str = "read"
    ack_timeout: int = 30
    catch_up: bool = True
    allow_delete: bool = True
    allow_delete_revoke: bool = True
    roster_limit: int = 0
    alias_max_chars: int = 40
    topics_limit: int = 50
    favourites: tuple[str, ...] = ()
    busy_hold_minutes: int = 30
    avatars: bool = False
    avatar_size: int = 64
    avatar_max_kb: int = 4
    photos_enabled: bool = True
    photos_host: str = "0.0.0.0"
    photos_port: int = 8080
    photos_public_host: str = ""
    photos_public_url: str = ""
    photos_password: str = ""
    photos_link_session: bool = True
    photos_dir: str = "photos"
    photo_width: int = 176
    photo_height: int = 220
    photo_max_kb: int = 40
    photo_keep_hours: int = 48
    photos_per_request: int = 5
    render_enabled: bool = True
    render_dir: str = "render"
    render_ttl_minutes: int = 30
    render_messages: int = 20
    render_ffmpeg: str = "ffmpeg"
    render_video_seconds: int = 60
    render_video_codec: str = "h263"
    render_video_kbps: int = 64
    render_video_fps: int = 15
    render_audio_seconds: int = 300
    render_source_max_mb: int = 25
    render_timeout: int = 120
    render_encoding: str = "utf-8"
    render_path: str = "/r/{n}"
    render_index: bool = False
    render_page_max_kb: int = 6
    downloads_dir: str = ""
    downloads_protected: bool = False
    emoji_to_text: bool = True
    text_to_emoji: bool = True
    offline_queue_per_chat: int = 30
    log_level: str = "INFO"
    log_telethon_level: str = "WARNING"
    log_file: str = ""
    log_file_max_mb: int = 5
    log_file_keep: int = 3
    log_filtered: bool = True
    assistant_enabled: bool = False
    assistant_command: str = "claude"
    assistant_workdir: str = "claude"
    assistant_model: str = ""
    assistant_effort: str = "low"
    assistant_system: str = ""
    assistant_tools: str = "WebSearch,WebFetch"
    assistant_args: str = ""
    assistant_timeout: int = 300
    assistant_session_hours: int = 0
    assistant_title: str = "Claude"
    assistant_group: str = "Боты"

    @classmethod
    def load(cls, path: str) -> "Config":
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
        oscar = raw.get("oscar", {})
        ph = raw.get("photos", {})
        rn = raw.get("render", {})
        lg = raw.get("log", {})
        dl = raw.get("downloads", {})
        ai = raw.get("assistant", {})
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
            archive_group=br.get("archive_group", cls.archive_group),
            mirror_outgoing=bool(br.get("mirror_outgoing", cls.mirror_outgoing)),
            show_sender_in_groups=bool(br.get("show_sender_in_groups", True)),
            max_message_chars=int(br.get("max_message_chars", cls.max_message_chars)),
            history_limit=int(br.get("history_limit", cls.history_limit)),
            idle_timeout=int(br.get("idle_timeout", cls.idle_timeout)),
            delivery_ack=bool(br.get("delivery_ack", True)),
            ack_on=str(br.get("ack_on", cls.ack_on)),
            ack_timeout=int(br.get("ack_timeout", cls.ack_timeout)),
            catch_up=bool(br.get("catch_up", True)),
            allow_delete=bool(br.get("allow_delete", True)),
            allow_delete_revoke=bool(br.get("allow_delete_revoke", True)),
            roster_limit=int(br.get("roster_limit", cls.roster_limit)),
            alias_max_chars=int(br.get("alias_max_chars", cls.alias_max_chars)),
            topics_limit=int(br.get("topics_limit", cls.topics_limit)),
            favourites=tuple(str(x).strip().lower() for x in br.get("favourites", [])),
            busy_hold_minutes=int(br.get("busy_hold_minutes", cls.busy_hold_minutes)),
            avatars=bool(br.get("avatars", cls.avatars)),
            avatar_size=int(br.get("avatar_size", cls.avatar_size)),
            avatar_max_kb=int(br.get("avatar_max_kb", cls.avatar_max_kb)),
            photos_enabled=bool(ph.get("enabled", True)),
            photos_host=ph.get("host", cls.photos_host),
            photos_port=int(ph.get("port", cls.photos_port)),
            photos_public_host=ph.get("public_host", ""),
            photos_public_url=str(ph.get("public_url", "")).rstrip("/"),
            photos_password=str(ph.get("password", "")),
            photos_link_session=bool(ph.get("link_session", cls.photos_link_session)),
            photos_dir=_resolve(base, ph.get("dir", cls.photos_dir)),
            photo_width=int(ph.get("width", cls.photo_width)),
            photo_height=int(ph.get("height", cls.photo_height)),
            photo_max_kb=int(ph.get("max_kb", cls.photo_max_kb)),
            photo_keep_hours=int(ph.get("keep_hours", cls.photo_keep_hours)),
            photos_per_request=int(ph.get("per_request", cls.photos_per_request)),
            render_enabled=bool(rn.get("enabled", cls.render_enabled)),
            render_dir=_resolve(base, rn.get("dir", cls.render_dir)),
            render_ttl_minutes=int(rn.get("ttl_minutes", cls.render_ttl_minutes)),
            render_messages=int(rn.get("messages", cls.render_messages)),
            render_ffmpeg=rn.get("ffmpeg", cls.render_ffmpeg),
            render_video_seconds=int(rn.get("video_seconds", cls.render_video_seconds)),
            render_video_codec=str(rn.get("video_codec", cls.render_video_codec)),
            render_video_kbps=int(rn.get("video_kbps", cls.render_video_kbps)),
            render_video_fps=int(rn.get("video_fps", cls.render_video_fps)),
            render_audio_seconds=int(rn.get("audio_seconds", cls.render_audio_seconds)),
            render_source_max_mb=int(rn.get("source_max_mb", cls.render_source_max_mb)),
            render_timeout=int(rn.get("timeout", cls.render_timeout)),
            render_encoding=rn.get("encoding", cls.render_encoding),
            render_path=str(rn.get("path", cls.render_path)),
            render_index=bool(rn.get("index", cls.render_index)),
            render_page_max_kb=int(rn.get("page_max_kb", cls.render_page_max_kb)),
            downloads_dir=_resolve(base, dl["dir"]) if dl.get("dir") else "",
            downloads_protected=bool(dl.get("protected", cls.downloads_protected)),
            log_level=str(lg.get("level", cls.log_level)).upper(),
            log_telethon_level=str(lg.get("telethon_level", cls.log_telethon_level)).upper(),
            log_file=_resolve(base, lg["file"]) if lg.get("file") else "",
            log_file_max_mb=int(lg.get("file_max_mb", cls.log_file_max_mb)),
            log_file_keep=int(lg.get("file_keep", cls.log_file_keep)),
            log_filtered=bool(lg.get("filtered", cls.log_filtered)),
            assistant_enabled=bool(ai.get("enabled", cls.assistant_enabled)),
            assistant_command=str(ai.get("command", cls.assistant_command)),
            assistant_workdir=_resolve(base, ai.get("workdir", cls.assistant_workdir)),
            assistant_model=str(ai.get("model", "")),
            assistant_effort=str(ai.get("effort", cls.assistant_effort)),
            assistant_system=str(ai.get("system", "")),
            assistant_tools=str(ai.get("tools", cls.assistant_tools)),
            assistant_args=str(ai.get("args", "")),
            assistant_timeout=int(ai.get("timeout", cls.assistant_timeout)),
            assistant_session_hours=int(ai.get("session_hours", cls.assistant_session_hours)),
            assistant_title=str(ai.get("title", cls.assistant_title)),
            assistant_group=str(ai.get("group", cls.assistant_group)),
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
