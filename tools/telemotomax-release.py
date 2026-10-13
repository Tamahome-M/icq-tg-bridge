#!/usr/bin/env python3
"""Publish and fetch TeleMotoMax JAR/JAD pairs; Python standard library only."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parent.parent
BASES = ("TeleMotoMax", "TeleMotoMax-Light", "TeleMotoMax-V8")
FILES = tuple(f"{base}.{ext}" for base in BASES for ext in ("jar", "jad"))
PROBE_BASE = "TmmFlipProbe"
PROBE_DIR = Path("tools/motorola_flip_probe")
PROBE_INPUTS = ("VERSION", "build.py", "FlipProbe.java", "FlipReader.java",
                "VodafoneFlip.java", "stubs")
MANIFEST = "telemotomax-release.json"
MAX_FILE = 16 * 1024 * 1024
MAX_JSON = 128 * 1024
# These are the inputs copied by build.sh and the existing signing identity.
# Build output, documentation and publication scripts do not change the client.
INPUTS = ("src", "res", "stubs", "util", "build.xml", "build.properties", "COPYING",
          "VERSION", "preverify", "sign.sh", "sign-keys")


def version(source: Path) -> str:
    value = (source / "telemotomax/VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?", value):
        raise ValueError("некорректный telemotomax/VERSION")
    return value


def probe_version(source: Path) -> str | None:
    path = source / PROBE_DIR / "VERSION"
    if not path.is_file():
        return None
    value = path.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?", value):
        raise ValueError("некорректный motorola_flip_probe/VERSION")
    return value


def release_files(source: Path) -> tuple[str, ...]:
    """Older releases have three client pairs; new ones also carry the separate probe."""
    if probe_version(source) is None:
        return FILES
    return FILES + (f"{PROBE_BASE}.jar", f"{PROBE_BASE}.jad")


def source_hash(source: Path) -> str:
    """Stable for Git checkouts and source ZIPs, irrespective of mode/mtime."""
    client = source / "telemotomax"
    digest = hashlib.sha256()
    files = []
    for name in INPUTS:
        path = client / name
        files.extend(path.rglob("*") if path.is_dir() else [path])
    for path in sorted(p for p in files if p.is_file()):
        digest.update(path.relative_to(client).as_posix().encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    if probe_version(source) is not None:
        files = []
        for name in PROBE_INPUTS:
            path = source / PROBE_DIR / name
            files.extend(path.rglob("*") if path.is_dir() else [path])
        for path in sorted(p for p in files if p.is_file()):
            digest.update(path.relative_to(source).as_posix().encode("utf-8") + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def attributes(data: bytes, *, folded: bool = False) -> dict[str, str]:
    lines = []
    for line in data.decode("utf-8").splitlines():
        if folded and line.startswith(" ") and lines:
            lines[-1] += line[1:]
        elif line:
            lines.append(line)
    values = {}
    for line in lines:
        key, sep, value = line.partition(":")
        if not sep or key in values:
            raise ValueError("некорректные или повторяющиеся атрибуты JAR/JAD")
        values[key] = value.strip()
    return values


def validate_pairs(source: Path, dist: Path) -> None:
    expected = version(source)
    probe = probe_version(source)
    bases = BASES + (PROBE_BASE,) if probe is not None else BASES
    for base in bases:
        jar = dist / f"{base}.jar"
        jad = attributes((dist / f"{base}.jad").read_bytes())
        if (jad.get("MIDlet-Version") != (probe if base == PROBE_BASE else expected)
                or jad.get("MIDlet-Jar-URL") != jar.name
                or jad.get("MIDlet-Jar-Size") != str(jar.stat().st_size)):
            raise ValueError(f"{base}: версия, ссылка или размер JAR не совпадают с JAD")
        with zipfile.ZipFile(jar) as archive:
            if archive.testzip() is not None:
                raise ValueError(f"{jar.name}: повреждённый JAR")
            manifest = attributes(archive.read("META-INF/MANIFEST.MF"), folded=True)
        for key in ("MIDlet-Version", "MIDlet-Name", "MIDlet-Vendor",
                    "MIDlet-Permissions", "MIDlet-Permissions-Opt"):
            if manifest.get(key) != jad.get(key):
                raise ValueError(f"{base}: атрибут {key} различается в JAR и JAD")
        if base == PROBE_BASE:
            for key, value in (("MIDlet-1", "TMM Flip Probe,,FlipProbe"),
                               ("Background", "True"), ("FlipInsensitive", "True")):
                if jad.get(key) != value or manifest.get(key) != value:
                    raise ValueError(f"{base}: некорректный атрибут {key}")
        if base == "TeleMotoMax-V8":
            keys = source / "telemotomax/sign-keys"
            for number, name in ((1, "signer.der"), (2, "ca.der")):
                encoded = jad.get(f"MIDlet-Certificate-1-{number}", "")
                if base64.b64decode(encoded, validate=True) != (keys / name).read_bytes():
                    raise ValueError("V8: сертификат отличается от доверенного телефоном")
            if not base64.b64decode(jad.get("MIDlet-Jar-RSA-SHA1", ""), validate=True):
                raise ValueError("V8: отсутствует подпись JAR")


def make_manifest(source: Path, dist: Path) -> dict:
    validate_pairs(source, dist)
    assets = {}
    for name in release_files(source):
        data = (dist / name).read_bytes()
        if not 0 < len(data) <= MAX_FILE:
            raise ValueError(f"некорректный размер {name}")
        assets[name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return {"format": 1, "version": version(source),
            "source_sha256": source_hash(source), "files": assets}


def validate_manifest(source: Path, manifest: dict) -> None:
    if (not isinstance(manifest, dict) or manifest.get("format") != 1
            or manifest.get("version") != version(source)):
        raise ValueError("манифест релиза не соответствует версии клиента")
    if manifest.get("source_sha256") != source_hash(source):
        raise ValueError("исходники клиента отличаются от релиза; увеличьте VERSION и опубликуйте сборку")
    assets = manifest.get("files")
    if not isinstance(assets, dict) or set(assets) != set(release_files(source)):
        raise ValueError("релиз должен содержать все ожидаемые пары JAR/JAD")
    for name, record in assets.items():
        if (not isinstance(record, dict) or type(record.get("size")) is not int
                or not 0 < record["size"] <= MAX_FILE
                or not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", "")))):
            raise ValueError(f"некорректный манифест для {name}")


def repo_url(repo: str) -> str:
    value = repo.rstrip("/").removesuffix(".git")
    if not urllib.parse.urlsplit(value).scheme:
        value = "https://github.com/" + value
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme not in ("https", "http") or not parsed.netloc
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("ожидается адрес репозитория без пароля и параметров")
    return value


def release_url(source: Path, repo: str) -> str:
    return f"{repo_url(repo)}/releases/download/telemotomax-v{version(source)}/"


def read_url(url: str, limit: int = MAX_JSON) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "TeleMotoMax-release"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("файл релиза превышает допустимый размер")
    return data


def download(source: Path, repo: str, dest: Path) -> None:
    """Stage and check every pair before replacing an installed directory."""
    url = release_url(source, repo)
    try:
        manifest = json.loads(read_url(url + MANIFEST))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            error.close()
            raise ValueError(f"релиз TeleMotoMax {version(source)} ещё не опубликован: {url}") from None
        raise
    validate_manifest(source, manifest)
    dest = dest.absolute()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".telemotomax-", dir=dest.parent) as work:
        staged = Path(work) / "dist"
        staged.mkdir()
        for name in release_files(source):
            record = manifest["files"][name]
            data = read_url(url + name, record["size"])
            if (len(data) != record["size"]
                    or hashlib.sha256(data).hexdigest() != record["sha256"]):
                raise ValueError(f"{name}: размер или SHA-256 не совпадает с релизом")
            (staged / name).write_bytes(data)
        validate_pairs(source, staged)
        backup = Path(work) / "previous"
        if dest.exists() or dest.is_symlink():
            if not dest.is_dir() or dest.is_symlink():
                raise ValueError("каталог сборок должен быть обычным каталогом")
            dest.rename(backup)
        try:
            staged.rename(dest)
        except OSError:
            if backup.exists():
                backup.rename(dest)
            raise
    note = " и отдельная диагностика флипа" if probe_version(source) is not None else ""
    print(f"TeleMotoMax {version(source)}: V3, Light и подписанная V8{note} → {dest}")


def check_version(source: Path, repo: str) -> None:
    """Reject source changes under a previously published version in PRs."""
    try:
        manifest = json.loads(read_url(release_url(source, repo) + MANIFEST))
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        error.close()
        print(f"TeleMotoMax {version(source)}: новая версия, будет собрана после попадания в main")
        return
    validate_manifest(source, manifest)
    print(f"TeleMotoMax {version(source)}: исходники соответствуют опубликованному релизу")


def api(repo: str, path: str, token: str, *, method: str = "GET",
        data: bytes | None = None, mime: str = "application/json") -> dict | None:
    url = path if path.startswith("https://uploads.github.com/") else f"https://api.github.com/repos/{repo}/{path}"
    headers = {"Accept": "application/vnd.github+json", "Authorization": "Bearer " + token,
               "Content-Type": mime, "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "TeleMotoMax-release"}
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers,
                                                     method=method), timeout=120) as response:
        return None if response.status == 204 else json.load(response)


def publish(source: Path, repo: str, dist: Path | None, work: Path, target: str) -> None:
    """Build on main, or import already tested binaries for the first release."""
    normalized = repo_url(repo)
    owner_repo = urllib.parse.urlsplit(normalized).path.strip("/")
    if not normalized.startswith("https://github.com/") or not re.fullmatch(r"[\w.-]+/[\w.-]+", owner_repo):
        raise ValueError("публикация поддерживает репозитории github.com")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError("для публикации нужен GH_TOKEN с правом Contents: write")
    tag = f"telemotomax-v{version(source)}"
    try:
        release = api(owner_repo, "releases/tags/" + tag, token)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        error.close()
        release = None
    if release and not release["draft"]:
        # Published versions are never overwritten, even when rerunning CI.
        with tempfile.TemporaryDirectory(prefix="tmm-check-") as check:
            download(source, normalized, Path(check) / "dist")
        print(f"Релиз уже опубликован и проверен: {release['html_url']}")
        return
    if dist is None:
        dist = work / "release"
        dist.mkdir(parents=True, exist_ok=True)
        for module in ("v3", "v3light", "v8"):
            env = dict(os.environ, TMM_MODULES=module, TMM_DIST="1", TMM_DIST_DIR=str(dist.absolute()))
            # An optional local V3 signature is not part of the public release.
            env.pop("TMM_SIGN_V3", None)
            subprocess.run([str(source / "telemotomax/build.sh"), str((work / "build").absolute())],
                           env=env, check=True)
        if probe_version(source) is not None:
            subprocess.run([sys.executable, str(source / PROBE_DIR / "build.py"),
                            "--toolchain", str((work / "build").absolute()),
                            "--output", str(dist.absolute())], check=True)
    manifest = make_manifest(source, dist)
    data = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (dist / MANIFEST).write_bytes(data)
    if not target:
        target = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if release is None:
        payload = {"tag_name": tag, "target_commitish": target,
                   "name": f"TeleMotoMax {version(source)}", "draft": True,
                   "body": "Сборки для Motorola: V3, Light и подписанная V8.\n\n"
                           + ("TmmFlipProbe.jar/.jad — отдельная диагностика крышки V3r.\n\n"
                              if probe_version(source) is not None else "") +
                           "Для установки скачайте JAR и JAD одного варианта. "
                           "На телефоне откройте JAD через раздел /d/ сервера моста.\n\n"
                           "telemotomax-release.json содержит версию, SHA-256 исходников и файлов."}
        release = api(owner_repo, "releases", token, method="POST", data=json.dumps(payload).encode())
    upload = release["upload_url"].split("{", 1)[0]
    # A failed upload leaves a draft; the next invocation can finish it.
    existing = {asset["name"]: asset for asset in release["assets"]}
    for name in (*release_files(source), MANIFEST):
        blob = (dist / name).read_bytes()
        if name in existing:
            asset = existing[name]
            expected_digest = "sha256:" + hashlib.sha256(blob).hexdigest()
            if asset.get("digest") == expected_digest and asset.get("state") == "uploaded":
                continue
            # Rebuilds may have different ZIP timestamps. Only an unpublished
            # draft can be repaired; completed releases remain untouched.
            api(owner_repo, f"releases/assets/{asset['id']}", token, method="DELETE")
        url = upload + "?" + urllib.parse.urlencode({"name": name})
        mime = "application/json" if name == MANIFEST else "application/octet-stream"
        api(owner_repo, url, token, method="POST", data=blob, mime=mime)
    release = api(owner_repo, f"releases/{release['id']}", token, method="PATCH",
                  data=json.dumps({"draft": False, "make_latest": "true"}).encode())
    with tempfile.TemporaryDirectory(prefix="tmm-check-") as check:
        download(source, normalized, Path(check) / "dist")
    print(f"Опубликовано: {release['html_url']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("download", "manifest", "publish", "check"))
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--repo", default="https://github.com/Tamahome-M/icq-tg-bridge")
    parser.add_argument("--dist", type=Path, help="готовые JAR/JAD для manifest или первой публикации")
    parser.add_argument("--dest", type=Path, help="куда скачать сборки (по умолчанию telemotomax/dist)")
    parser.add_argument("--work", type=Path, default=Path(tempfile.gettempdir()) / "telemotomax-release-build")
    parser.add_argument("--target", default="", help="коммит для тега первой публикации")
    args = parser.parse_args()
    try:
        if args.command == "download":
            download(args.source, args.repo, args.dest or args.source / "telemotomax/dist")
        elif args.command == "manifest":
            dist = args.dist or args.source / "telemotomax/dist"
            manifest = make_manifest(args.source, dist)
            (dist / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            print(f"Манифест TeleMotoMax {manifest['version']}: {dist / MANIFEST}")
        elif args.command == "publish":
            publish(args.source, args.repo, args.dist, args.work, args.target)
        else:
            check_version(args.source, args.repo)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        # Never print request headers or the publishing token.
        parser.exit(1, f"TeleMotoMax: {error}\n")


if __name__ == "__main__":
    main()
