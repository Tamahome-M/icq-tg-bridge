"""Низкоуровневые примитивы OSCAR: FLAP-кадры, SNAC-пакеты, TLV."""

from __future__ import annotations

import struct

FLAP_MARKER = 0x2A

FLAP_SIGNON = 1
FLAP_DATA = 2
FLAP_ERROR = 3
FLAP_SIGNOFF = 4
FLAP_KEEPALIVE = 5


class ProtocolError(Exception):
    pass


class Reader:
    """Курсор по байтовому буферу с чтением big-endian и little-endian полей."""

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    @property
    def left(self) -> int:
        return len(self.data) - self.pos

    def read(self, n: int) -> bytes:
        if n < 0 or self.left < n:
            raise ProtocolError(f"нужно {n} байт, осталось {self.left}")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def rest(self) -> bytes:
        chunk = self.data[self.pos:]
        self.pos = len(self.data)
        return chunk

    def u8(self) -> int:
        return self.read(1)[0]

    def u16(self) -> int:
        return struct.unpack(">H", self.read(2))[0]

    def u32(self) -> int:
        return struct.unpack(">I", self.read(4))[0]

    def u16le(self) -> int:
        return struct.unpack("<H", self.read(2))[0]

    def u32le(self) -> int:
        return struct.unpack("<I", self.read(4))[0]

    def pstr8(self) -> bytes:
        return self.read(self.u8())

    def pstr16(self) -> bytes:
        return self.read(self.u16())

    def tlvs(self, count: int | None = None) -> "TLVList":
        items: list[tuple[int, bytes]] = []
        while self.left >= 4 and (count is None or len(items) < count):
            t = self.u16()
            items.append((t, self.pstr16()))
        return TLVList(items)


class TLVList:
    def __init__(self, items: list[tuple[int, bytes]] | None = None):
        self.items = items or []

    def add(self, t: int, v: bytes) -> "TLVList":
        self.items.append((t, v))
        return self

    def get(self, t: int, default: bytes | None = None) -> bytes | None:
        for tt, v in self.items:
            if tt == t:
                return v
        return default

    def get_all(self, t: int) -> list[bytes]:
        return [v for tt, v in self.items if tt == t]

    def has(self, t: int) -> bool:
        return any(tt == t for tt, _ in self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __bytes__(self) -> bytes:
        return b"".join(tlv(t, v) for t, v in self.items)

    def __repr__(self) -> str:
        return "TLVList(%s)" % ", ".join(f"0x{t:04x}:{len(v)}b" for t, v in self.items)


def tlv(t: int, v: bytes = b"") -> bytes:
    return struct.pack(">HH", t, len(v)) + v


def tlv_u8(t: int, v: int) -> bytes:
    return tlv(t, struct.pack(">B", v))


def tlv_u16(t: int, v: int) -> bytes:
    return tlv(t, struct.pack(">H", v))


def tlv_u32(t: int, v: int) -> bytes:
    return tlv(t, struct.pack(">I", v))


def tlv_str(t: int, v: str, encoding: str = "utf-8") -> bytes:
    return tlv(t, v.encode(encoding, "replace"))


def pstr8(v: bytes) -> bytes:
    if len(v) > 255:
        v = v[:255]
    return bytes([len(v)]) + v


def pstr16(v: bytes) -> bytes:
    return struct.pack(">H", len(v)) + v


class Snac:
    __slots__ = ("family", "subtype", "flags", "request_id", "data")

    def __init__(self, family: int, subtype: int, flags: int, request_id: int, data: bytes):
        self.family = family
        self.subtype = subtype
        self.flags = flags
        self.request_id = request_id
        self.data = data

    @classmethod
    def parse(cls, payload: bytes) -> "Snac":
        if len(payload) < 10:
            raise ProtocolError("SNAC короче заголовка")
        family, subtype, flags, request_id = struct.unpack(">HHHI", payload[:10])
        body = payload[10:]
        # Флаг 0x8000 — перед телом идёт блок расширений произвольной длины.
        if flags & 0x8000 and len(body) >= 2:
            ext_len = struct.unpack(">H", body[:2])[0]
            body = body[2 + ext_len:]
        return cls(family, subtype, flags, request_id, body)

    def reader(self) -> Reader:
        return Reader(self.data)

    def __repr__(self) -> str:
        return f"SNAC {self.family:02x}/{self.subtype:02x} req={self.request_id} len={len(self.data)}"


def snac(family: int, subtype: int, data: bytes = b"", flags: int = 0, request_id: int = 0) -> bytes:
    return struct.pack(">HHHI", family, subtype, flags, request_id) + data


def flap(channel: int, seq: int, payload: bytes) -> bytes:
    return struct.pack(">BBHH", FLAP_MARKER, channel, seq & 0xFFFF, len(payload)) + payload


def roast_password(password: bytes) -> bytes:
    """XOR-«обжарка» пароля из старой схемы логина ICQ."""
    table = bytes([0xF3, 0x26, 0x81, 0xC4, 0x39, 0x86, 0xDB, 0x92,
                   0x71, 0xA3, 0xB9, 0xE6, 0x53, 0x7A, 0x95, 0x7C])
    return bytes(b ^ table[i % len(table)] for i, b in enumerate(password))
