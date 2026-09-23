#!/usr/bin/env python3
"""Полные разрешения Java-приложению на Motorola P2K (V3) — правкой его .pat.

На P2K нет способа добавить свой корневой сертификат: корни доменов
прошиты «флексом» и, по руководству V3x, «cannot be modified by the user».
Зато разрешения каждого мидлета телефон держит в своём файле
/c/mobile/kjava/j2meNN.pat (на части прошивок — /a/mobile/kjava/), и его
можно поправить по USB в режиме P2K (P2kCommander, MotoMidMan и т. п.).

Раскладка .pat (по гайдам сообщества P2K, yuetblog.blogspot.com):
  чётные смещения — выбранное значение группы, нечётные — что телефон
  даёт выбрать в меню «Разрешения»:
    06/07  сеть (Data Network)        0E/0F  запись мультимедиа
    08/09  сообщения                  10/11  чтение данных (файлы, PIM)
    0A/0B  автозапуск                 12/13  запись данных (файлы, PIM)
    0C/0D  локальные соединения       14/15  обмен данными между приложениями
  значение: 00 — нет доступа, 01 — всегда спрашивать, 02 — раз за запуск,
  04 — не спрашивать (полный доступ).

    python3 pat-full.py j2me05.pat          # рядом ляжет j2me05.pat.orig
    python3 pat-full.py j2me05.pat --ask    # спрашивать раз за запуск (02)

Какой .pat чей — по номеру: у TeleMotoMax тот же NN, что у его .jad
(внутри .jad видно MIDlet-Name). После загрузки файла обратно телефон
перезагрузить.
"""
import shutil
import sys

GROUPS = {0x06: "сеть", 0x08: "сообщения", 0x0A: "автозапуск", 0x0C: "локальные соединения",
          0x0E: "запись мультимедиа", 0x10: "чтение данных (файлы)", 0x12: "запись данных (файлы)",
          0x14: "обмен между приложениями"}


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        print(__doc__)
        return 2
    path = args[0]
    value = 0x02 if "--ask" in sys.argv else 0x04
    data = bytearray(open(path, "rb").read())
    if len(data) < 0x16:
        print(f"{path}: {len(data)} байт — на .pat не похоже (нужно хотя бы 22)")
        return 1
    shutil.copyfile(path, path + ".orig")
    for off, name in GROUPS.items():
        was, avail = data[off], data[off + 1]
        data[off] = value          # выбранное
        data[off + 1] = 0x04       # и пусть в меню будет виден полный доступ
        print(f"  {off:02X}: {name:28s} {was:02X}/{avail:02X} -> {value:02X}/04")
    open(path, "wb").write(data)
    print(f"записано: {path} (исходник в {path}.orig); телефон перезагрузить")
    return 0


if __name__ == "__main__":
    sys.exit(main())
