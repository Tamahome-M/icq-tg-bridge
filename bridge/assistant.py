"""Контакт «Claude»: всё, что ему пишут с телефона, уходит в Claude API,
ответ приходит от него же.

Это обычный контакт в списке — со статусом, «печатает» и историей на
телефоне. Разговор помнится в пределах последних реплик: экран маленький,
а каждый лишний токен — время на GPRS, поэтому и подсказка модели просит
отвечать коротко и без разметки.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

log = logging.getLogger("assistant")

# Псевдо-чат для контакта: у Telegram таких номеров не бывает (каналы — это
# -100 и десять-одиннадцать цифр), а в базе он живёт рядом с настоящими.
ASSISTANT_PEER = -999_999_999_999_999

DEFAULT_SYSTEM = (
    "Ты — помощник, с которым переписываются через ICQ-клиент на кнопочном "
    "телефоне с экраном 176×220. Отвечай по-русски, коротко и по делу: "
    "обычно одно-три предложения, в списках — не больше пяти пунктов. Без "
    "Markdown, без таблиц, без заголовков и эмодзи — только простой текст. "
    "Если вопрос требует длинного ответа, дай самое важное и предложи "
    "уточнить."
)


class Assistant:
    """Разговор с Claude от имени одного контакта."""

    def __init__(self, model: str, api_key: str = "", system: str = "",
                 history: int = 20, max_tokens: int = 2000, effort: str = "low",
                 fallbacks: bool = True, timeout: float = 120.0,
                 create: Callable[..., Awaitable] | None = None):
        self.model = model
        self.system = system or DEFAULT_SYSTEM
        self.history = max(0, history)
        self.max_tokens = max_tokens
        self.effort = effort
        self.fallbacks = fallbacks
        self.messages: list[dict] = []
        if create is not None:
            self._create = create        # подмена для проверок
        else:
            import anthropic             # лениво: без контакта библиотека не нужна
            client = anthropic.AsyncAnthropic(api_key=api_key or None, timeout=timeout)
            self._create = client.beta.messages.create

    def reset(self) -> None:
        self.messages.clear()

    async def ask(self, text: str) -> str:
        """Один ход разговора: вопрос — ответ. История подрезается снизу."""
        self.messages.append({"role": "user", "content": text})
        kwargs = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self.system,
            messages=self._trimmed(),
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
        )
        if self.fallbacks:
            # Отказ модели по политике перепоручается запасной — внутри того
            # же запроса, по категории отказа.
            kwargs.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        try:
            response = await self._create(**kwargs)
        except Exception:
            self.messages.pop()          # вопрос без ответа в истории не нужен
            raise

        answer = "".join(block.text for block in response.content
                         if getattr(block, "type", "") == "text").strip()
        if getattr(response, "stop_reason", "") == "refusal":
            details = getattr(response, "stop_details", None)
            why = getattr(details, "category", None) or "без объяснения"
            log.warning("Claude отказал (%s)", why)
            answer = answer or f"Claude отказался отвечать ({why})."
        if getattr(response, "stop_reason", "") == "max_tokens":
            answer += "\n[ответ обрезан — уточните вопрос]"
        if not answer:
            answer = "[пустой ответ]"
        # Ответ модели — нашими же словами, чтобы история сходилась.
        self.messages.append({"role": "assistant", "content": answer})
        self.messages = self._trimmed()
        return answer

    def _trimmed(self) -> list[dict]:
        """История не длиннее history реплик, и первой всегда идёт реплика человека."""
        kept = list(self.messages)
        if self.history and len(kept) > self.history:
            kept = kept[len(kept) - self.history:]
        while kept and kept[0]["role"] != "user":
            kept.pop(0)
        return kept
