"""Запуск Chromium с постоянным профилем, в котором живёт сессия eXpress.

Веб-клиент хранит токены и ключи шифрования в localStorage/IndexedDB,
поэтому профиль на диске и есть «файл сессии»: вошли один раз — дальше
браузер поднимается уже в аккаунте.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
from pathlib import Path

from playwright.async_api import BrowserContext, Page, Playwright

WEB_URL = "https://corp.express/"
ROOT = Path(__file__).resolve().parents[2]
# Системные библиотеки Chromium, распакованные рядом без root (см. README).
LOCAL_LIBS = ROOT / ".syslibs/usr/lib/x86_64-linux-gnu"
# Chromium, скачанный рядом с проектом (PLAYWRIGHT_BROWSERS_PATH при установке):
# служба работает без домашнего каталога, и в ~/.cache ей искать нечего.
LOCAL_BROWSERS = ROOT / ".browsers"

# Все экраны до входа (выбор способа, капча, код из СМС) свёрстаны
# классами login*; в самом приложении их нет.
LOGIN_SCREEN = '[class*="login"]'


def _der_items(data: bytes, offset: int = 0):
    """Элементы DER-последовательности: (тег, содержимое, весь элемент)."""
    while offset < len(data):
        tag = data[offset]
        length = data[offset + 1]
        head = 2
        if length & 0x80:
            count = length & 0x7F
            length = int.from_bytes(data[offset + 2:offset + 2 + count], "big")
            head += count
        end = offset + head + length
        yield tag, data[offset + head:end], data[offset:end]
        offset = end


def spki_hashes(path: str) -> list[str]:
    """Отпечатки открытых ключей сертификатов из файла (PEM, можно несколько,
    или DER) — в том виде, в каком их ждёт Chromium
    (--ignore-certificate-errors-spki-list): base64 от SHA-256 по
    SubjectPublicKeyInfo. Своих библиотек для этого не нужно: нужный
    элемент — седьмой в tbsCertificate (шестой, если версии нет)."""
    raw = Path(path).read_bytes()
    blocks = re.findall(rb"-----BEGIN CERTIFICATE-----(.*?)-----END CERTIFICATE-----", raw, re.S)
    certs = [base64.b64decode(b"".join(b.split())) for b in blocks] if blocks else [raw]
    out = []
    for der in certs:
        _, cert, _ = next(_der_items(der))
        _, tbs, _ = next(_der_items(cert))
        fields = list(_der_items(tbs))
        if fields and fields[0][0] == 0xA0:
            fields = fields[1:]                # явная версия — пропускаем
        spki = fields[5][2]                    # serial, sigAlg, issuer, validity, subject, spki
        out.append(base64.b64encode(hashlib.sha256(spki).digest()).decode())
    return out


def prepare() -> None:
    """Вызвать до запуска Playwright: показывает ему Chromium, лежащий рядом."""
    if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ and LOCAL_BROWSERS.is_dir():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(LOCAL_BROWSERS)


def _env(profile_dir: str) -> dict[str, str]:
    env = dict(os.environ)
    if LOCAL_LIBS.is_dir():
        env["LD_LIBRARY_PATH"] = f"{LOCAL_LIBS}:{env.get('LD_LIBRARY_PATH', '')}".rstrip(":")
    # Под службой HOME бывает чужим (root): Chromium пишет туда мелочи и
    # ругается, если нельзя, — отдаём ему каталог рядом с профилем.
    if not os.access(env.get("HOME") or "/", os.W_OK):
        env["HOME"] = str(Path(profile_dir).resolve().parent)
    return env


async def open_context(pw: Playwright, profile_dir: str, headless: bool = True,
                       executable: str = "", devtools_port: int = 0,
                       trust_ca: list[str] | None = None) -> BrowserContext:
    """executable — путь к системному Chromium или Chrome; пусто — тот, что
    скачан командой playwright install chromium. devtools_port — открыть
    отладочный порт Chrome на localhost: через него браузер видно и им можно
    управлять из обычного Chrome (chrome://inspect) по туннелю ssh.
    trust_ca — файлы сертификатов удостоверяющих центров, которым Chromium
    сам не верит (корпоративный сервер с сертификатом Минцифры): доверять
    только им, остальные проверки остаются."""
    Path(profile_dir).mkdir(parents=True, exist_ok=True)
    os.chmod(profile_dir, 0o700)
    args = [f"--remote-debugging-port={devtools_port}"] if devtools_port else []
    hashes = [h for path in trust_ca or [] for h in spki_hashes(path)]
    if hashes:
        args.append("--ignore-certificate-errors-spki-list=" + ",".join(hashes))
    return await pw.chromium.launch_persistent_context(
        profile_dir,
        headless=headless,
        executable_path=executable or None,
        args=args,
        env=_env(profile_dir),
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
