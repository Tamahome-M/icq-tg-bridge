#!/usr/bin/env python3
"""Separate native V8 releases; Java versions and manifests remain independent."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.error
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("java_release", Path(__file__).with_name("telemotomax-release.py"))
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)
FILES = ("TeleMotoMax-Native-V8.tar.gz", "TeleMotoMax-Native-V8.pep")
MANIFEST = "telemotomax-native-release.json"
MAX_FILE = 16 * 1024 * 1024


def version(source):
    value = (source / "native-v8/VERSION").read_text().strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", value): raise ValueError("Invalid native version")
    return value


def source_hash(source):
    native = source / "native-v8"
    files = [p for name in ("src", "tools", "sounds", "resources", "VERSION", "Makefile", "telemotomax.lin", "collect-log.lin", "collect-log-xp.cmd", "README.md", "features.tsv")
             for p in ((native / name).rglob("*") if (native / name).is_dir() else [native / name]) if p.is_file()]
    files += [source / "telemotomax/res/MIDP2/sounds/tg.mp3"]
    files += [source / "telemotomax/COPYING"]
    files += [source / "telemotomax/util/icon/make_icon.py"]
    files += [source / "telemotomax/res/GRAPHICS_32BIT/COMMON/icon.png"]
    files += [source / f"telemotomax/res/GRAPHICS_8BIT/COMMON/{n}.png" for n in ("statuses", "messages")]
    files += [source / f"telemotomax/res/GRAPHICS_32BIT/MODULES/SMILES_STD/{n}" for n in ("smiles.png", "smiles.txt")]
    digest = hashlib.sha256()
    for path in sorted(files):
        # Generated __pycache__ must never alter a source fingerprint.
        if "__pycache__" in path.parts: continue
        digest.update(path.relative_to(source).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def release_url(source, repo):
    return common.repo_url(repo) + f"/releases/download/telemotomax-native-v{version(source)}/"


def make_manifest(source, dist):
    return {"schema": 1, "version": version(source), "source_sha256": source_hash(source),
            "files": {name: {"size": (dist/name).stat().st_size,
                             "sha256": hashlib.sha256((dist/name).read_bytes()).hexdigest()} for name in FILES}}


def validate_manifest(source, manifest):
    if (not isinstance(manifest, dict) or manifest.get("schema") != 1 or manifest.get("version") != version(source)
            or manifest.get("source_sha256") != source_hash(source) or not isinstance(manifest.get("files"), dict)
            or set(manifest["files"]) != set(FILES)):
        raise ValueError("Native release does not match these sources; increment native-v8/VERSION")
    for record in manifest["files"].values():
        if not isinstance(record, dict) or type(record.get("size")) is not int or not 0 < record["size"] <= MAX_FILE or not re.fullmatch(r"[a-f0-9]{64}", str(record.get("sha256", ""))):
            raise ValueError("Invalid native release manifest")


def download(source, repo, dest):
    url = release_url(source, repo)
    manifest = json.loads(common.read_url(url + MANIFEST))
    validate_manifest(source, manifest)
    dest = dest.absolute(); dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".tmm-native-", dir=dest.parent) as temporary:
        staged = Path(temporary)/"dist"; staged.mkdir()
        for name in FILES:
            record = manifest["files"][name]; data = common.read_url(url + name, record["size"])
            if len(data) != record["size"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise ValueError(f"Native release integrity error: {name}")
            (staged/name).write_bytes(data)
        backup = Path(temporary)/"previous"
        if dest.exists() or dest.is_symlink():
            if not dest.is_dir() or dest.is_symlink(): raise ValueError("Native dist must be a regular directory")
            dest.rename(backup)
        try: staged.rename(dest)
        except OSError:
            if backup.exists(): backup.rename(dest)
            raise
    print(f"TeleMotoMax Native {version(source)} → {dest}")


def check(source, repo):
    try: manifest = json.loads(common.read_url(release_url(source, repo) + MANIFEST))
    except urllib.error.HTTPError as error:
        if error.code != 404: raise
        error.close(); print(f"New native version {version(source)}"); return
    validate_manifest(source, manifest)
    print(f"Native {version(source)} sources match published version")


def publish(source, repo, dist, target):
    normalized = common.repo_url(repo); owner = urllib.parse.urlsplit(normalized).path.strip("/")
    if not normalized.startswith("https://github.com/") or not re.fullmatch(r"[\w.-]+/[\w.-]+", owner): raise ValueError("Expected a GitHub repository")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token: raise ValueError("GH_TOKEN is required for publishing")
    tag = f"telemotomax-native-v{version(source)}"
    try: release = common.api(owner, "releases/tags/" + tag, token)
    except urllib.error.HTTPError as error:
        if error.code != 404: raise
        error.close(); release = None
    if release and not release["draft"]:
        with tempfile.TemporaryDirectory() as tmp: download(source, repo, Path(tmp)/"dist")
        print(release["html_url"]); return
    manifest = make_manifest(source, dist); validate_manifest(source, manifest)
    (dist/MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n")
    if not target: target = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if release is None:
        payload = {"tag_name": tag, "target_commitish": target, "draft": True,
                   "name": f"TeleMotoMax Native V8 {version(source)}",
                   "body": "Отдельный нативный клиент Motorola V8 / SAedition. Java-сборки выпускаются отдельно.\n\n"
                           "PEP — установка через vInstaller; tar.gz — ручная установка. Инструкция внутри архива. "
                           "Манифест содержит SHA-256 исходников и пакетов.\n\n"
                           "Первая нативная версия: аппаратные функции требуют проверки на телефоне."}
        release = common.api(owner, "releases", token, method="POST", data=json.dumps(payload).encode())
    existing = {a["name"]: a for a in release["assets"]}
    upload = release["upload_url"].split("{", 1)[0]
    for name in (*FILES, MANIFEST):
        data = (dist/name).read_bytes()
        if name in existing:
            asset = existing[name]
            if asset.get("digest") == "sha256:" + hashlib.sha256(data).hexdigest() and asset.get("state") == "uploaded": continue
            common.api(owner, f"releases/assets/{asset['id']}", token, method="DELETE")
        common.api(owner, upload + "?" + urllib.parse.urlencode({"name": name}), token, method="POST", data=data,
                   mime="application/json" if name == MANIFEST else "application/octet-stream")
    release = common.api(owner, f"releases/{release['id']}", token, method="PATCH", data=json.dumps({"draft": False, "make_latest": "false"}).encode())
    with tempfile.TemporaryDirectory() as tmp: download(source, repo, Path(tmp)/"dist")
    print(release["html_url"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "manifest", "download", "publish"))
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--repo", default="Tamahome-M/icq-tg-bridge")
    parser.add_argument("--dist", type=Path)
    parser.add_argument("--dest", type=Path)
    parser.add_argument("--target", default="")
    args = parser.parse_args(); dist = args.dist or args.source/"native-v8/dist"
    try:
        if args.command == "check": check(args.source, args.repo)
        elif args.command == "download": download(args.source, args.repo, args.dest or dist)
        elif args.command == "publish": publish(args.source, args.repo, dist, args.target)
        else:
            manifest = make_manifest(args.source, dist); validate_manifest(args.source, manifest)
            (dist/MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n")
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"TeleMotoMax Native: {error}\n")


if __name__ == "__main__": main()
