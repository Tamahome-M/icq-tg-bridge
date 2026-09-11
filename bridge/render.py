"""Страница переписки для встроенного браузера телефона.

Команда !render собирает последние сообщения чата в одну страницу: текст
как текст, фотографии — ужатыми, видео — в 3GP, голосовые — в AMR. Всё это
живёт по одной ссылке с ограниченным сроком, после которого и файлы, и сама
страница перестают отдаваться.

Вид сделан похожим на Telegram настолько, насколько понимает браузер вроде
того, что стоит в Motorola V3: XHTML Mobile Profile, таблицы вместо блоков,
цвета атрибутами и простейшим CSS — всё, чего он не поймёт, просто
пропускается, и страница остаётся читаемой.
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from . import photos

log = logging.getLogger("render")

TOKEN_CHARS = 10
# Что и как отдаём браузеру.
MIME = {
    "jpg": "image/jpeg",
    "3gp": "video/3gpp",
    "amr": "audio/amr",
    "html": "application/vnd.wap.xhtml+xml",
}

# Цвета Telegram: шапка, фон, свои и чужие сообщения.
COLOR_HEADER = "#527da3"
COLOR_PAGE = "#e6ebee"
COLOR_THEIRS = "#ffffff"
COLOR_MINE = "#effdde"
COLOR_NAME = "#3a76a1"
COLOR_TIME = "#8397a8"

# H.263 понимает только стандартные размеры кадра; QCIF — то, что подходит
# экрану такого телефона и что точно проигрывает его плеер.
VIDEO_WIDTH = 176
VIDEO_HEIGHT = 144


@dataclass
class Item:
    """Одно сообщение для страницы."""
    when: str = ""
    who: str = ""
    text: str = ""
    mine: bool = False
    kind: str = ""             # photo, video, voice, audio — или пусто
    raw: bytes | None = None
    # Загрузчик вложения: данные тянутся, когда до них дошла очередь, и
    # отпускаются сразу после перекодирования — иначе страница на двадцать
    # видео держала бы в памяти сотни мегабайт.
    fetch: Callable[[], Awaitable[bytes | None]] | None = None
    seconds: int = 0
    name: str = ""             # имя файла, если оно есть


@dataclass
class Asset:
    token: str
    path: str
    ext: str
    size: int

    @property
    def mime(self) -> str:
        return MIME.get(self.ext, "application/octet-stream")


@dataclass
class Page:
    token: str
    body: bytes
    made: float
    assets: list[str] = field(default_factory=list)


def _token() -> str:
    """Короткий непредсказуемый токен: ссылка живёт недолго, но угадать её нельзя."""
    alphabet = "abcdefghijkmnopqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(TOKEN_CHARS))


def _hms(seconds: int) -> str:
    if seconds <= 0:
        return ""
    return f"{seconds // 60}:{seconds % 60:02d}"


class Transcoder:
    """Перекодирование через ffmpeg. Без него страница всё равно собирается —
    просто вместо видео и голосовых в ней остаются пометки."""

    def __init__(self, ffmpeg: str = "ffmpeg", video_seconds: int = 60,
                 audio_seconds: int = 300, timeout: int = 120,
                 workdir: str = "/tmp"):
        self.ffmpeg = ffmpeg
        self.video_seconds = video_seconds
        self.audio_seconds = audio_seconds
        self.timeout = timeout
        self.workdir = workdir

    @property
    def available(self) -> bool:
        from shutil import which
        return bool(self.ffmpeg) and which(self.ffmpeg) is not None

    def video_args(self, src: str, dst: str) -> list[str]:
        # Кадр дополняем полями до ровного QCIF: H.263 других размеров не знает.
        scale = (f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,"
                 f"pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2")
        return [self.ffmpeg, "-y", "-loglevel", "error", "-i", src,
                "-t", str(self.video_seconds), "-vf", scale, "-r", "12",
                "-c:v", "h263", "-b:v", "128k",
                "-c:a", "libopencore_amrnb", "-ar", "8000", "-ac", "1", "-b:a", "12.2k",
                "-f", "3gp", dst]

    def audio_args(self, src: str, dst: str) -> list[str]:
        return [self.ffmpeg, "-y", "-loglevel", "error", "-i", src,
                "-t", str(self.audio_seconds),
                "-c:a", "libopencore_amrnb", "-ar", "8000", "-ac", "1", "-b:a", "12.2k",
                "-f", "amr", dst]

    async def convert(self, raw: bytes, kind: str) -> bytes | None:
        """Перегоняет видео в 3GP, звук — в AMR."""
        if not raw or not self.available:
            if raw and not self.available:
                log.warning("ffmpeg %r не найден — %s не перекодирую", self.ffmpeg, kind)
            return None

        ext = "3gp" if kind == "video" else "amr"
        stamp = _token()
        src = os.path.join(self.workdir, f"in-{stamp}")
        dst = os.path.join(self.workdir, f"out-{stamp}.{ext}")
        args = self.video_args(src, dst) if kind == "video" else self.audio_args(src, dst)
        try:
            with open(src, "wb") as fh:
                fh.write(raw)
            proc = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE)
            try:
                _, err = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()          # иначе останется зомби
                log.warning("ffmpeg не уложился в %d с — бросаю", self.timeout)
                return None
            if proc.returncode != 0:
                log.warning("ffmpeg вернул %s: %s", proc.returncode,
                            (err or b"").decode("utf-8", "replace")[:200])
                return None
            with open(dst, "rb") as fh:
                return fh.read() or None
        except Exception as exc:
            log.warning("не смог перекодировать %s: %s", kind, exc)
            return None
        finally:
            for path in (src, dst):
                try:
                    os.unlink(path)
                except OSError:
                    pass


class RenderStore:
    """Готовые страницы и файлы к ним. Живут заданное время, потом пропадают."""

    def __init__(self, directory: str, transcoder: Transcoder,
                 ttl_minutes: int = 30, width: int = photos.DEFAULT_WIDTH,
                 height: int = photos.DEFAULT_HEIGHT,
                 photo_max_bytes: int = photos.DEFAULT_MAX_BYTES,
                 encoding: str = "utf-8"):
        self.directory = directory
        self.transcoder = transcoder
        self.ttl = ttl_minutes * 60
        self.width = width
        self.height = height
        self.photo_max_bytes = photo_max_bytes
        self.encoding = encoding
        self._pages: dict[str, Page] = {}
        self._assets: dict[str, Asset] = {}
        os.makedirs(directory, exist_ok=True)

    # --- хранение -------------------------------------------------------

    def alive(self, made: float) -> bool:
        return self.ttl <= 0 or time.time() - made < self.ttl

    def put_asset(self, data: bytes, ext: str) -> Asset:
        token = _token()
        path = os.path.join(self.directory, f"{token}.{ext}")
        with open(path, "wb") as fh:
            fh.write(data)
        asset = Asset(token, path, ext, len(data))
        self._assets[token] = asset
        return asset

    def asset_for(self, token: str) -> Asset | None:
        """Файл по токену из ссылки — если срок ещё не вышел."""
        asset = self._assets.get(token or "")
        if asset is None:
            return None
        page = self._page_of(token)
        if page is not None and not self.alive(page.made):
            return None
        return asset if os.path.isfile(asset.path) else None

    def page_for(self, token: str) -> bytes | None:
        page = self._pages.get(token or "")
        if page is None or not self.alive(page.made):
            return None
        return page.body

    def _page_of(self, asset_token: str) -> Page | None:
        for page in self._pages.values():
            if asset_token in page.assets:
                return page
        return None

    def cleanup(self) -> int:
        """Убирает просроченное — и из памяти, и с диска.

        Страницы живут в памяти, поэтому после перезапуска файлы прошлых
        страниц (и временные файлы недоделанной перекодировки) остались бы
        навсегда: их убираем по возрасту файла.
        """
        gone = 0
        for token, page in list(self._pages.items()):
            if self.alive(page.made):
                continue
            for asset_token in page.assets:
                asset = self._assets.pop(asset_token, None)
                if asset is None:
                    continue
                try:
                    os.unlink(asset.path)
                    gone += 1
                except OSError:
                    pass
            del self._pages[token]

        if self.ttl > 0:
            deadline = time.time() - self.ttl
            for name in os.listdir(self.directory):
                if name.split(".", 1)[0] in self._assets:
                    continue
                path = os.path.join(self.directory, name)
                try:
                    if os.path.isfile(path) and os.path.getmtime(path) < deadline:
                        os.unlink(path)
                        gone += 1
                except OSError:
                    continue
        return gone

    # --- сборка страницы ------------------------------------------------

    async def build(self, title: str, items: list[Item],
                    progress: Callable[[int, int], Awaitable[None]] | None = None) -> Page | None:
        """Перекодирует вложения и собирает страницу. None — собирать нечего.

        progress(готово, всего) зовётся после каждого вложения — на медленной
        связи минуты тишины пугают, и есть чем их заполнить.
        """
        if not items:
            return None
        token = _token()
        assets: list[str] = []
        rows: list[str] = []
        total = sum(1 for item in items if item.kind)
        done = 0
        for item in items:
            row, used = await self._row(item)
            rows.append(row)
            assets.extend(used)
            if item.kind:
                done += 1
                if progress is not None:
                    await progress(done, total)

        body = self._document(title, rows).encode(self.encoding, "xmlcharrefreplace")
        page = Page(token, body, time.time(), assets)
        self._pages[token] = page
        log.info("страница %s: %d сообщений, %d вложений, %d КБ",
                 token, len(items), len(assets), len(body) // 1024)
        return page

    async def _row(self, item: Item) -> tuple[str, list[str]]:
        """Одно сообщение: пузырь с именем, временем, текстом и вложением."""
        used: list[str] = []
        inner: list[str] = []

        if item.who:
            inner.append(f'<div class="who">{html.escape(item.who)}</div>')

        media, token = await self._media(item)
        if token:
            used.append(token)
        if media:
            inner.append(media)
        if item.text:
            text = html.escape(item.text).replace("\n", "<br/>")
            inner.append(f'<div class="txt">{text}</div>')
        if not media and not item.text:
            inner.append('<div class="txt">[пусто]</div>')
        if item.when:
            inner.append(f'<div class="time">{html.escape(item.when)}</div>')

        colour = COLOR_MINE if item.mine else COLOR_THEIRS
        align = "right" if item.mine else "left"
        # Обёртка с align, а не плавающая таблица: старый браузер иначе может
        # поставить два пузыря в ряд. Перенос в конце заменяет отступ тем,
        # кто не понял CSS.
        bubble = (f'<div align="{align}" class="msg">'
                  f'<table width="94%" cellpadding="3" cellspacing="0" '
                  f'bgcolor="{colour}"><tr><td bgcolor="{colour}" align="left">'
                  + "".join(inner) + "</td></tr></table></div><br/>")
        return bubble, used

    async def _raw(self, item: Item) -> bytes:
        if item.raw is not None:
            return item.raw
        if item.fetch is None:
            return b""
        try:
            return await item.fetch() or b""
        except Exception as exc:
            log.warning("не смог скачать вложение: %s", exc)
            return b""

    async def _media(self, item: Item) -> tuple[str, str]:
        """Вложение: картинка прямо в странице, видео и звук — ссылкой."""
        if not item.kind:
            return "", ""
        raw = await self._raw(item)

        if item.kind == "photo":
            got = photos.shrink(raw, self.width, self.height, self.photo_max_bytes)
            if got is None:
                return '<div class="txt">[фото не открылось]</div>', ""
            data, width, height = got
            asset = self.put_asset(data, "jpg")
            return (f'<div><img src="/m/{asset.token}.jpg" width="{width}" '
                    f'height="{height}" alt="фото"/></div>'), asset.token

        if item.kind in ("video", "voice", "audio"):
            data = await self.transcoder.convert(raw, item.kind)
            del raw                    # исходник больше не нужен
            if not data:
                what = {"video": "видео", "voice": "голосовое",
                        "audio": "аудио"}[item.kind]
                return f'<div class="txt">[{what} перекодировать не вышло]</div>', ""
            ext = "3gp" if item.kind == "video" else "amr"
            asset = self.put_asset(data, ext)
            label = {"video": "видео", "voice": "голосовое", "audio": "аудио"}[item.kind]
            length = _hms(item.seconds)
            note = f"{label} {length}".strip()
            size = f"{asset.size // 1024 or 1} КБ"
            return (f'<div class="file"><a href="/m/{asset.token}.{ext}">'
                    f'{html.escape(note)}, {size}</a></div>'), asset.token

        return "", ""

    def _document(self, title: str, rows: list[str]) -> str:
        head = (
            '<?xml version="1.0" encoding="' + self.encoding + '"?>\n'
            '<!DOCTYPE html PUBLIC "-//WAPFORUM//DTD XHTML Mobile 1.0//EN" '
            '"http://www.wapforum.org/DTD/xhtml-mobile10.dtd">\n'
            '<html xmlns="http://www.w3.org/1999/xhtml"><head>\n'
            f'<meta http-equiv="Content-Type" content="text/html; charset={self.encoding}"/>\n'
            f'<title>{html.escape(title)}</title>\n'
            "<style type=\"text/css\">\n"
            f"body {{ background-color: {COLOR_PAGE}; color: #000000; "
            "font-size: small; margin: 0px; }\n"
            f".hdr {{ background-color: {COLOR_HEADER}; color: #ffffff; "
            "font-weight: bold; padding: 3px; }\n"
            f".who {{ color: {COLOR_NAME}; font-weight: bold; }}\n"
            f".time {{ color: {COLOR_TIME}; text-align: right; }}\n"
            ".txt { color: #000000; }\n"
            ".msg { margin-bottom: 3px; }\n"
            "img { border: 0px; }\n"
            "</style>\n</head>\n<body>\n"
            f'<div class="hdr"><table width="100%" cellpadding="3" cellspacing="0" '
            f'bgcolor="{COLOR_HEADER}"><tr><td bgcolor="{COLOR_HEADER}">'
            f'<b>{html.escape(title)}</b></td></tr></table></div>\n'
        )
        return head + "\n".join(rows) + "\n</body></html>\n"
