"""Native packages/release integrity, without SDK, network or user data."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec); spec.loader.exec_module(loaded)
    return loaded


release = module("native_release", ROOT / "tools/native-v8-release.py")
package = module("native_package", ROOT / "native-v8/tools/package.py")
client_tests = module("client_release_tests", ROOT / "tests/test_client_release.py")


class NativeReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "source"; self.root.mkdir()
        # Source fingerprint deliberately excludes build products and data.
        shutil.copytree(ROOT / "native-v8", self.root / "native-v8", ignore=shutil.ignore_patterns("build", "dist", "__pycache__"))
        for source in (*package.ASSETS.values(), ROOT / "telemotomax/COPYING"):
            target = self.root / source.relative_to(ROOT); target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, target)
        self.dist = self.root / "native-v8/dist"; self.dist.mkdir()
        for name in release.FILES: (self.dist/name).write_bytes(("package:" + name).encode())
        self.manifest = release.make_manifest(self.root, self.dist)

    def test_source_hash_ignores_build_and_python_cache(self):
        before = release.source_hash(self.root)
        for name in ("build/client.o", "dist/test.bin", "tools/__pycache__/cached.pyc"):
            path = self.root / "native-v8" / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"generated")
        self.assertEqual(before, release.source_hash(self.root))
        (self.root / "native-v8/src/crypto.cpp").write_text("changed")
        self.assertNotEqual(before, release.source_hash(self.root))

    def test_shared_sound_changes_require_native_version(self):
        (self.root / "telemotomax/res/MIDP2/sounds/tg.mp3").write_bytes(b"changed")
        with self.assertRaises(ValueError): release.validate_manifest(self.root, self.manifest)

    def test_manifest_rejects_wrong_source_assets_and_sizes(self):
        release.validate_manifest(self.root, self.manifest)
        cases = []
        for key, value in (("schema", 2), ("version", "0.0.0"), ("source_sha256", "a"*64), ("files", {})):
            changed = json.loads(json.dumps(self.manifest)); changed[key] = value; cases.append(changed)
        for size in (0, -1, release.MAX_FILE + 1, "42"):
            changed = json.loads(json.dumps(self.manifest)); changed["files"][release.FILES[0]]["size"] = size; cases.append(changed)
        for changed in cases:
            with self.subTest(manifest=changed), self.assertRaises(ValueError): release.validate_manifest(self.root, changed)

    def test_download_verifies_every_file_before_replacing(self):
        dest = Path(self.tmp.name)/"installed"; dest.mkdir(); (dest/"previous").write_bytes(b"keep")
        def read(url, limit=0):
            name = url.rsplit("/", 1)[-1]
            if name == release.MANIFEST: return json.dumps(self.manifest).encode()
            return b"damaged" if name == release.FILES[1] else (self.dist/name).read_bytes()
        with patch.object(release.common, "read_url", read), self.assertRaises(ValueError):
            release.download(self.root, "owner/repo", dest)
        self.assertEqual((dest/"previous").read_bytes(), b"keep")

    def test_successful_download_and_symlink_refusal(self):
        dest = Path(self.tmp.name)/"installed"
        def read(url, limit=0):
            name = url.rsplit("/", 1)[-1]
            return json.dumps(self.manifest).encode() if name == release.MANIFEST else (self.dist/name).read_bytes()
        with patch.object(release.common, "read_url", read): release.download(self.root, "owner/repo", dest)
        self.assertEqual({p.name for p in dest.iterdir()}, set(release.FILES))
        link = Path(self.tmp.name)/"linked"; link.symlink_to(dest, target_is_directory=True)
        with patch.object(release.common, "read_url", read), self.assertRaises(ValueError): release.download(self.root, "owner/repo", link)

    def test_packages_are_deterministic_and_have_no_account_data(self):
        binary = Path(self.tmp.name)/"arm"
        header = bytearray(52); header[:6] = b"\x7fELF\x01\x01"; header[18:20] = b"\x28\x00"; binary.write_bytes(header)
        first, second = Path(self.tmp.name)/"first", Path(self.tmp.name)/"second"
        package.build(binary, first); package.build(binary, second)
        for name in release.FILES:
            self.assertEqual((first/name).read_bytes(), (second/name).read_bytes())
            with tarfile.open(first/name) as archive:
                for item in archive:
                    self.assertFalse(item.name.startswith("/")); self.assertNotIn("..", Path(item.name).parts)
                    self.assertFalse(item.issym() or item.islnk()); self.assertNotIn("data", Path(item.name).parts)
                prefix = "app/" if name.endswith(".pep") else "TeleMotoMax-Native/"
                self.assertEqual(archive.getmember(prefix+"telemotomax.lin").mode, 0o755)
                self.assertIn("sounds/msg_low.mp3", "\n".join(archive.getnames()))
                if name.endswith(".pep"):
                    ini = archive.extractfile("description.ini").read()
                    self.assertIn(b"Name = TeleMotoMax Native", ini)
                    self.assertIn(b"Exec = telemotomax.lin", ini)

    def test_reject_host_binary(self):
        binary = Path(self.tmp.name)/"x86"; binary.write_bytes(b"\x7fELF\x02\x01" + b"\0"*50)
        with self.assertRaises(ValueError): package.inputs(binary)

    def test_publish_keeps_java_latest_and_uses_independent_tag(self):
        calls = []
        def api(owner, path, token, **kwargs):
            calls.append((owner, path, kwargs))
            if path.startswith("releases/tags/"):
                raise release.urllib.error.HTTPError(path, 404, "absent", {}, None)
            if path == "releases":
                payload = json.loads(kwargs["data"])
                self.assertEqual(payload["tag_name"], "telemotomax-native-v0.1.0")
                self.assertEqual(payload["target_commitish"], "commit")
                self.assertTrue(payload["draft"])
                return {"id": 99, "assets": [], "upload_url": "https://uploads.github.com/assets{?name}"}
            return {"html_url": "https://github.com/owner/repo/releases/native"}
        with patch.dict(os.environ, GH_TOKEN="test-token"), patch.object(release.common, "api", api), patch.object(release, "download") as verify:
            release.publish(self.root, "owner/repo", self.dist, "commit")
        patches = [json.loads(kw["data"]) for _, _, kw in calls if kw.get("method") == "PATCH"]
        self.assertEqual(patches, [{"draft": False, "make_latest": "false"}])
        self.assertEqual(sum(path.startswith("https://uploads.") for _, path, _ in calls), 3)
        verify.assert_called_once()

    def test_published_release_only_verifies_without_mutating_assets(self):
        with patch.dict(os.environ, GH_TOKEN="test-token"), patch.object(release.common, "api", return_value={"draft": False, "html_url": "release"}) as api, patch.object(release, "download") as verify:
            release.publish(self.root, "owner/repo", self.dist, "commit")
        api.assert_called_once()
        verify.assert_called_once()

    def test_bridge_update_does_not_fetch_or_publish_native_packages(self):
        source, assets, _ = client_tests.fixture(Path(self.tmp.name), "1.31")
        shutil.copyfile(ROOT / "tools/native-v8-release.py", source / "tools/native-v8-release.py")
        # Native sources are in Git, but native packages are installed on the
        # handset separately and must not become an updater dependency.
        shutil.rmtree(self.dist)
        helper = client_tests.ReleaseTests()
        helper.root = Path(self.tmp.name)
        install, events, env = helper.prepare_installed()
        with client_tests.serve(source, assets, events) as repo:
            result = helper.run_update(install, repo, env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((install/"telemotomax/dist/TeleMotoMax-V8.jad").is_file())
        self.assertFalse((install/"native-v8/dist").exists())
        self.assertNotIn("/releases/download/telemotomax-native-", events.read_text())


if __name__ == "__main__": unittest.main()
