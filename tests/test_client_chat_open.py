"""Actual chat opening, BART routing and preload recovery with fake MIDP UI."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_client_performance import make_stubs
from bridge.oscar import blocks


def run(work, classes, baseline):
    stubs = make_stubs()
    stubs.pop('jimm/ChatTextList.java')
    stubs['javax/microedition/lcdui/Canvas.java'] = stubs['javax/microedition/lcdui/Canvas.java'].replace(
        'public void repaint(){}', 'public void repaint(){} public void repaint(int x,int y,int w,int h){}')
    stubs['javax/microedition/lcdui/Image.java'] = stubs['javax/microedition/lcdui/Image.java'].replace(
        'public class Image {', 'public class Image { public int getHeight(){return 12;}public int getWidth(){return 12;}')
    stubs['DrawControls/ImageList.java'] = stubs['DrawControls/ImageList.java'].replace(
        'elementAt(int i){return null;}', 'elementAt(int i){return new javax.microedition.lcdui.Image();}')
    stubs['javax/microedition/rms/RecordStore.java'] = stubs['javax/microedition/rms/RecordStore.java'].replace(
        'public static RecordStore openRecordStore',
        'public static String[] listRecordStores(){return new String[0];}'
        'public static void deleteRecordStore(String name){stores.remove(name);} public static RecordStore openRecordStore')
    stubs['javax/microedition/lcdui/Display.java'] = stubs['javax/microedition/lcdui/Display.java'].replace(
        'public void callSerially(Runnable r){queued.addElement(r);}',
        'public static boolean fail; public void callSerially(Runnable r){if(fail)throw new OutOfMemoryError("UI queue");queued.addElement(r);}')
    stubs['javax/microedition/lcdui/Font.java'] = stubs['javax/microedition/lcdui/Font.java'].replace(
        'public static long measured;', 'public static Runnable beforeMeasure;public static long measured;').replace(
        'int width=0;measured+=length;',
        'if(beforeMeasure!=null){Runnable action=beforeMeasure;beforeMeasure=null;action.run();}int width=0;measured+=length;')
    cp = os.pathsep.join(map(str, [classes, *sorted((work/'wtk/lib').glob('*.jar'))]))
    with tempfile.TemporaryDirectory(prefix='tmm-chat-open-') as temp:
        directory = Path(temp); resources = directory/'resources'; resources.mkdir()
        for name in ('RU.lng', 'langlist.lng'):
            shutil.copy2(work/'src/build/res'/name, resources/name)
        for name, text in [('a', '[11.10 10:00] A: last A'), ('b', '[11.10 10:01] B: last B')]:
            (directory/(name+'.bin')).write_bytes(blocks.history_records([(text, '')], 6000, lambda _: None))
        token = bytes(range(16))
        for kind in ('photo', 'video', 'voice', 'file'):
            text = '[11.10 10:02] Я: own '+kind
            body = blocks.history_records([(text, kind+':20', True, 1000010, 2**63+23)],
                                          6000, lambda _: token, threads=True, quotes=True)
            (directory/(kind+'.bin')).write_bytes(body)
        sources = []
        for name, source in stubs.items():
            path = directory/name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source); sources.append(str(path))
        sources.append(str(ROOT/'tests/java/ClientChatOpenTest.java'))
        subprocess.run([str(work/'jdk/bin/javac'), '-encoding', 'UTF-8', '-cp', cp,
                        '-d', str(directory), *sources], check=True)
        subprocess.run([str(work/'jdk/bin/java'), '-Xbootclasspath/a:'+str(resources),
                        '-cp', str(directory)+os.pathsep+cp, 'jimm.ClientChatOpenTest',
                        str(directory), 'baseline' if baseline else 'verify'], check=True, timeout=30)


if __name__ == '__main__':
    work = Path(sys.argv[1]).resolve()
    run(work, Path(sys.argv[2]).resolve() if len(sys.argv)>2 else work/'src/build/compile/classes',
        len(sys.argv)>3 and sys.argv[3]=='baseline')
