"""Provider identifiers with valid zero values must survive event dispatch."""

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bridge.config import Config
from bridge.max.client import MaxSide, to_peer
from tests.test_max import FakeMax, ME, message


class ProviderEvents(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.incoming, self.reads = [], []

        async def incoming(*args, **kwargs):
            self.incoming.append((args, kwargs))
            return True

        async def read(*args):
            self.reads.append(args)

        self.side = MaxSide(Config(mirror_outgoing=True), incoming, client=FakeMax(), on_inbox_read=read)
        self.side.me_id = ME

    async def test_max_saved_messages_arrive_from_other_devices(self):
        await self.side._on_new_message(message(42, 0, ME, "saved on another device"))
        self.assertEqual(len(self.incoming), 1)
        args, kwargs = self.incoming[0]
        self.assertEqual(args[:3], (to_peer(0), "Я", "saved on another device"))
        self.assertEqual(kwargs["message_id"], 42)
        self.side._remember_own(0, 43)
        await self.side._on_new_message(message(43, 0, ME, "bridge's own message"))
        self.assertEqual(len(self.incoming), 1, "own messages must remain suppressed")

    async def test_max_saved_message_reads_reach_queue_cleanup(self):
        await self.side._on_read(SimpleNamespace(chat_id=0, user_id=ME, mark=123456789))
        self.assertEqual(self.reads, [(to_peer(0), 123456789)])
        await self.side._on_read(SimpleNamespace(user_id=ME, mark=123456790))
        await self.side._on_read(SimpleNamespace(chat_id=0, user_id=ME, mark=123456790,
                                               set_as_unread=True))
        self.assertEqual(len(self.reads), 1, "missing chat and unread event are not read confirmations")


if __name__ == "__main__":
    unittest.main()
