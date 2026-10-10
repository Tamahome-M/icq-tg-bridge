"""Resource bounds in the real bridge adapters, photo decoder and BART sender."""
import asyncio
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace as NS
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image
import playwright
from bridge import photos, avatars, profiles, render
from bridge.assistant import Assistant
from bridge.config import Config
from bridge.db import Storage
from bridge.oscar import const as C
from bridge.oscar.proto import Reader, Snac, ProtocolError
from bridge.oscar.server import Session, OscarServer
from bridge.max.client import MaxSide, to_peer
from bridge.express.client import ExpressSide, chat_peer
from bridge.express.web import JS_BLOBS
from tests.test_express import FakeExpress, raw_event, GROUP, PERSONAL, BOSS
from tests.test_photos import noisy_jpeg
from tests.test_session_cleanup import BrokenWriter
from bridge.webserver import PhotoServer, FileBody


def jpeg_memory():
    raw = io.BytesIO()
    Image.new("RGB", (6000, 4000), (20, 60, 80)).save(raw, "JPEG")
    loaded = []
    original = Image.Image.load
    def track(image, *args, **kw):
        loaded.append(image.size)
        return original(image, *args, **kw)
    with patch.object(Image.Image, "load", track):
        got = photos.shrink(raw.getvalue(), 176, 220, 7000)
        icon = avatars.convert(raw.getvalue(), 64, 4096)
    assert got and icon and got[1] <= 176 and got[2] <= 220
    assert loaded and max(w * h for w, h in loaded) <= 750 * 500, loaded
    noise = noisy_jpeg(176, 144)
    got = photos.shrink(noise, 176, 144, 1000)
    assert got and len(got[0]) <= 1000 and got[1] < 176
    assert photos.shrink(noise, 176, 144, 10) is None
    # The encoder still writes a baseline JPEG accepted by the old decoder.
    with Image.open(io.BytesIO(got[0])) as image:
        assert not image.info.get("progressive") and image.size == got[1:]
    print("PASS: 24-MP JPEG decodes at <=0.375 MP before RGB/EXIF; noisy photos obey byte budget; impossible limits fail; baseline JPEG retained")


def blobs():
    node = Path(playwright.__file__).parent / "driver/node"
    source = """const assert=require('assert'), fs=require('fs');
const script=JSON.parse(fs.readFileSync(0,'utf8'));let id=0;const revoked=[];
global.window={};global.Blob=class{constructor(size){this.size=size;this.type='test';}};
global.URL={createObjectURL:()=> 'blob:'+ ++id,revokeObjectURL:url=>revoked.push(url)};
eval(script);
for(let i=0;i<100;i++)URL.createObjectURL(new Blob(1024*1024));
assert.equal(window.__exBlobs.length,30);
URL.createObjectURL(new Blob(20*1024*1024));
assert(window.__exBlobs.reduce((n,b)=>n+b.size,0)<=32*1024*1024);
const large=URL.createObjectURL(new Blob(100*1024*1024));
assert.equal(window.__exBlobs.length,1);assert.equal(window.__exBlobs[0].url,large);
URL.revokeObjectURL(large);assert.equal(window.__exBlobs.length,0);assert.deepEqual(revoked,[large]);
eval(script);URL.createObjectURL(new Blob(1));assert.equal(window.__exBlobs.length,1);
console.log('PASS: actual browser Blob hook bounds count/bytes, retains only one large file, releases revoked URLs; initialization is idempotent');
"""
    subprocess.run([str(node), "-e", source], input=json.dumps(JS_BLOBS), text=True,
                   check=True, timeout=10)


async def adapters():
    client = FakeExpress()
    side = ExpressSide(Config(), None, client=client)
    await side._all_chats()
    other = client.message(raw_event(99, GROUP, BOSS, "other chat"))
    number = side._remember(other)
    assert await side._message(chat_peer(PERSONAL), number) is None
    assert side._cached_message(chat_peer(GROUP), number) is other

    class Maximum:
        next_id = 0
        async def send_message(self, chat, text, **kw):
            self.next_id += 1
            return NS(id=self.next_id, time=self.next_id + 1000)
        async def forward_message(self, **kw):
            return await self.send_message(kw["chat_id"], "forward")
    maximum = Maximum()
    side = MaxSide(Config(), None, client=maximum)
    for i in range(505):
        await side.send_photo(to_peer(10), b"jpeg")
    assert len(side._own_ids) == 500 and (10, 1) not in side._own_ids
    for kind, args in [("send_voice", (b"voice",)), ("send_video", (b"video",)),
                       ("send_document", ("unused", "file.bin")), ("send", ("hello",))]:
        await getattr(side, kind)(to_peer(10), *args)
        assert len(side._own_ids) == 500
    number = await side.quote(to_peer(10), to_peer(20), 123)
    assert (10, number) in side._own_ids and len(side._own_ids) == 500
    side._remember_own(10, 6)
    side._remember_own(10, 999)
    assert (10, 6) in side._own_ids and len(side._own_ids) == 500
    print("PASS: eXpress attachment cache cannot serve another chat; all MAX send paths bound echo cache, native forwards suppress echo")


async def bart():
    storage = Storage(":memory:")
    server = OscarServer(Config(), storage, None, storage.contacts)
    main = Session(server, None, BrokenWriter(None))
    service = Session(server, None, BrokenWriter(None))
    service.service_only = True
    server.session = main
    replies = []
    async def capture(family, subtype, body=b"", **kw):
        replies.append((family, subtype, body, kw))
        return True
    service.send_snac = capture
    data = bytes(range(256)) * 600
    try:
        for profile, expected in [("v3", 12*1024), ("v8", C.VIDEO_PART_BYTES), ("", C.VIDEO_PART_BYTES)]:
            replies.clear();main.profile_name = profile
            main.device = profiles.Device("j2me", 176 if profile=="v3" else 240, 220, 781 if profile=="v3" else 8192)
            await service._send_bart_parts(1000001, b"t"*16, data, C.BART_VOICE, 42)
            chunks = [];total = len(replies)
            for i, (family, subtype, body, kw) in enumerate(replies, 1):
                r = Reader(body);assert r.pstr8() == b"1000001"
                assert r.u16() == C.BART_VOICE and r.u8() == i
                assert r.pstr8() == b"t"*16 and r.u8() == 0 and r.u16() == C.BART_VOICE
                assert r.u8() == total and r.pstr8() == b"t"*16
                chunks.append(r.pstr16());assert not r.left
                assert len(chunks[-1]) <= expected and kw["request_id"] == 42
            assert b"".join(chunks) == data
        main.device = profiles.Device("j2me", 176, 220, 781)
        assert service._bart_part_size(500_000) == 12*1024
        assert service._bart_part_size(4_000_000)*255 >= 4_000_000
        main.device = None; main.profile_name = ""
        assert service._bart_part_size(500_000) == C.VIDEO_PART_BYTES
        await service.on_icon_request(Snac(C.SSBI, C.SSBI_ICQ_REQ, 0, 10, b""))
        replies.clear()
        await service._send_bart_parts(1000001, b"t"*16, b"x"*(C.VIDEO_PART_BYTES*255+1), C.BART_FILE, 43)
        assert len(replies) == 1 and replies[0][1] == 1
    finally:
        storage.close()
    print("PASS: BART uses main phone's live profile, 12-KiB V3 parts, legacy/V8 60-KB parts, byte-exact ordering, 255-part limits and malformed requests")


async def main():
    await adapters()
    await bart()
    await cleanup()
    await worker_limit()
    await http_buffers()
    protocol_bounds()


async def cleanup():
    storage = Storage(":memory:")
    server = OscarServer(Config(oscar_host="127.0.0.1", oscar_port=0), storage, None, storage.contacts)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]
    readers = []
    try:
        for _ in range(2):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            await reader.readexactly(10)
            readers.append((reader, writer))
        sessions = list(server._sessions)
        assert len(sessions) == 2
        sessions[0].service_only = sessions[0].authorized = True
        await server.stop()
        for reader, _ in readers:
            assert await asyncio.wait_for(reader.read(), 1) == b""
        await asyncio.sleep(.02)
        assert not server._sessions and not server._own_tasks and server.access.connections == 0
        assert all(not s._tasks for s in sessions)
    finally:
        for _, writer in readers:
            writer.close(); await writer.wait_closed()
        await server.stop(); storage.close()

    with tempfile.TemporaryDirectory() as temp:
        web = PhotoServer(photos.PhotoStore(temp), "127.0.0.1", 0)
        await web.start();port = web._server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            await writer.drain(); await asyncio.sleep(.02)
            assert web._writers
            await asyncio.wait_for(web.stop(), 1)
            assert await asyncio.wait_for(reader.read(), 1) == b""
            await asyncio.sleep(.02)
            assert not web._writers and web.access.connections == 0
        finally:
            writer.close(); await writer.wait_closed(); await web.stop()

    # A fake CLI spawns a child and writes only its PID file. Cancellation
    # must stop the whole process group; no real bot/account is contacted.
    with tempfile.TemporaryDirectory(prefix="tmm-cancel-bot-") as temp:
        directory = Path(temp); script = directory / "fake-claude"
        script.write_text(f"#!{sys.executable}\n" + """import json, os, subprocess, sys, time
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
open('ids.json','w').write(json.dumps([os.getpid(), child.pid]))
time.sleep(60)
""")
        script.chmod(0o700)
        bot = Assistant(str(script), str(directory), tools="", timeout=30)
        task = asyncio.create_task(bot.ask("test"))
        try:
            for _ in range(200):
                if (directory / "ids.json").exists(): break
                await asyncio.sleep(.01)
            assert (directory / "ids.json").exists(), "CLI did not start"
            ids = json.loads((directory / "ids.json").read_text())
            task.cancel()
            await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 2)
            for pid in ids:
                stat = Path(f"/proc/{pid}/stat")
                assert not stat.exists() or stat.read_text().split()[2] == "Z", "CLI process survived cancellation"
        finally:
            task.cancel(); await asyncio.gather(task, return_exceptions=True)

    class Probe:
        returncode = None
        killed = False
        async def communicate(self):
            if not self.killed: await asyncio.Event().wait()
            return b"", b""
        def kill(self): self.killed = True; self.returncode = -9
    probe = Probe()
    async def create(*args, **kw): return probe
    transcoder = render.Transcoder("resource-test-probe")
    with patch.object(render.asyncio, "create_subprocess_exec", create):
        task = asyncio.create_task(transcoder.encoders()); await asyncio.sleep(.01)
        task.cancel(); await asyncio.gather(task, return_exceptions=True)
    assert probe.killed and "resource-test-probe" not in render._ENCODERS
    print("PASS: stop closes unauthenticated/BART sockets, timers and sender; cancellation kills CLI process group and encoder probe")


async def worker_limit():
    storage = Storage(":memory:")
    server = OscarServer(Config(), storage, None, storage.contacts)
    session = Session(server, None, BrokenWriter(None)); session.authorized = True
    gate = asyncio.Event(); errors = []
    async def delayed(s): await gate.wait()
    async def failure(*args): errors.append(args)
    session.on_icon_request = delayed; session.send_error = failure
    try:
        for number in range(5):
            await session.handle_snac(Snac(C.SSBI, C.SSBI_ICQ_REQ, 0, number+1, b""))
        assert session._media_jobs == 4 and len(session._tasks) == 4
        assert errors and errors[0][2] == 5 and errors[0][3]
        # The slow jobs never occupy the OSCAR reading loop.
        await session.handle_flap(5, b"")
        assert session.pings_seen == 1
        gate.set(); await asyncio.gather(*session._tasks); await asyncio.sleep(0)
        assert session._media_jobs == 0
    finally:
        gate.set(); await session.close(); storage.close()
    print("PASS: four simultaneous heavy jobs stay bounded; excess request gets its own visible error; pings continue")


async def http_buffers():
    class Writer:
        def __init__(self): self.data=[];self.drains=0
        def write(self, data): self.data.append(data)
        async def drain(self): self.drains+=1
        def close(self): pass
        async def wait_closed(self): pass
    with tempfile.TemporaryDirectory() as temp:
        server = PhotoServer(photos.PhotoStore(temp), "localhost", 0)
        body = b"v"*1_000_000; writer = Writer()
        assert await server._reply(writer, 200, "video/3gpp", body)
        wire = b"".join(writer.data); header, actual = wire.split(b"\r\n\r\n", 1)
        assert actual == body and b"Content-Length: 1000000" in header
        assert max(map(len,writer.data)) <= 16*1024 and writer.drains > 60
        assert all(part.obj is body for part in writer.data[1:])
        writer = Writer(); assert await server._reply(writer, 200, "video/3gpp", body, True)
        assert len(writer.data) == 1 and b"Content-Length: 1000000" in writer.data[0]
        path = Path(temp) / "large.3gp";path.write_bytes(body)
        writer = Writer()
        assert await server._reply(writer, 206, "video/3gpp", FileBody(path, 15000, 20000))
        assert b"".join(writer.data).split(b"\r\n\r\n",1)[1] == body[15000:35000]
        assert max(map(len,writer.data)) <= 16*1024
        # Header-only responses must not load or even open the asset.
        writer = Writer(); descriptor = FileBody(path)
        with patch("builtins.open", side_effect=AssertionError("HEAD opened file")):
            assert await server._reply(writer, 200, "video/3gpp", descriptor, True)
        server.downloads_dir = temp
        assert server._find("/d/large.3gp", as_path=True)[0] == path
    print("PASS: HTTP writes bounded zero-copy slices with backpressure; byte-exact body, MIME/length and HEAD preserved")


def protocol_bounds():
    import struct
    header = struct.pack(">HHHI", C.ICBM, C.ICBM_SEND, 0x8001, 42)
    assert Snac.parse(header + b"\0\2xxbody").data == b"body"
    for data in (b"", b"x", b"\0\3xx"):
        try: Snac.parse(header + data)
        except ProtocolError: pass
        else: raise AssertionError("truncated SNAC extensions accepted")
    print("PASS: SNAC extension flag combinations and truncated lengths validated")


if __name__ == "__main__":
    jpeg_memory()
    blobs()
    asyncio.run(main())
