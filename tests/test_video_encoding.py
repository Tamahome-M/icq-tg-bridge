"""Real H.263/AMR-NB smoke test: python tests/test_video_encoding.py /path/to/ffmpeg."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bridge.bridge import Bridge
from bridge.config import Config
from bridge.profiles import BUILTIN


async def run(encoder: Path) -> None:
    probe = encoder.with_name("ffprobe")
    with tempfile.TemporaryDirectory(prefix="tmm-real-video-") as temp:
        directory = Path(temp)
        cfg = Config(tg_api_id=1, tg_api_hash="x", db=":memory:", render_enabled=False,
                     photos_dir=str(directory / "photos"), render_dir=str(directory / "render"),
                     render_ffmpeg=str(encoder), photos_public_url="http://host:8080")
        bridge = Bridge(cfg)
        bridge.oscar.session = SimpleNamespace(profile=BUILTIN["v8"], media={})
        uin = bridge.storage.uin_for_peer(555, kind="user", title="Чат", group_name="Личные")
        source = b""

        async def video_bytes(*_):
            return source

        bridge.side_for = lambda _: SimpleNamespace(video_bytes=video_bytes)
        assert bridge._video_kbps(30) == 90, "V8 budget must retain requested 90 kbps"
        try:
            for number, size in enumerate(("320x240", "240x320")):
                incoming = directory / "input.mp4"
                subprocess.run([str(encoder), "-y", "-loglevel", "error", "-f", "lavfi",
                                "-i", f"testsrc2=size={size}:rate=30", "-f", "lavfi", "-i",
                                "sine=frequency=440:sample_rate=44100", "-t", "2", "-c:v",
                                "mpeg4", "-c:a", "aac", str(incoming)], check=True, timeout=30)
                source = incoming.read_bytes()
                attach = f"video:{number + 1}"
                native = await bridge.fetch_video(uin, attach)
                assert native, "native video conversion failed"
                path = bridge.video_link(uin, attach).split("http://host:8080", 1)[1]
                page = bridge.videos.pages[path.rsplit("/", 1)[1]]
                bridge.videos.resolve(path)
                await asyncio.wait_for(asyncio.gather(*list(page.jobs.values())), 30)
                browser = bridge.videos.resolve(path + "/0.3gp")
                assert browser, "browser video conversion failed"
                for mode, data in (("native", native), ("browser", browser[0])):
                    output = directory / f"{size}-{mode}.3gp"
                    output.write_bytes(data)
                    result = subprocess.run([str(probe), "-v", "error", "-show_streams",
                                             "-show_format", "-of", "json", str(output)],
                                            capture_output=True, check=True, timeout=15)
                    info = json.loads(result.stdout)
                    video = next(s for s in info["streams"] if s["codec_type"] == "video")
                    audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
                    assert video["codec_name"] == "h263", video
                    assert (video["width"], video["height"]) == (176, 144), video
                    assert video["r_frame_rate"] == "15/1" and video["pix_fmt"] == "yuv420p", video
                    assert audio["codec_name"] == "amr_nb", audio
                    assert audio["sample_rate"] == "8000" and audio["channels"] == 1, audio
                    # ffprobe учитывает заголовки пакетов; режим 12.2 кбит/с
                    # проверяем по FT=7 первого AMR-NB кадра.
                    amr = subprocess.run([str(encoder), "-v", "error", "-i", str(output),
                                          "-vn", "-c:a", "copy", "-f", "amr", "-"],
                                         capture_output=True, check=True, timeout=15).stdout
                    assert amr.startswith(b"#!AMR\n") and (amr[6] >> 3) & 15 == 7, audio
                    assert info["format"]["tags"]["major_brand"].startswith("3gp"), info
                    subprocess.run([str(encoder), "-v", "error", "-i", str(output),
                                    "-f", "null", "-"], check=True, timeout=15)
                    print(f"  {size}, {mode}: H.263 176×144 15 fps + AMR-NB 8 kHz mono, decode OK")
        finally:
            await bridge.photo_server.stop()
            bridge.storage.close()
    print("REAL 3GP ENCODING VERIFIED")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("SKIP: provide a real ffmpeg with libopencore_amrnb and adjacent ffprobe")
    else:
        asyncio.run(run(Path(sys.argv[1]).resolve()))
