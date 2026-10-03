"""Контакт «Claude»: всё, что ему пишут с телефона, уходит в Claude Code,
ответ приходит от него же.

Это обычный контакт в списке — со статусом, «печатает» и историей на
телефоне. Отвечает не API по ключу, а сама программа `claude` в режиме
печати (`claude -p`) — то есть подписка того пользователя, под которым
запущен мост, и его же настройки, разрешения и инструменты. Разговор
живёт как обычный сеанс Claude Code: каждый следующий вопрос продолжает
предыдущий (`--resume`), пока его не забыли командой !reset.

Экран маленький, а каждая лишняя строка — время на GPRS, поэтому подсказка
просит отвечать коротко и без разметки.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import pwd
import shlex
import shutil
import sys
import time

log = logging.getLogger("assistant")

# Псевдо-чат для контакта: у Telegram таких номеров не бывает (каналы — это
# -100 и десять-одиннадцать цифр), а в базе он живёт рядом с настоящими.
ASSISTANT_PEER = -999_999_999_999_999

DEFAULT_SYSTEM = (
    "С тобой переписываются через ICQ-клиент на кнопочном телефоне с экраном "
    "176×220. Отвечай по-русски, коротко и по делу: обычно одно-три "
    "предложения, в списках — не больше пяти пунктов. Без Markdown, без "
    "таблиц, без заголовков и эмодзи — только простой текст. Если вопрос "
    "требует длинного ответа, дай самое важное и предложи уточнить. Если "
    "нужного инструмента нет или он не разрешён, так и скажи одной фразой."
)
# Картинки от Claude: всё, что он сохранит в этот каталог внутри workdir,
# после ответа уходит на телефон фотографиями (ужатыми под его экран).
OUT_DIR = "out"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
IMAGES_PROMPT = (
    " Чтобы прислать картинку (карту, график, снимок страницы), сохрани её файлом PNG "
    "или JPEG в каталог {outdir} — мост сам отправит её на телефон, ужав под экран; "
    "в тексте ответа имя файла не упоминай, просто скажи, что на картинке."
)
ROUTE_PROMPT = (
    " Маршрут словами и картой строит команда: {python} {route} \"откуда\" \"куда\" "
    "--out {outdir}/route.png (по умолчанию пешком; --mode bike|car, если просят иначе; "
    "«куда» может быть «метро» — ближайшее); "
    "её вывод перескажи как есть, картинка уйдёт сама."
)
SNAPSHOT_PROMPT = (
    " Снимок веб-страницы (например, маршрут на картах) делает команда: "
    "{python} {snapshot} URL файл.png — и файл тоже клади в {outdir}."
)
# Инструменты по умолчанию: только сеть. Команды и правка файлов от имени
# пользователя моста с телефона не нужны — а если нужны, это включается в
# настройках явно.
DEFAULT_TOOLS = "WebSearch,WebFetch"


class AssistantError(Exception):
    """`claude` не ответил: не нашёлся, упал, не уложился в срок."""


class Assistant:
    """Разговор с Claude Code от имени одного контакта."""

    def __init__(self, command: str = "claude", workdir: str = "", model: str = "",
                 effort: str = "low", system: str = "", tools: str = DEFAULT_TOOLS,
                 args: str = "", timeout: float = 300.0, session_hours: float = 0.0,
                 run=None):
        self.command = command
        self.workdir = workdir
        self.model = model
        self.effort = effort
        self.outdir = os.path.join(workdir, OUT_DIR) if workdir else ""
        self.system = (system or DEFAULT_SYSTEM) + self._images_prompt()
        self._images: dict[int, str] = {}      # номер картинки -> путь к файлу
        self._fresh: list[tuple[int, str]] = []  # что сохранил последний ответ
        self._next_image = 1
        self.tools = tools
        self.args = shlex.split(args) if args else []
        self.timeout = timeout
        self.session_hours = session_hours
        self.session_id: str | None = None
        self.last_asked = 0.0
        self._lock = asyncio.Lock()        # вопросы — по одному, как в чате
        self._run = run or self._spawn     # подмена для проверок

    @property
    def available(self) -> bool:
        return shutil.which(self.command) is not None

    def _images_prompt(self) -> str:
        if not self.outdir:
            return ""
        prompt = IMAGES_PROMPT.format(outdir=self.outdir)
        tools_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
        prompt += ROUTE_PROMPT.format(python=sys.executable, route=os.path.join(tools_dir, "route.py"),
                                      outdir=self.outdir)
        snapshot = os.path.join(tools_dir, "snapshot.py")
        try:
            import playwright  # noqa: F401
        except ImportError:
            return prompt
        return prompt + SNAPSHOT_PROMPT.format(python=sys.executable, snapshot=snapshot,
                                               outdir=self.outdir)

    def _image_files(self) -> dict[str, float]:
        """Картинки в каталоге ответов: имя -> время изменения."""
        if not self.outdir:
            return {}
        try:
            os.makedirs(self.outdir, exist_ok=True)
            return {name: os.path.getmtime(os.path.join(self.outdir, name))
                    for name in os.listdir(self.outdir)
                    if name.lower().endswith(IMAGE_SUFFIXES)}
        except OSError:
            return {}

    def _collect_images(self, before: dict[str, float]) -> None:
        """Новые или обновлённые картинки после ответа — под номерами, по
        которым телефон их потом попросит."""
        self._fresh = []
        for name, stamp in sorted(self._image_files().items(), key=lambda kv: kv[1]):
            if before.get(name) == stamp:
                continue
            number = self._next_image
            self._next_image += 1
            self._images[number] = os.path.join(self.outdir, name)
            self._fresh.append((number, name))
            if len(self._images) > 100:
                self._images.pop(next(iter(self._images)))

    def take_images(self) -> list[tuple[int, str]]:
        """Картинки последнего ответа: (номер, имя файла)."""
        fresh, self._fresh = self._fresh, []
        return fresh

    def photo_bytes(self, number: int) -> bytes | None:
        path = self._images.get(number)
        if not path:
            return None
        try:
            with open(path, "rb") as source:
                return source.read()
        except OSError:
            return None

    def reset(self) -> None:
        self.session_id = None

    def argv(self, resume: str | None) -> list[str]:
        cmd = [self.command, "-p", "--output-format", "json",
               "--append-system-prompt", self.system]
        if self.model:
            cmd += ["--model", self.model]
        if self.effort:
            cmd += ["--effort", self.effort]
        if self.tools is not None:
            # --tools ограничивает набор, --allowedTools снимает вопрос
            # «разрешить?», на который в режиме печати некому отвечать.
            cmd += ["--tools", self.tools]
            if self.tools and self.tools != "default":
                cmd += ["--allowedTools", self.tools]
        cmd += self.args
        if resume:
            cmd += ["--resume", resume]
        return cmd

    async def ask(self, text: str) -> str:
        """Один ход разговора: вопрос — ответ. Сеанс продолжается, пока жив."""
        async with self._lock:
            if (self.session_hours and self.session_id
                    and time.time() - self.last_asked > self.session_hours * 3600):
                log.info("сеанс %s залежался — начинаю новый", self.session_id[:8])
                self.session_id = None
            resume = self.session_id
            before = self._image_files()
            reply = await self._run(self.argv(resume), text)
            if reply is None and resume:
                # Сеанс на диске не нашёлся (почистили ~/.claude, сменили
                # каталог) — не страшно, начинаем заново.
                log.info("сеанс %s не продолжился — начинаю новый", resume[:8])
                self.session_id = None
                reply = await self._run(self.argv(None), text)
            if reply is None:
                raise AssistantError("claude вернул не то, что ждали")
            self.last_asked = time.time()
            self._collect_images(before)
            return self._answer(reply)

    def _answer(self, reply: dict) -> str:
        if reply.get("session_id"):
            self.session_id = reply["session_id"]
        answer = str(reply.get("result") or "").strip()
        if reply.get("is_error"):
            log.warning("claude ответил ошибкой: %s", answer[:200])
            raise AssistantError(answer[:200] or "ошибка без текста")
        stop = reply.get("stop_reason") or ""
        if stop == "refusal":
            log.warning("Claude отказал")
            answer = answer or "Claude отказался отвечать."
        elif stop == "max_tokens":
            answer += "\n[ответ обрезан — уточните вопрос]"
        if reply.get("permission_denials"):
            names = sorted({d.get("tool_name", "?") for d in reply["permission_denials"]})
            log.info("claude просил инструменты, но не получил: %s", ", ".join(names))
        return answer or "[пустой ответ]"

    async def _spawn(self, argv: list[str], text: str) -> dict | None:
        """Запускает `claude -p`, вопрос — через stdin, ответ — JSON из stdout.

        None — сеанс не продолжился; ошибка запуска — исключением."""
        if not self.available:
            raise AssistantError(f"программа {self.command!r} не найдена")
        env = dict(os.environ)
        # Мост запускают из-под службы: без терминала claude всё равно
        # работает, но пусть и не пытается его искать. А вход в аккаунт он
        # ищет в ~/.claude — значит, HOME должен быть домом пользователя моста.
        env.setdefault("TERM", "dumb")
        env.setdefault("HOME", pwd.getpwuid(os.getuid()).pw_dir)
        started = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, cwd=self.workdir or None, env=env,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE)
        except OSError as exc:
            raise AssistantError(f"не запустился: {exc}") from exc
        try:
            out, err = await asyncio.wait_for(proc.communicate(text.encode()),
                                              timeout=self.timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise AssistantError(f"не ответил за {int(self.timeout)} с")
        took = time.monotonic() - started
        stderr = err.decode(errors="replace").strip()
        reply = self._parse(out)
        if reply is None:
            if "No conversation found" in stderr:
                return None
            log.warning("claude завершился с кодом %s за %.0f с: %s",
                        proc.returncode, took, stderr[-300:] or "(тишина)")
            raise AssistantError(stderr.splitlines()[-1][:200] if stderr
                                 else f"код выхода {proc.returncode}")
        log.info("claude ответил за %.0f с (ходов: %s)", took, reply.get("num_turns", "?"))
        if stderr:
            log.debug("claude stderr: %s", stderr[-500:])
        return reply

    @staticmethod
    def _parse(out: bytes) -> dict | None:
        """Итог — последняя строка JSON с type=result; всё прочее пропускаем."""
        for line in reversed(out.decode(errors="replace").splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if isinstance(data, dict) and data.get("type") == "result":
                return data
        return None
