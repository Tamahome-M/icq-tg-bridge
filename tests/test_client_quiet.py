"""Quiet message wire/storage/alerts and real V8 local RMS settings/sync.

Usage: python tests/test_client_quiet.py BUILD_WORK [CLASSES]
Only MIDP widgets, RMS and the transport are fake; client logic is compiled.
"""
from pathlib import Path
import os
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_client_faults import ui_stubs
from tests.test_client_packet_memory import envelope, channel2, subblock, ack, write_blob
from bridge.oscar.proto import tlv


def fixtures():
    for channel in (1, 2):
        text = 'Тихое сообщение'
        sub = subblock(text)
        body = channel2(sub) if channel == 2 else tlv(0x0101, b'\0\2\0\0' + text.encode('utf-16-be'))
        for name, extra, quiet in (
            ('missing', b'', False), ('valid', tlv(0x9005, b'\1'), True),
            ('zero', tlv(0x9005, b'\0'), False), ('other', tlv(0x9005, b'\2'), False),
            ('empty', tlv(0x9005, b''), False), ('long', tlv(0x9005, b'\1\0'), False),
            ('truncated', b'\x90\x05\x00\x02\x01', False),
            ('extra', tlv(0x9999, b'ignored') + tlv(0x9005, b'\1') + tlv(0x9002, bytes(range(8))), True),
        ):
            yield str(channel) + '-' + name, envelope(channel, body, extra), quiet, ack(sub) if channel == 2 else b''


def run(work, classes):
    stubs = ui_stubs(audio=True)
    stubs['javax/microedition/lcdui/Command.java'] = stubs['javax/microedition/lcdui/Command.java'].replace(
        'public Command(String s,int t,int p) {}', 'private String label;public String getLabel(){return label;}public Command(String s,int t,int p){label=s;}')
    stubs['javax/microedition/lcdui/Display.java'] = stubs['javax/microedition/lcdui/Display.java'].replace(
        'private Displayable current;', 'public static int vibrations,flashes;public boolean vibrate(int n){vibrations++;return true;}private Displayable current;').replace(
        'flashBacklight(int n){return true;}', 'flashBacklight(int n){flashes++;return true;}')
    stubs['jimm/Jimm.java'] = stubs['jimm/Jimm.java'].replace(
        'public static void setMinimized(boolean b){}', 'public static int raised;public static void setMinimized(boolean b){if(!b)raised++;}')
    stubs['javax/microedition/lcdui/StringItem.java'] = '''package javax.microedition.lcdui;
public class StringItem extends Item {private String text;public StringItem(String l,String t){label=l;text=t;}public void setText(String t){text=t;}public String getText(){return text;}}
'''
    stubs['javax/microedition/rms/RecordStore.java'] = stubs['javax/microedition/rms/RecordStore.java'].replace(
        'public static java.util.Hashtable stores=', 'public static boolean failRead,failWrite;public static int writes;public static java.util.Hashtable stores=').replace(
        'return (byte[])records.elementAt(id-1);', 'if(failRead)throw new IllegalStateException("RMS read");return ((byte[])records.elementAt(id-1)).clone();').replace(
        'public int addRecord(byte[] b,int o,int n){', 'public int addRecord(byte[] b,int o,int n){if(failWrite)throw new IllegalStateException("RMS write");writes++;').replace(
        'public void setRecord(int id,byte[] b,int o,int n){', 'public void setRecord(int id,byte[] b,int o,int n){if(failWrite)throw new IllegalStateException("RMS write");writes++;')
    v8 = not (classes/'jimm/VodafoneFlipState.class').exists()
    cp = os.pathsep.join(map(str, [classes, *sorted((work/'wtk/lib').glob('*.jar'))]))
    with tempfile.TemporaryDirectory(prefix='tmm-quiet-') as temp:
        directory = Path(temp); resources = directory/'resources'; resources.mkdir()
        for name in ('RU.lng', 'langlist.lng', 'message.mp3', 'msg_low.mp3', 'tg.mp3', 'typing.mp3'):
            shutil.copy2(work/'src/build/res'/name, resources/name)
        cases = list(fixtures())
        with (directory/'wire.bin').open('wb') as out:
            out.write(struct.pack('>H', len(cases)))
            for name, packet, quiet, expected_ack in cases:
                write_blob(out, name.encode());write_blob(out, packet);out.write(bytes([quiet]));write_blob(out, expected_ack)
        sources = []
        for name, source in stubs.items():
            path = directory/name;path.parent.mkdir(parents=True, exist_ok=True);path.write_text(source);sources.append(str(path))
        sources.append(str(ROOT/'tests/java/QuietMessagesTest.java'))
        if v8:
            sources.append(str(ROOT/'tests/java/QuietSettingsTest.java'))
        subprocess.run([str(work/'jdk/bin/javac'), '-encoding', 'UTF-8', '-cp', cp, '-d', str(directory), *sources], check=True)
        runtime = str(directory)+os.pathsep+cp
        tests = ['jimm.QuietMessagesTest'] + (['jimm.QuietSettingsTest'] if v8 else [])
        for test in tests:
            subprocess.run([str(work/'jdk/bin/java'), '-Xbootclasspath/a:'+str(resources), '-cp', runtime,
                            test, str(directory/'wire.bin'), 'v8' if v8 else 'legacy'], check=True, timeout=30)


if __name__ == '__main__':
    work = Path(sys.argv[1]).resolve()
    run(work, Path(sys.argv[2]).resolve() if len(sys.argv)>2 else work/'src/build/compile/classes')
