"""Interrupted media work must release its files and await cancelled workers."""

import asyncio
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image
from bridge.render import Item, RenderStore
from bridge.videos import VideoSpec, VideoStore


def picture():
    out = io.BytesIO()
    Image.new("RGB", (16, 16), "red").save(out, format="PNG")
    return out.getvalue()


class MediaLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_failed_render_discards_unpublished_assets_only(self):
        with tempfile.TemporaryDirectory() as folder:
            store = RenderStore(folder, SimpleNamespace(), ttl_minutes=1)
            kept = await store.build("published", [Item(kind="photo", raw=picture())])
            existing = set(store._assets)

            async def fail_progress(*args):
                raise ConnectionError("phone disconnected while reporting progress")

            with self.assertRaises(ConnectionError):
                await store.build("failed", [Item(kind="photo", raw=picture())], fail_progress)
            self.assertEqual(set(store._assets), existing)
            self.assertEqual(set(store._pages), {kept.token})
            self.assertEqual(len(list(Path(folder).iterdir())), 1)

    async def test_cancelled_video_render_discards_its_thumbnail(self):
        with tempfile.TemporaryDirectory() as folder:
            entered = asyncio.Event()

            async def convert(*args):
                entered.set()
                await asyncio.Future()

            async def thumb():
                return picture()

            store = RenderStore(folder, SimpleNamespace(convert=convert))
            task = asyncio.create_task(store.build("cancelled", [
                Item(kind="video", raw=b"video", thumb=thumb)]))
            await entered.wait()
            self.assertEqual(len(store._assets), 1, "thumbnail was created before cancellation")
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertFalse(store._assets)
            self.assertFalse(store._pages)
            self.assertFalse(list(Path(folder).iterdir()))

    async def test_video_shutdown_waits_for_workers_detached_by_update_or_expiry(self):
        for operation in ("update", "drop"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as folder:
                entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

                async def fetch(*args):
                    entered.set()
                    try:
                        await asyncio.Future()
                    finally:
                        cleaning.set()
                        await release.wait()

                store = VideoStore(folder, fetch)
                spec = VideoSpec(ffmpeg=sys.executable)
                path = store.register(1000001, "video:42", "Chat", spec)
                store.resolve(path)
                page = next(iter(store.pages.values()))
                job = page.jobs[0]
                await entered.wait()
                if operation == "update":
                    store.update_spec(VideoSpec(ffmpeg=sys.executable, kbps=48))
                else:
                    store._drop(page)
                await cleaning.wait()
                stopping = asyncio.create_task(store.stop())
                try:
                    await asyncio.sleep(0)
                    await asyncio.sleep(0)
                    self.assertFalse(stopping.done(), "stop returned while cancelled fetch was cleaning up")
                finally:
                    release.set()
                    await stopping
                    await asyncio.gather(job, return_exceptions=True)
                self.assertTrue(job.done())


if __name__ == "__main__":
    unittest.main()
