"""Real tree sorting, contact updates and indexed colours with desktop meters.

Usage: python tests/test_client_tree_memory.py BUILD_WORK [CLASSES] [baseline]
MIDP widgets are stubbed; allocation/comparison counts are not phone timings.
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
    stubs['javax/microedition/lcdui/Image.java'] = stubs['javax/microedition/lcdui/Image.java'].replace(
        'public class Image {', 'public class Image { public int getHeight(){return 12;}public int getWidth(){return 12;}')
    stubs['DrawControls/ImageList.java'] = stubs['DrawControls/ImageList.java'].replace(
        'elementAt(int i){return null;}', 'elementAt(int i){return new javax.microedition.lcdui.Image();}')
    stubs['javax/microedition/rms/RecordStore.java'] = stubs['javax/microedition/rms/RecordStore.java'].replace(
        'public static RecordStore openRecordStore',
        'public static String[] listRecordStores(){return new String[0];}'
        'public static void deleteRecordStore(String name){stores.remove(name);}'
        'public static RecordStore openRecordStore')
    cp = os.pathsep.join(map(str, [classes, *sorted((work / 'wtk/lib').glob('*.jar'))]))
    with tempfile.TemporaryDirectory(prefix='tmm-tree-memory-') as temp:
        directory = Path(temp); resources = directory / 'resources'; resources.mkdir()
        for name in ('RU.lng', 'langlist.lng'):
            shutil.copy2(work / 'src/build/res' / name, resources / name)
        sources = []
        for name, source in stubs.items():
            path = directory / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source); sources.append(str(path))
        sources.append(str(ROOT / 'tests/java/TreeMemoryTest.java'))
        subprocess.run([str(work / 'jdk/bin/javac'), '-encoding', 'UTF-8', '-cp', cp,
                        '-d', str(directory), *sources], check=True)
        subprocess.run([str(work / 'jdk/bin/java'), '-XX:-DoEscapeAnalysis',
                        '-Xbootclasspath/a:' + str(resources), '-cp', str(directory) + os.pathsep + cp,
                        'DrawControls.TreeMemoryTest', 'baseline' if baseline else 'verify'],
                       check=True, timeout=30)


if __name__ == '__main__':
    work = Path(sys.argv[1]).resolve()
    run(work, Path(sys.argv[2]).resolve() if len(sys.argv) > 2
        else work / 'src/build/compile/classes', len(sys.argv) > 3 and sys.argv[3] == 'baseline')
