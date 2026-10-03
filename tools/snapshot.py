#!/usr/bin/env python3
"""Снимок веб-страницы в файл — для контакта «Claude» на мосту.

    tools/snapshot.py URL файл.png [--width 800] [--height 600] [--wait 3] [--full]

Открывает адрес в Chromium без окна (тот же, что у стороны eXpress) и
сохраняет PNG. Так Claude может, например, построить маршрут на картах и
прислать его картинкой: мост ужмёт снимок под экран телефона сам.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright  # noqa: E402

from bridge.express.browser import _env, prepare  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description="снимок веб-страницы")
    parser.add_argument("url")
    parser.add_argument("out")
    parser.add_argument("--width", type=int, default=480)
    parser.add_argument("--height", type=int, default=640)
    parser.add_argument("--wait", type=float, default=3.0, help="секунд подождать после загрузки")
    parser.add_argument("--full", action="store_true", help="вся страница, не только экран")
    args = parser.parse_args()
    prepare()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(env=_env(os.path.dirname(os.path.abspath(args.out)) or "."))
        page = await browser.new_page(viewport={"width": args.width, "height": args.height},
                                      locale="ru-RU")
        await page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(int(args.wait * 1000))
        await page.screenshot(path=args.out, full_page=args.full)
        await browser.close()
    print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
