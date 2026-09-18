"""Шифрование канала TeleMotoMax ↔ мост: ChaCha20-Poly1305 (RFC 8439).

Зачем своё: у Motorola V3 нет TLS, который принял бы современный сервер,
а хочется, чтобы переписка не читалась на пути от телефона к VPS. Общий
ключ — фраза в настройках клиента и в config.toml; на её основе после
входа обе стороны переходят на шифрование каждого FLAP.

Схема (та же байт в байт на телефоне, jimm.comm.Crypto):
- K32 = MD5(фраза‖0x01) ‖ MD5(фраза‖0x02) — MD5 здесь только как способ
  получить 32 байта из фразы: он и так есть в Jimm, а SHA-256 на телефон
  тащить незачем;
- клиент шлёт SNAC 01/F0, мост отвечает 01/F1 с 8 случайными байтами
  сеанса (snonce) и с этого момента шифрует всё, что отправляет;
- ключи направлений: K_dir = первые 32 байта потока ChaCha20(K32,
  счётчик 0, nonce = метка(4) ‖ snonce(8)), метки «c2s\\0» и «s2c\\0»;
- каждый FLAP: канал получает бит 0x80, тело = ChaCha20-Poly1305(K_dir,
  nonce = 0(4) ‖ номер кадра(8, big-endian), без дополнительных данных),
  то есть шифртекст ‖ тег(16). Номера считаются в каждом направлении с
  нуля, по шифрованным кадрам.

Реализация на чистом Python: объёмы у нас скромные (кадр до 64 КБ), а
зависимость ради этого не нужна. Проверяется векторами RFC 8439.
"""

from __future__ import annotations

import hashlib
import struct

MASK = 0xFFFFFFFF
TAG_LEN = 16
ENCRYPTED = 0x80             # бит канала FLAP: тело зашифровано


def _rotl(v: int, n: int) -> int:
    return ((v << n) | (v >> (32 - n))) & MASK


def _quarter(s: list[int], a: int, b: int, c: int, d: int) -> None:
    s[a] = (s[a] + s[b]) & MASK; s[d] = _rotl(s[d] ^ s[a], 16)
    s[c] = (s[c] + s[d]) & MASK; s[b] = _rotl(s[b] ^ s[c], 12)
    s[a] = (s[a] + s[b]) & MASK; s[d] = _rotl(s[d] ^ s[a], 8)
    s[c] = (s[c] + s[d]) & MASK; s[b] = _rotl(s[b] ^ s[c], 7)


def chacha20_block(key: bytes, counter: int, nonce: bytes) -> bytes:
    if len(key) != 32 or len(nonce) != 12:
        raise ValueError("ChaCha20: ключ 32 байта, nonce 12")
    state = [0x61707865, 0x3320646E, 0x79622D32, 0x6B206574,
             *struct.unpack("<8I", key), counter & MASK, *struct.unpack("<3I", nonce)]
    s = list(state)
    for _ in range(10):
        _quarter(s, 0, 4, 8, 12); _quarter(s, 1, 5, 9, 13)
        _quarter(s, 2, 6, 10, 14); _quarter(s, 3, 7, 11, 15)
        _quarter(s, 0, 5, 10, 15); _quarter(s, 1, 6, 11, 12)
        _quarter(s, 2, 7, 8, 13); _quarter(s, 3, 4, 9, 14)
    return struct.pack("<16I", *((x + y) & MASK for x, y in zip(s, state)))


def chacha20_xor(key: bytes, counter: int, nonce: bytes, data: bytes) -> bytes:
    out = bytearray(len(data))
    for i in range(0, len(data), 64):
        block = chacha20_block(key, counter + i // 64, nonce)
        chunk = data[i:i + 64]
        out[i:i + len(chunk)] = bytes(a ^ b for a, b in zip(chunk, block))
    return bytes(out)


def poly1305(key: bytes, msg: bytes) -> bytes:
    r = int.from_bytes(key[:16], "little") & 0x0FFFFFFC0FFFFFFC0FFFFFFC0FFFFFFF
    s = int.from_bytes(key[16:32], "little")
    p = (1 << 130) - 5
    acc = 0
    for i in range(0, len(msg), 16):
        chunk = msg[i:i + 16]
        n = int.from_bytes(chunk, "little") + (1 << (8 * len(chunk)))
        acc = ((acc + n) * r) % p
    return ((acc + s) & ((1 << 128) - 1)).to_bytes(16, "little")


def _pad16(data: bytes) -> bytes:
    rem = len(data) % 16
    return data + (b"\0" * (16 - rem) if rem else b"")


def seal(key: bytes, nonce: bytes, plain: bytes, aad: bytes = b"") -> bytes:
    """AEAD RFC 8439: шифртекст ‖ тег."""
    otk = chacha20_block(key, 0, nonce)[:32]
    ct = chacha20_xor(key, 1, nonce, plain)
    mac = poly1305(otk, _pad16(aad) + _pad16(ct)
                   + struct.pack("<QQ", len(aad), len(ct)))
    return ct + mac


def open_(key: bytes, nonce: bytes, sealed: bytes, aad: bytes = b"") -> bytes | None:
    """None — тег не сошёлся (чужой ключ или порча)."""
    if len(sealed) < TAG_LEN:
        return None
    ct, tag = sealed[:-TAG_LEN], sealed[-TAG_LEN:]
    otk = chacha20_block(key, 0, nonce)[:32]
    mac = poly1305(otk, _pad16(aad) + _pad16(ct)
                   + struct.pack("<QQ", len(aad), len(ct)))
    if not _const_eq(mac, tag):
        return None
    return chacha20_xor(key, 1, nonce, ct)


def _const_eq(a: bytes, b: bytes) -> bool:
    diff = 0
    for x, y in zip(a, b):
        diff |= x ^ y
    return diff == 0 and len(a) == len(b)


def master_key(secret: str) -> bytes:
    raw = secret.encode("utf-8")
    return hashlib.md5(raw + b"\x01").digest() + hashlib.md5(raw + b"\x02").digest()


def direction_key(k32: bytes, label: bytes, snonce: bytes) -> bytes:
    if len(label) != 4 or len(snonce) != 8:
        raise ValueError("метка 4 байта, snonce 8")
    return chacha20_block(k32, 0, label + snonce)[:32]


class Cipher:
    """Одно направление: свой ключ и счётчик кадров."""

    def __init__(self, key: bytes) -> None:
        self.key = key
        self.counter = 0

    def _nonce(self) -> bytes:
        nonce = b"\0\0\0\0" + struct.pack(">Q", self.counter)
        self.counter += 1
        return nonce

    def seal(self, plain: bytes) -> bytes:
        return seal(self.key, self._nonce(), plain)

    def open(self, sealed: bytes) -> bytes | None:
        return open_(self.key, self._nonce(), sealed)


def session_ciphers(secret: str, snonce: bytes) -> tuple[Cipher, Cipher]:
    """(что читаем от телефона, чем шифруем телефону)."""
    k32 = master_key(secret)
    return (Cipher(direction_key(k32, b"c2s\0", snonce)),
            Cipher(direction_key(k32, b"s2c\0", snonce)))
