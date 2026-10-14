"""Вход в личный Яндекс ID на сервере: ./run.py login taxi."""

from __future__ import annotations

import asyncio
import getpass
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

from .browser import TaxiBrowser
from .model import LoginRequired


def _read(prompt):
    # Пароль/код не попадают в shell history, config.toml и журнал моста.
    if sys.stdin.isatty():
        return getpass.getpass(prompt).strip()
    print(prompt, flush=True)
    value = sys.stdin.readline()
    if not value:
        raise EOFError
    return value.strip()


async def _show(page, path):
    await page.screenshot(path=str(path))
    os.chmod(path, 0o600)
    text = await page.locator("body").inner_text()
    print("\n" + "\n".join(text.splitlines()[:25]), flush=True)
    print(f"Снимок экрана: {path}", flush=True)


async def main(cfg):
    browser = TaxiBrowser(cfg)
    shot = Path(cfg.taxi_session) / "login.png"
    marker = shot.with_name("login.ok")

    async def authorized(reload=False):
        if reload:
            await browser._load()
        try:
            account = await browser.ensure_logged_in()
        except LoginRequired:
            return False
        marker.write_text(account + "\n", encoding="ascii")
        os.chmod(marker, 0o600)
        print("Вход в Яндекс Go выполнен. Профиль сохранён в", cfg.taxi_session, flush=True)
        return True

    try:
        await browser._open()
        if await authorized():
            return 0
        print("Входите в ту же личную учётку, что используете в Яндекс Go.", flush=True)
        if cfg.taxi_devtools_port:
            print(f"Живой браузер: chrome://inspect, localhost:{cfg.taxi_devtools_port}. "
                  "На удалённом сервере используйте SSH-туннель.", flush=True)
        async with browser.context.expect_page(timeout=cfg.taxi_timeout * 1000) as opened:
            await browser.page.get_by_role("button", name="Войти", exact=True).click()
        page = await opened.value
        await page.wait_for_load_state("domcontentloaded")
        deadline = asyncio.get_running_loop().time() + 15 * 60
        qr = False
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(1)
            returned = page.is_closed() or urlsplit(page.url).hostname == "taxi.yandex.ru"
            if await authorized(reload=returned):
                return 0
            if page.is_closed():
                print("Окно входа закрылось без авторизации.", file=sys.stderr)
                return 1
            await _show(page, shot)
            if qr:
                # Пользователь сам подтверждает QR в приложении/браузере.
                await asyncio.sleep(4)
                continue
            value = await asyncio.to_thread(
                _read, "Номер/код/пароль; qr — QR-код; кнопка <название> — нажать; "
                "пусто — проверить вход; q — выйти: ")
            if value.casefold() == "q":
                return 1
            if value.casefold() == "qr":
                await page.get_by_role("button", name="QR-код", exact=True).click()
                qr = True
                continue
            if value.casefold().startswith("кнопка "):
                await page.get_by_role("button", name=value[7:].strip(), exact=True).click()
                continue
            if not value:
                if await authorized(reload=True):
                    return 0
                continue
            fields = page.locator('input:visible:not([type=submit]):not([type=checkbox]):not([type=hidden])')
            count = await fields.count()
            if count == 1:
                await fields.first.fill(value)
                await fields.first.press("Enter")
            elif count > 1 and len(value) == count and value.isdigit() and all(
                    [await fields.nth(i).get_attribute("maxlength") == "1" for i in range(count)]):
                for i, char in enumerate(value):
                    await fields.nth(i).fill(char)
            else:
                print("Форма требует выбора поля. Используйте живой браузер через chrome://inspect.",
                      file=sys.stderr)
        print("Время входа истекло; можно запустить login taxi снова.", file=sys.stderr)
        return 1
    except EOFError:
        return 1
    finally:
        await browser.close()
        # На снимке может остаться телефон или QR входа, после завершения он не нужен.
        shot.unlink(missing_ok=True)
