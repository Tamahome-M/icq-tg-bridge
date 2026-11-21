"""Exercise the native BOS watchdog over real TCP with the bridge's normal packet handlers."""
import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import shlex
import signal
import tempfile
from unittest.mock import patch

from test_network import C, Config, OscarServer, Phone, Storage, compile_driver


async def wait_for(test, timeout=4):
    async def poll():
        while not test():
            await asyncio.sleep(.02)
    await asyncio.wait_for(poll(), timeout)


async def control(phone, line, key):
    phone.p.stdin.write((line + "\n").encode())
    await phone.p.stdin.drain()
    return await phone.wait(lambda event: key in event)


@asynccontextmanager
async def connected(driver, directory, encrypted, **env):
    config = Config(oscar_host="127.0.0.1", oscar_port=0, bos_host="127.0.0.1",
                    oscar_uin="12345", oscar_password="test", oscar_psk="1234")
    store = Storage(":memory:")
    who = store.uin_for_peer(100, kind="user", title="Ping", group_name="Telegram")
    async def outgoing(*_): return 1
    async def info(_): return {"title": "Ping"}
    server = OscarServer(config, store, outgoing, store.contacts, chat_info=info)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]
    config.oscar_port = config.bos_port = port
    process = await asyncio.create_subprocess_exec(
        *driver, str(port), str(int(encrypted)), "1", str(directory),
        env=dict(os.environ, **env), stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    phone = Phone(process)
    try:
        await phone.wait(lambda e: e.get("type") == 0 and e["state"] == 2)
        # Drain any startup announcements before simulating one-way packet loss.
        await phone.command(13, 11, who)
        await phone.response(11, 8)
        yield phone, server, who
    finally:
        if process.returncode is None:
            process.stdin.write(b"quit\n")
            await process.stdin.drain()
            try:
                await asyncio.wait_for(process.wait(), 5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise
        await server.stop()
        store.close()


async def awake_after_video(driver, folder, encrypted, *, stopped_clock=False, **env):
    async with connected(driver, folder, encrypted, **env) as (phone, server, who):
        session = server.session
        async def history(*_):
            return ([("Ping\nПроверка истории", "", False, 0, 90)], False)
        async def attachment(*_):
            raise AssertionError("delivery of a video message must not fetch its preview")
        server.fetch_history = history
        server.fetch_attachment = attachment
        await wait_for(lambda: session.pings_seen >= 2)
        await server.deliver(who, "[видео]", attach="video:91", message_id=91)
        message = await phone.wait(lambda e: e.get("type") == 3 and e.get("messages")
                                   and e["messages"][0]["kind"] == C.ATTACH_VIDEO)
        assert len(bytes.fromhex(message["messages"][0]["token"])) == 16
        await wait_for(lambda: server.ack_works and not server.storage.peek_pending())
        if stopped_clock:
            await control(phone, "freeze-clock", "clockStopped")
        before = session.pings_seen
        await phone.command(3, 15, who, limit=1)
        page = await phone.response(15, 6)
        assert "Проверка истории" in page["messages"][0]["text"]
        await wait_for(lambda: session.pings_seen >= before + 3, timeout=5)
        assert server.session is session and not session.closed
    log = (await phone.p.stderr.read()).decode()
    if env.get("TMM_TEST_RTC_DENIED"):
        assert "RTC_SW_SETTIME" in log and "software, 1 s, rtc_sw off" in log, log
    elif env.get("TMM_TEST_RTC"):
        assert log.count("rtc_sw, 1 s, rtc_sw on") >= 3 and "RTC_SW_JOB_DONE" not in log, log


async def paused_worker(driver, folder, encrypted, **env):
    async with connected(driver, folder, encrypted, **env) as (phone, server, who):
        session = server.session
        before = session.pings_seen
        os.kill(phone.p.pid, signal.SIGSTOP)
        try:
            # Longer than three one-second intervals, on a healthy connection.
            await asyncio.sleep(3.4)
        finally:
            os.kill(phone.p.pid, signal.SIGCONT)
        await wait_for(lambda: session.pings_seen > before or session.closed)
        assert not session.closed, "elapsed sleep was counted as unanswered pings"
        await phone.command(13, 12, who)
        await phone.response(12, 8)
        assert session.pings_seen == before + 1, "overdue probes were sent in a burst"


def wire_writer(session):
    return session.writer.raw if session.encrypted else session.writer


async def slow_video(driver, folder, encrypted):
    async with connected(driver, folder, encrypted) as (phone, server, who):
        session = server.session
        writer = wire_writer(session)
        send = writer.write
        pending = bytearray()
        started = asyncio.Event()
        video = bytes(range(256)) * 100

        async def fetch(*_):
            started.set()
            return video

        def slow_write(data):
            if started.is_set():
                pending.extend(data)
            else:
                send(data)

        server.fetch_video = fetch
        server.fetch_attachment = fetch
        token = server.register_attachment(who, "video:1")
        with patch.object(writer, "write", slow_write):
            await phone.command(7, 13, who, token=token)
            await wait_for(lambda: len(pending) > len(video))
            before = session.pings_seen
            for _ in range(16):
                # Neither the FLAP body nor the first encrypted record completes.
                send(bytes(pending[:8]))
                del pending[:8]
                await asyncio.sleep(.24)
            assert session.pings_seen >= before + 2, "pings stopped inside a partial video frame"
            send(bytes(pending))
        media = await phone.response(13, 9)
        assert Path(media["path"]).read_bytes() == video
        assert server.session is session and not session.closed


async def silent_server(driver, folder, encrypted, misses, **env):
    async with connected(driver, folder, encrypted, TMM_TEST_DISABLE_KEEPALIVE="1",
                         TMM_TEST_RECONNECT="1", **env) as (phone, server, _):
        session = server.session
        assert not session.pings_seen
        times = []
        handle = session.handle_flap
        clock = asyncio.get_running_loop().time

        async def observe(channel, payload):
            if channel == 5:
                times.append(clock())
            await handle(channel, payload)

        if misses == 3:
            # Leave the reader waiting inside a FLAP header (or TMME length).
            # A stopped transfer must still detect a genuine half-open socket.
            wire_writer(session).write(b"\x00" if encrypted else b"*")
        with patch.object(session, "handle_flap", observe), patch.object(wire_writer(session), "write"):
            await control(phone, f"pings 1 {misses}", "configured")
            failure = await phone.wait(lambda e: e.get("type") == 12 and not e["id"])
            assert "пинг" in failure["text"], failure
            assert len(times) == misses and clock() - times[-1] >= .85, times
        await phone.wait(lambda e: e.get("type") == 0 and e["state"] == 3)
        await phone.wait(lambda e: e.get("type") == 0 and e["state"] == 2)
        await wait_for(lambda: server.session and server.session is not session
                       and server.session.pings_seen > 0)


async def busy_ui(driver, folder, encrypted):
    async with connected(driver, folder, encrypted, TMM_TEST_MISSED_PINGS="1") as (phone, server, who):
        session = server.session
        assert session.pings_seen, "first keepalive missing after login"
        await control(phone, "hold-events", "draining")
        for _ in range(140):  # More than the worker's 128-event queue.
            await session.notify_status(who, C.STATUS_AWAY)
        before = session.pings_seen
        await wait_for(lambda: session.pings_seen >= before + 3, timeout=5)
        await control(phone, "drain-events", "draining")
        await phone.command(13, 14, who)
        await phone.response(14, 8)
        updates = [e for e in phone.events if e.get("type") == 2 and e["uin"] == who
                   and e["contacts"][0]["status"] == C.STATUS_AWAY]
        assert len(updates) == 140, len(updates)
        await control(phone, "pings 0 1", "configured")
        await phone.command(13, 15, who)
        await phone.response(15, 8)
        before = session.pings_seen
        await asyncio.sleep(1.6)
        assert session.pings_seen == before and not session.closed


async def main():
    with tempfile.TemporaryDirectory(prefix="tmm-native-pings-") as directory:
        root = Path(directory)
        if os.environ.get("TMM_NETWORK_DRIVER"):
            driver = shlex.split(os.environ["TMM_NETWORK_DRIVER"])
        else:
            binary = root / "network-test"
            compile_driver(binary, rtc_adapter=True)
            driver = [str(binary)]
        for encrypted in (False, True):
            cases = (paused_worker, slow_video, busy_ui, awake_after_video)
            runs = [case(driver, root / case.__name__, encrypted) for case in cases]
            runs += [silent_server(driver, root, encrypted, n) for n in (1, 3)]
            runs.append(awake_after_video(driver, root / "stalled", encrypted, stopped_clock=True))
            if not os.environ.get("TMM_NETWORK_DRIVER"):  # host-only Motorola driver adapter
                runs.append(paused_worker(driver, root / "delayed-rtc", encrypted, TMM_TEST_RTC="1"))
                runs.append(silent_server(driver, root, encrypted, 3, TMM_TEST_RTC="1"))
                runs.append(awake_after_video(driver, root / "rtc", encrypted, stopped_clock=True,
                                              TMM_TEST_RTC="1", TMM_TEST_FROZEN_WALL="1"))
                runs.append(awake_after_video(driver, root / "denied", encrypted, stopped_clock=True,
                                              TMM_TEST_RTC="1", TMM_TEST_RTC_DENIED="1"))
            await asyncio.gather(*runs)
            print("PASS native keepalive", "TMME" if encrypted else "plain",
                  "video ACK, history, idle, stalled clocks, RTC, resume, fragmented input, UI backlog, reconnect")


if __name__ == "__main__":
    asyncio.run(main())
