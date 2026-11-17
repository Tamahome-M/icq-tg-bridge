"""Reproducible native V8 tar/PEP packages; explicit public file allowlist."""
import argparse
import gzip
import io
from pathlib import Path
import re
import tarfile

ROOT = Path(__file__).resolve().parents[1]
ASSETS = {
    **{f"sounds/{name}.mp3": ROOT.parent / f"telemotomax/res/MIDP2/sounds/{name}.mp3"
       for name in ("message", "msg_low", "tg", "typing")},
    "icon.png": ROOT.parent / "telemotomax/res/GRAPHICS_32BIT/COMMON/icon.png",
    "back.png": ROOT.parent / "telemotomax/res/GRAPHICS_32BIT/COMMON/back.png",
    "statuses.png": ROOT.parent / "telemotomax/res/GRAPHICS_8BIT/COMMON/statuses.png",
    "smiles.png": ROOT.parent / "telemotomax/res/GRAPHICS_32BIT/MODULES/SMILES_STD/smiles.png",
    "smiles.txt": ROOT.parent / "telemotomax/res/GRAPHICS_32BIT/MODULES/SMILES_STD/smiles.txt",
}


def version():
    text = (ROOT / "VERSION").read_text().strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", text):
        raise ValueError("Invalid native version")
    return text


def inputs(binary):
    header = binary.read_bytes()[:52]
    if len(header) < 52 or header[:6] != b"\x7fELF\x01\x01" or header[18:20] != b"\x28\x00":
        raise ValueError("Expected a little-endian ELF32 ARM executable")
    result = dict(ASSETS)
    result.update({"telemotomax-native": binary, "telemotomax.lin": ROOT / "telemotomax.lin",
                   "collect-log.lin": ROOT / "collect-log.lin",
                   "features.tsv": ROOT / "features.tsv",
                   "README.md": ROOT / "README.md", "COPYING": ROOT.parent / "telemotomax/COPYING"})
    return result


def archive(files):
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", filename="", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as output:
            directories = set()
            for name in files:
                for parent in Path(name).parents:
                    if str(parent) != ".": directories.add(parent.as_posix() + "/")
            for name in sorted(directories):
                item = tarfile.TarInfo(name); item.type = tarfile.DIRTYPE; item.mode = 0o755
                output.addfile(item)
            for name, (blob, executable) in sorted(files.items()):
                item = tarfile.TarInfo(name); item.mode = 0o755 if executable else 0o644; item.size = len(blob)
                output.addfile(item, io.BytesIO(blob))
    return buffer.getvalue()


def build(binary, output):
    app = {name: (path.read_bytes(), name in ("telemotomax-native", "telemotomax.lin", "collect-log.lin")) for name, path in inputs(binary).items()}
    output.mkdir(parents=True, exist_ok=True)
    (output / "TeleMotoMax-Native-V8.tar.gz").write_bytes(archive({"TeleMotoMax-Native/" + n: v for n, v in app.items()}))
    description = f"""[Actions]
InstallApp = 1
AddAppToMenu = 1

[InstallApp]
Name = TeleMotoMax Native
Exec = telemotomax.lin
Args =
InstallPath = /ezxlocal/download/mystuff/TeleMotoMax-Native/
AppLockable = 0
Daemon = 0
Author = TeleMotoMax / Codex
Version = {version()}
Icon = icon.png
BigIcon = icon.png
AniIcon = icon.png

[AddAppToMenu]
ParentFolderID = AM_ROOT_FOLDER
"""
    pep = {"app/" + n: v for n, v in app.items()}
    pep["description.ini"] = (description.encode(), False)
    pep["icon.png"] = (ASSETS["icon.png"].read_bytes(), False)
    (output / "TeleMotoMax-Native-V8.pep").write_bytes(archive(pep))
    print(f"Native {version()} packages: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.binary, args.output)
