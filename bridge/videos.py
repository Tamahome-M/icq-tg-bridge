"""Отдельная страница видео: скачивание и перекодирование начинаются по клику."""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import os
import re
import secrets
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Awaitable, Callable

from .render import Transcoder

log = logging.getLogger("video")
TOKEN = re.compile(r"[A-Za-z0-9_-]{16}\Z")
ROUTE = re.compile(r"/v/(?P<token>[A-Za-z0-9_-]{16})(?:/(?P<segment>\d+)"
                   r"(?:-v(?P<version>\d+)(?:-(?P<settings>[a-f0-9]{16}))?)?"
                   r"(?P<asset>\.3gp)?)?(?:/(?P<retry>retry))?\Z")
VIDEO_TAG = re.compile(r"\[(?:видео|видеосообщение)(?: ([^]\n]+))?\]")
MAX_PAGES = 500
MAX_SEGMENT = 10000
ENCODING_VERSION = 5


def link_text(text: str, url: str) -> str:
    """Короткая подпись ссылки; клиент прячет адрес и рисует [видео]."""
    tag = VIDEO_TAG.search(text)
    duration = f" {tag[1]}" if tag and tag[1] else ""
    if tag:
        text = (text[:tag.start()] + text[tag.end():]).strip()
    label = f"[видео]({url}){duration}"
    return label + ("\n" + text if text else "")


@dataclass(frozen=True)
class VideoSpec:
    # Изменение формата создаёт новую ссылку вместо старого файла из кеша.
    # Поле в конце сохраняет порядок позиционных параметров.
    ffmpeg: str = "ffmpeg"
    seconds: int = 60
    timeout: int = 120
    codec: str = "h263"
    kbps: int = 90
    fps: int = 15
    width: int = 176
    height: int = 144
    rotate: bool = False
    encoding_version: int = ENCODING_VERSION

    @property
    def cache_tag(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]

    def coder(self, directory: str) -> Transcoder:
        return Transcoder(self.ffmpeg, self.seconds, timeout=self.timeout,
                          workdir=directory, video_codec=self.codec,
                          video_kbps=self.kbps, video_fps=self.fps,
                          video_size=(self.width, self.height), video_rotate=self.rotate)


@dataclass
class VideoPage:
    token: str
    uin: int
    attach: str
    title: str
    made: float
    spec: VideoSpec
    duration: float | None = None
    states: dict[int, str] = field(default_factory=dict)
    jobs: dict[int, asyncio.Task] = field(default_factory=dict)


class VideoStore:
    def __init__(self, directory: str, fetch: Callable[[int, str], Awaitable[bytes | None]],
                 keep_hours: int = 48, max_source_bytes: int = 25 * 1024 * 1024):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.fetch = fetch
        self.keep_hours = max(1, keep_hours)
        self.max_source_bytes = max_source_bytes
        self.pages: dict[str, VideoPage] = {}
        self._keys: dict[tuple, str] = {}
        self._gate = asyncio.Semaphore(1)
        for path in self.directory.glob("*.json"):
            if not TOKEN.fullmatch(path.stem):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data["spec"].setdefault("encoding_version", 1)
                page = VideoPage(path.stem, int(data["uin"]), data["attach"], data["title"],
                                 float(data["made"]), VideoSpec(**data["spec"]), data.get("duration"))
                if page.spec.encoding_version < ENCODING_VERSION:
                    # Старые ссылки тоже должны получить новый формат: удаляем
                    # только готовые части, исходник остаётся для перекодировки.
                    for asset in self.directory.glob(f"{page.token}.*.3gp"):
                        asset.unlink()
                    page.spec = replace(page.spec, encoding_version=ENCODING_VERSION)
                    self._save(page)
                self.pages[page.token] = page
                self._keys[self._key(page.uin, page.attach, page.spec)] = page.token
            except (OSError, ValueError, KeyError, TypeError):
                log.warning("не смог прочитать страницу видео %s", path.name)
        self.cleanup()

    @staticmethod
    def _key(uin: int, attach: str, spec: VideoSpec) -> tuple:
        return uin, attach, spec

    def _save(self, page: VideoPage) -> None:
        data = {"uin": page.uin, "attach": page.attach, "title": page.title,
                "made": page.made, "spec": asdict(page.spec), "duration": page.duration}
        path = self.directory / f"{page.token}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    def update_spec(self, spec: VideoSpec) -> None:
        """Настройки телефона применяются и к уже присланным ссылкам."""
        self.cleanup()
        changed = 0
        for page in self.pages.values():
            if page.spec == spec:
                continue
            old_key = self._key(page.uin, page.attach, page.spec)
            if self._keys.get(old_key) == page.token:
                self._keys.pop(old_key)
            for task in page.jobs.values():
                task.cancel()
            page.jobs.clear()
            page.states.clear()
            for asset in self.directory.glob(f"{page.token}.*.3gp"):
                asset.unlink()
            page.spec = spec
            self._save(page)
            self._keys[self._key(page.uin, page.attach, spec)] = page.token
            changed += 1
        if changed:
            log.info("настройки видео с телефона применены к %d ссылкам: %d×%d, %d кбит/с",
                     changed, spec.width, spec.height, spec.kbps)

    def register(self, uin: int, attach: str, title: str, spec: VideoSpec) -> str:
        if not re.fullmatch(r"video:\d+", attach):
            return ""
        self.cleanup()
        key = self._key(uin, attach, spec)
        token = self._keys.get(key)
        if token in self.pages:
            return f"/v/{token}"
        while len(self.pages) >= MAX_PAGES:
            self._drop(min(self.pages.values(), key=lambda p: p.made))
        token = secrets.token_urlsafe(12)
        page = VideoPage(token, uin, attach, title, time.time(), spec)
        self._save(page)
        self.pages[token] = page
        self._keys[key] = token
        return f"/v/{token}"

    def _drop(self, page: VideoPage) -> None:
        self.pages.pop(page.token, None)
        self._keys.pop(self._key(page.uin, page.attach, page.spec), None)
        for task in page.jobs.values():
            task.cancel()
        for path in self.directory.glob(f"{page.token}.*"):
            try:
                path.unlink()
            except OSError:
                pass

    def cleanup(self) -> None:
        deadline = time.time() - self.keep_hours * 3600
        for page in list(self.pages.values()):
            if page.made < deadline:
                self._drop(page)

    async def stop(self) -> None:
        tasks = [task for page in self.pages.values() for task in page.jobs.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def resolve(self, path: str, start: bool = True, as_path: bool = False) -> tuple[bytes | Path, str, str] | None:
        match = ROUTE.fullmatch(path)
        if match is None:
            return None
        self.cleanup()
        page = self.pages.get(match["token"])
        segment = int(match["segment"] or 0)
        if page is None or segment > MAX_SEGMENT or (segment and page.spec.seconds <= 0):
            return None
        if match["version"] and (not match["asset"] or int(match["version"]) != page.spec.encoding_version):
            return None
        if match["settings"] and match["settings"] != page.spec.cache_tag:
            return None
        asset = self.directory / f"{page.token}.{segment}.3gp"
        if match["asset"]:
            if not asset.is_file():
                return None
            return (asset if as_path else asset.read_bytes()), "video/3gpp", "вложение"
        state = "ready" if asset.is_file() else page.states.get(segment, "new")
        if page.duration is not None and segment * page.spec.seconds >= page.duration:
            state = "end"
        if match["retry"] and state == "error":
            state = "new"
        if start and state == "new":
            page.states[segment] = "pending"
            page.jobs[segment] = asyncio.create_task(self._prepare(page, segment))
            state = "pending"
        body = self._html(page, segment, state)
        return body, "application/vnd.wap.xhtml+xml; charset=utf-8", "страница"

    async def _prepare(self, page: VideoPage, segment: int) -> None:
        try:
            async with self._gate:
                if page.jobs.get(segment) is not asyncio.current_task():
                    return
                spec = page.spec
                coder = spec.coder(str(self.directory))
                if not coder.available:
                    raise ValueError("ffmpeg недоступен")
                source = self.directory / f"{page.token}.source"
                if source.is_file():
                    raw = source.read_bytes()
                else:
                    raw = await asyncio.wait_for(self.fetch(page.uin, page.attach),
                                                 timeout=max(1, spec.timeout))
                    if not raw or len(raw) > self.max_source_bytes:
                        raise ValueError("исходное видео не доступно или слишком велико")
                    source.write_bytes(raw)
                if page.duration is None:
                    page.duration = await coder.probe_duration(raw)
                    self._save(page)
                start = segment * spec.seconds
                if page.duration is not None and start >= page.duration:
                    page.states[segment] = "end"
                    return
                if coder.video_rotate:
                    size = await coder.probe_size(raw)
                    coder.video_rotate = bool(size and size[0] > size[1])
                data = await coder.convert(raw, "video", start=start)
                if page.jobs.get(segment) is not asyncio.current_task():
                    return
                if not data:
                    raise ValueError("видео не перекодировалось")
                (self.directory / f"{page.token}.{segment}.3gp").write_bytes(data)
                page.states[segment] = "ready"
                log.info("видео %s, часть %d готова: %d КБ", page.attach, segment + 1, len(data) // 1024)
        except asyncio.CancelledError:
            if self.pages.get(page.token) is page and page.jobs.get(segment) is asyncio.current_task():
                page.states[segment] = "new"
            raise
        except Exception as exc:
            if page.jobs.get(segment) is asyncio.current_task():
                page.states[segment] = "error"
                log.warning("не удалось подготовить %s: %s", page.attach, exc)
        finally:
            if page.jobs.get(segment) is asyncio.current_task():
                page.jobs.pop(segment, None)

    def _html(self, page: VideoPage, segment: int, state: str) -> bytes:
        path = f"/v/{page.token}/{segment}"
        rows = [f"<p><b>{html.escape(page.title)}</b></p>"]
        if page.spec.seconds > 0 and state != "end":
            start = segment * page.spec.seconds
            finish = min(start + page.spec.seconds, int(page.duration)) if page.duration else start + page.spec.seconds
            rows.append(f"<p>Видео: {start // 60}:{start % 60:02d}–{finish // 60}:{finish % 60:02d}</p>")
        if state == "ready":
            size = (self.directory / f"{page.token}.{segment}.3gp").stat().st_size
            # Новая версия формата получает новый URL: браузер не должен
            # брать прежний 3GP из суточного HTTP-кеша после перекодировки.
            rows.append(f'<p><a href="{path}-v{page.spec.encoding_version}-{page.spec.cache_tag}.3gp">Смотреть видео</a> ({(size + 1023) // 1024} КБ)</p>')
            if page.spec.seconds > 0 and (page.duration is None or (segment + 1) * page.spec.seconds < page.duration):
                rows.append(f'<p><a href="/v/{page.token}/{segment + 1}">Дальше</a></p>')
        elif state == "end":
            rows.append("<p>Конец видео.</p>")
        elif state == "error":
            rows.append(f'<p>Не удалось подготовить видео.</p><p><a href="{path}/retry">Попробовать снова</a></p>')
        else:
            rows.append(f'<p>Видео готовится…</p><p><a href="{path}">Обновить</a></p>')
        if segment:
            rows.append(f'<p><a href="/v/{page.token}/{segment - 1}">Назад</a></p>')
        refresh = '<meta http-equiv="refresh" content="3"/>' if state in ("pending", "new") else ""
        return ('<?xml version="1.0" encoding="utf-8"?>\n'
                '<!DOCTYPE html PUBLIC "-//WAPFORUM//DTD XHTML Mobile 1.0//EN" '
                '"http://www.wapforum.org/DTD/xhtml-mobile10.dtd">\n'
                '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
                '<meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>'
                f'<title>Видео</title>{refresh}</head><body>' + "".join(rows) +
                '</body></html>\n').encode("utf-8")
