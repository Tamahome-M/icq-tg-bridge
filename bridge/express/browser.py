"""Запуск Chromium с постоянным профилем, в котором живёт сессия eXpress.

Веб-клиент хранит токены и ключи шифрования в localStorage/IndexedDB,
поэтому профиль на диске и есть «файл сессии»: вошли один раз — дальше
браузер поднимается уже в аккаунте.
"""

from __future__ import annotations

import os
from pathlib import Path

from playwright.async_api import BrowserContext, Page, Playwright

WEB_URL = "https://corp.express/"
# Системные библиотеки Chromium, распакованные рядом без root (см. README).
LOCAL_LIBS = Path(__file__).resolve().parents[2] / ".syslibs/usr/lib/x86_64-linux-gnu"

# Все экраны до входа (выбор способа, капча, код из СМС) свёрстаны
# классами login*; в самом приложении их нет.
LOGIN_SCREEN = '[class*="login"]'


def _env() -> dict[str, str]:
    env = dict(os.environ)
    if LOCAL_LIBS.is_dir():
        env["LD_LIBRARY_PATH"] = f"{LOCAL_LIBS}:{env.get('LD_LIBRARY_PATH', '')}".rstrip(":")
    return env


async def open_context(pw: Playwright, profile_dir: str, headless: bool = True) -> BrowserContext:
    Path(profile_dir).mkdir(parents=True, exist_ok=True)
    os.chmod(profile_dir, 0o700)
    return await pw.chromium.launch_persistent_context(
        profile_dir,
        headless=headless,
        env=_env(),
        locale="ru-RU",
        viewport={"width": 1280, "height": 800},
    )


async def open_app(ctx: BrowserContext, timeout: float = 90) -> Page:
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    await page.goto(WEB_URL, wait_until="domcontentloaded", timeout=timeout * 1000)
    # Заставка исчезает, когда приложение решило, что показывать: вход или чаты.
    await page.wait_for_selector(".initial-loading-overlay", state="detached", timeout=timeout * 1000)
    await page.wait_for_timeout(1500)
    return page


async def is_logged_in(page: Page) -> bool:
    return await page.locator(LOGIN_SCREEN).count() == 0
