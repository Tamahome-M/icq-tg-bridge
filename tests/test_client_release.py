"""Release integrity, publication recovery and VPS migration (no GitHub writes)."""

from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import zipfile


ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("client_release", ROOT / "tools/telemotomax-release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def fixture(root: Path) -> tuple[Path, Path, dict]:
    source = root / "source"
    client = source / "telemotomax"
    (client / "src").mkdir(parents=True)
    (client / "src/App.java").write_text("class App {}\n")
    (client / "VERSION").write_text("1.15\n")
    keys = client / "sign-keys"
    keys.mkdir()
    (keys / "signer.der").write_bytes(b"fixture-signer")
    (keys / "ca.der").write_bytes(b"fixture-root")
    (source / "tools").mkdir()
    shutil.copyfile(ROOT / "tools/telemotomax-release.py", source / "tools/telemotomax-release.py")
    shutil.copyfile(ROOT / "tools/update-from-github.sh", source / "tools/update-from-github.sh")
    (source / "run.py").write_text("# new server\n")
    (source / "requirements.txt").write_text("")
    (source / "bridge").mkdir()
    (source / "bridge/app.py").write_text("# new bridge\n")
    dist = root / "assets"
    dist.mkdir()
    for base in release.BASES:
        jar = dist / f"{base}.jar"
        attrs = ("Manifest-Version: 1.0\nMIDlet-Name: TeleMotoMax\n"
                 "MIDlet-Vendor: fixture\nMIDlet-Version: 1.15\n"
                 "MIDlet-Permissions-Opt: javax.microedition.io.Connector.socket\n")
        with zipfile.ZipFile(jar, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("META-INF/MANIFEST.MF", attrs)
            archive.writestr("App.class", b"test-class")
        jad = attrs + f"MIDlet-Jar-URL: {jar.name}\nMIDlet-Jar-Size: {jar.stat().st_size}\n"
        if base == "TeleMotoMax-V8":
            for number, cert in ((1, b"fixture-signer"), (2, b"fixture-root")):
                jad += f"MIDlet-Certificate-1-{number}: {base64.b64encode(cert).decode()}\n"
            jad += f"MIDlet-Jar-RSA-SHA1: {base64.b64encode(b'fixture-signature').decode()}\n"
        (dist / f"{base}.jad").write_text(jad)
    manifest = release.make_manifest(source, dist)
    (dist / release.MANIFEST).write_text(json.dumps(manifest))
    return source, dist, manifest


def add_probe(source: Path, dist: Path) -> dict:
    folder = source / release.PROBE_DIR
    folder.mkdir(parents=True)
    for name in release.PROBE_INPUTS:
        if name == "stubs":
            (folder / name).mkdir()
            (folder / name / "Api.java").write_text("// compile-only fixture\n")
        else:
            (folder / name).write_text("0.1.0\n" if name == "VERSION" else "// probe fixture\n")
    jar = dist / "TmmFlipProbe.jar"
    attrs = ("MIDlet-Name: TMM Flip Probe\nMIDlet-Vendor: TeleMotoMax\n"
             "MIDlet-Version: 0.1.0\nMIDlet-1: TMM Flip Probe,,FlipProbe\n"
             "Background: True\nFlipInsensitive: True\n")
    with zipfile.ZipFile(jar, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n" + attrs)
        archive.writestr("FlipProbe.class", b"test-probe-class")
    (dist / "TmmFlipProbe.jad").write_text(
        attrs + f"MIDlet-Jar-URL: {jar.name}\nMIDlet-Jar-Size: {jar.stat().st_size}\n")
    manifest = release.make_manifest(source, dist)
    (dist / release.MANIFEST).write_text(json.dumps(manifest))
    return manifest


@contextmanager
def serve(source: Path, dist: Path, events: Path | None = None):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for path in source.rglob("*"):
            if path.is_file():
                output.write(path, "project-main/" + path.relative_to(source).as_posix())

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if events is not None:
                with events.open("a") as log:
                    log.write("get " + self.path + "\n")
            if self.path == "/project/archive/refs/heads/main.zip":
                data = archive.getvalue()
            elif self.path.startswith("/project/releases/download/telemotomax-v1.15/"):
                path = dist / self.path.rsplit("/", 1)[-1]
                if not path.is_file():
                    self.send_error(404)
                    return
                data = path.read_bytes()
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/project"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def snapshot(folder: Path) -> dict[str, bytes]:
    return {path.relative_to(folder).as_posix(): path.read_bytes()
            for path in folder.rglob("*") if path.is_file()}


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tmm-release-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.dist, self.manifest = fixture(self.root)

    def test_download_keeps_pairs_and_signed_jad_exact(self):
        destination = self.root / "installed"
        destination.mkdir()
        (destination / "TeleMotoMax.jar").write_bytes(b"old")
        with serve(self.source, self.dist) as repo:
            release.download(self.source, repo, destination)
        self.assertEqual(set(snapshot(destination)), set(release.FILES))
        for name in release.FILES:
            self.assertEqual((destination / name).read_bytes(), (self.dist / name).read_bytes())

    def test_download_carries_separate_probe_with_its_own_version(self):
        self.manifest = add_probe(self.source, self.dist)
        destination = self.root / "installed"
        with serve(self.source, self.dist) as repo:
            release.download(self.source, repo, destination)
        self.assertEqual(set(snapshot(destination)), set(release.FILES) | {
            "TmmFlipProbe.jar", "TmmFlipProbe.jad"})
        for name in release.release_files(self.source):
            self.assertEqual((destination / name).read_bytes(), (self.dist / name).read_bytes())
        self.assertIn("MIDlet-Version: 0.1.0", (destination / "TmmFlipProbe.jad").read_text())

    def test_missing_or_corrupt_probe_keeps_all_installed_pairs(self):
        self.manifest = add_probe(self.source, self.dist)
        destination = self.root / "installed"
        destination.mkdir()
        for name in release.release_files(self.source):
            (destination / name).write_bytes(b"previous-" + name.encode())
        before = snapshot(destination)
        jad = self.dist / "TmmFlipProbe.jad"
        original = jad.read_bytes()
        jad.write_bytes(b"corrupt")
        with serve(self.source, self.dist) as repo:
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                release.download(self.source, repo, destination)
        self.assertEqual(snapshot(destination), before)
        jad.unlink()
        with serve(self.source, self.dist) as repo:
            with self.assertRaises(urllib.error.HTTPError) as failure:
                release.download(self.source, repo, destination)
            failure.exception.close()
        self.assertEqual(snapshot(destination), before)
        jad.write_bytes(original)

    def test_probe_sources_are_part_of_release_identity(self):
        self.manifest = add_probe(self.source, self.dist)
        release.validate_manifest(self.source, self.manifest)
        (self.source / release.PROBE_DIR / "VodafoneFlip.java").write_text("// changed\n")
        with self.assertRaisesRegex(ValueError, "VERSION"):
            release.validate_manifest(self.source, self.manifest)

    def test_probe_pair_is_required_and_background_attributes_are_validated(self):
        self.manifest = add_probe(self.source, self.dist)
        incomplete = json.loads(json.dumps(self.manifest))
        incomplete["files"].pop("TmmFlipProbe.jar")
        with self.assertRaises(ValueError):
            release.validate_manifest(self.source, incomplete)
        path = self.dist / "TmmFlipProbe.jad"
        original = path.read_text()
        for old, new in (("MIDlet-Version: 0.1.0", "MIDlet-Version: 1.15"),
                         ("FlipInsensitive: True", "FlipInsensitive: False"),
                         ("MIDlet-Jar-URL: TmmFlipProbe.jar", "MIDlet-Jar-URL: Other.jar")):
            path.write_text(original.replace(old, new))
            with self.assertRaises(ValueError):
                release.make_manifest(self.source, self.dist)
        path.write_text(original)

    def test_corrupt_last_asset_does_not_change_installed_files(self):
        destination = self.root / "installed"
        destination.mkdir()
        (destination / "TeleMotoMax.jar").write_bytes(b"previous")
        before = snapshot(destination)
        with (self.dist / release.FILES[-1]).open("ab") as file:
            file.write(b"corruption")
        with serve(self.source, self.dist) as repo:
            with self.assertRaises(ValueError):
                release.download(self.source, repo, destination)
        self.assertEqual(snapshot(destination), before)
        self.assertFalse(list(self.root.glob(".telemotomax-*")))

    def test_source_change_requires_new_version(self):
        (self.source / "telemotomax/src/App.java").write_text("class NewApp {}")
        with self.assertRaisesRegex(ValueError, "VERSION"):
            release.validate_manifest(self.source, self.manifest)

    def test_ci_version_check_rejects_changed_published_client(self):
        with patch.object(release, "read_url", return_value=json.dumps(self.manifest).encode()):
            release.check_version(self.source, "owner/repo")
            (self.source / "telemotomax/src/App.java").write_text("class NewApp {}")
            with self.assertRaisesRegex(ValueError, "VERSION"):
                release.check_version(self.source, "owner/repo")

    def test_ci_version_check_allows_unpublished_version(self):
        missing = urllib.error.HTTPError("test", 404, "not found", {}, None)
        with patch.object(release, "read_url", side_effect=missing):
            release.check_version(self.source, "owner/repo")

    def test_ci_network_failure_is_not_treated_as_new_version(self):
        denied = urllib.error.HTTPError("test", 403, "denied", {}, None)
        self.addCleanup(denied.close)
        with patch.object(release, "read_url", side_effect=denied):
            with self.assertRaises(urllib.error.HTTPError):
                release.check_version(self.source, "owner/repo")

    def test_source_hash_ignores_documentation_and_generated_binaries(self):
        (self.source / "telemotomax/README.md").write_text("new documentation")
        (self.source / "telemotomax/dist").mkdir()
        (self.source / "telemotomax/dist/TeleMotoMax.jar").write_bytes(b"local build")
        release.validate_manifest(self.source, self.manifest)

    def test_vendor_stub_signatures_are_build_inputs(self):
        folder = self.source / "telemotomax/stubs/com/vodafone/system"
        folder.mkdir(parents=True)
        (folder / "DeviceControl.java").write_text("// changed vendor signatures\n")
        with self.assertRaises(ValueError):
            release.validate_manifest(self.source, self.manifest)

    def test_wrong_version_missing_pair_and_invalid_sizes(self):
        for mutation in (
            lambda data: data.update(version="1.16"),
            lambda data: data["files"].pop("TeleMotoMax-Light.jar"),
            lambda data: data["files"]["TeleMotoMax.jar"].update(size=0),
            lambda data: data["files"]["TeleMotoMax.jar"].update(size=True),
            lambda data: data["files"]["TeleMotoMax.jar"].update(sha256="bad"),
        ):
            changed = json.loads(json.dumps(self.manifest))
            mutation(changed)
            with self.assertRaises(ValueError):
                release.validate_manifest(self.source, changed)

    def test_wrong_relative_url_size_and_certificate_are_rejected(self):
        for name, old, new in (
            ("TeleMotoMax.jad", "MIDlet-Jar-URL: TeleMotoMax.jar", "MIDlet-Jar-URL: Other.jar"),
            ("TeleMotoMax-Light.jad", "MIDlet-Version: 1.15", "MIDlet-Version: 1.14"),
            ("TeleMotoMax-V8.jad", base64.b64encode(b"fixture-root").decode(), base64.b64encode(b"other-root").decode()),
        ):
            path = self.dist / name
            original = path.read_text()
            path.write_text(original.replace(old, new))
            with self.assertRaises(ValueError):
                release.make_manifest(self.source, self.dist)
            path.write_text(original)

    def test_failed_directory_swap_restores_previous_build(self):
        destination = self.root / "installed"
        destination.mkdir()
        (destination / "previous.jar").write_bytes(b"previous")
        rename = Path.rename

        def fail_staged(path, target):
            if path.name == "dist":
                raise OSError("simulated rename failure")
            return rename(path, target)

        with serve(self.source, self.dist) as repo, patch.object(Path, "rename", fail_staged):
            with self.assertRaises(OSError):
                release.download(self.source, repo, destination)
        self.assertEqual(snapshot(destination), {"previous.jar": b"previous"})

    def test_published_release_is_checked_without_upload_or_build(self):
        published = {"draft": False, "html_url": "https://github.com/owner/repo/releases/test"}
        with patch.dict(os.environ, {"GH_TOKEN": "test-token"}), \
                patch.object(release, "api", return_value=published) as api, \
                patch.object(release, "download") as download, \
                patch.object(release.subprocess, "run") as build:
            release.publish(self.source, "owner/repo", None, self.root / "work", "main")
        api.assert_called_once()
        download.assert_called_once()
        build.assert_not_called()

    def test_draft_is_only_published_after_all_assets_upload(self):
        calls = []
        draft = {"id": 7, "draft": True, "assets": [],
                 "upload_url": "https://uploads.github.com/repos/owner/repo/releases/7/assets{?name,label}"}

        def fake_api(repo, path, token, **kwargs):
            calls.append((path, kwargs.get("method", "GET")))
            if path.startswith("releases/tags/"):
                raise urllib.error.HTTPError(path, 404, "not found", {}, None)
            if path == "releases/7":
                return {"html_url": "https://github.com/owner/repo/releases/test"}
            return draft

        with patch.dict(os.environ, {"GH_TOKEN": "test-token"}), \
                patch.object(release, "api", side_effect=fake_api), \
                patch.object(release, "download"):
            release.publish(self.source, "owner/repo", self.dist, self.root / "work", "main")
        uploads = [path for path, method in calls if path.startswith("https://uploads.")]
        self.assertEqual(len(uploads), 7)
        self.assertEqual(calls[-1], ("releases/7", "PATCH"))

    def test_ci_builds_all_variants_in_separate_local_directory(self):
        # The fake builder emits the validated fixtures into the requested
        # output directory; no real compilation/network download is needed.
        draft = {"id": 7, "draft": True, "assets": [],
                 "upload_url": "https://uploads.github.com/repos/owner/repo/releases/7/assets{?name,label}"}
        modules = []

        def builder(command, *, env, check):
            modules.append(env["TMM_MODULES"])
            self.assertEqual(env["TMM_DIST"], "1")
            self.assertNotIn("TMM_SIGN_V3", env)
            destination = Path(env["TMM_DIST_DIR"])
            self.assertEqual(destination, self.root / "work/release")
            for name in release.FILES:
                shutil.copyfile(self.dist / name, destination / name)

        with patch.dict(os.environ, {"GH_TOKEN": "test-token", "TMM_SIGN_V3": "1"}), \
                patch.object(release, "api", return_value=draft), \
                patch.object(release, "download"), \
                patch.object(release.subprocess, "run", side_effect=builder):
            # Return a draft on lookup so publication proceeds to building.
            draft["html_url"] = "test"
            release.publish(self.source, "owner/repo", None, self.root / "work", "main")
        self.assertEqual(modules, ["v3", "v3light", "v8"])

    def test_ci_builds_probe_after_clients_and_uploads_nine_assets(self):
        self.manifest = add_probe(self.source, self.dist)
        draft = {"id": 7, "draft": True, "assets": [], "html_url": "test",
                 "upload_url": "https://uploads.github.com/repos/owner/repo/releases/7/assets{?name,label}"}
        modules = []

        def builder(command, **kwargs):
            if "env" in kwargs:
                modules.append(kwargs["env"]["TMM_MODULES"])
                destination = Path(kwargs["env"]["TMM_DIST_DIR"])
                for name in release.FILES:
                    shutil.copyfile(self.dist / name, destination / name)
            else:
                self.assertEqual(modules, ["v3", "v3light", "v8"])
                self.assertEqual(Path(command[1]), self.source / release.PROBE_DIR / "build.py")
                self.assertEqual(Path(command[command.index("--toolchain") + 1]), self.root / "work/build")
                destination = Path(command[command.index("--output") + 1])
                for name in ("TmmFlipProbe.jar", "TmmFlipProbe.jad"):
                    shutil.copyfile(self.dist / name, destination / name)
                modules.append("probe")

        with patch.dict(os.environ, {"GH_TOKEN": "test-token"}), \
                patch.object(release, "api", return_value=draft) as api, \
                patch.object(release, "download"), \
                patch.object(release.subprocess, "run", side_effect=builder):
            release.publish(self.source, "owner/repo", None, self.root / "work", "main")
        self.assertEqual(modules, ["v3", "v3light", "v8", "probe"])
        uploads = [call for call in api.call_args_list if call.args[1].startswith("https://uploads.")]
        self.assertEqual(len(uploads), 9)
        self.assertTrue(any("TmmFlipProbe.jar" in call.args[1] for call in uploads))
        self.assertTrue(any("TmmFlipProbe.jad" in call.args[1] for call in uploads))
        self.assertEqual(set(json.loads((self.root / "work/release" / release.MANIFEST).read_text())["files"]),
                         set(release.release_files(self.source)))

    def test_interrupted_draft_upload_can_resume(self):
        calls = []
        first = (self.dist / release.FILES[0]).read_bytes()
        draft = {"id": 7, "draft": True, "assets": [
            {"id": 1, "name": release.FILES[0], "state": "uploaded",
             "digest": "sha256:" + hashlib.sha256(first).hexdigest()},
            {"id": 2, "name": release.FILES[1], "state": "starter", "digest": None}],
            "upload_url": "https://uploads.github.com/repos/owner/repo/releases/7/assets{?name,label}"}

        def fake_api(repo, path, token, **kwargs):
            calls.append((path, kwargs.get("method", "GET")))
            return {"html_url": "test"} if path == "releases/7" else draft

        with patch.dict(os.environ, {"GH_TOKEN": "test-token"}), \
                patch.object(release, "api", side_effect=fake_api), \
                patch.object(release, "download"):
            release.publish(self.source, "owner/repo", self.dist, self.root / "work", "main")
        self.assertIn(("releases/assets/2", "DELETE"), calls)
        self.assertEqual(sum(path.startswith("https://uploads.") for path, _ in calls), 6)
        self.assertEqual(calls[-1], ("releases/7", "PATCH"))

    def prepare_installed(self):
        install = self.root / "vps"
        (install / "telemotomax/dist").mkdir(parents=True)
        (install / "bridge").mkdir()
        (install / "tools").mkdir()
        (install / "run.py").write_text("# old server\n")
        (install / "bridge/app.py").write_text("# old bridge\n")
        (install / "bridge/obsolete.py").write_text("# obsolete\n")
        (install / "tools/update-from-github.sh").write_text("# old updater\n")
        for name in release.FILES:
            (install / "telemotomax/dist" / name).write_bytes(b"old-" + name.encode())
        for name in ("config.toml", "tg.session", "max.session", "bridge.db",
                     "downloads/custom.jar", "photos/p.jpg", ".venv/keep"):
            path = install / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"keep-" + name.encode())
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        events = self.root / "events"
        events.touch()
        service = bin_dir / "rc-service"
        service.write_text('#!/bin/sh\nprintf "service %s\\n" "$2" >> "$TEST_EVENTS"\n')
        service.chmod(0o755)
        sleeper = bin_dir / "sleep"
        sleeper.write_text("#!/bin/sh\nexit 0\n")
        sleeper.chmod(0o755)
        # Exercise the existing venv/Python selection without installing pip
        # packages or stopping a real service.
        python = install / ".venv/bin/python"
        python.parent.mkdir()
        python.write_text('#!/bin/sh\nif [ "$1" = -m ] && [ "$2" = pip ]; then exit 0; fi\n'
                          'exec "$TEST_PYTHON" "$@"\n')
        python.chmod(0o755)
        env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ["PATH"],
                   TEST_EVENTS=str(events), TEST_PYTHON=sys.executable)
        return install, events, env

    def run_update(self, install, repo, env, *extra, installed=False):
        script = (install if installed else ROOT) / "tools/update-from-github.sh"
        return subprocess.run(["sh", str(script), "-d", str(install),
                               "-r", repo, "-u", "tmm-test-nonexistent-user", *extra],
                              env=env, text=True, capture_output=True, timeout=30)

    def test_vps_first_update_prepares_clients_before_stopping_service(self):
        install, events, env = self.prepare_installed()
        before = snapshot(install)
        with serve(self.source, self.dist, events) as repo:
            result = self.run_update(install, repo, env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name in release.FILES:
            self.assertEqual((install / "telemotomax/dist" / name).read_bytes(), (self.dist / name).read_bytes())
        self.assertEqual((install / "bridge/app.py").read_text(), "# new bridge\n")
        self.assertFalse((install / "bridge/obsolete.py").exists())
        for name, data in before.items():
            if name.startswith((".", "downloads/", "photos/")) or name in (
                    "config.toml", "tg.session", "max.session", "bridge.db"):
                self.assertEqual((install / name).read_bytes(), data)
        trace = events.read_text().splitlines()
        stop = trace.index("service stop")
        self.assertEqual(sum(line.startswith("get ") for line in trace[:stop]), 8)
        self.assertEqual(trace[-1], "service start")

    def test_ordinary_vps_update_installs_probe_on_every_pass(self):
        self.manifest = add_probe(self.source, self.dist)
        install, events, env = self.prepare_installed()
        with serve(self.source, self.dist, events) as repo:
            first = self.run_update(install, repo, env)
            second = self.run_update(install, repo, env, installed=True)
        for result in (first, second):
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name in release.release_files(self.source):
            self.assertEqual((install / "telemotomax/dist" / name).read_bytes(),
                             (self.dist / name).read_bytes())
        trace = events.read_text().splitlines()
        stop = trace.index("service stop")
        self.assertEqual(sum(line.startswith("get ") for line in trace[:stop]), 10)
        self.assertEqual(trace.count("service start"), 2)

    def test_failed_probe_download_does_not_stop_or_update_bridge(self):
        self.manifest = add_probe(self.source, self.dist)
        install, events, env = self.prepare_installed()
        before = snapshot(install)
        (self.dist / "TmmFlipProbe.jar").write_bytes(b"corrupt")
        with serve(self.source, self.dist, events) as repo:
            result = self.run_update(install, repo, env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(snapshot(install), before)
        self.assertNotIn("service ", events.read_text())
        self.assertIn("TmmFlipProbe.jar", result.stderr)

    def test_installed_updater_restores_clients_removed_by_legacy_first_pass(self):
        install, events, env = self.prepare_installed()
        # The legacy script installs these sources, but removes dist because
        # release binaries are absent from the source archive.
        shutil.rmtree(install / "telemotomax/dist")
        for name in ("update-from-github.sh", "telemotomax-release.py"):
            shutil.copyfile(ROOT / "tools" / name, install / "tools" / name)
        before = snapshot(install)
        with serve(self.source, self.dist, events) as repo:
            result = self.run_update(install, repo, env, installed=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name in release.FILES:
            self.assertEqual((install / "telemotomax/dist" / name).read_bytes(),
                             (self.dist / name).read_bytes())
        self.assertEqual((install / "config.toml").read_bytes(), before["config.toml"])
        self.assertEqual((install / "downloads/custom.jar").read_bytes(), before["downloads/custom.jar"])
        trace = events.read_text().splitlines()
        self.assertEqual(sum(line.startswith("get ") for line in trace[:trace.index("service stop")]), 8)
        self.assertEqual(trace[-1], "service start")

    def test_vps_dry_run_downloads_and_validates_without_changing_installation(self):
        install, events, env = self.prepare_installed()
        before = snapshot(install)
        with serve(self.source, self.dist, events) as repo:
            result = self.run_update(install, repo, env, "-n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(snapshot(install), before)
        self.assertNotIn("service ", events.read_text())

    def test_vps_missing_or_broken_release_keeps_bridge_running(self):
        install, events, env = self.prepare_installed()
        before = snapshot(install)
        manifest = self.dist / release.MANIFEST
        original = manifest.read_bytes()
        manifest.unlink()
        with serve(self.source, self.dist, events) as repo:
            missing = self.run_update(install, repo, env)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("ещё не опубликован", missing.stderr)
        manifest.write_bytes(original)
        (self.dist / release.FILES[-1]).write_bytes(b"broken")
        with serve(self.source, self.dist, events) as repo:
            broken = self.run_update(install, repo, env)
        self.assertNotEqual(broken.returncode, 0)
        self.assertIn("SHA-256", broken.stderr)
        self.assertEqual(snapshot(install), before)
        self.assertNotIn("service ", events.read_text())

    def test_update_to_legacy_archive_with_embedded_clients_still_works(self):
        # A selected old branch may predate Releases and include its own JARs.
        (self.source / "tools/telemotomax-release.py").unlink()
        embedded = self.source / "telemotomax/dist"
        embedded.mkdir()
        for name in release.FILES:
            shutil.copyfile(self.dist / name, embedded / name)
        install, events, env = self.prepare_installed()
        with serve(self.source, self.dist, events) as repo:
            result = self.run_update(install, repo, env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name in release.FILES:
            self.assertEqual((install / "telemotomax/dist" / name).read_bytes(), (self.dist / name).read_bytes())
        self.assertEqual(sum(line.startswith("get ") for line in events.read_text().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
