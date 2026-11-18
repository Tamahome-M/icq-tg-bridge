"""Generate the QObject header matching the V8 firmware's private flag layout.

The archived SDK omits one bit before blockSig. Its inline signalsBlocked()
reads bit 4, while the firmware's blockSignals(bool) writes bit 5. Custom moc
emitters then silently discard signals from parented objects. Keep the SDK
untouched and preinclude this generated header for every ARM translation unit.
"""
import argparse
from pathlib import Path
import re


def prepare(header, output):
    source = header.read_text()
    flags = re.compile(
        r"(uint\s+isSignal\s*:\s*1;\s*"
        r"uint\s+isWidget\s*:\s*1;\s*"
        r"uint\s+pendTimer\s*:\s*1;\s*"
        r"uint\s+pendEvent\s*:\s*1;)(\s*)"
        r"(uint\s+blockSig\s*:\s*1;\s*"
        r"uint\s+wasDeleted\s*:\s*1;\s*"
        r"uint\s+isTree\s*:\s*1;)"
    )
    source, count = flags.subn(
        r"\1\2uint tmmV8Reserved : 1;\2\3", source
    )
    if count != 1:
        raise ValueError("Unsupported SDK QObject flags; expected the archived V8 SDK layout")
    source = "// Generated V8 QObject flag compatibility header; keep the SDK unchanged.\n" + source
    output.parent.mkdir(parents=True, exist_ok=True)
    if not output.exists() or output.read_text() != source:
        output.write_text(source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--header", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    prepare(args.header, args.output)


if __name__ == "__main__":
    main()
