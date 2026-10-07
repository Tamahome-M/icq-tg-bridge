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


def container_boxes(data: bytes) -> list[bytes]:
    """Read atom boundaries, including the children of the H.263 sample entry."""
    names = []

    def walk(start: int, end: int) -> None:
        while start < end:
            assert start + 8 <= end, "truncated 3GP atom header"
            size = int.from_bytes(data[start:start + 4], "big")
            name = data[start + 4:start + 8]
            header = 8
            if size == 1:
                assert start + 16 <= end
                size = int.from_bytes(data[start + 8:start + 16], "big")
                header = 16
            elif size == 0:
                size = end - start
            assert header <= size <= end - start, (name, size)
            names.append(name)
            payload = start + header
            if name in (b"moov", b"trak", b"mdia", b"minf", b"stbl"):
                walk(payload, start + size)
            elif name == b"stsd":
                walk(payload + 8, start + size)
            elif name == b"s263":
                walk(payload + 78, start + size)
            start += size

    walk(0, len(data))
    assert b"s263" in names and b"d263" in names, names
    return names


def packets(probe: Path, path: Path) -> list[dict]:
    result = subprocess.run([str(probe), "-v", "error", "-show_packets",
                             "-show_data_hash", "sha256", "-show_entries",
                             "packet=stream_index,pts,dts,duration,size,data_hash",
                             "-of", "json", str(path)],
                            capture_output=True, check=True, timeout=15)
    return json.loads(result.stdout)["packets"]


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
            cases = (("320x240", False), ("240x320", False), ("320x240", True))
            for number, (size, rotate) in enumerate(cases):
                bridge.oscar.session.media = {"video_rotate": rotate}
                label = size + ("-rotated" if rotate else "")
                incoming = directory / "input.mp4"
                subprocess.run([str(encoder), "-y", "-loglevel", "error", "-f", "lavfi",
                                "-i", f"testsrc2=size={size}:rate=30", "-f", "lavfi", "-i",
                                "sine=frequency=440:sample_rate=44100", "-t", "2", "-c:v",
                                "mpeg4", "-c:a", "aac", str(incoming)], check=True, timeout=30)
                source = incoming.read_bytes()
                reference = directory / "recipe.3gp"
                filters = ("transpose=1," if rotate else "") + "scale=176:144,fps=15"
                subprocess.run([str(encoder), "-y", "-v", "error", "-i", str(incoming),
                                "-c:v", "h263", "-vf", filters, "-b:v", "90k",
                                "-c:a", "libopencore_amrnb", "-b:a", "12.2k", "-ar", "8000",
                                "-ac", "1", "-f", "3gp", str(reference)], check=True, timeout=30)
                baseline_boxes = container_boxes(reference.read_bytes())
                assert b"fiel" in baseline_boxes and b"pasp" in baseline_boxes, \
                    "the old recipe must reproduce the incompatible container atoms"
                baseline_packets = packets(probe, reference)
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
                    atoms = container_boxes(data)
                    assert b"fiel" not in atoms and b"pasp" not in atoms, \
                        f"{mode}: Motorola V3 rejects these optional container atoms"
                    output = directory / f"{label}-{mode}.3gp"
                    output.write_bytes(data)
                    assert packets(probe, output) == baseline_packets, \
                        f"{mode}: suppressing container atoms must preserve encoded packets and timestamps"
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
                    print(f"  {label}, {mode}: H.263 + AMR-NB, no fiel/pasp, packets unchanged, decode OK")
            bridge.oscar.session.profile = BUILTIN["v3"]
            for width, height in ((128, 96), (176, 144)):
                for kbps in (16, 24, 32, 48, 64, 96, 120):
                    bridge.oscar.session.media = {"video_width": width, "video_height": height,
                                                   "video_kbps": kbps, "video_rotate": False}
                    attach = f"video:{width * 1000 + kbps}"
                    path = bridge.video_link(uin, attach).split("http://host:8080", 1)[1]
                    page = bridge.videos.pages[path.rsplit("/", 1)[1]]
                    args = page.spec.coder(temp).video_args("in", "out")
                    assert args[args.index("-b:v") + 1] == f"{kbps}k"
                    bridge.videos.resolve(path)
                    await asyncio.gather(*list(page.jobs.values()))
                    data = bridge.videos.resolve(path + "/0.3gp")[0]
                    atoms = container_boxes(data)
                    assert b"fiel" not in atoms and b"pasp" not in atoms
                    output = directory / f"v3-{width}x{height}-{kbps}.3gp"
                    output.write_bytes(data)
                    result = subprocess.run([str(probe), "-v", "error", "-show_streams", "-of", "json", str(output)],
                                            capture_output=True, check=True, timeout=15)
                    streams = json.loads(result.stdout)["streams"]
                    video = next(s for s in streams if s["codec_type"] == "video")
                    assert video["codec_name"] == "h263" and (video["width"], video["height"]) == (width, height)
                    assert video["r_frame_rate"] == "15/1", video
                    subprocess.run([str(encoder), "-v", "error", "-i", str(output), "-f", "null", "-"],
                                   check=True, timeout=15)
            print("  V3: all 14 resolution/bitrate choices encoded, dimensions verified, no fiel/pasp, decode OK")
        finally:
            await bridge.photo_server.stop()
            bridge.storage.close()
    print("REAL 3GP ENCODING VERIFIED")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("SKIP: provide a real ffmpeg with libopencore_amrnb and adjacent ffprobe")
    else:
        asyncio.run(run(Path(sys.argv[1]).resolve()))
