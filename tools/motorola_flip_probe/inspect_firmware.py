#!/usr/bin/env python3
"""Read Java ROM tables in a specific V3r B3R SBF; never access a phone or flash it."""
import argparse
import hashlib
import json
from pathlib import Path
import struct


SNAPSHOT_SHA256 = "ad3052fc4d352b121d5c7c7f7097050942a5bb208c1a800f8eb5e211607d8b07"
FLASH_DELTA = 0x1006FFEE
CLASS_RAM_DELTA = 0x13AD0FEE
UTF_TABLE = 0xC57582
CLASS_TABLE = 0xC579C6


def inspect(data):
    def u16(offset):
        return struct.unpack_from(">H", data, offset)[0]

    def u32(offset):
        return struct.unpack_from(">I", data, offset)[0]

    def flash_offset(pointer):
        offset = pointer - FLASH_DELTA
        if not 0 <= offset < len(data):
            raise ValueError(f"Flash pointer outside image: {pointer:#x}")
        return offset

    def class_offset(pointer):
        offset = pointer - CLASS_RAM_DELTA
        if not 0 <= offset < len(data):
            raise ValueError(f"Class pointer outside image: {pointer:#x}")
        return offset

    utf = {}
    names = {}
    for bucket in range(u32(UTF_TABLE)):
        pointer = u32(UTF_TABLE + 8 + 4 * bucket)
        while pointer:
            offset = flash_offset(pointer)
            if offset in utf:
                raise ValueError("Repeated UTF entry")
            length = u16(offset + 4)
            key = u16(offset + 6)
            raw = data[offset + 8:offset + 8 + length]
            if len(raw) != length or data[offset + 8 + length] != 0:
                raise ValueError("Invalid UTF entry")
            utf[offset] = raw
            names[key] = raw
            pointer = u32(offset)
    if len(utf) != u32(UTF_TABLE + 4):
        raise ValueError("Incomplete UTF table")

    def symbol(pointer):
        return utf[flash_offset(pointer)].decode("utf-8") if pointer else ""

    classes = {}
    for bucket in range(u32(CLASS_TABLE)):
        pointer = u32(CLASS_TABLE + 8 + 4 * bucket)
        while pointer:
            offset = class_offset(pointer)
            if offset in classes:
                raise ValueError("Repeated class entry")
            package, simple = symbol(u32(offset + 8)), symbol(u32(offset + 12))
            classes[offset] = package + "/" + simple if package else simple
            pointer = u32(offset + 16)
    if len(classes) != u32(CLASS_TABLE + 4):
        raise ValueError("Incomplete class table")

    def member_name(offset):
        return names[u16(offset)].decode("utf-8")

    def reference(value, tag):
        if tag == 0x87:
            return classes[class_offset(value)]
        if tag in (0x89, 0x8A, 0x8B):
            offset = flash_offset(value)
            owner = u32(offset + (8 if tag == 0x89 else 24))
            return classes[class_offset(owner)] + "." + member_name(offset)
        return f"{value:#x}"

    targets = {
        "com/motorola/synerj/svc/device/Case",
        "com/motorola/synerj/svc/SecurityManager",
        "com/vodafone/system/DeviceControl",
        "java/util/Timer",
    }
    result = {"sha256": SNAPSHOT_SHA256, "utf_entries": len(utf), "classes": len(classes),
              "secondary_display_classes": [name for name in classes.values()
                                            if "secondarydisplay" in name.lower()], "targets": []}
    for offset, name in classes.items():
        if name not in targets:
            continue
        row = {"class": name, "sbf_offset": hex(offset), "methods": [], "references": {}}
        pool = flash_offset(u32(offset + 28))
        size = u32(pool)
        tags = data[pool + size * 4:pool + size * 5]
        for index in range(1, size):
            if tags[index] in (0x87, 0x89, 0x8A, 0x8B):
                row["references"][str(index)] = reference(u32(pool + 4 * index), tags[index])
        table = flash_offset(u32(offset + 36))
        for index in range(u32(table)):
            method = table + 4 + 32 * index
            method_name = member_name(method)
            if (name == "java/util/Timer" and method_name != "waitResume"):
                continue
            address = u32(method + 4)
            access = u32(method + 20)
            item = {"name": method_name, "access": hex(access), "address": hex(address),
                    "sbf_offset": hex(method)}
            if not access & 0x100:
                start = flash_offset(address)
                size = u16(method + 16)
                item["vm_bytecode"] = data[start:start + size].hex(" ")
            row["methods"].append(item)
        result["targets"].append(row)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sbf", type=Path)
    args = parser.parse_args()
    data = args.sbf.read_bytes()
    if hashlib.sha256(data).hexdigest() != SNAPSHOT_SHA256:
        parser.error("This tool supports only the documented B3R snapshot; image checksum differs")
    print(json.dumps(inspect(data), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
