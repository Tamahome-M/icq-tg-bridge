"""Create local copies of legacy ld scripts; leave the downloaded SDK intact."""
import argparse
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    library = args.sdk.resolve() / "arm-linux-gnueabi/lib"
    args.output.mkdir(parents=True, exist_ok=True)
    for name in ("libc.so", "libpthread.so"):
        source = (library / name).read_text()
        def replace(match):
            path = library / match[1]
            if not path.is_file():
                raise SystemExit(f"SDK is incomplete: {path}")
            return '"' + str(path) + '"'
        result = re.sub(r"/arm-eabi/arm-linux-gnueabi/lib/([A-Za-z0-9_.+-]+)", replace, source)
        (args.output / name).write_text(result)
    (args.output / ".ready").touch()


if __name__ == "__main__":
    main()
