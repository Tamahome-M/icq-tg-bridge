"""A stalled HTTP download must release its connection; slow progress is allowed."""

import asyncio
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bridge.photos import PhotoStore
from bridge.webserver import FileBody, PhotoServer


class Writer:
    def __init__(self, stall="", delay=0):
        self.stall, self.delay = stall, delay
        self.aborted = self.closed = False
        self._closed_wait = None
        self._buffer = 0
        self.transport = SimpleNamespace(abort=self.abort, get_write_buffer_size=lambda: self._buffer)
        self.data = bytearray()

    def write(self, data):
        self.data.extend(data)
        self._buffer += len(data)

    def get_extra_info(self, key):
        return ("127.0.0.1", 12345)

    async def drain(self):
        if self.stall == "drain":
            await asyncio.Future()
        await asyncio.sleep(self.delay)
        self._buffer = 0

    def close(self):
        self.closed = True

    async def wait_closed(self):
        if self.stall == "close" and not self.aborted:
            self._closed_wait = asyncio.Future()
            await self._closed_wait

    def abort(self):
        self.aborted = True
        self._buffer = 0
        if self._closed_wait is not None and not self._closed_wait.done():
            self._closed_wait.set_result(None)


class HttpStall(unittest.IsolatedAsyncioTestCase):
    async def test_one_slow_drain_or_close_with_buffer_progress_is_allowed(self):
        class ProgressWriter(Writer):
            async def progress(self):
                # Each wait is four timeout intervals long, but never idle.
                for _ in range(12):
                    await asyncio.sleep(.01)
                    self._buffer = max(0, self._buffer - 1)

            async def drain(self):
                if self.stall == "drain" and self._buffer:
                    await self.progress()

            async def wait_closed(self):
                if self.stall == "close":
                    await self.progress()

        with tempfile.TemporaryDirectory() as folder:
            server = PhotoServer(PhotoStore(folder), "127.0.0.1", 0)
            for operation in ("drain", "close"):
                with self.subTest(operation=operation):
                    writer = ProgressWriter(operation)
                    with patch("bridge.webserver.WRITE_TIMEOUT", .03):
                        sent = await server._reply(writer, 200, "text/plain", b"slow")
                    self.assertTrue(sent)
                    self.assertFalse(writer.aborted)

    async def test_stalled_send_and_close_are_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            server = PhotoServer(PhotoStore(folder), "127.0.0.1", 0)
            path = Path(folder) / "download.jar"
            path.write_bytes(b"x" * 65536)
            for stall, body in (("drain", b"photo"), ("drain", FileBody(path)), ("close", b"page")):
                with self.subTest(stall=stall, file=isinstance(body, FileBody)):
                    writer = Writer(stall)
                    with patch("bridge.webserver.WRITE_TIMEOUT", 0.01, create=True):
                        sent = await asyncio.wait_for(server._reply(writer, 200, "application/octet-stream", body), .2)
                    self.assertFalse(sent)
                    self.assertTrue(writer.aborted)

    async def test_download_progress_can_outlast_one_timeout_interval(self):
        with tempfile.TemporaryDirectory() as folder:
            server = PhotoServer(PhotoStore(folder), "127.0.0.1", 0)
            writer = Writer(delay=.01)
            body = b"x" * (16 * 1024 * 8)
            with patch("bridge.webserver.WRITE_TIMEOUT", .05, create=True):
                sent = await server._reply(writer, 200, "application/octet-stream", body)
            self.assertTrue(sent)
            self.assertFalse(writer.aborted)
            self.assertEqual(writer.data.split(b"\r\n\r\n", 1)[1], body)

    async def test_shutdown_can_abort_a_handler_already_closing(self):
        with tempfile.TemporaryDirectory() as folder:
            server = PhotoServer(PhotoStore(folder), "127.0.0.1", 0)
            reader = asyncio.StreamReader()
            reader.feed_data(b"GET / HTTP/1.0\r\n\r\n")
            reader.feed_eof()
            writer = Writer(stall="close")

            async def fail_route(*args):
                raise ConnectionError("route interrupted")

            server._route = fail_route
            with self.assertLogs("web", level="WARNING"):
                handler = asyncio.create_task(server._handle(reader, writer))
                try:
                    while not writer.closed:
                        await asyncio.sleep(0)
                    self.assertIn(writer, server._writers)
                    self.assertEqual(server.access.connections, 1)
                    await server.stop()
                finally:
                    writer.abort()
                    await handler
            self.assertTrue(writer.aborted)
            self.assertFalse(server._writers)
            self.assertEqual(server.access.connections, 0)


if __name__ == "__main__":
    unittest.main()
