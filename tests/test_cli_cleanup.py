"""Real CLI parent/child cleanup during startup, timeout and repeated cancel."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bridge.assistant import Assistant, AssistantError
from bridge.codex import CodexAssistant


def running(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except FileNotFoundError:
        return False


async def ids_ready(directory):
    path = directory/'ids.json'
    async with asyncio.timeout(2):
        while not path.exists():
            await asyncio.sleep(.005)
    return json.loads(path.read_text())


async def stopped(ids):
    async with asyncio.timeout(1):
        while any(running(pid) for pid in ids):
            await asyncio.sleep(.005)


async def exercise(bot_class, mode):
    with tempfile.TemporaryDirectory(prefix='tmm-cli-cleanup-') as temp:
        directory = Path(temp)
        command = directory/'fake-cli'
        command.write_text(f"#!{sys.executable}\n" + """import json, os, subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
Path('ids.tmp').write_text(json.dumps([os.getpid(), child.pid]))
os.replace('ids.tmp', 'ids.json')
time.sleep(30)
""")
        command.chmod(0o700)
        bot = bot_class(str(command), str(directory), timeout=.15 if mode == 'timeout' else 10)
        entered, release = asyncio.Event(), asyncio.Event()
        loop = asyncio.get_running_loop()
        connect_pipe = loop.connect_write_pipe
        create_process = asyncio.create_subprocess_exec
        cleanup_done = False

        async def blocked_pipe(*args, **kwargs):
            value = await connect_pipe(*args, **kwargs)
            entered.set()
            await release.wait()
            return value

        async def tracked_process(*args, **kwargs):
            proc = await create_process(*args, **kwargs)
            communicate = proc.communicate
            calls = 0

            async def blocked_cleanup(input=None):
                nonlocal calls, cleanup_done
                calls += 1
                if calls > 1:
                    entered.set()
                    await release.wait()
                value = await communicate(input)
                if calls > 1:
                    cleanup_done = True
                return value

            proc.communicate = blocked_cleanup
            return proc

        if mode == 'startup':
            context = patch.object(loop, 'connect_write_pipe', blocked_pipe)
        elif mode == 'cleanup':
            context = patch.object(asyncio, 'create_subprocess_exec', tracked_process)
        else:
            from contextlib import nullcontext
            context = nullcontext()
        task = None
        ids = []
        try:
            with context:
                task = asyncio.create_task(bot.ask('test'))
                ids = await ids_ready(directory)
                if mode == 'startup':
                    await asyncio.wait_for(entered.wait(), 1)
                if mode != 'timeout':
                    task.cancel()
                    if mode == 'cleanup':
                        await asyncio.wait_for(entered.wait(), 1)
                    await asyncio.sleep(.01)
                    task.cancel()
                    await asyncio.sleep(.01)
                    assert not task.done(), 'repeated cancellation interrupted resource cleanup'
                    release.set()
                result, = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 2)
                if mode == 'timeout':
                    assert isinstance(result, AssistantError) and 'не ответил' in str(result), result
                else:
                    assert isinstance(result, asyncio.CancelledError), result
                await stopped(ids)
                if mode == 'cleanup':
                    assert cleanup_done, 'pipe draining did not finish after repeated cancel'
            print(f'PASS: {bot_class.__name__} {mode}, parent/child stop and cancellation preserved')
        finally:
            release.set()
            if ids and any(running(pid) for pid in ids):
                try:
                    os.killpg(ids[0], signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


async def main():
    for bot in (Assistant, CodexAssistant):
        for mode in ('startup', 'cleanup', 'timeout'):
            await exercise(bot, mode)
    # Failure before a PID exists must retain its original OSError.
    bot = Assistant()
    try:
        await bot._communicate(['/nonexistent/tmm-cli'], 'test', dict(os.environ))
    except FileNotFoundError:
        print('PASS: failed spawn reports the original error, no orphan startup/cleanup task')
    else:
        raise AssertionError('spawn failure was hidden')


if __name__ == '__main__':
    asyncio.run(main())
