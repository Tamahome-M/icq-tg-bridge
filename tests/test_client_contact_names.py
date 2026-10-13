"""Real bridge packets through the client parser, UI queue and temporary chats."""
from pathlib import Path
import asyncio
import os
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_client_performance import make_stubs
from tests.test_contact_names import make_session
from bridge.oscar import blocks, const as C
from bridge.oscar.proto import tlv


async def fixtures(directory):
    server, storage, session, packets, known, outside = make_session()
    async def unused_attachment(*args):
        raise AssertionError("naming a sender must not download media")
    server.fetch_attachment = unused_attachment
    server.on_quote = unused_attachment
    server.quote_supported = lambda uin: True
    rows = []
    async def live(label, sender, text, wait_ack=False, **kwargs):
        packets.clear()
        await session.deliver(sender, text, wait_ack=wait_ack, **kwargs)
        rows.append((label, 0, packets[0][2]))
    await live("live-tg", outside[0], "первое Telegram")
    await live("live-max", outside[1], "первое MAX", True, attach="photo:42", message_id=123)
    await live("live-express", outside[2], "первое eXpress", True, url="https://example.org/video")
    for label, value in [("blank", b"  "), ("invalid", b"\xff"), ("oversize", b"x"*257),
                         ("control", b"bad\0name")]:
        await live(label, outside[0], "метаданные не должны терять текст")
        packet = rows[-1][2]
        name = tlv(C.TLV_TMM_SENDER_NAME, "Мама".encode())
        rows[-1] = (label, 0, packet[:-len(name)] + tlv(C.TLV_TMM_SENDER_NAME, value))
    await live("truncated", outside[0], "текст с неполным именем")
    packet = rows[-1][2]
    rows[-1] = ("truncated", 0, packet[:-len(name)] + struct.pack(">HH", C.TLV_TMM_SENDER_NAME, 100) + b"short")
    session.tmm_version = (1, 19)
    await live("legacy", outside[0], "старый мост")
    session.tmm_version = (1, 20)
    for label, tail in [("offline", session.sender_name_tlv(outside[0])), ("offline-legacy", b""),
                        ("offline-invalid", tlv(C.TLV_TMM_SENDER_NAME, b"\xff"))]:
        rows.append((label, 1, blocks.offline_message(outside[0], 1700000000, "накопленное") + tail))
    broken = bytearray(rows[-1][2]); struct.pack_into("<H", broken, 12, 65535)
    rows.append(("offline-broken", 1, bytes(broken)))
    with (directory/"packets.bin").open("wb") as out:
        out.write(struct.pack(">H", len(rows)))
        for label, offline, data in rows:
            encoded = label.encode(); out.write(struct.pack(">H", len(encoded))+encoded)
            out.write(bytes([offline])); out.write(struct.pack(">I", len(data))+data)
    storage.close()


def run(work, classes):
    stubs = make_stubs()
    stubs.pop("jimm/ChatTextList.java")
    stubs["javax/microedition/lcdui/Canvas.java"] = stubs["javax/microedition/lcdui/Canvas.java"].replace(
        "public void repaint(){}", "public void repaint(){}public void repaint(int x,int y,int w,int h){}")
    stubs["javax/microedition/lcdui/Image.java"] = stubs["javax/microedition/lcdui/Image.java"].replace(
        "public class Image {", "public class Image {public int getHeight(){return 12;}public int getWidth(){return 12;}")
    stubs["DrawControls/ImageList.java"] = stubs["DrawControls/ImageList.java"].replace(
        "elementAt(int i){return null;}", "elementAt(int i){return new javax.microedition.lcdui.Image();}")
    stubs["javax/microedition/rms/RecordStore.java"] = stubs["javax/microedition/rms/RecordStore.java"].replace(
        "public static RecordStore openRecordStore", "public static String[] listRecordStores(){return new String[0];}"
        "public static void deleteRecordStore(String name){stores.remove(name);}public static RecordStore openRecordStore")
    cp = os.pathsep.join(map(str, [classes, *sorted((work/"wtk/lib").glob("*.jar"))]))
    with tempfile.TemporaryDirectory(prefix="tmm-contact-names-") as temp:
        directory = Path(temp); resources = directory/"resources"; resources.mkdir()
        for name in ["RU.lng", "langlist.lng"]:
            shutil.copy2(work/"src/build/res"/name, resources/name)
        asyncio.run(fixtures(directory))
        sources = []
        for name, value in stubs.items():
            path = directory/name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value); sources.append(str(path))
        sources.append(str(ROOT/"tests/java/ClientContactNamesTest.java"))
        subprocess.run([str(work/"jdk/bin/javac"), "-encoding", "UTF-8", "-cp", cp, "-d", str(directory), *sources], check=True)
        subprocess.run([str(work/"jdk/bin/java"), "-Xbootclasspath/a:"+str(resources), "-cp", str(directory)+os.pathsep+cp,
                        "jimm.ClientContactNamesTest", str(directory/"packets.bin")], check=True, timeout=30)


if __name__ == "__main__":
    work = Path(sys.argv[1]).resolve()
    run(work, Path(sys.argv[2]).resolve() if len(sys.argv)>2 else work/"src/build/compile/classes")
