"""Вход в аккаунт из терминала: python3 run.py login express

Экраны после ввода номера (код из СМС, капча, пароль) скрипт не знает
заранее, поэтому показывает текст страницы и передаёт ей то, что вы
наберёте. После каждого шага кладёт снимок экрана в профиль (login.png).
"""

from __future__ import annotations

import asyncio
import os
import sys

from playwright.async_api import async_playwright

from .browser import is_logged_in, open_app, open_context, prepare

DEFAULT_PROFILE = "express.session"


FIFO: str | None = None


def ask(prompt: str) -> str:
    """Спросить в терминале; без терминала — ждать строку из FIFO профиля
    (echo 123456 > session/login.in)."""
    if FIFO is None:
        return input(prompt).strip()
    print(f"{prompt}[жду строку в {FIFO}]", flush=True)
    with open(FIFO) as pipe:
        return pipe.readline().strip()


async def _show(page, shot: str) -> None:
    await page.screenshot(path=shot)
    text = await page.evaluate("document.body.innerText")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    print("\n--- страница ---")
    print("\n".join(lines[:25]))
    print(f"--- снимок: {shot} ---")


async def main(profile: str, executable: str = "") -> int:
    global FIFO
    shot = f"{profile}/login.png"
    prepare()
    async with async_playwright() as pw:
        ctx = await open_context(pw, profile, executable=executable)
        if not sys.stdin.isatty():
            FIFO = f"{profile}/login.in"
            if not os.path.exists(FIFO):
                os.mkfifo(FIFO, 0o600)
        try:
            page = await open_app(ctx)
            if await is_logged_in(page):
                print("Уже в аккаунте.")
                return 0
            if await page.locator("input[type=tel]").count():
                phone = await asyncio.to_thread(ask, "Номер телефона без +7 (10 цифр): ")
                await page.locator("input[type=tel]").fill(phone)
                await page.get_by_role("button", name="Продолжить").click()
            while True:
                await page.wait_for_timeout(3000)
                if await is_logged_in(page):
                    # Дать клиенту дописать ключи и токены в хранилище.
                    await page.wait_for_timeout(8000)
                    await page.screenshot(path=shot)
                    print("Вход выполнен, сессия сохранена в", profile)
                    return 0
                await _show(page, shot)
                value = await asyncio.to_thread(
                    ask, "Что ввести (код из СМС и т.п.; пусто — подождать, q — выйти): ")
                if value == "q":
                    return 1
                if value:
                    field = page.locator("input:visible").last
                    if await field.count():
                        await field.focus()
                    await page.keyboard.type(value, delay=60)
                    await page.keyboard.press("Enter")
        finally:
            await ctx.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PROFILE)))
