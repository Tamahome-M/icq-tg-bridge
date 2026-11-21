#!/usr/bin/env python3
"""Run an ARM UI probe with matching V8 firmware, never on the physical phone.

Uses Yam's isolated QWS harness. Qt/widgets/fonts are real firmware code;
framebuffer, external listeners and unavailable OTP hardware use test adapters.
This does not validate physical audio, camera, cellular networking or timing.
Build the adapters from Yam's ui-mod/qws sources first; they are never packaged.
"""

import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile


def existing(value):
    try:
        return Path(value).resolve(strict=True)
    except OSError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yam-root", required=True, type=existing)
    for option in ("firmware", "resources", "language", "setup", "hardware-stubs", "qemu"):
        parser.add_argument("--" + option, required=True, type=existing)
    parser.add_argument("--local-listener", type=existing)
    parser.add_argument("--framebuffer", type=existing)
    parser.add_argument("--program", default="/work/ui-probe")
    parser.add_argument("tag", help="fresh report name; existing evidence is never overwritten")
    parser.add_argument("--png", action="store_true")
    parser.add_argument("--skin")
    parser.add_argument("--theme")
    args = parser.parse_args()
    native = Path(__file__).resolve().parents[1]
    harness = args.yam_root / "ui-mod/qws"
    if not (harness / "run_qws.py").is_file():
        parser.error("--yam-root must contain ui-mod/qws/run_qws.py")
    adapters = (
        (args.local_listener or args.yam_root / "build/qws-startup-study/liblocal-listener.so",
         native / "build/qws-startup-study/liblocal-listener.so"),
        (args.framebuffer or args.yam_root / "build/qws-menu-study/libv8framebuffer.so",
         native / "build/qws-menu-study/libv8framebuffer.so"),
    )
    for source, destination in adapters:
        if not source.is_file():
            parser.error("build the external QWS test adapter first: " + str(source))
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != destination.resolve() and (
            not destination.exists() or source.read_bytes() != destination.read_bytes()
        ):
            # Parallel isolated runs must never truncate a library another
            # QEMU process has already mapped.
            fd, temporary = tempfile.mkstemp(prefix=".qws-adapter-", dir=destination.parent)
            os.close(fd)
            try:
                shutil.copyfile(source, temporary)
                os.replace(temporary, destination)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
    for option in ("firmware", "resources", "language", "setup", "hardware_stubs", "qemu"):
        os.environ["V8_QWS_" + option.upper()] = str(getattr(args, option))
    if args.program == "/work/java-ui-probe":
        # The handset launcher sources ezxenv.sh, including $QTDIR/lib. Use
        # that firmware path for the real phone and address-book entry points.
        paths = os.environ.get("V8_QWS_INPUT_LIBS", "").split(":")
        paths.extend(("/test-hardware", "/usr/lib/ezx/lib"))
        os.environ["V8_QWS_INPUT_LIBS"] = ":".join(dict.fromkeys(filter(None, paths)))
    sys.path.insert(0, str(harness))
    spec = importlib.util.spec_from_file_location("tmm_external_qws", harness / "run_qws.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    runner.ROOT = native
    runner.WORK = native / "build/qws-startup-study"
    sys.argv = [str(harness / "run_qws.py"), args.program, args.tag]
    if args.png:
        sys.argv.append("--png")
    for name in ("skin", "theme"):
        value = getattr(args, name)
        if value:
            sys.argv.extend(("--" + name, value))
    print("Firmware Qt/QWS only; physical framebuffer/listener/OTP boundaries use test adapters.",
          flush=True)
    print("Reports: " + str(runner.WORK / (args.tag + ".json")), flush=True)
    return runner.main()


if __name__ == "__main__":
    raise SystemExit(main())
