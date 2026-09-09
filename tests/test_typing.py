"""Проверка того, что «печатает» не только зажигается, но и гаснет."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge import bridge as bridge_module
from bridge.bridge import Bridge
from bridge.config import Config
from bridge.oscar import const as C


def make_bridge() -> tuple[Bridge, list[tuple[int, bool]]]:
    cfg = Config(tg_api_id=1, tg_api_hash="x")
    work = tempfile.mkdtemp()
    cfg.db = os.path.join(work, "test.db")
    # Telethon заводит файл сессии сразу при создании клиента — уводим его
    # во временный каталог, чтобы тесты не оставляли следов в проекте.
    cfg.tg_session = os.path.join(work, "test.session")
    cfg.photos_enabled = False
    bridge = Bridge(cfg)
    bridge.storage.uin_for_peer(555, kind="user", title="Мама", group_name="Личные")
    bridge.storage.uin_for_peer(-4001, kind="chat", title="Дача", group_name="Группы")
    bridge.storage.uin_for_peer(-4002, kind="chat", title="Шумная",
                                group_name="Группы", muted=1)
    bridge._roster = bridge.storage.contacts()

    sent: list[tuple[int, bool]] = []

    async def notify(uin: int, active: bool) -> None:
        sent.append((uin, active))

    bridge.oscar.notify_typing = notify
    return bridge, sent


async def main() -> None:
    bridge_module.TYPING_TIMEOUT = 0.3      # чтобы не ждать в тесте восемь секунд
    mom = None

    # --- гаснет само, если Telegram замолчал ------------------------------
    bridge, sent = make_bridge()
    mom = bridge.storage.contact_by_peer(555).uin
    await bridge.on_telegram_typing(555, True)
    assert sent == [(mom, True)], sent

    await asyncio.sleep(0.15)
    assert len(sent) == 1, "индикатор погас слишком рано"
    await asyncio.sleep(0.35)
    assert sent[-1] == (mom, False), f"индикатор так и не погас: {sent}"

    # --- повторные уведомления продлевают, а не дублируют -----------------
    sent.clear()
    for _ in range(3):
        await bridge.on_telegram_typing(555, True)
        await asyncio.sleep(0.1)
    assert all(active for _, active in sent), sent
    await asyncio.sleep(0.4)
    assert sent[-1] == (mom, False), sent

    # --- пришло сообщение — набор закончен --------------------------------
    sent.clear()
    await bridge.on_telegram_typing(555, True)
    await bridge.on_telegram_message(555, "", "привет", int(time.time()))
    assert (mom, False) in sent, f"сообщение должно гасить индикатор: {sent}"
    await asyncio.sleep(0.4)
    assert sent.count((mom, False)) == 1, f"погасили дважды: {sent}"

    # --- отмена набора в Telegram -----------------------------------------
    sent.clear()
    await bridge.on_telegram_typing(555, True)
    await bridge.on_telegram_typing(555, False)
    assert sent == [(mom, True), (mom, False)], sent

    # --- «не беспокоить»: заглушённый чат не должен дёргать телефон -------
    sent.clear()
    await bridge.on_owner_status(C.STATUS_DND)
    await bridge.on_telegram_typing(-4002, True)
    assert sent == [], f"из заглушённого чата индикатор показывать нельзя: {sent}"
    bridge.storage.close()

    print("  индикатор набора: гаснет по таймауту, по сообщению и по отмене — ок")
    print("«ПЕЧАТАЕТ» ПРОВЕРЕНО")


if __name__ == "__main__":
    asyncio.run(main())
