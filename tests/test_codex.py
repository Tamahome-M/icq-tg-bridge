"""Codex CLI JSONL, sessions, process cleanup and independent bot contacts."""
from __future__ import annotations

import asyncio
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bridge.assistant import ASSISTANT_PEER, Assistant, AssistantError
from bridge.bridge import Bridge
from bridge.codex import CODEX_PEER, CodexAssistant
from bridge.config import Config
from bridge.oscar import const as C
from PIL import Image


def result(text="Ответ", session="session-one", error=False):
    return {"result": text, "session_id": session, "is_error": error}


async def run_adapter():
    calls = []
    replies = [result(), result("Два"), None, result("Заново", "session-two"),
               result("Нет входа", error=True), result("После сброса", "session-three")]

    async def fake(argv, text):
        calls.append((argv, text))
        return replies.pop(0)

    bot = CodexAssistant(model="chosen-model", effort="low", args="--profile phone", run=fake)
    assert await bot.ask("Привет") == "Ответ"
    argv, question = calls[-1]
    assert question == "Привет" and argv[-1] == "-" and "Привет" not in argv
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert argv[argv.index("--ask-for-approval") + 1] == "never"
    assert 'web_search="live"' in argv and 'model_reasoning_effort="low"' in argv
    assert argv[argv.index("--model") + 1] == "chosen-model" and "--profile" in argv
    assert "--json" in argv and "--skip-git-repo-check" in argv
    assert "resume" not in argv and bot.session_id == "session-one"
    assert await bot.ask("Два") == "Два" and "session-one" in calls[-1][0]
    assert await bot.ask("Три") == "Заново"
    assert "resume" in calls[-2][0] and "resume" not in calls[-1][0]
    try:
        await bot.ask("Четыре")
    except AssistantError as exc:
        assert str(exc) == "Нет входа" and bot.session_id == "session-two"
    else:
        raise AssertionError("Codex failure was hidden")
    bot.reset()
    assert await bot.ask("Пять") == "После сброса" and "resume" not in calls[-1][0]
    bot.session_hours = 1
    bot.last_asked = time.time() - 7200
    replies.append(result("Срок"))
    assert await bot.ask("Шесть") == "Срок" and "resume" not in calls[-1][0]
    assert 'web_search="disabled"' in CodexAssistant(search=False).argv(None)
    try:
        CodexAssistant(sandbox="invalid")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid sandbox accepted")

    stream = [
        {"type": "thread.started", "thread_id": "thread-id"},
        {"type": "item.completed", "item": {"type": "reasoning", "text": "secret reasoning"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "progress"}},
        {"type": "item.completed", "item": {"type": "command_execution", "aggregated_output": "secret command"}},
        {"type": "error", "message": "retrying transport"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Final answer"}},
        {"type": "turn.completed"},
    ]
    out = "noise\n[]\n" + "\n".join(json.dumps(row) for row in stream)
    assert bot._parse(out.encode()) == result("Final answer", "thread-id")
    assert bot._parse(b'{"type":"item.completed","item":{"type":"agent_message","text":"partial"}}') is None
    failed = bot._parse(b'{"type":"turn.failed","error":{"message":"denied"}}')
    assert failed["is_error"] and failed["result"] == "denied"

    entered, release = asyncio.Event(), asyncio.Event()
    async def blocked(argv, text):
        entered.set()
        await release.wait()
        return result("Старый ответ", "old-session")
    bot = CodexAssistant(run=blocked)
    task = asyncio.create_task(bot.ask("старый вопрос"))
    await entered.wait()
    bot.reset()
    release.set()
    assert await task == "Старый ответ" and bot.session_id is None, "!reset lost to in-flight answer"
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def ordered(argv, text):
        calls.append((argv,text))
        if text == "one":
            entered.set()
            await release.wait()
        return result(text,"ordered-session")
    bot = CodexAssistant(run=ordered)
    first = asyncio.create_task(bot.ask("one"))
    await entered.wait()
    second = asyncio.create_task(bot.ask("two"))
    await asyncio.sleep(0.01)
    assert len(calls) == 1, "parallel questions must not fork the conversation"
    release.set()
    assert await asyncio.gather(first,second) == ["one","two"]
    assert "ordered-session" in calls[1][0], "second question must resume the first"
    print("  adapter: args, JSONL, resume, reset, expiry, errors and in-flight reset OK")


FAKE = '''#!/usr/bin/env python3
import json,os,subprocess,sys,time
from pathlib import Path
text=sys.stdin.read()
with open('calls.jsonl','a') as log:log.write(json.dumps({'argv':sys.argv,'text':text})+'\\n')
if text=='missing' and 'resume' in sys.argv:
    print('No session found',file=sys.stderr);sys.exit(1)
if text=='fail':
    print(json.dumps({'type':'turn.failed','error':{'message':'Not logged in'}}));sys.exit(1)
if text=='slow':
    child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
    Path('pids').write_text(str(os.getpid())+' '+str(child.pid))
    time.sleep(60)
print(json.dumps({'type':'thread.started','thread_id':'spawn-session'}))
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'Ответ: '+text}}))
print(json.dumps({'type':'turn.completed'}))
'''


def running(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except FileNotFoundError:
        return False


async def run_process(directory):
    command = directory / "fake-codex"
    command.write_text(FAKE)
    command.chmod(0o755)
    bot = CodexAssistant(str(command), str(directory), timeout=2)
    assert await bot.ask("Привет") == "Ответ: Привет"
    assert await bot.ask("missing") == "Ответ: missing"
    assert bot.session_id == "spawn-session"
    try:
        await bot.ask("fail")
    except AssistantError as exc:
        assert "Not logged in" in str(exc)
    else:
        raise AssertionError("failed CLI did not report error")
    calls = [json.loads(row) for row in (directory / "calls.jsonl").read_text().splitlines()]
    assert sum(row["text"] == "missing" for row in calls) == 2
    assert sum(row["text"] == "fail" for row in calls) == 1, "auth errors must not repeat a task"
    bot.timeout = 0.3
    try:
        await bot.ask("slow")
    except AssistantError as exc:
        assert "не ответил" in str(exc)
    else:
        raise AssertionError("CLI timeout missing")
    pids = [int(pid) for pid in (directory / "pids").read_text().split()]
    await asyncio.sleep(0.05)
    assert not any(running(pid) for pid in pids), "timeout left CLI or child running"
    (directory / "pids").unlink()
    bot.timeout = 10
    task = asyncio.create_task(bot.ask("slow"))
    for _ in range(100):
        if (directory / "pids").exists(): break
        await asyncio.sleep(0.01)
    assert (directory / "pids").exists()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    pids = [int(pid) for pid in (directory / "pids").read_text().split()]
    await asyncio.sleep(0.05)
    assert not any(running(pid) for pid in pids), "cancellation left CLI or child running"
    print("  process: stdin, JSONL, missing session, auth error, timeout and process group cancellation OK")


async def run_bridge(directory):
    cfg = Config(tg_api_id=1, tg_api_hash="x", db=":memory:", photos_enabled=False,
                 tg_session=str(directory / "test.session"),
                 avatars=False, assistant_enabled=True, codex_enabled=True,
                 assistant_workdir=str(directory / "claude"), codex_workdir=str(directory / "codex"),
                 roster_limit=1)
    bridge = Bridge(cfg)
    assert Path(cfg.codex_workdir).is_dir()
    async def dialogs(): return []
    async def forbidden(*args, **kwargs): raise AssertionError("bot request reached Telegram")
    bridge.telegram.dialogs = dialogs
    bridge.telegram.send = bridge.telegram.set_typing = bridge.telegram.set_muted = forbidden
    sent, typing, questions = [], [], []
    async def deliver(uin, text, **kwargs): sent.append((uin, text, kwargs)); return True
    async def notify(uin, active): typing.append((uin, active))
    bridge.oscar.deliver, bridge.oscar.notify_typing = deliver, notify
    async def codex_run(argv, text): questions.append(("codex", text)); return result("Ответ Codex", "cx")
    async def claude_run(argv, text): questions.append(("claude", text)); return {"type":"result","result":"Ответ Claude","session_id":"cl"}
    bridge.codex = CodexAssistant(run=codex_run)
    bridge.assistant = Assistant(run=claude_run)
    await bridge.refresh_roster()
    cx, cl = (bridge.storage.contact_by_peer(peer) for peer in (CODEX_PEER, ASSISTANT_PEER))
    assert cx and cl and cx.uin != cl.uin and cx.title == "Codex" and cx.kind == "bot"
    assert {cx.uin,cl.uin} <= {c.uin for c in bridge.roster()}, "roster_limit displaced a bot"
    assert bridge.status_of(cx.uin) == C.STATUS_ONLINE
    assert bridge.group_paths(bridge.roster())[cx.uin] == "Боты"
    assert await bridge.on_phone_message(cx.uin, "вопрос Codex") == -1
    assert await bridge.on_phone_message(cl.uin, "вопрос Claude") == -1
    await asyncio.gather(*list(bridge._background))
    assert questions == [("codex","вопрос Codex"),("claude","вопрос Claude")]
    assert [(uin,text) for uin,text,_ in sent] == [(cx.uin,"Ответ Codex"),(cl.uin,"Ответ Claude")], sent
    assert typing == [(cx.uin,True),(cx.uin,False),(cl.uin,True),(cl.uin,False)]
    assert bridge.codex.session_id == "cx" and bridge.assistant.session_id == "cl"
    await bridge.on_phone_message(cx.uin,"!reset")
    await asyncio.gather(*list(bridge._background))
    assert bridge.codex.session_id is None and bridge.assistant.session_id == "cl"
    await bridge.on_phone_message(cx.uin,"!help")
    await asyncio.gather(*list(bridge._background))
    assert "Codex CLI" in sent[-1][1] and "!reset" in sent[-1][1]
    assert (await bridge.chat_info(cx.uin))["network"] == "Codex CLI"
    await bridge.on_phone_typing(cx.uin,True)
    await bridge.on_phone_privacy(cx.uin,True)
    await bridge.on_phone_remove(cx.uin,False)
    assert "Codex" in sent[-1][1] and not bridge.storage.contact_by_peer(CODEX_PEER).gone
    assert await bridge.fetch_history(cx.uin,1) is None
    await bridge.refresh_roster()
    assert not bridge.storage.contact_by_peer(CODEX_PEER).gone
    # Одинаковые номера картинок у двух ботов не пересекаются.
    for bot, color in ((bridge.codex,"red"),(bridge.assistant,"blue")):
        out = io.BytesIO(); Image.new("RGB",(5,5),color).save(out,format="PNG")
        path = directory / (color + ".png"); path.write_bytes(out.getvalue())
        bot._images[1] = str(path)
    one = await bridge.fetch_attachment(cx.uin,"photo:1")
    two = await bridge.fetch_attachment(cl.uin,"photo:1")
    assert one and two and one != two
    bridge.codex = None
    await bridge.on_phone_message(cx.uin,"выключен")
    await asyncio.gather(*list(bridge._background))
    assert "Codex выключен" in sent[-1][1]
    await bridge.refresh_roster()
    assert bridge.storage.contact_by_peer(CODEX_PEER).gone and not bridge.storage.contact_by_peer(ASSISTANT_PEER).gone
    # Остановка моста дожидается отмены задачи и убивает дерево Codex.
    bridge.codex = CodexAssistant(str(directory / "fake-codex"), cfg.codex_workdir, timeout=10)
    await bridge.on_phone_message(cx.uin,"slow")
    pids_file = Path(cfg.codex_workdir) / "pids"
    for _ in range(100):
        if pids_file.exists(): break
        await asyncio.sleep(0.01)
    assert pids_file.exists()
    async def stop(): bridge.telegram.client.session.close()
    bridge.telegram.stop = stop
    await bridge.close()
    pids = [int(pid) for pid in pids_file.read_text().split()]
    await asyncio.sleep(0.05)
    assert not any(running(pid) for pid in pids) and not bridge._background
    assert typing[-1] == (cx.uin,False), "shutdown must clear typing"
    print("  bridge: separate contacts/sessions/images, typing, commands, roster, disabled bot and no Telegram routing OK")


async def main():
    with tempfile.TemporaryDirectory(prefix="icq-codex-") as temp:
        directory = Path(temp)
        config = directory / "config.toml"
        config.write_text('[oscar]\nuin="100500"\n[telegram]\napi_id=1\napi_hash="x"\n[codex]\nenabled=true\nworkdir="cx"\nsandbox="workspace-write"\nsearch=false\nmodel="chosen-model"\n')
        cfg = Config.load(str(config))
        assert cfg.codex_workdir == str(directory / "cx") and cfg.codex_enabled
        assert cfg.codex_sandbox == "workspace-write" and not cfg.codex_search and cfg.codex_model == "chosen-model"
        assert not cfg.assistant_enabled and not Config().codex_enabled
        await run_adapter()
        await run_process(directory)
        await run_bridge(directory)
    if len(sys.argv)>1:
        cli = CodexAssistant(sys.argv[1])
        for session in (None,"0199a213-81c0-7800-8aa1-bbab2a035a53"):
            check = subprocess.run(cli.argv(session)+["--help"],capture_output=True,text=True)
            assert check.returncode == 0, check.stderr
        print("  real CLI: new/resume flags accepted (no model request)")
    print("CODEX BOT VERIFIED")


if __name__ == "__main__":
    asyncio.run(main())
