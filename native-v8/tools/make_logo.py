"""Rebuild the native splash icon from the existing TeleMotoMax vector drawing.

Optional: python3 native-v8/tools/make_logo.py (requires Pillow).
Normal ARM builds/package use the checked-in PNG and do not require Pillow.
"""
import importlib.util
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT.parent / "telemotomax/util/icon/make_icon.py"
    spec = importlib.util.spec_from_file_location("telemotomax_icon", source)
    icon = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(icon)
    destination = ROOT / "resources/logo.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    icon.draw().resize((96, 96), Image.Resampling.LANCZOS).save(destination, optimize=True)
    print(destination)


if __name__ == "__main__":
    main()
