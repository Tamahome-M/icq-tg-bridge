#!/usr/bin/env python3
"""Мост ICQ (OSCAR) <-> Telegram.

  python3 run.py login       — один раз войти в аккаунт Telegram
  python3 run.py login max   — один раз войти в аккаунт MAX (если включён)
  python3 run.py             — запустить мост
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


LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)-8s %(message)s"


def setup_logging(cfg=None) -> None:
    """Журнал: уровень и файл из секции [log], переменные окружения сильнее.

    INFO — события: кто подключился, что ушло и пришло (без текста), что
    отсеяно и почему. DEBUG — сами сообщения и каждый SNAC. WARNING — то,
    что мост пережил сам, ERROR — то, что не должно было случиться.
    """
    level = os.environ.get("BRIDGE_LOGLEVEL") or (cfg.log_level if cfg else "INFO")
    telethon = (os.environ.get("BRIDGE_TELETHON_LOGLEVEL")
                or (cfg.log_telethon_level if cfg else "WARNING"))
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(level.upper())
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(LOG_FORMAT, datefmt="%H:%M:%S"))
    root.addHandler(console)
    if cfg is not None and cfg.log_file:
        from logging.handlers import RotatingFileHandler
        handler = RotatingFileHandler(cfg.log_file, maxBytes=cfg.log_file_max_mb * 1024 * 1024,
                                      backupCount=cfg.log_file_keep, encoding="utf-8")
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt="%d.%m %H:%M:%S"))
        root.addHandler(handler)
    # Telethon многословен: в отладочном режиме моста его записи о пакетах
    # забивают журнал. Держим его отдельно, по умолчанию тише.
    logging.getLogger("telethon").setLevel(telethon.upper())
    logging.getLogger("pymax").setLevel((cfg.log_max_level if cfg else "WARNING").upper())


async def main() -> int:
    setup_logging()
    if not os.path.exists(CONFIG):
        print(f"Нет файла {CONFIG}. Скопируйте config.example.toml в config.toml "
              f"и заполните его.", file=sys.stderr)
        return 1
    cfg = Config.load(CONFIG)
    setup_logging(cfg)

    from bridge.config import warn_about_permissions
    loose = warn_about_permissions([CONFIG, cfg.tg_session, cfg.db]
                                   + ([cfg.max_session] if cfg.max_enabled else []))
    for path in loose:
        logging.getLogger("bridge").warning(
            "файл %s доступен другим пользователям — сделайте chmod 600", path)

    bridge = Bridge(cfg)

    if len(sys.argv) > 1 and sys.argv[1] == "login":
        if len(sys.argv) > 2 and sys.argv[2] == "max":
            if bridge.max is None:
                print("MAX выключен: включите [max] enabled = true и укажите phone",
                      file=sys.stderr)
                return 1
            try:
                await bridge.max.login()
            except Exception as exc:
                # Сервер отвечает по-русски и по делу («Требуется установить
                # 2FA») — этого достаточно, трассировка тут ни к чему.
                print(f"Вход в MAX не удался: {exc}", file=sys.stderr)
                return 1
            return 0
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
