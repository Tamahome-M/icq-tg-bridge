"""Real chat storage, text rows and UTF-8, with desktop MIDP and allocation meter.

Usage: python tests/test_client_chat_memory.py BUILD_WORK [CLASSES] [baseline]
Baseline mode records allocation and retained-container counts from older builds.
The meter is a desktop comparison, not a measurement of the Motorola VM.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_client_performance import make_stubs


def run(work, classes, baseline):
    stubs = make_stubs()
    stubs.pop('jimm/ChatTextList.java')
    stubs['javax/microedition/lcdui/Canvas.java'] = stubs['javax/microedition/lcdui/Canvas.java'].replace(
        'public void repaint(){}', 'public void repaint(){} public void repaint(int x,int y,int w,int h){}')
    stubs['javax/microedition/lcdui/Image.java'] = stubs['javax/microedition/lcdui/Image.java'].replace(
        'public class Image {', 'public class Image { public int getHeight(){return 12;}public int getWidth(){return 12;}')
    stubs['DrawControls/ImageList.java'] = stubs['DrawControls/ImageList.java'].replace(
        'elementAt(int i){return null;}', 'elementAt(int i){return new javax.microedition.lcdui.Image();}')
    stubs['javax/microedition/lcdui/Font.java'] = stubs['javax/microedition/lcdui/Font.java'].replace(
        'public static long measured;', 'public static Runnable beforeMeasure; public static long measured;').replace(
        'int width=0;measured+=length;',
        'if(beforeMeasure!=null){Runnable action=beforeMeasure;beforeMeasure=null;action.run();}int width=0;measured+=length;')
    stubs['javax/microedition/rms/RecordStore.java'] = stubs['javax/microedition/rms/RecordStore.java'].replace(
        'public static RecordStore openRecordStore',
        'public static String[] listRecordStores(){return new String[0];}'
        'public static void deleteRecordStore(String name){stores.remove(name);}'
        'public static RecordStore openRecordStore')
    cp = os.pathsep.join(map(str, [classes, *sorted((work / 'wtk/lib').glob('*.jar'))]))
    with tempfile.TemporaryDirectory(prefix='tmm-chat-memory-') as temp:
        directory = Path(temp); resources = directory / 'resources'; resources.mkdir()
        for name in ('RU.lng', 'langlist.lng'):
            shutil.copy2(work / 'src/build/res' / name, resources / name)
        sources = []
        for name, source in stubs.items():
            path = directory / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source); sources.append(str(path))
        sources.append(str(ROOT / 'tests/java/ChatMemoryTest.java'))
        subprocess.run([str(work / 'jdk/bin/javac'), '-encoding', 'UTF-8', '-cp', cp,
                        '-d', str(directory), *sources], check=True)
        subprocess.run([str(work / 'jdk/bin/java'), '-XX:-DoEscapeAnalysis',
                        '-Xbootclasspath/a:' + str(resources), '-cp', str(directory) + os.pathsep + cp,
                        'jimm.ChatMemoryTest', 'baseline' if baseline else 'verify'],
                       check=True, timeout=30)


if __name__ == '__main__':
    work = Path(sys.argv[1]).resolve()
    run(work, Path(sys.argv[2]).resolve() if len(sys.argv) > 2
        else work / 'src/build/compile/classes', len(sys.argv) > 3 and sys.argv[3] == 'baseline')
