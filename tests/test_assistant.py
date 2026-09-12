"""Контакт «Claude»: вопросы с телефона уходят в Claude API, ответы — обратно."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.assistant import ASSISTANT_PEER, DEFAULT_SYSTEM, Assistant
from bridge.bridge import Bridge
from bridge.config import Config
from bridge.oscar import const as C
from bridge.tg.client import Dialog


def fake_api(replies: list[str], calls: list[dict], stop: str = "end_turn"):
    async def create(**kwargs):
        calls.append(kwargs)
        text = replies.pop(0) if replies else "…"
        if text == "RAISE":
            raise RuntimeError("сеть упала")
        return SimpleNamespace(
            content=[SimpleNamespace(type="thinking", thinking=""),
                     SimpleNamespace(type="text", text=text)],
            stop_reason=stop, stop_details=None)
    return create


async def run_assistant() -> None:
    calls: list[dict] = []
    bot = Assistant("claude-opus-5", history=4, max_tokens=500, effort="low",
                    create=fake_api(["Привет!", "Ага", "Три", "Четыре", "RAISE", "Пять"], calls))

    assert await bot.ask("привет") == "Привет!"
    req = calls[0]
    assert req["model"] == "claude-opus-5" and req["max_tokens"] == 500, req
    assert req["system"] == DEFAULT_SYSTEM, "без своей подсказки — встроенная"
    assert req["thinking"] == {"type": "adaptive"} and req["output_config"] == {"effort": "low"}
    assert req["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in req["betas"]
    assert req["messages"] == [{"role": "user", "content": "привет"}], req["messages"]

    await bot.ask("как дела")
    assert calls[1]["messages"][:2] == [{"role": "user", "content": "привет"},
                                        {"role": "assistant", "content": "Привет!"}], \
        "история едет в следующий запрос"

    # История не длиннее history реплик и начинается с человека.
    await bot.ask("три")
    await bot.ask("четыре")
    assert len(bot.messages) == 4, bot.messages
    assert bot.messages[0]["role"] == "user"
    assert calls[-1]["messages"][0] == {"role": "user", "content": "три"}, calls[-1]["messages"]
    assert bot.messages == [{"role": "user", "content": "три"}, {"role": "assistant", "content": "Три"},
                            {"role": "user", "content": "четыре"},
                            {"role": "assistant", "content": "Четыре"}], bot.messages

    # Ошибка API: вопрос из истории убирается, ошибка уходит наверх.
    before = list(bot.messages)
    try:
        await bot.ask("а это?")
    except RuntimeError:
        pass
    else:
        raise AssertionError("ошибка должна дойти до моста")
    assert bot.messages == before, "неотвеченный вопрос не должен оставаться в истории"

    bot.reset()
    assert bot.messages == []
    assert await bot.ask("снова") == "Пять"

    # Отказ модели и обрезанный ответ — понятным текстом.
    stopped = Assistant("claude-opus-5", fallbacks=False,
                        create=fake_api(["начало"], [], stop="max_tokens"))
    assert "обрезан" in await stopped.ask("длинно")
    refused = Assistant("claude-opus-5", fallbacks=False, create=fake_api([""], [], stop="refusal"))
    assert "отказался" in await refused.ask("нельзя")
    print("  разговор: ок (запрос, история, ошибки, отказ)")


async def run_bridge() -> None:
    cfg = Config(tg_api_id=1, tg_api_hash="x")
    work = tempfile.mkdtemp()
    cfg.db = os.path.join(work, "test.db")
    cfg.tg_session = os.path.join(work, "test.session")
    cfg.photos_enabled = False
    cfg.roster_limit = 1
    bridge = Bridge(cfg)
    calls: list[dict] = []
    bridge.assistant = Assistant("claude-opus-5", create=fake_api(["Ответ Claude"], calls))

    async def dialogs():
        return [Dialog(555, "user", "Мама", "Личные", 0, "online"),
                Dialog(-4001, "chat", "Дача", "Группы", 1, "online")]

    bridge.telegram.dialogs = dialogs
    await bridge.refresh_roster()

    # Контакт есть в списке, переживает roster_limit и не считается пропавшим.
    bot = bridge.storage.contact_by_peer(ASSISTANT_PEER)
    assert bot is not None and bot.title == "Claude" and bot.group_name == "Боты"
    assert bot.kind == "bot" and bot.favourite == 1
    assert any(c.uin == bot.uin for c in bridge.roster()), "roster_limit не должен вытеснять помощника"
    assert bridge.status_of(bot.uin) == C.STATUS_ONLINE
    await bridge.refresh_roster()
    assert bridge.storage.contact_by_peer(ASSISTANT_PEER).gone == 0

    sent: list[str] = []
    typing: list[bool] = []

    async def deliver(target, text, forced=False, url="", ts=0):
        sent.append(text)
        return True

    async def notify_typing(uin, active):
        typing.append(active)

    bridge.oscar.deliver = deliver
    bridge.oscar.notify_typing = notify_typing

    # Вопрос — ответ, с «печатает» на время ожидания; в Telegram ничего не уходит.
    tg_sent: list = []

    async def send(*a, **k):
        tg_sent.append(a)
        return 1

    bridge.telegram.send = send
    result = await bridge.on_phone_message(bot.uin, "сколько будет 2+2?")
    assert result == -1, "у ответа помощника нет номера в Telegram"
    assert sent == [], "галочка телефону сразу, ответ — когда Claude закончит"
    await asyncio.sleep(0.1)
    assert sent == ["Ответ Claude"], sent
    assert typing == [True, False], typing
    assert tg_sent == [], "вопрос помощнику не должен уходить в Telegram"
    assert calls[-1]["messages"][-1]["content"] == "сколько будет 2+2?"

    # !reset забывает разговор, !help объясняет.
    sent.clear()
    await bridge.on_phone_message(bot.uin, "!reset")
    await asyncio.sleep(0.05)
    assert bridge.assistant.messages == [] and "забыт" in sent[-1]
    await bridge.on_phone_message(bot.uin, "!help")
    await asyncio.sleep(0.05)
    assert "!reset" in sent[-1]

    # Ошибка API — коротким текстом, индикатор гаснет.
    bridge.assistant = Assistant("claude-opus-5", create=fake_api(["RAISE"], calls))
    sent.clear(); typing.clear()
    await bridge.on_phone_message(bot.uin, "упади")
    await asyncio.sleep(0.1)
    assert sent and "Не вышло" in sent[-1], sent
    assert typing == [True, False]

    # Карточка контакта — своя, без похода в Telegram.
    info = await bridge.chat_info(bot.uin)
    assert info["kind"] == "Бот" and "claude-opus-5" in info["about"]

    # Удаление и списки видимости к помощнику не применяются.
    sent.clear()
    await bridge.on_phone_remove(bot.uin, revoke=False)
    assert bridge.storage.contact_by_peer(ASSISTANT_PEER).gone == 0 and sent

    bridge.storage.close()
    print("  контакт в мосту: ок (список, вопрос-ответ, печатает, команды, карточка)")


async def main() -> None:
    await run_assistant()
    await run_bridge()
    print("ПОМОЩНИК ПРОВЕРЕН")


if __name__ == "__main__":
    asyncio.run(main())
