"""Optional TMME/1 transport. The ordinary FLAP greeting stays unchanged.

PSK handshake; HKDF-SHA256; ChaCha20 + HMAC-SHA256/128 encrypt-then-MAC.
No forward secrecy. A record contains u16 length, ciphertext, 16-byte tag;
the implicit u64 sequence is authenticated and forms the nonce.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import struct

CHANNEL = 0x7E
MAGIC = b"TMME\x01"
INFO = b"TeleMotoMax secure v1"
MAX_RECORD = 1024
TAG_SIZE = 16
MAX_SEQUENCE = (1 << 63) - 1


class SecureError(ConnectionError):
    pass


def parse_psk(value: str) -> bytes:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ValueError("oscar.psk: нужны 64 шестнадцатеричных знака (32 случайных байта)")
    return bytes.fromhex(value)


def mac(key: bytes, *parts: bytes) -> bytes:
    digest = hmac.new(key, digestmod=hashlib.sha256)
    for part in parts:
        digest.update(part)
    return digest.digest()


def client_hello(psk: bytes, nonce: bytes) -> bytes:
    if len(nonce) != 16:
        raise ValueError("client nonce length")
    body = MAGIC + b"\x01" + nonce
    return body + mac(psk, b"client hello", body)[:TAG_SIZE]


def server_hello(psk: bytes, request: bytes, nonce: bytes | None = None) -> bytes:
    if (len(request) != 38 or not request.startswith(MAGIC + b"\x01")
            or not hmac.compare_digest(request[-16:], mac(psk, b"client hello", request[:-16])[:16])):
        raise SecureError("неверный ключ или запрос шифрования")
    nonce = os.urandom(32) if nonce is None else nonce
    if len(nonce) != 32:
        raise ValueError("server nonce length")
    body = MAGIC + b"\x02" + nonce
    return body + mac(psk, b"server hello", request, body)[:16]


def client_finish(psk: bytes, request: bytes, response: bytes) -> bytes:
    if (len(response) != 54 or not response.startswith(MAGIC + b"\x02")
            or not hmac.compare_digest(response[-16:], mac(psk, b"server hello", request, response[:-16])[:16])):
        raise SecureError("сервер не подтвердил ключ шифрования")
    return MAGIC + b"\x03" + mac(psk, b"client finish", request, response)[:16]


def session_keys(psk: bytes, request: bytes, response: bytes) -> bytes:
    # RFC 5869: Extract(salt, PSK), Expand(info, 128); four independent keys.
    salt = request[6:22] + response[6:38]
    prk = mac(salt, psk)
    previous = b""
    result = b""
    for block in range(1, 5):
        previous = mac(prk, previous, INFO, bytes([block]))
        result += previous
    return result


class RecordCipher:
    def __init__(self, key: bytes, auth_key: bytes):
        self.key, self.auth_key = key, auth_key
        self.sequence = 0

    def _header(self, length: int) -> bytes:
        if not 1 <= length <= MAX_RECORD or self.sequence >= MAX_SEQUENCE:
            raise SecureError("неверный размер или счётчик защищённого блока")
        return struct.pack(">QH", self.sequence, length)

    def _crypt(self, data: bytes) -> bytes:
        # Leading zero words also make this layout interoperable with the
        # older 64/64 ChaCha API. A record never exhausts the block counter.
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
        iv = b"\x00" * 8 + struct.pack(">Q", self.sequence)
        context = Cipher(algorithms.ChaCha20(self.key, iv), mode=None).encryptor()
        return context.update(data) + context.finalize()

    def seal(self, data: bytes) -> bytes:
        header = self._header(len(data))
        ciphertext = self._crypt(data)
        tag = mac(self.auth_key, header, ciphertext)[:16]
        self.sequence += 1
        return header[-2:] + ciphertext + tag

    def open(self, record: bytes) -> bytes:
        if len(record) < 19:
            raise SecureError("неполный защищённый блок")
        length = struct.unpack(">H", record[:2])[0]
        header = self._header(length)
        if len(record) != length + 18:
            raise SecureError("неверный размер защищённого блока")
        ciphertext = record[2:-16]
        if not hmac.compare_digest(record[-16:], mac(self.auth_key, header, ciphertext)[:16]):
            raise SecureError("защищённый блок не прошёл проверку")
        data = self._crypt(ciphertext)
        self.sequence += 1
        return data


class SecureReader:
    def __init__(self, raw, cipher: RecordCipher):
        self.raw, self.cipher = raw, cipher
        self.buffer = bytearray()

    async def readexactly(self, length: int) -> bytes:
        while len(self.buffer) < length:
            header = await self.raw.readexactly(2)
            size = struct.unpack(">H", header)[0]
            if not 1 <= size <= MAX_RECORD:
                raise SecureError("слишком большой защищённый блок")
            body = await self.raw.readexactly(size + 16)
            self.buffer.extend(self.cipher.open(header + body))
        data = bytes(self.buffer[:length])
        del self.buffer[:length]
        return data


class SecureWriter:
    def __init__(self, raw, cipher: RecordCipher):
        self.raw, self.cipher = raw, cipher

    def write(self, data: bytes) -> None:
        for start in range(0, len(data), MAX_RECORD):
            self.raw.write(self.cipher.seal(data[start:start + MAX_RECORD]))

    def __getattr__(self, name):
        return getattr(self.raw, name)


def wrap(reader, writer, keys: bytes, *, server: bool):
    client = RecordCipher(keys[:32], keys[32:64])
    server_cipher = RecordCipher(keys[64:96], keys[96:128])
    rx, tx = (client, server_cipher) if server else (server_cipher, client)
    return SecureReader(reader, rx), SecureWriter(writer, tx)
