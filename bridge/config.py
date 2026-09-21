"""Чтение config.toml."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field

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

    max_enabled: bool = False
    max_phone: str = ""
    max_session: str = "max.session"
    max_group: str = "MAX"
    max_roster_limit: int = 0
    max_contacts: bool = True

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
    typing_prime: bool = True
    typing_repeat: int = 10
    ack_on: str = "read"
    ack_timeout: int = 30
    catch_up: bool = True
    allow_delete: bool = True
    allow_delete_revoke: bool = True
    roster_limit: int = 0
    roster_reuse: bool = True          # отвечать «список не менялся» на 13/05
    alias_max_chars: int = 40
    topics_limit: int = 50
    favourites: tuple[str, ...] = ()
    background_groups: tuple[str, ...] = ()
    background_hours: int = 24
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
    log_max_level: str = "WARNING"
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
    tmm_photo_width: int = 176
    tmm_photo_height: int = 176
    tmm_photo_max_kb: int = 20
    tmm_video_seconds: int = 10
    tmm_voice_seconds: int = 60
    tmm_history_max: int = 200
    tmm_voice_kbps: float = 12.2
    # Профили телефонов: имя → {match, min_width, photo_width, ...}. Мост
    # выбирает профиль по сведениям, которые TeleMotoMax присылает при
    # входе, и берёт из него настройки вместо общих tmm_*.
    tmm_profiles: dict = field(default_factory=dict)

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
        tm = raw.get("telemotomax", {})
        tg = raw.get("telegram", {})
        mx = raw.get("max", {})
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
            max_enabled=bool(mx.get("enabled", cls.max_enabled)),
            max_phone=str(mx.get("phone", "")).strip(),
            max_session=_resolve(base, mx.get("session", cls.max_session)),
            max_group=str(mx.get("group", cls.max_group)).strip() or cls.max_group,
            max_roster_limit=int(mx.get("roster_limit", cls.max_roster_limit)),
            max_contacts=bool(mx.get("contacts", cls.max_contacts)),
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
            typing_prime=bool(br.get("typing_prime", cls.typing_prime)),
            typing_repeat=int(br.get("typing_repeat", cls.typing_repeat)),
            ack_on=str(br.get("ack_on", cls.ack_on)),
            ack_timeout=int(br.get("ack_timeout", cls.ack_timeout)),
            catch_up=bool(br.get("catch_up", True)),
            allow_delete=bool(br.get("allow_delete", True)),
            allow_delete_revoke=bool(br.get("allow_delete_revoke", True)),
            roster_limit=int(br.get("roster_limit", cls.roster_limit)),
            roster_reuse=bool(br.get("roster_reuse", True)),
            alias_max_chars=int(br.get("alias_max_chars", cls.alias_max_chars)),
            topics_limit=int(br.get("topics_limit", cls.topics_limit)),
            favourites=tuple(str(x).strip().lower() for x in br.get("favourites", [])),
            background_groups=tuple(str(x).strip().lower()
                                    for x in br.get("background_groups", [])),
            background_hours=int(br.get("background_hours", cls.background_hours)),
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
            log_max_level=str(lg.get("max_level", cls.log_max_level)).upper(),
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
            tmm_photo_width=int(tm.get("photo_width", cls.tmm_photo_width)),
            tmm_photo_height=int(tm.get("photo_height", cls.tmm_photo_height)),
            tmm_photo_max_kb=int(tm.get("photo_max_kb", cls.tmm_photo_max_kb)),
            tmm_video_seconds=int(tm.get("video_seconds", cls.tmm_video_seconds)),
            tmm_voice_seconds=int(tm.get("voice_seconds", cls.tmm_voice_seconds)),
            tmm_history_max=int(tm.get("history_max", cls.tmm_history_max)),
            tmm_voice_kbps=float(tm.get("voice_kbps", cls.tmm_voice_kbps)),
            tmm_profiles={str(k): dict(v) for k, v in (tm.get("profile") or {}).items()
                          if isinstance(v, dict)},
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


def describe(cfg: "Config") -> list[str]:
    """Что включено, а что нет — одной строкой на функцию, для журнала при
    старте. Иначе по журналу не понять, почему чего-то не происходит:
    выключено в настройках или не сработало."""
    def onoff(flag: bool, on: str = "включено", off: str = "выключено") -> str:
        return on if flag else off

    lines = [
        f"Telegram: сессия {cfg.tg_session}, группы по "
        + ("папкам" if cfg.grouping == "folders" else "типам чатов")
        + f", помечать прочитанным — {onoff(cfg.mark_read, 'да', 'нет')}, "
        + f"свои сообщения с других устройств — {onoff(cfg.mirror_outgoing, 'показывать', 'нет')}",
        "MAX: " + (f"включён, телефон {cfg.max_phone}, группа «{cfg.max_group}», "
                   f"контакты без переписки — {onoff(cfg.max_contacts, 'да', 'нет')}, "
                   f"roster_limit {cfg.max_roster_limit or 'без ограничения'}"
                   if cfg.max_enabled else "выключен ([max] enabled = false)"),
        f"контакт-лист: roster_limit {cfg.roster_limit or 'без ограничения'}, "
        + (f"фоновые группы: {', '.join(cfg.background_groups)} (давность {cfg.background_hours} ч)"
           if cfg.background_groups else "фоновых групп нет")
        + (f", избранные по названию: {', '.join(cfg.favourites)}" if cfg.favourites else ""),
        f"аватарки: {onoff(cfg.avatars, 'включены', 'выключены')}"
        + (f" ({cfg.avatar_size}×{cfg.avatar_size}, до {cfg.avatar_max_kb} КБ)" if cfg.avatars else
           " ([bridge] avatars = false)"),
        f"подтверждения доставки: {onoff(cfg.delivery_ack, 'канал 2, галочка по ' + cfg.ack_on, 'канал 1, без галочек')}"
        + f"; прививка «печатает» при входе — {onoff(cfg.typing_prime, 'да', 'нет')}"
        + f"; догрузка при старте — {onoff(cfg.catch_up, 'да', 'нет')}"
        + f"; удаление чатов с телефона — {onoff(cfg.allow_delete, 'да', 'нет')}",
        "фотографии: " + (f"раздача на {cfg.photos_host}:{cfg.photos_port}"
                          + (f", наружу как {cfg.photos_public_url}" if cfg.photos_public_url else "")
                          + (", с паролем" if cfg.photos_password else ", без пароля")
                          if cfg.photos_enabled else "выключены ([photos] enabled = false)"),
        "страница !render: " + (f"включена, {cfg.render_messages} сообщений, ffmpeg «{cfg.render_ffmpeg}», "
                                f"видео {cfg.render_video_codec} {cfg.render_video_kbps} кбит/с"
                                if cfg.render_enabled and cfg.photos_enabled else
                                "выключена" + ("" if cfg.render_enabled else " ([render] enabled = false)")),
        "загрузки: " + (f"каталог {cfg.downloads_dir}" + (", с паролем" if cfg.downloads_protected else "")
                        if cfg.downloads_dir else "раздела нет ([downloads] dir пуст)"),
        f"TeleMotoMax: снимки в чате {cfg.tmm_photo_width}×{cfg.tmm_photo_height}, "
        f"до {cfg.tmm_photo_max_kb} КБ; видео — первые {cfg.tmm_video_seconds} с "
        f"({cfg.render_video_codec}, {cfg.render_video_kbps} кбит/с)"
        if cfg.tmm_video_seconds > 0 else
        f"TeleMotoMax: снимки в чате {cfg.tmm_photo_width}×{cfg.tmm_photo_height}, "
        f"до {cfg.tmm_photo_max_kb} КБ; видео выключено",
        "контакт «Claude»: " + (f"включён, команда «{cfg.assistant_command}», инструменты "
                                f"{cfg.assistant_tools or 'никаких'}" if cfg.assistant_enabled
                                else "выключен ([assistant] enabled = false)"),
        f"журнал: {cfg.log_level}, telethon {cfg.log_telethon_level}, pymax {cfg.log_max_level}"
        + (f", файл {cfg.log_file}" if cfg.log_file else ", только консоль")
        + (", отсеянные на INFO" if cfg.log_filtered else ", отсеянные на DEBUG"),
    ]
    return lines


def _resolve(base: str, path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(base, path)
