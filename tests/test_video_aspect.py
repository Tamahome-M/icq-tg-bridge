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
        coders = []
        original_coder = bridge._transcoder

        def tracked_coder(seconds):
            coder = original_coder(seconds)
            coders.append(coder)
            return coder

        bridge._transcoder = tracked_coder
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
            ("hour-512", "320x240", "1", "mpeg4", "never", False, (240, 180), (240, 180)),
            ("hour-768", "320x240", "1", "mpeg4", "never", False, (240, 180), (240, 180)),
            ("hour-1024", "320x240", "1", "mpeg4", "never", False, (240, 180), (240, 180)),
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
                long_clip = name.startswith("hour-")
                bitrate = int(name.split("-")[1]) if long_clip else 192
                seconds = 3600 if long_clip else 300
                session.media = {"video_codec": codec, "video_width": 240 if codec == "mpeg4" else 176,
                                 "video_height": 180 if codec == "mpeg4" else 144,
                                 "video_kbps": bitrate, "video_seconds": seconds,
                                 "video_max_kb": 524288 if long_clip else 8192,
                                 "bart_parts16": long_clip,
                                 "video_rotate": automatic}
                assert bridge._video_kbps(seconds) == bitrate
                data = await bridge.fetch_video(uin, f"video:{index + 1}", rotate=rotate)
                assert data, name
                if long_clip:
                    assert coders[-1].video_seconds == 3600 and coders[-1].timeout >= 7200
                output = root / f"{name}.3gp"
                output.write_bytes(data)
                info = json.loads(subprocess.check_output([
                    str(probe), "-v", "error", "-select_streams", "v:0", "-show_streams", "-of", "json", str(output)
                ], timeout=15))["streams"][0]
                assert info["codec_name"] == codec, (name, info)
                assert (info["width"], info["height"]) == frame, (name, info)
                if codec == "mpeg4":
                    assert info.get("sample_aspect_ratio", "1:1") == "1:1", (name, info)
                    if long_clip:
                        assert info["level"] == 4, (name, info)
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
            # A real hour-long timeline catches hidden 300-second cutoffs;
            # static low-FPS input keeps the fixture small and cheap to encode.
            incoming = root / "full-hour.mp4"
            subprocess.run([str(encoder), "-y", "-v", "error", "-f", "lavfi", "-i",
                            "color=white:size=128x96:rate=1", "-t", "3600", "-c:v", "mpeg4",
                            str(incoming)], check=True, timeout=120)
            source = incoming.read_bytes()
            session.media = {"video_codec": "mpeg4", "video_width": 240, "video_height": 180,
                             "video_kbps": 512, "video_seconds": 3600, "video_max_kb": 524288,
                             "bart_parts16": True, "video_rotate": False}
            encoded = await bridge.fetch_video(uin, "video:999", rotate="never")
            assert encoded
            output = root / "full-hour.3gp"
            output.write_bytes(encoded)
            info = json.loads(subprocess.check_output([str(probe), "-v", "error", "-show_format",
                                                       "-show_streams", "-of", "json", str(output)], timeout=20))
            assert abs(float(info["format"]["duration"]) - 3600) < 0.1, info
            assert int(info["streams"][0]["nb_frames"]) == 54000, info
            print("full hour: encoded duration 3600 s, 54000 frames, no hidden cutoff")
        finally:
            await bridge.photo_server.stop()
            bridge.storage.close()
    print("REAL VIDEO ASPECT/ROTATION PASS")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("SKIP: provide ffmpeg with libopencore_amrnb and adjacent ffprobe")
    else:
        asyncio.run(run(Path(sys.argv[1]).resolve()))
