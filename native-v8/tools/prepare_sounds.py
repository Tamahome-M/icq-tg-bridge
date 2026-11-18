#!/usr/bin/env python3
"""Regenerate V8 short alerts without changing the shared Java resources.

Needs ffmpeg with libmp3lame. Generated files are committed; normal builds
and bridge installations do not need ffmpeg for native sound packaging.
"""
import argparse
from pathlib import Path
import subprocess

from package import check_sound

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("message", "msg_low", "typing")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    (ROOT / "sounds").mkdir(exist_ok=True)
    for name in NAMES:
        source = ROOT.parent / f"telemotomax/res/MIDP2/sounds/{name}.mp3"
        target = ROOT / f"sounds/{name}.mp3"
        subprocess.run([
            args.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(source), "-map", "0:a:0", "-vn", "-map_metadata", "-1",
            "-c:a", "libmp3lame", "-b:a", "96k", "-ar", "22050",
            "-write_xing", "0", "-id3v2_version", "0", "-write_id3v1", "0",
            "-fflags", "+bitexact", "-flags:a", "+bitexact", str(target),
        ], check=True)
        check_sound(target)
        print(f"{target.name}: {target.stat().st_size} bytes")


if __name__ == "__main__":
    main()
