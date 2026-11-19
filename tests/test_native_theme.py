"""Resource integrity and reversible skin installation, using the actual C++ core."""
import importlib.util
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'native-v8'
BUNDLE = NATIVE / 'resources/status-icons.ezx'
spec = importlib.util.spec_from_file_location('status_icons', NATIVE / 'tools/make_status_icons.py')
icons = importlib.util.module_from_spec(spec)
spec.loader.exec_module(icons)


def unpack(data):
    header = int(data[16:24], 16)
    assert header % 4 == 0
    magic, names, count, index, payload = struct.unpack_from('<5I', data, header)
    assert magic == 0xabcddcba and index == header + 20 and payload == index + count * 12
    result = {}
    for at in range(count):
        hashed, name, offset = struct.unpack_from('<3I', data, index + at * 12)
        key = data[names + name:data.index(b'\n', names + name)].decode('ascii')
        assert hashed == icons.resource_hash(key) and key not in result
        magic, size = struct.unpack_from('<2I', data, payload + offset)
        assert magic == 0xdcbaabcd and payload + offset + 8 + size <= len(data)
        result[key] = data[payload + offset + 8:payload + offset + 8 + size]
    return result


class NativeThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        cls.driver = Path(cls.build.name) / 'theme-patch'
        subprocess.run(['g++', '-std=c++98', '-Wall', '-Wextra', '-Werror',
                        '-I' + str(NATIVE / 'src'), str(NATIVE / 'tests/theme_patch_driver.cpp'),
                        str(NATIVE / 'src/theme_patch.cpp'), '-o', str(cls.driver)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.skin = self.root / 'original skin'
        self.skin.mkdir()
        (self.skin / 'phone_p.ini').write_bytes(b'[palette]\ncolor=123\n')
        (self.skin / 'relative.ini').symlink_to('phone_p.ini')
        self.patch = self.root / 'persistent data'
        self.patch.mkdir()
        self.config = self.root / 'ezx_theme.cfg'
        self.initial = ('[THEME_CONFIG_TABLE]\r\nColor = 5\r\n[THEME_GROUP_LOG]\r\n'
                        f'CurrentSkin = {self.skin}\r\nCurrentTheme = /original/theme.phm\r\n').encode()
        self.config.write_bytes(self.initial)
        self.config.chmod(0o640)

    def run_tool(self, action='install', bundle=BUNDLE, success=True):
        result = subprocess.run([str(self.driver), action, str(self.config),
                                 str(self.patch), str(bundle)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0 if success else 1, result.stderr)
        return result

    def test_bundle_has_all_states_and_valid_small_pngs(self):
        images = unpack(BUNDLE.read_bytes())
        self.assertEqual(len(images), 13)
        for key, data in images.items():
            self.assertTrue(key.startswith('tmm_') and len(key) <= 60)
            self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
            w, h = struct.unpack_from('>II', data, 16)
            self.assertLessEqual(w, 40)
            self.assertLessEqual(h, 20)

    def test_install_restore_preserve_original_styles_and_other_settings(self):
        self.run_tool()
        clone = self.patch / 'skin'
        self.assertEqual((clone / 'relative.ini').read_bytes(), b'[palette]\ncolor=123\n')
        self.assertTrue((clone / 'phone_p.ini').is_symlink())
        self.assertEqual(unpack((clone / 'iconres.ezx').read_bytes()), unpack(BUNDLE.read_bytes()))
        self.assertEqual((self.patch / 'theme-backup.cfg').read_bytes(), self.initial)
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o640)
        changed = self.config.read_bytes().replace(b'Color = 5', b'Color = 8')
        self.config.write_bytes(changed)
        self.run_tool('restore')
        self.assertEqual(self.config.read_bytes(), self.initial.replace(b'Color = 5', b'Color = 8'))
        self.assertFalse((self.skin / 'iconres.ezx').exists())

    def test_repeat_install_does_not_nest_clone_or_overwrite_backup(self):
        self.run_tool()
        first = (self.patch / 'skin/iconres.ezx').read_bytes()
        self.run_tool()
        self.assertEqual(first, (self.patch / 'skin/iconres.ezx').read_bytes())
        self.assertEqual((self.patch / 'theme-backup.cfg').read_bytes(), self.initial)
        self.run_tool('restore')
        self.assertEqual(self.config.read_bytes(), self.initial)

    def test_restoration_does_not_replace_a_theme_selected_later(self):
        self.run_tool()
        self.config.write_bytes(self.initial.replace(b'Color = 5', b'Color = 6'))
        current = self.config.read_bytes()
        self.run_tool('restore', success=False)
        self.assertEqual(self.config.read_bytes(), current)

    def test_corrupt_pack_leaves_config_and_existing_output_intact(self):
        self.run_tool()
        previous = (self.patch / 'skin/iconres.ezx').read_bytes()
        config = self.config.read_bytes()
        data = BUNDLE.read_bytes()
        bad = self.root / 'bad.ezx'
        for blob in (b'', data[:24], data[:len(data)//2], b'bad' + data[3:]):
            bad.write_bytes(blob)
            self.run_tool(bundle=bad, success=False)
            self.assertEqual(config, self.config.read_bytes())
            self.assertEqual(previous, (self.patch / 'skin/iconres.ezx').read_bytes())

    def test_pack_merge_preserves_original_image_payloads_exactly(self):
        # Include a .g payload and duplicate keys; the addon must override only
        # its names. Unrelated opaque Motorola payloads remain byte-for-byte.
        payload = b'unchanged-original-gif-data'
        base = icons.pack({'original': payload, 'tmm_offline_cli': b'old-patch'})
        (self.skin / 'iconres.ezx').write_bytes(base)
        self.run_tool()
        merged = unpack((self.patch / 'skin/iconres.ezx').read_bytes())
        self.assertEqual(merged.pop('original.g'), payload)
        self.assertEqual(merged, unpack(BUNDLE.read_bytes()))
        self.assertEqual((self.skin / 'iconres.ezx').read_bytes(), base)

    def test_selecting_new_theme_does_not_keep_old_theme_files(self):
        (self.skin / 'old-only.ini').write_bytes(b'old theme')
        self.run_tool()
        other = self.root / 'other'
        other.mkdir()
        (other / 'new-only.ini').write_bytes(b'new theme')
        self.config.write_bytes(self.initial.replace(str(self.skin).encode(), str(other).encode()))
        self.run_tool()
        self.assertFalse((self.patch / 'skin/old-only.ini').exists())
        self.assertEqual((self.patch / 'skin/new-only.ini').read_bytes(), b'new theme')
        self.run_tool('restore')
        self.assertIn(str(other).encode(), self.config.read_bytes())

    def test_ambiguous_config_and_symlinked_clone_are_refused(self):
        self.config.write_bytes(self.initial + b'CurrentSkin = /other\r\n')
        before = self.config.read_bytes()
        self.run_tool(success=False)
        self.assertEqual(self.config.read_bytes(), before)
        self.config.write_bytes(self.initial)
        (self.patch / 'skin').symlink_to(self.skin, target_is_directory=True)
        self.run_tool(success=False)
        self.assertFalse((self.skin / 'iconres.ezx').exists())


if __name__ == '__main__':
    unittest.main()
