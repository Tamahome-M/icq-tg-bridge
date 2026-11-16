"""Native C++ bytes against bridge/cryptography, including stream state on error.

Native run: TMM_CRYPTO_DRIVER='qemu-arm -L ... build/crypto-driver' python3 ...
The default builds a host executable; no networking or user data is involved.
"""
import hashlib
import hmac
import importlib.util
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bridge_secure", ROOT.parent / "bridge/oscar/secure.py")
secure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(secure)


class CryptoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        if os.environ.get("TMM_CRYPTO_DRIVER"):
            cls.command = shlex.split(os.environ["TMM_CRYPTO_DRIVER"])
        else:
            binary = Path(cls.tmp.name) / "crypto"
            subprocess.run(["g++", "-std=c++98", "-O2", "-Isrc", "tests/crypto_driver.cpp", "src/crypto.cpp", "-o", str(binary)], cwd=ROOT, check=True)
            cls.command = [str(binary)]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_lines(self, commands):
        data = "\n".join(op + " " + " ".join(x.hex() or "-" for x in values) for op, values in commands) + "\n"
        result = subprocess.run(self.command, input=data, text=True, stdout=subprocess.PIPE, check=True, timeout=30)
        lines = []
        for line in result.stdout.splitlines():
            ok, value = line.split()
            lines.append((ok == "OK", bytes.fromhex(value) if value != "-" else b""))
        self.assertEqual(len(lines), len(commands))
        return lines

    def test_hash_boundaries(self):
        commands, expected = [], []
        for length in (0, 1, 55, 56, 63, 64, 65, 127, 128, 1024, 65536):
            data = bytes(i % 256 for i in range(length))
            for op, fn in (("sha", hashlib.sha256), ("md5", hashlib.md5)):
                commands.append((op, [data])); expected.append((True, fn(data).digest()))
        self.assertEqual(self.run_lines(commands), expected)

    def test_hmac_long_and_binary_keys(self):
        commands, expected = [], []
        for length in (0, 1, 32, 64, 65, 128):
            key = bytes(range(length)); data = bytes(range(256))
            commands.append(("hmac", [key, data])); expected.append((True, hmac.digest(key, data, "sha256")))
        self.assertEqual(self.run_lines(commands), expected)

    def test_psk_java_compatible_unicode_and_hex(self):
        values = ["1234", "\x00\t Привет \n", "a" * 64, "b" * 63, "😀" * 32, "!" * 64, " "]
        for value in values:
            try: expected = (True, secure.parse_psk(value))
            except ValueError: expected = (False, b"")
            self.assertEqual(self.run_lines([("psk", [value.encode()])])[0], expected)
        bad = [b"\xff", b"\xc0\x80", b"\xed\xa0\x80", b"\xf4\x90\x80\x80", b"a" * 65, "😀".encode() * 33]
        self.assertEqual(self.run_lines([("psk", [v]) for v in bad]), [(False, b"")] * len(bad))

    def test_handshake(self):
        key, nonce = bytes(range(32)), bytes(range(16))
        request = secure.client_hello(key, nonce)
        response = secure.server_hello(key, request, bytes(range(32, 64)))
        expected = secure.client_finish(key, request, response) + secure.session_keys(key, request, response)
        results = self.run_lines([("hello", [key, nonce]), ("finish", [key, request, response]),
                                  ("finish", [key, request, response[:-1] + bytes([response[-1] ^ 1])])])
        self.assertEqual(results, [(True, request), (True, expected), (False, b"")])

    def test_records_replay_tamper_and_sequence(self):
        key, auth = bytes(range(32)), bytes(range(32, 64))
        cipher = secure.RecordCipher(key, auth)
        commands, expected = [("reset", [key, auth])], [(True, b"")]
        for length in (1, 63, 64, 65, 1024, 42):
            plain = bytes((i * 19) % 256 for i in range(length))
            wire = cipher.seal(plain)
            commands.extend([("seal", [plain]), ("open", [wire[:-1] + bytes([wire[-1] ^ 1])]), ("open", [wire]), ("open", [wire])])
            expected.extend([(True, wire), (False, b""), (True, plain), (False, b"")])
        for plain in (b"", b"a" * 1025):
            commands.append(("seal", [plain])); expected.append((False, b""))
        self.assertEqual(self.run_lines(commands), expected)

    def test_urandom(self):
        values = self.run_lines([("random", []), ("random", [])])
        self.assertTrue(all(ok and len(value) == 32 for ok, value in values))
        self.assertNotEqual(values[0][1], values[1][1])


if __name__ == "__main__":
    unittest.main()
