"""Actual ICQ message/roster parsing, ownership and desktop allocation checks.

Usage: python tests/test_client_packet_memory.py BUILD_WORK [CLASSES] [baseline]
Packets and expected ACKs are built independently in Python; MIDP is stubbed.
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
from tests.test_client_performance import make_stubs
from bridge.oscar import blocks
from bridge.oscar.proto import tlv

COOKIE = bytes(range(8))
UIN = b'1000037'
TOKEN = bytes(range(16))
REF = (2**63 + 12345).to_bytes(8, 'big')


def subblock(text, url=''):
    body = blocks.channel2_message(COOKIE, text, url)
    at = 26
    while at < len(body):
        kind, length = struct.unpack_from('>HH', body, at)
        at += 4
        if kind == 0x2711:
            return body[at:at+length]
        at += length
    raise AssertionError('message subblock missing')


def channel2(sub, prefix=b''):
    return b'\0\0' + COOKIE + blocks.CAP_SERVER_RELAY + prefix + tlv(0x2711, sub)


def envelope(channel, body, extra=b'', noisy=False):
    user = blocks.user_info(UIN.decode())
    if noisy:
        at = 1 + len(UIN) + 2
        count = struct.unpack_from('>H', user, at)[0]
        user = user[:at] + struct.pack('>H', count+1) + user[at+2:] + tlv(0x4567, b'x'*2048)
    return COOKIE + struct.pack('>H', channel) + user + tlv(5 if channel != 1 else 2, body) + extra


def ack(sub):
    return COOKIE + b'\0\2' + bytes([len(UIN)]) + UIN + b'\0\3' + sub[:51] + b'\1\0\0'


def fixtures():
    rows = []
    def add(name, channel, body, text='', url='', kind=0, extra=b'', expected_ack=b'', state=1, noisy=False):
        rows.append((name, envelope(channel, body, extra, noisy), text, url, kind,
                     TOKEN if kind else b'', REF if extra and state == 1 and channel != 4 else b'', expected_ack, state))
    extra = tlv(0x9001, b'\2'+TOKEN) + tlv(0x9002, REF)
    for i, text in enumerate(['', '1', 'Привет\r\nмир', '😀 текст', 'Ж'*900]):
        sub = subblock(text)
        add('c2-'+str(i), 2, channel2(sub), text.replace('\r', ''), expected_ack=ack(sub))
    for kind in range(1, 5):
        sub = subblock('медиа')
        add('media-'+str(kind), 2, channel2(sub), 'медиа', kind=kind,
            extra=tlv(0x9001, bytes([kind])+TOKEN)+tlv(0x9002, REF), expected_ack=ack(sub))
    sub = subblock('[видео]', 'http://host/v/token')
    add('browser', 2, channel2(sub, tlv(99, b'ignored')), '[видео]', 'http://host/v/token',
        2, extra, ack(sub), noisy=True)
    sub = subblock('Ж'*900)
    add('benchmark', 2, channel2(sub, tlv(0x7777, b'x'*1024)), 'Ж'*900,
        extra=tlv(0x4567, b'y'*1024)+tlv(0x9002, REF), expected_ack=ack(sub), noisy=True)
    for charset, encoding in [(0, 'cp1251'), (2, 'utf-16-be')]:
        text = 'Привет\r\nмир'
        body = tlv(0x0501, b'cap')+tlv(0x0101, struct.pack('>HH', charset, 0)+text.encode(encoding))
        add('c1-'+str(charset), 1, body, text.replace('\r', ''), kind=2, extra=extra)
    text = 'Legacy\r\ntext'
    payload = text.encode()+b'\0'
    add('c4', 4, struct.pack('<IHH', 1000037, 1, len(payload))+payload, text.replace('\r', ''))
    plugin = b'Send Web Page Address (URL)'; payload = b'Legacy link'
    extended = subblock('')[:45] + struct.pack('<HHHH', 0x1a, 0, 0, 0)
    extended += b'\0'*20 + struct.pack('<I', len(plugin))+plugin + b'\0'*19 + struct.pack('<I', len(payload))+payload
    body = channel2(extended)
    expected = COOKIE+b'\0\2'+bytes([len(UIN)])+UIN+b'\0\3'+body[:51]+b'\1\0\0'+extended[53:]
    add('extended-url', 2, body, 'Legacy link', expected_ack=expected)
    ignored = bytearray(subblock('ignored')); struct.pack_into('<H', ignored, 45, 1000)
    add('unsupported-type', 2, channel2(bytes(ignored)), state=2)
    body = channel2(subblock('test'))
    for cut in [0, 1, 2, 7, 20, 40, len(body)-1]:
        packet = envelope(2, body)
        rows.append(('truncated-'+str(cut), packet[:11+len(blocks.user_info(UIN.decode()))-1+cut], '', '', 0, b'', b'', b'', 3))
    bad = bytearray(subblock('test')); struct.pack_into('<H', bad, 51, 65535)
    add('bad-text-length', 2, channel2(bytes(bad)), state=3)
    bad = bytearray(subblock('test'))
    guid = 53 + struct.unpack_from('<H', bad, 51)[0] + 8
    struct.pack_into('<I', bad, guid, 0x7fffffff)
    add('bad-guid-length', 2, channel2(bytes(bad)), state=3)
    bad = bytearray(subblock('test')); struct.pack_into('<I', bad, guid, 0xffffffff)
    add('negative-guid-length', 2, channel2(bytes(bad)), state=3)
    add('nested-crosses-body', 2, b'\0\0'+COOKIE+blocks.CAP_SERVER_RELAY+struct.pack('>HH',0x2711,1000)+b'x',
        extra=tlv(0x4567, b'x'*2048), state=3)
    add('c1-crosses-body', 1, struct.pack('>HH',0x0101,32)+b'\0'*4,
        extra=tlv(0x4567, b'x'*128), state=3)
    return rows


def write_blob(out, value):
    out.write(struct.pack('>I', len(value))); out.write(value)


def run(work, classes, baseline):
    stubs = make_stubs()
    stubs['javax/microedition/lcdui/Canvas.java'] = stubs['javax/microedition/lcdui/Canvas.java'].replace(
        'public void repaint(){}', 'public void repaint(){} public void repaint(int x,int y,int w,int h){}')
    stubs['javax/microedition/lcdui/Image.java'] = stubs['javax/microedition/lcdui/Image.java'].replace(
        'public class Image {', 'public class Image {public int getHeight(){return 12;}public int getWidth(){return 12;}')
    stubs['DrawControls/ImageList.java'] = stubs['DrawControls/ImageList.java'].replace(
        'public class ImageList {',
        'public class ImageList { private static javax.microedition.lcdui.Image[] cache=new javax.microedition.lcdui.Image[64];').replace(
        'elementAt(int i){return null;}',
        'elementAt(int i){if(cache[i]==null)cache[i]=new javax.microedition.lcdui.Image();return cache[i];}')
    stubs['javax/microedition/rms/RecordStore.java'] = stubs['javax/microedition/rms/RecordStore.java'].replace(
        'public static RecordStore openRecordStore',
        'public static String[] listRecordStores(){return new String[0];}'
        'public static void deleteRecordStore(String name){stores.remove(name);}'
        'public static RecordStore openRecordStore')
    cp = os.pathsep.join(map(str, [classes, *sorted((work/'wtk/lib').glob('*.jar'))]))
    with tempfile.TemporaryDirectory(prefix='tmm-packet-memory-') as temp:
        directory = Path(temp); resources = directory/'resources'; resources.mkdir()
        for name in ('RU.lng', 'langlist.lng'):
            shutil.copy2(work/'src/build/res'/name, resources/name)
        rows = fixtures()
        with (directory/'messages.bin').open('wb') as out:
            out.write(struct.pack('>H', len(rows)))
            for name, packet, text, url, kind, token, ref, response, state in rows:
                for value in (name.encode(), packet, text.encode(), url.encode()): write_blob(out, value)
                out.write(bytes([kind, state]))
                for value in (token, ref, response): write_blob(out, value)
        records = []
        for i in range(97):
            more = tlv(0x0131, ('Контакт '+str(i)).encode())
            if i == 0: more += tlv(0x006d, b'server-data')+tlv(0x015d, b'other-data')
            if i == 1: more += tlv(0x0066, b'')
            records.append(blocks.ssi_item(str(1000001+i).encode(), 1, i+1, 0, more))
        (directory/'roster.bin').write_bytes(b'\0'+struct.pack('>H',len(records))+b''.join(records)+b'\0'*4)
        (directory/'server-data.bin').write_bytes(tlv(0x006d,b'server-data')+tlv(0x015d,b'other-data'))
        sources = []
        for name, source in stubs.items():
            path = directory/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(source); sources.append(str(path))
        sources.append(str(ROOT/'tests/java/PacketMemoryTest.java'))
        subprocess.run([str(work/'jdk/bin/javac'),'-encoding','UTF-8','-cp',cp,'-d',str(directory),*sources],check=True)
        subprocess.run([str(work/'jdk/bin/java'),'-XX:-DoEscapeAnalysis','-Xbootclasspath/a:'+str(resources),
                        '-cp',str(directory)+os.pathsep+cp,'jimm.comm.PacketMemoryTest',str(directory),
                        'baseline' if baseline else 'verify'],check=True,timeout=30)


if __name__ == '__main__':
    work = Path(sys.argv[1]).resolve()
    run(work, Path(sys.argv[2]).resolve() if len(sys.argv)>2 else work/'src/build/compile/classes',
        len(sys.argv)>3 and sys.argv[3]=='baseline')
