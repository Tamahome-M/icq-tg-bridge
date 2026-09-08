#!/usr/bin/env python3
"""Мост ICQ (OSCAR) <-> Telegram.

  python3 run.py login   — один раз войти в аккаунт Telegram
  python3 run.py         — запустить мост
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def use_venv() -> None:
    """Запуск ./run.py системным питоном перекидываем в .venv, где стоит telethon."""
    if os.environ.get("BRIDGE_REEXEC"):
        return
    venv_python = os.path.join(HERE, ".venv", "bin", "python")
    if sys.executable == venv_python or not os.path.exists(venv_python):
        return
    try:
        import telethon  # noqa: F401
    except ImportError:
        os.environ["BRIDGE_REEXEC"] = "1"
        os.execv(venv_python, [venv_python, os.path.abspath(__file__), *sys.argv[1:]])


use_venv()

try:
    from bridge.bridge import Bridge
    from bridge.config import Config
except ImportError as exc:
    print(f"Не хватает зависимости: {exc.name or exc}.\n"
          f"Установите её: {os.path.join(HERE, '.venv', 'bin', 'python')} -m pip install "
          f"-r {os.path.join(HERE, 'requirements.txt')}", file=sys.stderr)
    raise SystemExit(1)

CONFIG = os.environ.get("BRIDGE_CONFIG",
                        os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.toml"))


def setup_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("BRIDGE_LOGLEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)-7s %(name)-8s %(message)s",
        datefmt="%H:%M:%S",
    )
    # Telethon многословен: в отладочном режиме моста его записи о пакетах
    # забивают журнал. Держим его отдельно, по умолчанию тише.
    logging.getLogger("telethon").setLevel(
        os.environ.get("BRIDGE_TELETHON_LOGLEVEL", "WARNING").upper())


async def main() -> int:
    setup_logging()
    if not os.path.exists(CONFIG):
        print(f"Нет файла {CONFIG}. Скопируйте config.example.toml в config.toml "
              f"и заполните его.", file=sys.stderr)
        return 1
    cfg = Config.load(CONFIG)

    from bridge.config import warn_about_permissions
    loose = warn_about_permissions([CONFIG, cfg.tg_session, cfg.db])
    for path in loose:
        logging.getLogger("bridge").warning(
            "файл %s доступен другим пользователям — сделайте chmod 600", path)

    bridge = Bridge(cfg)

    if len(sys.argv) > 1 and sys.argv[1] == "login":
        await bridge.telegram.login()
        await bridge.telegram.stop()
        return 0

    try:
        await bridge.run()
    except KeyboardInterrupt:
        pass
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    finally:
        await bridge.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
