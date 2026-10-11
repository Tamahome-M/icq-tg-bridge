"""Downloads remain available when release files arrive after bridge startup."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bridge.photos import PhotoStore
from bridge.webserver import PhotoServer


class DownloadsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="tmm-downloads-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dist = self.root / "telemotomax/dist"
        self.server = PhotoServer(PhotoStore(str(self.root / "photos")), "127.0.0.1", 0,
                                  password="private", client_dir=str(self.dist))
        self.addAsyncCleanup(self.server.stop)
        await self.server.start()
        self.port = self.server._server.sockets[0].getsockname()[1]

    async def get(self, path):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        try:
            writer.write(f"GET {path} HTTP/1.1\r\nHost: phone\r\n\r\n".encode())
            await writer.drain()
            raw = await asyncio.wait_for(reader.read(), timeout=5)
        finally:
            writer.close()
            await writer.wait_closed()
        head, _, body = raw.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        headers = dict(line.lower().split(": ", 1) for line in lines[1:] if ": " in line)
        return int(lines[0].split()[1]), headers, body

    def install_clients(self):
        self.dist.mkdir(parents=True)
        pairs = {}
        for base in ("TeleMotoMax", "TeleMotoMax-Light", "TeleMotoMax-V8"):
            pairs[f"{base}.jar"] = b"PK\x03\x04" + base.encode()
            pairs[f"{base}.jad"] = f"MIDlet-Name: {base}\nMIDlet-Jar-URL: {base}.jar\n".encode()
        for name, data in pairs.items():
            (self.dist / name).write_bytes(data)
        return pairs

    async def test_missing_clients_appear_without_restart(self):
        status, _, home = await self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b'href="/d/"', home)
        status, _, index = await self.get("/d/")
        self.assertEqual(status, 200)
        self.assertIn("Пусто.".encode(), index)
        self.assertEqual((await self.get("/d/TeleMotoMax.jar"))[0], 404)

        pairs = self.install_clients()
        status, _, index = await self.get("/d/")
        self.assertEqual(status, 200)
        for name, expected in pairs.items():
            self.assertIn(f'href="/d/{name}"'.encode(), index)
            status, headers, body = await self.get("/d/" + name)
            self.assertEqual(status, 200)
            self.assertEqual(body, expected)
            mime = "application/java-archive" if name.endswith(".jar") else "text/vnd.sun.j2me.app-descriptor"
            self.assertEqual(headers["content-type"], mime)
        home = (await self.get("/"))[2]
        self.assertIn(b'href="/d/TeleMotoMax-Light.jad"', home)

    async def test_late_clients_respect_downloads_password(self):
        self.server.downloads_protected = True
        self.assertEqual((await self.get("/d/"))[0], 401)
        self.install_clients()
        self.assertEqual((await self.get("/d/TeleMotoMax.jar"))[0], 401)
        status, _, body = await self.get("/d/TeleMotoMax.jar?key=private")
        self.assertEqual(status, 200)
        self.assertEqual(body, (self.dist / "TeleMotoMax.jar").read_bytes())

    async def test_unconfigured_downloads_and_invalid_paths_stay_unavailable(self):
        self.server.client_dir = ""
        self.assertEqual((await self.get("/d/?key=private"))[0], 404)
        self.assertNotIn(b'href="/d/"', (await self.get("/"))[2])
        self.server.client_dir = str(self.dist)
        self.install_clients()
        for path in ("/d/../outside.jar", "/d/%2e%2e/outside.jar", "/d/.secret", "/d/sub/file.jar"):
            self.assertEqual((await self.get(path))[0], 404, path)


if __name__ == "__main__":
    unittest.main()
