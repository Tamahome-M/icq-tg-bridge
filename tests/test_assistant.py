"""Контакт «Claude»: вопросы с телефона уходят в `claude -p`, ответы — обратно."""

from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.assistant import ASSISTANT_PEER, DEFAULT_SYSTEM, Assistant, AssistantError
from bridge.bridge import Bridge
from bridge.config import Config
from bridge.oscar import const as C
from bridge.tg.client import Dialog


def fake_run(replies: list, calls: list):
    """Подмена запуска: replies — что «вернул» claude (dict, None или RAISE)."""
    async def run(argv, text):
        calls.append((argv, text))
        item = replies.pop(0) if replies else {"type": "result", "result": "…"}
        if item == "RAISE":
            raise AssistantError("сеть упала")
        return item
    return run


def result(text: str, session: str = "s-1", **extra) -> dict:
    return {"type": "result", "result": text, "session_id": session, "is_error": False,
            "stop_reason": "end_turn", **extra}


async def run_assistant() -> None:
    calls: list = []
    bot = Assistant("claude", "/tmp/w", model="opus", effort="low", tools="WebSearch",
                    args="--max-turns 3",
                    run=fake_run([result("Привет!"), result("Ага"), None, result("Заново", "s-2"),
                                  "RAISE", result("Пять", "s-2")], calls))

    assert await bot.ask("привет") == "Привет!"
    argv, text = calls[0]
    assert text == "привет", "вопрос уходит через stdin, а не в аргументах"
    assert argv[:4] == ["claude", "-p", "--output-format", "json"], argv
    assert argv[argv.index("--append-system-prompt") + 1] == DEFAULT_SYSTEM
    assert argv[argv.index("--model") + 1] == "opus"
    assert argv[argv.index("--effort") + 1] == "low"
    assert argv[argv.index("--tools") + 1] == "WebSearch"
    assert argv[argv.index("--allowedTools") + 1] == "WebSearch", "инструменты разрешены заранее"
    assert "--max-turns" in argv and "3" in argv, "свои аргументы дописываются"
    assert "--resume" not in argv, "первый вопрос — новый сеанс"
    assert bot.session_id == "s-1"

    # Второй вопрос продолжает тот же сеанс.
    await bot.ask("как дела")
    argv, _ = calls[1]
    assert argv[argv.index("--resume") + 1] == "s-1", argv

    # Сеанс на диске пропал: claude не нашёл его — начинаем новый и не теряем вопрос.
    assert await bot.ask("три") == "Заново"
    assert len(calls) == 4, "после неудачного --resume должен быть второй запуск"
    assert "--resume" in calls[2][0] and "--resume" not in calls[3][0]
    assert calls[3][1] == "три"
    assert bot.session_id == "s-2"

    # Ошибка запуска уходит наверх, сеанс остаётся.
    try:
        await bot.ask("а это?")
    except AssistantError:
        pass
    else:
        raise AssertionError("ошибка должна дойти до моста")
    assert bot.session_id == "s-2"

    bot.reset()
    assert bot.session_id is None
    assert await bot.ask("снова") == "Пять"
    assert "--resume" not in calls[-1][0]

    # Без инструментов и с полным набором — разные аргументы.
    none = Assistant("claude", tools="", run=fake_run([], []))
    argv = none.argv(None)
    assert argv[argv.index("--tools") + 1] == "" and "--allowedTools" not in argv
    full = Assistant("claude", tools="default", run=fake_run([], []))
    argv = full.argv(None)
    assert argv[argv.index("--tools") + 1] == "default" and "--allowedTools" not in argv

    # Ошибка, отказ и обрезанный ответ — понятным текстом.
    failed = Assistant("claude", run=fake_run([result("нет входа", is_error=True)], []))
    try:
        await failed.ask("x")
    except AssistantError as exc:
        assert "нет входа" in str(exc)
    else:
        raise AssertionError("is_error должен стать ошибкой")
    stopped = Assistant("claude", run=fake_run([result("начало", stop_reason="max_tokens")], []))
    assert "обрезан" in await stopped.ask("длинно")
    refused = Assistant("claude", run=fake_run([result("", stop_reason="refusal")], []))
    assert "отказался" in await refused.ask("нельзя")

    # Разбор вывода: итог — строка с type=result, мусор вокруг не мешает.
    out = b'warning: something\n{"type":"system"}\n' + json.dumps(result("ok")).encode() + b"\n"
    assert Assistant._parse(out)["result"] == "ok"
    assert Assistant._parse(b"No conversation found\n") is None
    print("  разговор: ок (аргументы, сеанс, потеря сеанса, ошибки, отказ)")


FAKE_CLAUDE = r'''#!/bin/sh
# Подделка claude: печатает JSON как настоящий, помнит один сеанс.
args="$*"
question=$(cat)
case "$args" in
  *--resume\ lost*) echo "No conversation found with session ID: lost" >&2; exit 1 ;;
  *--resume\ known*) sid=known ;;
  *) sid=known ;;
esac
case "$question" in
  sleep*) sleep 5 ;;
  fail*) echo "Not logged in" >&2; exit 1 ;;
esac
printf '{"type":"result","result":"echo: %s","session_id":"%s","is_error":false,"stop_reason":"end_turn","num_turns":1}\n' "$question" "$sid"
'''


async def run_process() -> None:
    """Настоящий запуск процесса: stdin, JSON, потеря сеанса, ошибка, срок."""
    work = tempfile.mkdtemp()
    path = os.path.join(work, "claude")
    with open(path, "w") as fh:
        fh.write(FAKE_CLAUDE)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)

    bot = Assistant(path, work, tools="", timeout=1)
    assert bot.available
    assert await bot.ask("привет, мир") == "echo: привет, мир"
    assert bot.session_id == "known"
    assert await bot.ask("ещё") == "echo: ещё"

    bot.session_id = "lost"
    assert await bot.ask("после потери") == "echo: после потери", "новый сеанс вместо потерянного"
    assert bot.session_id == "known"

    try:
        await bot.ask("fail now")
    except AssistantError as exc:
        assert "Not logged in" in str(exc), exc
    else:
        raise AssertionError("ошибка claude должна дойти до моста")

    try:
        await bot.ask("sleep")
    except AssistantError as exc:
        assert "не ответил за" in str(exc), exc
    else:
        raise AssertionError("зависший claude должен быть убит по сроку")

    missing = Assistant(os.path.join(work, "nope"), work)
    assert not missing.available
    try:
        await missing.ask("x")
    except AssistantError as exc:
        assert "не найдена" in str(exc)
    print("  процесс: ок (stdin, JSON, потеря сеанса, ошибка, срок, нет программы)")


async def run_bridge() -> None:
    cfg = Config(tg_api_id=1, tg_api_hash="x")
    work = tempfile.mkdtemp()
    cfg.db = os.path.join(work, "test.db")
    cfg.tg_session = os.path.join(work, "test.session")
    cfg.photos_enabled = False
    cfg.roster_limit = 1
    cfg.assistant_enabled = True
    cfg.assistant_workdir = os.path.join(work, "claude")
    bridge = Bridge(cfg)
    assert os.path.isdir(cfg.assistant_workdir), "рабочий каталог для сеансов заводится сам"
    calls: list = []
    bridge.assistant = Assistant("claude", run=fake_run([result("Ответ Claude")], calls))

    async def dialogs():
        return [Dialog(555, "user", "Мама", "Личные", 0, "online"),
                Dialog(-4001, "chat", "Дача", "Группы", 1, "online")]

    bridge.telegram.dialogs = dialogs
    await bridge.refresh_roster()

    # Контакт есть в списке, переживает roster_limit и не считается пропавшим.
    bot = bridge.storage.contact_by_peer(ASSISTANT_PEER)
    assert bot is not None and bot.title == "Claude" and bot.group_name == "Боты"
    assert bot.kind == "bot" and bot.favourite == 1
    assert any(c.uin == bot.uin for c in bridge.roster()), "roster_limit не должен вытеснять контакт"
    assert bridge.status_of(bot.uin) == C.STATUS_ONLINE
    await bridge.refresh_roster()
    assert bridge.storage.contact_by_peer(ASSISTANT_PEER).gone == 0

    sent: list[str] = []
    typing: list[bool] = []

    async def deliver(target, text, forced=False, url="", ts=0, attach=""):
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
    result_id = await bridge.on_phone_message(bot.uin, "сколько будет 2+2?")
    assert result_id == -1, "у ответа Claude нет номера в Telegram"
    assert sent == [], "галочка телефону сразу, ответ — когда Claude закончит"
    await asyncio.sleep(0.1)
    assert sent == ["Ответ Claude"], sent
    assert typing == [True, False], typing
    assert tg_sent == [], "вопрос Claude не должен уходить в Telegram"
    assert calls[-1][1] == "сколько будет 2+2?"

    # !reset забывает разговор, !help объясняет.
    sent.clear()
    await bridge.on_phone_message(bot.uin, "!reset")
    await asyncio.sleep(0.05)
    assert bridge.assistant.session_id is None and "забыт" in sent[-1]
    await bridge.on_phone_message(bot.uin, "!help")
    await asyncio.sleep(0.05)
    assert "!reset" in sent[-1]

    # Ошибка запуска — коротким текстом, индикатор гаснет.
    bridge.assistant = Assistant("claude", run=fake_run(["RAISE"], calls))
    sent.clear(); typing.clear()
    await bridge.on_phone_message(bot.uin, "упади")
    await asyncio.sleep(0.1)
    assert sent and sent[-1] == "Claude не ответил: сеть упала", sent
    assert typing == [True, False]

    # Карточка контакта — своя, без похода в Telegram.
    info = await bridge.chat_info(bot.uin)
    assert info["kind"] == "Бот" and "!reset" in info["about"]

    # Удаление и списки видимости к контакту не применяются.
    sent.clear()
    await bridge.on_phone_remove(bot.uin, revoke=False)
    assert bridge.storage.contact_by_peer(ASSISTANT_PEER).gone == 0 and sent

    bridge.storage.close()
    print("  контакт в мосту: ок (список, вопрос-ответ, печатает, команды, карточка)")


async def main() -> None:
    await run_assistant()
    await run_process()
    await run_bridge()
    print("КОНТАКТ CLAUDE ПРОВЕРЕН")


if __name__ == "__main__":
    asyncio.run(main())
