"""Real native worker/server transfer past the old 255-part ceiling, plain and TMME."""
import asyncio
import hashlib
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from bridge.config import Config
from bridge.db import Storage
from bridge.oscar.server import OscarServer, Session
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_network import compile_driver, Phone


async def scenario(executable, root, encrypted, maximum_mb, size, capable=True):
    cfg = Config(oscar_host="127.0.0.1", oscar_port=0, oscar_uin="12345", oscar_password="test",
                 bos_host="127.0.0.1", oscar_psk="1234")
    storage = Storage(":memory:")
    who = storage.uin_for_peer(100, kind="user", title="Video", group_name="Test")
    raw = (bytes(range(256)) * ((size + 255) // 256))[:size]

    async def outgoing(*_): return 1
    async def video(*_): return raw
    async def photo(*_): return b"photo" * 3000
    server = OscarServer(cfg, storage, outgoing, storage.contacts, fetch_video=video,
                         fetch_attachment=photo)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]
    cfg.oscar_port = cfg.bos_port = port
    cache = root / f"cache-{encrypted}-{maximum_mb}-{capable}"
    cache.mkdir()
    env = dict(os.environ, TMM_TEST_MAX_MEDIA="1024")
    if capable:
        env["TMM_TEST_LARGE_VIDEO"] = str(maximum_mb)
    process = await asyncio.create_subprocess_exec(str(executable), str(port), str(int(encrypted)), "1", str(cache),
                                                    stdin=asyncio.subprocess.PIPE,
                                                    stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE, env=env)
    phone = Phone(process)
    try:
        await phone.wait(lambda e: e.get("type") == 0 and e.get("state") == 2)
        token = server.register_attachment(who, "video:1")
        await phone.command(7, 101, who, token=token)
        event = await phone.wait(lambda e: e.get("id") == 101 and e.get("type") in (9, 12), timeout=40)
        success = capable and size <= maximum_mb * 1024 * 1024
        assert (event["type"] == 9) == success, event
        if success:
            result = Path(event["path"])
            assert result.stat().st_size == size
            assert hashlib.sha256(result.read_bytes()).digest() == hashlib.sha256(raw).digest()
            assert server.session.media["bart_parts16"]
            assert server.session.media["video_max_kb"] == maximum_mb * 1024
            # Video-specific override must not raise the separate photo limit.
            await phone.command(6, 102, who, token=server.register_attachment(who, "photo:1"))
            error = await phone.wait(lambda e: e.get("id") == 102 and e.get("type") == 12)
            assert "лимит" in error["text"], error
        await phone.command(2, 103, mode=1)
        assert (await phone.response(103, 13))["flag"]
        print(f"large video: encrypted={encrypted}, limit={maximum_mb} MiB, bytes={size}, "
              f"capable={capable}, success={success}, connection retained")
    finally:
        if process.returncode is None:
            process.stdin.write(b"quit\n")
            await process.stdin.drain()
            await asyncio.wait_for(process.wait(), 5)
        await server.stop()
        storage.close()


async def main():
    # A legacy secondary connection must not inherit the main native client's
    # optional packet format when only its device/heap profile is shared.
    owner = SimpleNamespace(media={"bart_parts16": True}, profile_name="v8", device=None)
    legacy_service = SimpleNamespace(service_only=True, media={}, server=SimpleNamespace(session=owner))
    assert Session._bart_part_size(legacy_service, 16 * 1024 * 1024) > 60000
    with tempfile.TemporaryDirectory(prefix="native-large-video-") as temp:
        root = Path(temp)
        binary = root / "network-test"
        compile_driver(binary)
        for encrypted in (False, True):
            await scenario(binary, root, encrypted, 32, 16 * 1024 * 1024 + 123)
        await scenario(binary, root, False, 1, 1024 * 1024 + 1)
        await scenario(binary, root, False, 32, 16 * 1024 * 1024 + 123, capable=False)
    print("LARGE VIDEO TRANSFER PASS")


if __name__ == "__main__":
    asyncio.run(main())
