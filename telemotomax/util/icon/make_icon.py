"""Иконка TeleMotoMax: круг Telegram + MAX с самолётиком.

Запуск из корня репозитория: .venv/bin/python telemotomax/util/icon/make_icon.py
Пишет 15×15 в res/GRAPHICS_32BIT/COMMON/icon.png (RGBA) и
res/GRAPHICS_8BIT/COMMON/icon.png (палитра) — размер иконки у Jimm такой.
"""

import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "..", "..", "res")
S = 256


def draw() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    tg, mx = (42, 171, 238), (110, 60, 240)       # синий Telegram, фиолетовый MAX
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).ellipse((4, 4, S - 4, S - 4), fill=255)
    base = Image.new("RGBA", (S, S), tg + (255,))
    right = Image.new("RGBA", (S, S), mx + (255,))
    diag = Image.new("L", (S, S), 0)
    ImageDraw.Draw(diag).polygon([(S, 0), (S, S), (0, S)], fill=255)
    base.paste(right, (0, 0), diag)
    img.paste(base, (0, 0), mask)
    d = ImageDraw.Draw(img)
    white = (255, 255, 255, 255)
    d.polygon([(52, 130), (204, 62), (156, 200), (118, 150)], fill=white)
    d.polygon([(118, 150), (156, 200), (124, 186)], fill=(220, 220, 240, 255))
    d.polygon([(52, 130), (118, 150), (110, 176)], fill=(235, 235, 245, 255))
    d.ellipse((4, 4, S - 4, S - 4), outline=(255, 255, 255, 230), width=8)
    return img


def main() -> None:
    img = draw()
    small = img.resize((15, 15), Image.LANCZOS)
    small.save(os.path.join(RES, "GRAPHICS_32BIT", "COMMON", "icon.png"), optimize=True)
    bg = Image.new("RGBA", small.size, (255, 0, 255, 255))
    bg.paste(small, (0, 0), small)
    pal = bg.convert("RGB").quantize(colors=16)
    pal.save(os.path.join(RES, "GRAPHICS_8BIT", "COMMON", "icon.png"),
             transparency=pal.getpixel((0, 0)), optimize=True)


if __name__ == "__main__":
    main()
