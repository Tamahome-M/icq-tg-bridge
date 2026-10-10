"""Real client presence parser, UI scheduling and contact tree, fake MIDP drawing."""
from pathlib import Path
import os
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_client_performance import make_stubs
from tests.test_presence import statuses
from bridge.oscar import blocks, const as C


def run(work, classes):
    stubs = make_stubs()
    stubs['javax/microedition/lcdui/Canvas.java'] = stubs['javax/microedition/lcdui/Canvas.java'].replace(
        'public void repaint(){}', 'public static int repaints; public void repaint(){repaints++;} public void repaint(int x,int y,int w,int h){repaints++;}')
    stubs['javax/microedition/lcdui/Image.java'] = stubs['javax/microedition/lcdui/Image.java'].replace(
        'public class Image {', 'public class Image { public int getHeight(){return 12;}public int getWidth(){return 12;}')
    stubs['DrawControls/ImageList.java'] = stubs['DrawControls/ImageList.java'].replace(
        'elementAt(int i){return null;}', 'elementAt(int i){return new javax.microedition.lcdui.Image();}')
    stubs['javax/microedition/rms/RecordStore.java'] = stubs['javax/microedition/rms/RecordStore.java'].replace(
        'public static RecordStore openRecordStore',
        'public static String[] listRecordStores(){String[] keys=new String[stores.size()];int i=0;'
        'for(java.util.Enumeration e=stores.keys();e.hasMoreElements();)keys[i++]=(String)e.nextElement();return keys;}'
        'public static void deleteRecordStore(String name){stores.remove(name);} public static RecordStore openRecordStore')
    cp = os.pathsep.join(map(str, [classes, *sorted((work / 'wtk/lib').glob('*.jar'))]))
    with tempfile.TemporaryDirectory(prefix='tmm-presence-') as temp:
        directory = Path(temp); resources = directory / 'resources'; resources.mkdir()
        for name in ('RU.lng', 'langlist.lng'):
            shutil.copy2(work / 'src/build/res' / name, resources / name)
        records = [blocks.user_info(str(uin), status=C.STATUS_WIRE_OFFLINE if status == C.STATUS_OFFLINE else status,
                         signon_time=1000, online_seconds=3600, icon_hash=bytes([7])*16) for uin, status in statuses().items()]
        initial = b''.join(records)
        (directory / 'initial.bin').write_bytes(initial)
        (directory / 'departed.bin').write_bytes(b''.join(blocks.buddy_departed(uin) for uin in statuses()))
        packets = [b''.join(records[i:i+20]) for i in range(0, len(records), 20)]
        (directory / 'packets.bin').write_bytes(b''.join(struct.pack('>H', len(packet))+packet for packet in packets))
        record = records[1]
        count_offset = 1 + record[0] + 2
        count = struct.unpack_from('>H', record, count_offset)[0]
        idle = record[:count_offset] + struct.pack('>H', count+1) + record[count_offset+2:] + struct.pack('>HHH', 4, 2, 37)
        (directory / 'idle.bin').write_bytes(idle)
        sources = []
        for name, source in stubs.items():
            path = directory / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source); sources.append(str(path))
        sources.append(str(ROOT / 'tests/java/ClientPresenceTest.java'))
        subprocess.run([str(work / 'jdk/bin/javac'), '-encoding', 'UTF-8', '-cp', cp,
                        '-d', str(directory), *sources], check=True)
        subprocess.run([str(work / 'jdk/bin/java'), '-Xbootclasspath/a:'+str(resources),
                        '-cp', str(directory)+os.pathsep+cp, 'ClientPresenceTest',
                        str(directory / 'initial.bin'), str(directory / 'departed.bin'),
                        str(directory / 'packets.bin'), str(directory / 'idle.bin')], check=True, timeout=30)


if __name__ == '__main__':
    work = Path(sys.argv[1]).resolve()
    run(work, Path(sys.argv[2]).resolve() if len(sys.argv)>2 else work / 'src/build/compile/classes')
