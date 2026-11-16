"""Run the original i386 MotoMAGX SDK with user-mode QEMU on x86_64 hosts.

Creates command wrappers only; does not alter the SDK or install binfmt handlers.
"""
import argparse
from pathlib import Path
import shlex


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--qemu", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--with-c", action="store_true", help="Also wrap gcc/cc1 for C libraries such as Mbed TLS")
    args = parser.parse_args()
    sdk, qemu, output = args.sdk.resolve(), args.qemu.resolve(), args.output.resolve()
    targets = {
        "cc1plus": sdk / "libexec/gcc/arm-linux-gnueabi/3.4.3/cc1plus",
        "collect2": sdk / "libexec/gcc/arm-linux-gnueabi/3.4.3/collect2",
        "as": sdk / "bin/arm-linux-gnueabi-as",
        "ld": sdk / "bin/arm-linux-gnueabi-ld",
        "arm-linux-gnueabi-as": sdk / "bin/arm-linux-gnueabi-as",
        "arm-linux-gnueabi-ld": sdk / "bin/arm-linux-gnueabi-ld",
        "moc": sdk / "lib/qt-v8/bin/moc",
        "arm-linux-gnueabi-g++": sdk / "bin/arm-linux-gnueabi-g++",
    }
    if args.with_c:
        targets.update({
            "cc1": sdk / "libexec/gcc/arm-linux-gnueabi/3.4.3/cc1",
            "arm-linux-gnueabi-gcc": sdk / "bin/arm-linux-gnueabi-gcc",
        })
    for path in [qemu, *targets.values()]:
        if not path.is_file():
            parser.error(f"missing {path}")
    output.mkdir(parents=True, exist_ok=True)
    for name, target in targets.items():
        command = [str(qemu), str(target)]
        if name in ("arm-linux-gnueabi-g++", "arm-linux-gnueabi-gcc"):
            command += ["-B" + str(output) + "/", "-B" + str(sdk / "lib/gcc/arm-linux-gnueabi/3.4.3") + "/"]
        wrapper = output / name
        wrapper.write_text("#!/bin/sh\nexec " + shlex.join(command) + ' "$@"\n')
        wrapper.chmod(0o755)
    print("Wrappers created. Build with:")
    print(shlex.join(["make", "-C", "native", "SDK=" + str(sdk),
                      "CXX=" + str(output / "arm-linux-gnueabi-g++"),
                      "MOC=" + str(output / "moc")]))


if __name__ == "__main__":
    main()
