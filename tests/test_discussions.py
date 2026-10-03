"""Группа обсуждений канала наследует его мьют и группу контактов."""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import sys
import tempfile
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon import functions, types, utils

from bridge.config import Config
from bridge.tg.client import TelegramSide

NEWS, COMMENTS, OTHER = 101, 202, 303
FOREVER = dt.datetime(2037, 1, 1, tzinfo=dt.timezone.utc)


def channel(cid: int, title: str, group: bool = False):
    return types.Channel(id=cid, title=title, photo=types.ChatPhotoEmpty(),
                         date=dt.datetime.now(dt.timezone.utc),
                         broadcast=not group, megagroup=group)


def dialog(entity, muted: bool):
    settings = NS(silent=False, mute_until=FOREVER if muted else None)
    return NS(entity=entity, name=entity.title, pinned=False, archived=False, unread_count=0,
              dialog=NS(notify_settings=settings))


class FakeTelethon:
    def __init__(self, linked: dict[int, int]):
        self.linked = linked
        self.full_requests = 0
        self.dialogs = [dialog(channel(NEWS, "Новости"), muted=True),
                        dialog(channel(COMMENTS, "Новости Chat", group=True), muted=False),
                        dialog(channel(OTHER, "Соседи", group=True), muted=False)]

    async def iter_dialogs(self, **kw):
        for d in self.dialogs:
            yield d

    async def __call__(self, request):
        if isinstance(request, functions.messages.GetDialogFiltersRequest):
            return NS(filters=[])
        if isinstance(request, functions.channels.GetFullChannelRequest):
            self.full_requests += 1
            return NS(full_chat=NS(linked_chat_id=self.linked.get(request.channel.id)))
        raise AssertionError(f"неожиданный запрос {type(request).__name__}")


async def main() -> None:
    work = tempfile.mkdtemp()
    cfg = Config(tg_api_id=1, tg_api_hash="x")
    cfg.tg_session = os.path.join(work, "t.session")
    side = TelegramSide(cfg, None)
    fake = FakeTelethon({NEWS: COMMENTS})
    side.client = fake

    out = {d.title: d for d in await side.dialogs()}
    comments = utils.get_peer_id(types.PeerChannel(COMMENTS))
    assert out["Новости Chat"].peer_id == comments
    assert out["Новости Chat"].muted, "обсуждения заглушены вместе с каналом"
    assert out["Новости Chat"].group_name == out["Новости"].group_name == "Каналы"
    assert not out["Соседи"].muted and out["Соседи"].group_name == "Группы", "чужая группа не тронута"
    assert fake.full_requests == 1

    # Связь канала с группой помнится — повторный список без лишних запросов.
    await side.dialogs()
    assert fake.full_requests == 1

    # Канал больше не заглушён — и обсуждения тоже.
    fake.dialogs[0] = dialog(channel(NEWS, "Новости"), muted=False)
    out = {d.title: d for d in await side.dialogs()}
    assert not out["Новости Chat"].muted
    print("  обсуждения канала: ок (мьют и группа — от канала)")
    print("ОБСУЖДЕНИЯ ПРОВЕРЕНЫ")


if __name__ == "__main__":
    asyncio.run(main())
