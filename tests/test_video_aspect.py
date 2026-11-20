"""Real codec/rotation/padding regression: python tests/test_video_aspect.py /path/to/ffmpeg."""
from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from bridge.bridge import Bridge
from bridge.config import Config
from bridge.profiles import BUILTIN
from tests.test_video_encoding import container_boxes


async def run(encoder: Path) -> None:
    probe = encoder.with_name("ffprobe")
    with tempfile.TemporaryDirectory(prefix="tmm-video-aspect-") as temp:
        root = Path(temp)
        cfg = Config(tg_api_id=1, tg_api_hash="x", db=":memory:", render_enabled=False,
                     photos_dir=str(root / "photos"), render_dir=str(root / "render"),
                     render_ffmpeg=str(encoder))
        bridge = Bridge(cfg)
        session = SimpleNamespace(profile=BUILTIN["v8"], media={})
        bridge.oscar.session = session
        uin = bridge.storage.uin_for_peer(555, kind="user", title="Video test", group_name="Test")
        source = b""

        async def video_bytes(*_):
            return source

        bridge.side_for = lambda _: SimpleNamespace(video_bytes=video_bytes)
        # Expected *visible* white rectangle, excluding letterboxing. This is
        # measured after decoding the actual encoded output, not from -vf text.
        cases = [
            ("wide-auto", "640x360", "1", "mpeg4", "auto", True, (180, 240), (134, 240)),
            ("wide-never", "640x360", "1", "mpeg4", "never", True, (240, 180), (240, 134)),
            ("portrait-auto", "360x640", "1", "mpeg4", "auto", True, (240, 180), (100, 180)),
            ("portrait-always", "360x640", "1", "mpeg4", "always", True, (180, 240), (180, 100)),
            ("square-auto", "320x320", "1", "mpeg4", "auto", True, (240, 180), (180, 180)),
            ("anamorphic", "720x576", "16/15", "mpeg4", "never", False, (240, 180), (240, 180)),
            ("anamorphic-portrait", "480x360", "1/2", "mpeg4", "auto", True, (240, 180), (120, 180)),
            ("metadata-portrait", "640x360", "1", "mpeg4", "auto", True, (240, 180), (100, 180)),
            ("v3-wide", "640x360", "1", "h263", "never", False, (176, 144), (176, 98)),
            ("v3-portrait", "360x640", "1", "h263", "never", False, (176, 144), (80, 144)),
        ]
        try:
            for index, (name, size, sar, codec, rotate, automatic, frame, visible) in enumerate(cases):
                incoming = root / "input.mp4"
                subprocess.run([str(encoder), "-y", "-v", "error", "-f", "lavfi", "-i",
                                f"color=white:size={size}:rate=15", "-vf", f"setsar={sar}",
                                "-t", "0.5", "-c:v", "mpeg4", str(incoming)], check=True, timeout=20)
                if name == "metadata-portrait":
                    tagged = root / "tagged.mp4"
                    subprocess.run([str(encoder), "-y", "-v", "error", "-display_rotation:v:0", "90",
                                    "-i", str(incoming), "-c", "copy", str(tagged)],
                                   check=True, timeout=15)
                    incoming = tagged
                source = incoming.read_bytes()
                session.media = {"video_codec": codec, "video_width": 240 if codec == "mpeg4" else 176,
                                 "video_height": 180 if codec == "mpeg4" else 144,
                                 "video_kbps": 192, "video_seconds": 300, "video_max_kb": 8192,
                                 "video_rotate": automatic}
                assert bridge._video_kbps(300) == 192
                data = await bridge.fetch_video(uin, f"video:{index + 1}", rotate=rotate)
                assert data, name
                output = root / f"{name}.3gp"
                output.write_bytes(data)
                info = json.loads(subprocess.check_output([
                    str(probe), "-v", "error", "-select_streams", "v:0", "-show_streams", "-of", "json", str(output)
                ], timeout=15))["streams"][0]
                assert info["codec_name"] == codec, (name, info)
                assert (info["width"], info["height"]) == frame, (name, info)
                if codec == "mpeg4":
                    assert info.get("sample_aspect_ratio", "1:1") == "1:1", (name, info)
                if codec == "h263":
                    assert not {b"fiel", b"pasp"}.intersection(container_boxes(data)), name
                png = subprocess.check_output([str(encoder), "-v", "error", "-i", str(output),
                                               "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "-"], timeout=15)
                mask = Image.open(io.BytesIO(png)).convert("L").point(lambda value: 255 if value > 128 else 0)
                box = mask.getbbox()
                assert box, name
                measured = (box[2] - box[0], box[3] - box[1])
                assert measured == visible, (name, "stretched/cropped content", measured, visible)
                assert abs(box[0] - (frame[0] - visible[0]) / 2) <= 1, (name, box)
                assert abs(box[1] - (frame[1] - visible[1]) / 2) <= 1, (name, box)
                print(f"{name}: {codec} {frame}, content {measured}, centered, decode OK")
        finally:
            await bridge.photo_server.stop()
            bridge.storage.close()
    print("REAL VIDEO ASPECT/ROTATION PASS")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("SKIP: provide ffmpeg with libopencore_amrnb and adjacent ffprobe")
    else:
        asyncio.run(run(Path(sys.argv[1]).resolve()))
