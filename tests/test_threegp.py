"""Удаление блоков 3GP: размеры контейнеров и байты пакетов сохраняются."""

from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.threegp import h263_without_display_atoms


def box(tag: bytes, payload: bytes = b"", extended: bool = False) -> bytes:
    if extended:
        return struct.pack(">I4sQ", 1, tag, len(payload) + 16) + payload
    return struct.pack(">I4s", len(payload) + 8, tag) + payload


def video_fixture(display_atoms: tuple[bytes, ...] = (b"fiel", b"pasp"),
                  extended: bool = False, moov_first: bool = False) -> bytes:
    ftyp = box(b"ftyp", b"3gp4\x00\x00\x02\x003gp4")
    # Имена блоков внутри данных пакета не должны трактоваться как блоки.
    mdat = box(b"mdat", b"FAKEMEDIA-fiel-pasp")
    prefix = bytearray(78)
    struct.pack_into(">HH", prefix, 24, 176, 144)
    children = box(b"d263", b"FFMP\x00\x0a\x00")
    for tag in display_atoms:
        children += box(tag, b"\x01\x00" if tag == b"fiel" else struct.pack(">II", 12, 11))
    children += box(b"zzzz", b"unchanged")
    entry = box(b"s263", bytes(prefix) + children, extended)
    stsd = box(b"stsd", b"\x00" * 4 + struct.pack(">I", 1) + entry)
    # Неизменность таблиц смещений проверяется вместе со всем контейнером.
    stco = box(b"stco", b"\x00" * 4 + struct.pack(">II", 1, len(ftyp) + 8))
    co64 = box(b"co64", b"\x00" * 4 + struct.pack(">IQ", 1, len(ftyp) + 8))
    moov = box(b"moov", box(b"trak", box(b"mdia", box(b"minf", box(b"stbl", stsd + stco + co64)))), extended)
    return ftyp + (moov + mdat if moov_first else mdat + moov)


FAKE_VIDEO = video_fixture(())


def run() -> None:
    for extended in (False, True):
        expected = video_fixture((), extended)
        for atoms in ((b"fiel",), (b"pasp",), (b"fiel", b"pasp")):
            raw = video_fixture(atoms, extended)
            fixed = h263_without_display_atoms(raw)
            assert fixed == expected, "меняются только fiel/pasp и размеры родительских блоков"
            assert len(raw) - len(fixed) == sum(10 if tag == b"fiel" else 16 for tag in atoms)
            assert h263_without_display_atoms(fixed) is fixed, "повторная обработка не меняет файл"
    assert h263_without_display_atoms(video_fixture((), moov_first=True)) == video_fixture((), moov_first=True)
    invalid = (
        b"FAKEMEDIA", b"\x00" * 7, struct.pack(">I4s", 1, b"ftyp"),
        struct.pack(">I4s", 1000, b"ftyp"),
        box(b"ftyp") + box(b"mdat"),
        box(b"ftyp") + box(b"mdat") + box(b"moov"),
        box(b"ftyp") + box(b"mdat") + box(b"moov", box(b"stsd", b"\x00")),
        box(b"ftyp") + box(b"mdat") + box(b"moov", box(b"stsd", b"\x00" * 8 + box(b"s263", b"\x00"))),
        video_fixture(moov_first=True),
    )
    for raw in invalid:
        try:
            h263_without_display_atoms(raw)
        except ValueError:
            pass
        else:
            raise AssertionError("повреждённый контейнер или сдвиг mdat должны приводить к отказу")
    # Нулевой размер moov обозначает конец файла; после изменения пишем
    # явный размер и проверяем весь результат, включая таблицы смещений.
    raw = video_fixture()
    at = raw.index(b"moov") - 4
    raw = raw[:at] + b"\x00" * 4 + raw[at + 4:]
    assert h263_without_display_atoms(raw) == FAKE_VIDEO
    print("3GP ПРОВЕРЕН: fiel/pasp удалены, пакеты и смещения неизменны, повреждения отвергаются")


if __name__ == "__main__":
    run()
