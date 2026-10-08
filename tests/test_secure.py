"""TMME crypto oracle, malformed records, and real legacy/encrypted OSCAR sockets."""
from __future__ import annotations

import asyncio
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from bridge.config import Config
from bridge.oscar import secure, const as C, blocks
from bridge.oscar.proto import flap, pstr8, tlv
from tests.fake_jimm import FakeJimm
from tests.test_telemotomax import make_server

PSK = bytes(range(32))  # Public test vector, never a deployment key.


async def recv_raw(reader):
    header = await asyncio.wait_for(reader.readexactly(6), 5)
    assert header[0] == 42
    return header[1], await reader.readexactly(int.from_bytes(header[4:6], "big"))


class TapReader:
    def __init__(self, raw, wire): self.raw, self.wire = raw, wire
    async def readexactly(self, n):
        data = await self.raw.readexactly(n); self.wire.extend(data); return data


class TapWriter:
    def __init__(self, raw, wire): self.raw, self.wire = raw, wire
    def write(self, data): self.wire.extend(data); self.raw.write(data)
    def __getattr__(self, name): return getattr(self.raw, name)


class SecureDialer:
    def __init__(self, key=PSK): self.key, self.wire, self.keys = key, bytearray(), []
    async def __call__(self, host, port):
        reader, writer = await asyncio.open_connection(host, port)
        try:
            assert await recv_raw(reader) == (1, b"\x00\x00\x00\x01")
            request = secure.client_hello(self.key, len(self.keys).to_bytes(16, "big"))
            writer.write(flap(secure.CHANNEL, 1, request)); await writer.drain()
            channel, response = await recv_raw(reader)
            assert channel == secure.CHANNEL
            finish = secure.client_finish(self.key, request, response)
            writer.write(flap(secure.CHANNEL, 2, finish)); await writer.drain()
            keys = secure.session_keys(self.key, request, response); self.keys.append(keys)
            return secure.wrap(TapReader(reader, self.wire), TapWriter(writer, self.wire), keys, server=False)
        except BaseException:
            writer.close(); await writer.wait_closed(); raise


class CryptoTests(unittest.TestCase):
    def test_derivation_and_records(self):
        request = secure.client_hello(PSK, bytes(range(16)))
        response = secure.server_hello(PSK, request, bytes(range(32)))
        derived = secure.session_keys(PSK, request, response)
        oracle = HKDF(algorithm=hashes.SHA256(), length=128, salt=request[6:22]+response[6:38], info=secure.INFO).derive(PSK)
        self.assertEqual(derived, oracle)
        self.assertEqual(len(set(derived[i:i+32] for i in range(0, 128, 32))), 4)
        for sequence in (0, 1, 32768, 65536, 0xffffffff, 0x100000000):
            for size in (1, 17, 64, 65, 1024):
                tx = secure.RecordCipher(derived[:32], derived[32:64])
                rx = secure.RecordCipher(derived[:32], derived[32:64])
                tx.sequence = rx.sequence = sequence
                data = bytes(i % 256 for i in range(size))
                record = tx.seal(data)
                self.assertEqual(rx.open(record), data)
                with self.assertRaises(secure.SecureError): rx.open(record)

    def test_reject_before_decrypt(self):
        tx = secure.RecordCipher(PSK, PSK[::-1]); record = tx.seal(b"private")
        for changed in (bytes([record[0]^1])+record[1:], record[:-1]+bytes([record[-1]^1]), record[:-1], b"\0\0"+bytes(16)):
            rx = secure.RecordCipher(PSK, PSK[::-1])
            rx._crypt = lambda _: self.fail("unauthenticated data decrypted")
            with self.assertRaises(secure.SecureError): rx.open(changed)
        with self.assertRaises(secure.SecureError): secure.RecordCipher(PSK, PSK).seal(bytes(1025))
        tx.sequence = secure.MAX_SEQUENCE
        with self.assertRaises(secure.SecureError): tx.seal(b"x")
        with self.assertRaises(secure.SecureError): secure.RecordCipher(PSK[::-1], PSK).open(record)

    def test_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"config.toml"
            for key in ("", PSK.hex().upper()):
                path.write_text(f'[oscar]\nuin="100500"\npsk="{key}"\n[telegram]\napi_id=1\napi_hash="x"\n')
                self.assertEqual(Config.load(str(path)).oscar_psk, key)
            for key in ("01", "g"*64, "00 "*32):
                path.write_text(f'[oscar]\nuin="100500"\npsk="{key}"\n[telegram]\napi_id=1\napi_hash="x"\n')
                with self.assertRaises(ValueError): Config.load(str(path))


class WireTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server, self.storage = make_server(0)
        self.server.cfg.oscar_psk = PSK.hex()
        await self.server.start()
        self.port = self.server._server.sockets[0].getsockname()[1]
        self.server.cfg.oscar_port = self.port
        self.clients = []

    async def asyncTearDown(self):
        for client in self.clients: await client.close()
        await self.server.stop(); await asyncio.sleep(0.03)
        self.storage.close()

    async def login(self, dialer=None):
        client = FakeJimm("127.0.0.1", self.port, "100500", "s3cret")
        client.tmm_version = (0, 88) if dialer else None
        if dialer: client.open_transport = dialer
        self.clients.append(client)
        await client.connect(); await client.bos(await client.login_md5_jimm())
        await client.drain_for(0.05)
        return client

    async def test_jimm_unchanged_with_psk_configured(self):
        client = await self.login()
        self.assertFalse(self.server.session.encrypted)
        uin = self.storage.contact_by_peer(555).uin
        await self.server.deliver(uin, "legacy hello")
        await client.drain_for(0.05)
        self.assertTrue(any("legacy hello" in text for _, text in client.received))

    async def test_encrypted_auth_bos_messages_history_attachment(self):
        dialer = SecureDialer(); client = await self.login(dialer)
        self.assertTrue(self.server.session.encrypted)
        uin = self.storage.contact_by_peer(555).uin
        incoming, outgoing = "IN-PRIVATE-0123456789", "OUT-PRIVATE-9876543210"
        sent = []
        async def on_outgoing(target, text, *args): sent.append((target, text)); return 42
        self.server.on_outgoing = on_outgoing
        await self.server.deliver(uin, incoming)
        await client.drain_for(0.05)
        self.assertTrue(any(incoming in text for _, text in client.received))
        body = bytes(8)+struct.pack(">H", 1)+pstr8(str(uin).encode())+tlv(2, blocks.message_fragments(outgoing))
        await client.send_snac(C.ICBM, C.ICBM_SEND, body); await client.drain_for(0.05)
        self.assertTrue(any(outgoing in text for _, text in sent))
        image = bytes(range(256))*40
        async def fetch_attachment(*args): return image
        async def fetch_history(*args): return [(incoming, "", False)], False
        self.server.fetch_attachment, self.server.fetch_history = fetch_attachment, fetch_history
        token = self.server.register_attachment(uin, "photo:42")
        self.assertEqual((await client.request_photo(uin, token))["image"], image)
        rows, more = await client.request_history_page(uin, 20)
        self.assertFalse(more); self.assertEqual(rows[0][0], incoming)
        self.assertEqual(len(dialer.keys), 4)  # auth, BOS, photo BART, history BART
        self.assertEqual(len(set(dialer.keys)), 4)
        for value in (incoming.encode(), outgoing.encode(), image[:256], PSK):
            self.assertNotIn(value, dialer.wire)
        await client.ping(); await client.drain_for(0.05)
        self.assertEqual(self.server.session.pings_seen, 1)

    async def test_disabled_bad_key_and_bad_finish(self):
        for configured, key, expected in (("", PSK, 1), (PSK.hex(), bytes(32), 2)):
            self.server.cfg.oscar_psk = configured
            reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
            await recv_raw(reader)
            writer.write(flap(secure.CHANNEL, 1, secure.client_hello(key, bytes(16)))); await writer.drain()
            self.assertEqual(await recv_raw(reader), (secure.CHANNEL, secure.MAGIC+b"\xff"+bytes([expected])))
            self.assertEqual(await reader.read(), b""); writer.close(); await writer.wait_closed()
        self.server.cfg.oscar_psk = PSK.hex()
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port); await recv_raw(reader)
        writer.write(flap(secure.CHANNEL, 1, secure.client_hello(PSK, bytes(16)))); await writer.drain(); await recv_raw(reader)
        writer.write(flap(secure.CHANNEL, 2, secure.MAGIC+b"\x03"+bytes(16))); await writer.drain()
        self.assertEqual((await recv_raw(reader))[1], secure.MAGIC+b"\xff\x02")
        self.assertEqual(await reader.read(), b""); writer.close(); await writer.wait_closed()

    async def test_corruption_closes_connection(self):
        for bad_mac in (False, True):
            reader, writer = await SecureDialer()("127.0.0.1", self.port)
            self.assertEqual(await recv_raw(reader), (1, b"\x00\x00\x00\x01"))
            if bad_mac:
                packet = writer.cipher.seal(flap(5, 1, b""))
                packet = packet[:-1] + bytes([packet[-1]^1])
            else:
                packet = b"\xff\xff"  # reject before reading/allocating body
            writer.raw.write(packet); await writer.raw.drain()
            self.assertEqual(await reader.raw.raw.read(), b"")
            writer.close(); await writer.wait_closed()


if __name__ == "__main__":
    unittest.main()
