"""Убираем неподдерживаемые V3 блоки, не перемультиплексируя H.263/AMR."""

from __future__ import annotations

import struct
from collections.abc import Iterator


def _atoms(data: bytes) -> Iterator[tuple[bytes, bytes, int]]:
    pos = 0
    while pos < len(data):
        if len(data) - pos < 8:
            raise ValueError("оборван заголовок блока 3GP")
        size, tag = struct.unpack_from(">I4s", data, pos)
        header = 8
        if size == 1:
            if len(data) - pos < 16:
                raise ValueError("оборван длинный заголовок блока 3GP")
            size = struct.unpack_from(">Q", data, pos + 8)[0]
            header = 16
        elif size == 0:
            size = len(data) - pos
        if size < header or size > len(data) - pos:
            raise ValueError("неверный размер блока 3GP")
        yield tag, data[pos:pos + size], header
        pos += size


def _replace_payload(atom: bytes, header: int, payload: bytes) -> bytes:
    if atom[header:] == payload:
        return atom
    tag = atom[4:8]
    if header == 16:
        return struct.pack(">I4sQ", 1, tag, len(payload) + 16) + payload
    return struct.pack(">I4s", len(payload) + 8, tag) + payload


def h263_without_display_atoms(data: bytes) -> bytes:
    """Удалить fiel/pasp внутри s263; mdat и смещения его пакетов не меняются.

    FFmpeg иногда снова выставляет progressive после -field_order 0.
    Поэтому проверяем готовый контейнер. Наш video_args не включает
    faststart: moov идёт после mdat. Если изменяемый moov стоит перед mdat,
    отказываемся вместо повреждения абсолютных смещений stco/co64.
    """
    top = list(_atoms(data))
    if not top or top[0][0] != b"ftyp" or not any(tag == b"mdat" for tag, _, _ in top):
        raise ValueError("ffmpeg не записал контейнер 3GP")
    if sum(tag == b"moov" for tag, _, _ in top) != 1:
        raise ValueError("в 3GP должен быть один блок moov")
    found = False

    def children(raw: bytes, parent: bytes) -> bytes:
        nonlocal found
        result = []
        for tag, atom, header in _atoms(raw):
            payload = atom[header:]
            if parent == b"s263" and tag in (b"fiel", b"pasp"):
                continue
            if tag in (b"trak", b"mdia", b"minf", b"stbl"):
                payload = children(payload, tag)
            elif tag == b"stsd":
                if len(payload) < 8:
                    raise ValueError("оборван блок stsd")
                payload = payload[:8] + children(payload[8:], tag)
            elif parent == b"stsd" and tag == b"s263":
                if len(payload) < 78:
                    raise ValueError("оборвано описание H.263")
                found = True
                payload = payload[:78] + children(payload[78:], tag)
            result.append(_replace_payload(atom, header, payload))
        return b"".join(result)

    moov_index = next(i for i, (tag, _, _) in enumerate(top) if tag == b"moov")
    _, moov, header = top[moov_index]
    fixed = _replace_payload(moov, header, children(moov[header:], b"moov"))
    if not found:
        raise ValueError("в 3GP нет описания H.263")
    if fixed == moov:
        return data
    if any(tag == b"mdat" for tag, _, _ in top[moov_index + 1:]):
        raise ValueError("нельзя удалить блоки H.263: moov стоит перед mdat")
    return b"".join(fixed if i == moov_index else atom for i, (_, atom, _) in enumerate(top))
