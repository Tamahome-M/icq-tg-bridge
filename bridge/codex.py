"""Отдельный контакт Codex: один диалог через `codex exec --json`."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import time

from .assistant import Assistant, AssistantError

log = logging.getLogger("codex")
CODEX_PEER = -999_999_999_999_998


class CodexAssistant(Assistant):
    def __init__(self, command: str = "codex", workdir: str = "", model: str = "",
                 effort: str = "low", system: str = "", sandbox: str = "read-only",
                 search: bool = True, args: str = "", timeout: float = 300,
                 session_hours: float = 0, run=None):
        if sandbox not in ("read-only", "workspace-write", "danger-full-access"):
            raise ValueError("[codex] sandbox: read-only, workspace-write или danger-full-access")
        self.sandbox = sandbox
        self.search = search
        self._generation = 0
        super().__init__(command, workdir, model, effort, system, None, args,
                         timeout, session_hours, run)

    def _images_prompt(self) -> str:
        return super()._images_prompt() if self.sandbox != "read-only" else ""

    def reset(self) -> None:
        self._generation += 1
        super().reset()

    def argv(self, resume: str | None) -> list[str]:
        # Настройки перед exec применяются и к новому запуску, и к resume.
        cmd = [self.command, "--ask-for-approval", "never", "--sandbox", self.sandbox,
               "-c", "developer_instructions=" + json.dumps(self.system, ensure_ascii=False),
               "-c", 'web_search="live"' if self.search else 'web_search="disabled"']
        if self.model:
            cmd += ["--model", self.model]
        if self.effort:
            cmd += ["-c", "model_reasoning_effort=" + json.dumps(self.effort)]
        cmd += self.args
        cmd += ["exec", "--json", "--skip-git-repo-check"]
        if resume:
            cmd += ["resume", resume]
        return cmd + ["-"]

    async def ask(self, text: str) -> str:
        async with self._lock:
            if (self.session_hours and self.session_id
                    and time.time() - self.last_asked > self.session_hours * 3600):
                self.reset()
            generation = self._generation
            resume = self.session_id
            before = self._image_files()
            reply = await self._run(self.argv(resume), text)
            if reply is None and resume:
                log.info("сеанс %s не найден — начинаю новый", resume[:8])
                if generation == self._generation:
                    self.session_id = None
                reply = await self._run(self.argv(None), text)
            if reply is None:
                raise AssistantError("Codex вернул не то, что ждали")
            if reply.get("is_error"):
                raise AssistantError(str(reply.get("result") or "ошибка без текста")[:200])
            if generation == self._generation and reply.get("session_id"):
                self.session_id = reply["session_id"]
            self.last_asked = time.time()
            self._collect_images(before)
            return str(reply.get("result") or "").strip() or "[пустой ответ]"

    @staticmethod
    def _parse(out: bytes) -> dict | None:
        thread = answer = error = ""
        completed = failed = False
        for line in out.decode(errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            kind = event.get("type")
            if kind == "thread.started":
                thread = str(event.get("thread_id") or "")
            elif kind == "item.completed":
                item = event.get("item") or {}
                if isinstance(item, dict) and item.get("type") == "agent_message":
                    answer = str(item.get("text") or "")
            elif kind == "turn.completed":
                completed = True
            elif kind == "turn.failed":
                failed = True
                detail = event.get("error") or {}
                error = str(detail.get("message") or "ошибка Codex") if isinstance(detail, dict) else str(detail)
            elif kind == "error":
                error = str(event.get("message") or "ошибка Codex")
        if failed or (error and not completed):
            return {"session_id": thread, "result": error, "is_error": True}
        if not completed:
            return None
        return {"session_id": thread, "result": answer, "is_error": False}

    async def _spawn(self, argv: list[str], text: str) -> dict | None:
        if not self.available:
            raise AssistantError(f"программа {self.command!r} не найдена")
        env = dict(os.environ)
        env.setdefault("TERM", "dumb")
        started = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, cwd=self.workdir or None, env=env, start_new_session=True,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE)
        except OSError as exc:
            raise AssistantError(f"не запустился: {exc}") from exc
        finished = False
        try:
            out, err = await asyncio.wait_for(proc.communicate(text.encode()), timeout=self.timeout)
            finished = True
        except asyncio.TimeoutError as exc:
            raise AssistantError(f"не ответил за {int(self.timeout)} с") from exc
        finally:
            if not finished:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await proc.wait()
        stderr = err.decode(errors="replace").strip()
        reply = self._parse(out)
        if proc.returncode or reply is None:
            detail = str(reply.get("result") or "") if reply and reply.get("is_error") else stderr
            missing = ("no session found", "no conversation found", "no rollout found", "could not find session")
            if "resume" in argv and any(reason in detail.lower() for reason in missing):
                return None
            if reply and reply.get("is_error"):
                return reply
            raise AssistantError(detail.splitlines()[-1][:200] if detail
                                 else f"код выхода {proc.returncode}, нет завершённого ответа")
        log.info("Codex ответил за %.0f с", time.monotonic() - started)
        return reply
