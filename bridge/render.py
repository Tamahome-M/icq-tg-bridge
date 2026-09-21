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
# экрану такого телефона и что точно проигрывает его плеер. Плеер RAZR V3
# декодирует H.263 Baseline Level 10 и MPEG-4 Simple Profile Level 0: обоим
# положено не больше 64 кбит/с и 15 кадров в секунду — выше плеер файл
# просто не откроет.
VIDEO_WIDTH = 176
VIDEO_HEIGHT = 144
# Кодировщики каждой сборки ffmpeg — спрашиваем по одному разу на путь.
_ENCODERS: dict[str, set[str]] = {}

# Приметы звуковых форматов, которые ffmpeg опознаёт сам.
AUDIO_MAGIC = (b"#!AMR", b"RIFF", b"OggS", b"ID3", b"fLaC", b"\xff\xfb", b"\xff\xf1")


def _known_audio(raw: bytes) -> bool:
    """Похоже ли начало записи на формат, который ffmpeg опознает сам."""
    if len(raw) >= 12 and raw[4:8] == b"ftyp":
        return True                       # 3GP, MP4 и родня
    return any(raw.startswith(magic) for magic in AUDIO_MAGIC)


# Режимы AMR-NB: других кодек не знает, поэтому заданный битрейт
# округляем к ближайшему из них.
AMR_RATES = (4.75, 5.15, 5.9, 6.7, 7.4, 7.95, 10.2, 12.2)


def amr_rate(kbps: float) -> float:
    """Ближайший режим AMR-NB к заданному битрейту."""
    return min(AMR_RATES, key=lambda rate: abs(rate - kbps))


VIDEO_KBPS = 64
VIDEO_FPS = 15
VIDEO_CODECS = {
    "h263": ["-c:v", "h263"],
    # Simple Profile, Level 0; тег mp4v — как пишут телефоны сами.
    "mpeg4": ["-c:v", "mpeg4", "-profile:v", "0", "-level", "8", "-vtag", "mp4v"],
}


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
    # Миниатюра видео из Telegram: показывается как фото, под ней ссылка.
    thumb: Callable[[], Awaitable[bytes | None]] | None = None
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
    path: str = ""             # адрес страницы — по формату из настроек
    title: str = ""
    messages: int = 0
    part: int = 1              # номер части; длинная переписка режется на части
    parts: int = 1


# Транслитерация для адреса: кириллица в URL на телефоне — мучение.
_TRANSLIT = dict(zip(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "j", "k", "l", "m", "n", "o", "p",
     "r", "s", "t", "u", "f", "h", "c", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


def slug(title: str, limit: int = 16) -> str:
    """Название чата латиницей и цифрами: «Дача 2026» → dacha-2026."""
    out = []
    for ch in title.lower():
        if ch in _TRANSLIT:
            out.append(_TRANSLIT[ch])
        elif ch.isascii() and ch.isalnum():
            out.append(ch)
        else:
            out.append("-")
    text = "".join(out).strip("-")
    while "--" in text:
        text = text.replace("--", "-")
    return text[:limit].strip("-") or "chat"


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
                 workdir: str = "/tmp", video_codec: str = "h263",
                 video_kbps: int = VIDEO_KBPS, video_fps: int = VIDEO_FPS,
                 voice_kbps: float = 12.2, video_size: tuple[int, int] = (VIDEO_WIDTH, VIDEO_HEIGHT),
                 video_rotate: bool = False):
        self.ffmpeg = ffmpeg
        self.video_seconds = video_seconds
        self.audio_seconds = audio_seconds
        self.timeout = timeout
        self.workdir = workdir
        self.video_codec = video_codec if video_codec in VIDEO_CODECS else "h263"
        self.video_kbps = video_kbps
        self.video_fps = video_fps
        self.voice_kbps = amr_rate(voice_kbps)
        self.video_size = (max(16, int(video_size[0])), max(16, int(video_size[1])))
        self.video_rotate = bool(video_rotate)

    @property
    def available(self) -> bool:
        from shutil import which
        return bool(self.ffmpeg) and which(self.ffmpeg) is not None

    async def encoders(self) -> set[str]:
        """Кодировщики этой сборки ffmpeg — спрашиваем один раз на путь.

        Сборки разнятся: без USE=opus в ffmpeg нет libopus, и голосовое,
        которое мы честно записали, некуда было бы уложить."""
        known = _ENCODERS.get(self.ffmpeg)
        if known is not None:
            return known
        names: set[str] = set()
        try:
            proc = await asyncio.create_subprocess_exec(
                self.ffmpeg, "-hide_banner", "-encoders",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
            for line in out.decode("utf-8", "replace").splitlines():
                parts = line.split()
                # Строка вида « A..... libopus  libopus Opus»
                if len(parts) >= 2 and len(parts[0]) == 6 and parts[0][0] in "VAS":
                    names.add(parts[1])
        except Exception as exc:
            log.warning("не смог спросить у ffmpeg список кодировщиков: %s", exc)
        _ENCODERS[self.ffmpeg] = names
        return names

    async def ogg_codec(self) -> str | None:
        """Чем кодировать голосовое: opus (как ждут Telegram и MAX) или,
        если его в сборке нет, vorbis — он хотя бы проиграется."""
        names = await self.encoders()
        if not names:
            return "libopus"           # список не дался — пробуем как раньше
        for codec in ("libopus", "opus", "libvorbis", "vorbis"):
            if codec in names:
                return codec
        return None

    async def probe_size(self, raw: bytes) -> tuple[int, int] | None:
        """Видимый размер кадра исходника: ширина и высота с учётом тега
        поворота (телефонные ролики часто сняты «боком» и помечены
        rotate=90 — на экране они вертикальные)."""
        if not raw:
            return None
        probe = os.path.join(os.path.dirname(self.ffmpeg) or "", "ffprobe") \
            if os.path.sep in self.ffmpeg else "ffprobe"
        stamp = _token()
        src = os.path.join(self.workdir, f"probe-{stamp}")
        try:
            os.makedirs(self.workdir, exist_ok=True)
            with open(src, "wb") as fh:
                fh.write(raw)
            proc = await asyncio.create_subprocess_exec(
                probe, "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height:stream_tags=rotate:stream_side_data=rotation",
                "-of", "default=noprint_wrappers=1", src,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
            width = height = 0
            rotation = 0
            for line in out.decode("utf-8", "replace").splitlines():
                key, _, value = line.partition("=")
                value = value.strip()
                try:
                    if key == "width":
                        width = int(value)
                    elif key == "height":
                        height = int(value)
                    elif key in ("TAG:rotate", "rotation"):
                        rotation = int(float(value))
                except ValueError:
                    pass
            if not width or not height:
                return None
            if abs(rotation) % 180 == 90:
                width, height = height, width
            return width, height
        except Exception as exc:
            log.warning("не смог узнать размер ролика: %s", exc)
            return None
        finally:
            try:
                os.unlink(src)
            except OSError:
                pass

    def video_args(self, src: str, dst: str) -> list[str]:
        width, height = self.video_size
        codec = self.video_codec
        # Кадр «боком»: ролик поворачивается на 90°, и на вертикальном экране
        # телефона его смотрят, повернув сам телефон, — картинка во всю
        # ширину, а не полоска посередине. Размер кадра при этом тоже
        # становится вертикальным.
        rotate = "transpose=1," if self.video_rotate else ""
        if self.video_rotate:
            width, height = height, width
        if codec == "h263" and (width, height) not in ((176, 144), (352, 288), (128, 96)):
            # H.263 знает только стандартные кадры; повёрнутый или иной
            # размер — это уже MPEG-4.
            codec = "mpeg4"
        codec_args = list(VIDEO_CODECS[codec])
        if codec == "mpeg4" and width * height > 176 * 144:
            # Simple Profile Level 0 — это QCIF и не больше: кадр 320×240 с
            # таким заголовком плеер телефона отвергал («MediaException:
            # convert»). До CIF (352×288) — Level 3.
            codec_args = ["-c:v", "mpeg4", "-profile:v", "0", "-level", "3", "-vtag", "mp4v"]
        # Кадр дополняем полями до ровного размера: плеер телефона ждёт
        # именно объявленный размер.
        scale = (f"{rotate}scale={width}:{height}:force_original_aspect_ratio=decrease,"
                 f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2")
        kbps = f"{self.video_kbps}k"
        return ([self.ffmpeg, "-y", "-loglevel", "error", "-i", src,
                 "-t", str(self.video_seconds), "-vf", scale, "-r", str(self.video_fps)]
                + codec_args
                # Ровный битрейт под потолок уровня: без maxrate кодер даёт
                # пики выше, чем плеер готов принять.
                + ["-b:v", kbps, "-maxrate", kbps, "-bufsize", kbps,
                   "-c:a", "libopencore_amrnb", "-ar", "8000", "-ac", "1", "-b:a", "12.2k",
                   # moov в начале: старый плеер не станет искать его в конце файла.
                   "-movflags", "+faststart", "-f", "3gp", dst])

    def audio_args(self, src: str, dst: str) -> list[str]:
        return [self.ffmpeg, "-y", "-loglevel", "error", "-i", src,
                "-t", str(self.audio_seconds),
                "-c:a", "libopencore_amrnb", "-ar", "8000", "-ac", "1", "-b:a", "12.2k",
                "-f", "amr", dst]

    def ogg_args(self, src: str, dst: str, codec: str = "libopus") -> list[str]:
        """OGG для Telegram и MAX: голосовое там именно в нём. Кодек берём
        какой есть — opus предпочтительнее, vorbis тоже принимается."""
        rate = ["-ar", "48000", "-ac", "1"]
        if codec in ("libopus", "opus"):
            quality = ["-b:a", "24k"]
        else:
            quality = ["-q:a", "3"]
        extra = ["-strict", "-2"] if codec == "opus" else []
        return ([self.ffmpeg, "-y", "-loglevel", "error", "-i", src,
                 "-t", str(self.audio_seconds), "-vn", "-c:a", codec]
                + rate + quality + extra + ["-f", "ogg", dst])

    def note_args(self, src: str, dst: str, vcodec: str) -> list[str]:
        """Кружок для Telegram и MAX: квадрат, MP4, H.264 (libx264) и AAC.
        Кадр режется до квадрата по меньшей стороне и ужимается до 384."""
        vf = "crop='min(iw,ih)':'min(iw,ih)',scale=384:384,fps=24"
        video = ([vcodec, "-preset", "veryfast", "-profile:v", "baseline",
                  "-pix_fmt", "yuv420p"] if vcodec == "libx264" else [vcodec])
        return ([self.ffmpeg, "-y", "-loglevel", "error", "-i", src,
                 "-t", str(self.video_seconds), "-vf", vf, "-c:v"] + video
                + ["-b:v", "400k", "-c:a", "aac", "-ar", "44100", "-ac", "1", "-b:a", "64k",
                   "-movflags", "+faststart", "-f", "mp4", dst])

    async def to_note(self, raw: bytes) -> bytes | None:
        """Запись с камеры телефона — в квадратный MP4/H.264 для кружка.
        Без libx264 в ffmpeg кружка не будет: Telegram показывает круглым
        только H.264."""
        if not raw:
            return None
        if "libx264" not in await self.encoders():
            log.warning("в ffmpeg нет libx264 — кружок отправлю обычным видео")
            return None
        return await self.convert(raw, "note", "libx264")

    async def to_ogg(self, raw: bytes) -> bytes | None:
        """Запись с телефона — в OGG для Telegram и MAX.

        Телефон отдаёт то, что записал сам (обычно AMR, иногда 3GP и без
        всякой приметы в начале). Если ffmpeg не опознал поток, пробуем ещё
        раз, приписав заголовок AMR: без него разбирать голый AMR он не
        берётся."""
        if not raw:
            return None
        log.info("голосовое с телефона: %d байт, начало %s",
                 len(raw), raw[:8].hex())
        codec = await self.ogg_codec()
        if codec is None:
            log.warning("в ffmpeg %r нет ни libopus, ни libvorbis — голосовое "
                        "уйдёт файлом; пересоберите ffmpeg с поддержкой opus",
                        self.ffmpeg)
            return None
        out = await self.convert(raw, "ogg", codec=codec)
        if out is None and not _known_audio(raw):
            log.info("ffmpeg не опознал запись — пробую ещё раз как голый AMR")
            out = await self.convert(b"#!AMR\n" + raw, "ogg", codec=codec)
        if out is not None and codec not in ("libopus", "opus"):
            log.warning("голосовое закодировано в %s: без libopus Telegram "
                        "может показать его не голосовым, а звуковым файлом", codec)
        return out

    def voice_args(self, src: str, dst: str) -> list[str]:
        """AMR в контейнере 3GP: голый .amr плеер телефона не опознаёт,
        а audio/3gpp он объявляет сам.

        Битрейт AMR-NB выбирается не любой: кодек знает ровно восемь
        режимов (см. AMR_RATES). 12.2 кбит/с — самый «жирный», 4.75 —
        самый экономный; речь разборчива и на нём, а качать по GPRS
        вдвое-втрое меньше.
        """
        return [self.ffmpeg, "-y", "-loglevel", "error", "-i", src,
                "-t", str(self.audio_seconds), "-vn",
                "-c:a", "libopencore_amrnb", "-ar", "8000", "-ac", "1",
                "-b:a", f"{self.voice_kbps}k",
                "-movflags", "+faststart", "-f", "3gp", dst]

    async def convert(self, raw: bytes, kind: str, codec: str = "libopus") -> bytes | None:
        """Перегоняет видео в 3GP, звук — в AMR."""
        if not raw or not self.available:
            if raw and not self.available:
                log.warning("ffmpeg %r не найден — %s не перекодирую", self.ffmpeg, kind)
            return None

        ext = {"audio": "amr", "ogg": "ogg", "note": "mp4"}.get(kind, "3gp")
        stamp = _token()
        src = os.path.join(self.workdir, f"in-{stamp}")
        dst = os.path.join(self.workdir, f"out-{stamp}.{ext}")
        if kind == "video":
            args = self.video_args(src, dst)
        elif kind == "voice":
            args = self.voice_args(src, dst)
        elif kind == "ogg":
            args = self.ogg_args(src, dst, codec)
        elif kind == "note":
            args = self.note_args(src, dst, codec)
        else:
            args = self.audio_args(src, dst)
        try:
            os.makedirs(self.workdir, exist_ok=True)
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
                 encoding: str = "utf-8", path_format: str = "/r/{n}",
                 next_seq: Callable[[], int] | None = None, index: bool = False,
                 page_max_bytes: int = 6 * 1024):
        self.directory = directory
        self.transcoder = transcoder
        self.ttl = ttl_minutes * 60
        self.width = width
        self.height = height
        self.photo_max_bytes = photo_max_bytes
        self.encoding = encoding
        # Адрес страницы: {n} — сквозной номер, {chat} — название латиницей,
        # {token} — случайный. Номер короткий и набирается с телефона, зато
        # угадывается — на этот случай у сервера есть пароль.
        self.path_format = path_format if path_format.startswith("/") else "/" + path_format
        self._next_seq = next_seq or self._local_seq
        self._seq = 0
        self.index_enabled = index
        # Потолок одной страницы: браузер телефона (и WAP-шлюз за него)
        # отвергает ответы больше своего предела — у Openwave на V3 это около
        # 10 КБ, с запасом берём меньше. Что не влезло — на следующей части.
        self.page_max_bytes = page_max_bytes
        self._pages: dict[str, Page] = {}
        self._assets: dict[str, Asset] = {}
        self._paths: dict[str, str] = {}      # адрес -> токен страницы
        os.makedirs(directory, exist_ok=True)

    def _local_seq(self) -> int:
        self._seq += 1
        return self._seq

    def make_path(self, title: str, token: str) -> str:
        path = self.path_format.format(n=self._next_seq(), chat=slug(title), token=token)
        # Занятый адрес (например, {chat} без номера) переходит к новой странице:
        # старая остаётся доступной только по токену.
        return path

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

    def page_by_path(self, path: str) -> bytes | None:
        """Страница по её адресу из ссылки — или по токену, как раньше."""
        path = path.rstrip("/") or "/"
        token = self._paths.get(path)
        if token is None and path.startswith("/r/"):
            token = path[len("/r/"):]
        return self.page_for(token or "")

    def is_index(self, path: str) -> bool:
        return self.index_enabled and path.rstrip("/") in ("/r", "/r/index")

    def live_pages(self) -> list[Page]:
        pages = [p for p in self._pages.values() if self.alive(p.made) and p.part == 1]
        return sorted(pages, key=lambda p: -p.made)

    def index_html(self) -> bytes:
        """Список живых страниц — чтобы не набирать адреса руками."""
        rows = []
        for page in self.live_pages():
            left = max(0, int((page.made + self.ttl - time.time()) / 60)) if self.ttl > 0 else 0
            when = time.strftime("%H:%M", time.localtime(page.made))
            note = f"{when}, {page.messages} сообщ., {len(page.assets)} влож."
            if self.ttl > 0:
                note += f", ещё {left} мин"
            rows.append(f'<div align="left" class="msg"><table width="94%" cellpadding="3" '
                        f'cellspacing="0" bgcolor="{COLOR_THEIRS}"><tr>'
                        f'<td bgcolor="{COLOR_THEIRS}"><div class="who">'
                        f'<a href="{html.escape(page.path)}">{html.escape(page.title)}</a></div>'
                        f'<div class="time">{html.escape(note)}</div></td></tr></table></div><br/>')
        if not rows:
            rows.append('<div class="txt">Страниц пока нет — наберите !render в чате.</div>')
        return self._document("Страницы", rows).encode(self.encoding, "xmlcharrefreplace")

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
            removed = 0
            for asset_token in page.assets:
                asset = self._assets.pop(asset_token, None)
                if asset is None:
                    continue
                try:
                    os.unlink(asset.path)
                    removed += 1
                except OSError:
                    pass
            del self._pages[token]
            self._paths = {path: t for path, t in self._paths.items() if t != token}
            gone += removed
            log.info("страница %s «%s» просрочена — убрана, файлов удалено: %d",
                     page.path, page.title, removed)

        orphans = left = 0
        if self.ttl > 0:
            deadline = time.time() - self.ttl
            for name in os.listdir(self.directory):
                if name.split(".", 1)[0] in self._assets:
                    continue
                path = os.path.join(self.directory, name)
                try:
                    if not os.path.isfile(path):
                        continue
                    if os.path.getmtime(path) < deadline:
                        os.unlink(path)
                        orphans += 1
                    else:
                        left += 1
                except OSError:
                    continue
        if orphans:
            log.info("уборка страниц: удалено %d файлов без страницы%s", orphans,
                     f", ещё {left} моложе срока — позже" if left else "")
        elif left:
            log.debug("уборка страниц: %d файлов без страницы ждут срока", left)
        else:
            log.debug("уборка страниц: убирать нечего")
        return gone + orphans

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

        chunks = self._split(title, rows)
        path = self.make_path(title, token)
        made = time.time()
        first: Page | None = None
        for index, chunk in enumerate(chunks, start=1):
            part_token = token if index == 1 else _token()
            part_path = path if index == 1 else f"{path.rstrip('/')}/{index}"
            nav = self._nav(path, index, len(chunks))
            body = self._document(title, chunk + [nav]).encode(self.encoding,
                                                              "xmlcharrefreplace")
            page = Page(part_token, body, made, assets if index == 1 else [],
                        part_path, title, len(items), index, len(chunks))
            self._pages[part_token] = page
            self._paths[part_path.rstrip("/") or "/"] = part_token
            first = first or page
        log.info("страница %s (%s): %d сообщений, %d вложений, %d КБ%s",
                 path, token, len(items), len(assets),
                 sum(len(self._pages[t].body) for t in self._pages
                     if self._pages[t].made == made) // 1024,
                 f" в {len(chunks)} частях" if len(chunks) > 1 else "")
        return first

    def _split(self, title: str, rows: list[str]) -> list[list[str]]:
        """Режет сообщения на части, чтобы каждая страница влезла в потолок."""
        if self.page_max_bytes <= 0:
            return [rows]
        overhead = len(self._document(title, [self._nav("/x", 1, 2)]).encode(
            self.encoding, "xmlcharrefreplace"))
        chunks: list[list[str]] = [[]]
        size = overhead
        for row in rows:
            weight = len(row.encode(self.encoding, "xmlcharrefreplace"))
            if chunks[-1] and size + weight > self.page_max_bytes:
                chunks.append([])
                size = overhead
            chunks[-1].append(row)
            size += weight
        return chunks

    @staticmethod
    def _nav(path: str, index: int, total: int) -> str:
        """Переходы между частями — внизу, где палец после чтения."""
        if total <= 1:
            return ""
        base = path.rstrip("/")
        links = []
        if index > 1:
            prev = base if index == 2 else f"{base}/{index - 1}"
            links.append(f'<a href="{html.escape(prev)}">&#171; назад</a>')
        links.append(f"{index} из {total}")
        if index < total:
            links.append(f'<a href="{html.escape(base)}/{index + 1}">далее &#187;</a>')
        return '<div class="txt" align="center">' + " &#160;|&#160; ".join(links) + "</div>"

    async def _row(self, item: Item) -> tuple[str, list[str]]:
        """Одно сообщение: пузырь с именем, временем, текстом и вложением."""
        used: list[str] = []
        inner: list[str] = []

        if item.who:
            inner.append(f'<div class="who">{html.escape(item.who)}</div>')

        media, tokens = await self._media(item)
        used.extend(tokens)
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

    def _picture(self, raw: bytes, alt: str) -> tuple[str, str]:
        """Картинка прямо в странице: разметка и токен файла."""
        got = photos.shrink(raw, self.width, self.height, self.photo_max_bytes)
        if got is None:
            return "", ""
        data, width, height = got
        asset = self.put_asset(data, "jpg")
        return (f'<div><img src="/m/{asset.token}.jpg" width="{width}" '
                f'height="{height}" alt="{alt}"/></div>'), asset.token

    async def _media(self, item: Item) -> tuple[str, list[str]]:
        """Вложение: фото — картинкой, видео — превью и ссылкой, звук — ссылкой."""
        if not item.kind:
            return "", []
        parts: list[str] = []
        tokens: list[str] = []

        if item.kind == "photo":
            markup, token = self._picture(await self._raw(item), "фото")
            if not token:
                return '<div class="txt">[фото не открылось]</div>', []
            return markup, [token]

        if item.kind == "video" and item.thumb is not None:
            # Превью — та миниатюра, что Telegram показывает в ленте: видно,
            # что за ролик, ещё до скачивания.
            try:
                thumb = await item.thumb() or b""
            except Exception as exc:
                log.warning("не смог скачать превью видео: %s", exc)
                thumb = b""
            if thumb:
                markup, token = self._picture(thumb, "видео")
                if token:
                    parts.append(markup)
                    tokens.append(token)

        if item.kind in ("video", "voice", "audio"):
            label = {"video": "видео", "voice": "голосовое", "audio": "аудио"}[item.kind]
            length = _hms(item.seconds)
            raw = await self._raw(item)
            data = await self.transcoder.convert(raw, item.kind)
            del raw                    # исходник больше не нужен
            if not data:
                parts.append(f'<div class="txt">[{label} {length} — перекодировать '
                             f'не вышло]</div>'.replace("  ", " "))
                return "".join(parts), tokens
            ext = "3gp" if item.kind == "video" else "amr"
            asset = self.put_asset(data, ext)
            tokens.append(asset.token)
            note = f"{label} {length}".strip()
            size = f"{asset.size // 1024 or 1} КБ"
            verb = "смотреть" if item.kind == "video" else "слушать"
            parts.append(f'<div class="file"><a href="/m/{asset.token}.{ext}">'
                         f'{verb}: {html.escape(note)}, {size}</a></div>')
            return "".join(parts), tokens

        return "", []

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
