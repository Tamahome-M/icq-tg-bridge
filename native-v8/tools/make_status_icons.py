#!/usr/bin/env python3
"""Optional Pillow generator. Normal builds use the checked-in resource bundle.

Input: native ICQ images exported by RES_ICON_Reader from the user's V8
firmware. Only the small ICQ source images are retained, never a firmware pack.
The resource hash matches UTIL_Res::hashVal (including signed ASR #20).
"""
import argparse
import io
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[1]


def resource_hash(name):
    value = 0
    for byte in name.encode('ascii'):
        signed = value if value < 0x80000000 else value - 0x100000000
        value = ((signed >> 20) ^ (value << 1) ^ byte) & 0xffffffff
    return value


def pack(images):
    names = b''
    data = b''
    records = []
    for name, image in sorted(images.items()):
        filename = name + '.g'
        records.append((resource_hash(filename), len(names), len(data)))
        names += filename.encode('ascii') + b'\n'
        data += struct.pack('<II', 0xdcbaabcd, len(image)) + image
        data += b'\0' * (-len(data) % 4)
    prefix = b'motoskin\n\nv1.00\n00000000\n'
    header = (len(prefix) + len(names) + 3) & ~3
    names += b'\0' * (header - len(prefix) - len(names))
    index = header + 20
    prefix = prefix[:16] + f'{header:08X}'.encode() + prefix[24:]
    return (prefix + names + struct.pack('<5I', 0xabcddcba, len(prefix),
            len(records), index, index + 12 * len(records)) +
            b''.join(struct.pack('<3I', *record) for record in records) + data)


def main():
    from PIL import Image, ImageDraw, ImageOps
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export', type=Path, help='RES_ICON_Reader export directory')
    args = parser.parse_args()
    source = ROOT / 'resources/status-source'
    source.mkdir(exist_ok=True)
    bases = {'online': ('im_icq_cli4', 'im_icq_idle5'),
             'away': ('im_icq_away_cli4', 'im_icq_away_idle5'),
             'busy': ('im_busy_cli4', 'im_busy_idle4'),
             'invisible': ('im_icq_invisible_cli4', 'im_icq_invisible_idle5')}
    if args.export:
        for pair in bases.values():
            for name in pair:
                (source / (name + '.png')).write_bytes((args.export / (name + '.png')).read_bytes())
    # Readable envelope at native 20px size; drawn on a pixel grid, no font or
    # new image codec dependency on the phone. Preserve each base's alpha mask.
    envelope = Image.new('RGBA', (11, 8))
    draw = ImageDraw.Draw(envelope)
    draw.rectangle((0, 0, 10, 7), fill='#ffffed', outline='#272727')
    draw.line((0, 0, 5, 4, 10, 0), fill='#4f4f4f')
    draw.line((0, 7, 3, 4), fill='#737373')
    draw.line((10, 7, 7, 4), fill='#737373')
    images = {}
    preview = []
    for state in ('offline', 'online', 'away', 'busy', 'invisible'):
        for display, name in zip(('cli', 'main'), bases.get(state, bases['online'])):
            original = Image.open(source / (name + '.png')).convert('RGBA')
            if state == 'offline':
                alpha = original.getchannel('A')
                original = ImageOps.grayscale(original).convert('RGBA')
                original.putalpha(alpha)
                images['tmm_offline_' + display] = original
            unread = original.copy()
            edge = original.getbbox()[2]
            unread.alpha_composite(envelope, (min(original.width - 11, edge - 8), 12))
            images['tmm_msg_' + state + '_' + display] = unread
            if display == 'main':
                preview.append((state, original, unread))
    images['tmm_status_v1'] = Image.new('RGBA', (1, 1), (0, 0, 0, 255))
    encoded = {}
    for key, value in images.items():
        output = io.BytesIO()
        value.save(output, 'PNG', optimize=True)
        encoded[key] = output.getvalue()
    (ROOT / 'resources/status-icons.ezx').write_bytes(pack(encoded))
    sheet = Image.new('RGB', (240, 5 * 96), '#444444')
    draw = ImageDraw.Draw(sheet)
    for row, (state, normal, unread) in enumerate(preview):
        draw.text((2, row * 96 + 4), state, fill='white')
        for column, icon in enumerate((normal, unread)):
            zoom = icon.resize((icon.width * 3, icon.height * 3), Image.Resampling.NEAREST)
            sheet.paste(zoom, (80 + 80 * column, row * 96 + 20), zoom)
    sheet.save(ROOT / 'resources/status-icons-preview.png')


if __name__ == '__main__':
    main()
