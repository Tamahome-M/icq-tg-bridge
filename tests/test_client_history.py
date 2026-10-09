"""Real HistoryViewer/TextList: incremental pages, memory, metadata and failures.

Usage: python tests/test_client_history.py BUILD_WORK [CLASSES] [baseline]
MIDP widgets/fonts are stubbed; parser, layout and history commands are real.
Baseline mode records layout and work from 0.93 for comparison.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from tests.test_client_performance import make_stubs


def run(work, classes, baseline):
    stubs = make_stubs()
    stubs['javax/microedition/lcdui/Canvas.java'] = stubs['javax/microedition/lcdui/Canvas.java'].replace(
        'public void repaint(){}', 'public void repaint(){} public void repaint(int x,int y,int w,int h){}')
    stubs['jimm/ChatTextList.java'] = stubs['jimm/ChatTextList.java'].replace(
        'getInOutColor(boolean incoming) {return 0;}', 'getInOutColor(boolean incoming) {return incoming?0x123456:0x654321;}')
    stubs['javax/microedition/lcdui/Font.java'] = stubs['javax/microedition/lcdui/Font.java'].replace(
        'public static long measured;', 'public static Runnable beforeMeasure; public static long measured;').replace(
        'int width=0;measured+=length;',
        'if(beforeMeasure!=null){Runnable action=beforeMeasure;beforeMeasure=null;action.run();}int width=0;measured+=length;')
    cp = os.pathsep.join(str(p) for p in [classes, *sorted((work/'wtk/lib').glob('*.jar'))])
    with tempfile.TemporaryDirectory(prefix='tmm-history-') as temp:
        directory = Path(temp)
        resources = directory/'resources'; resources.mkdir()
        for name in ['RU.lng', 'langlist.lng']:
            shutil.copy2(work/'src/build/res'/name, resources/name)
        sources = []
        for name, source in stubs.items():
            path = directory/name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source); sources.append(str(path))
        sources.append(str(root/'tests/java/HistoryMemoryTest.java'))
        subprocess.run([str(work/'jdk/bin/javac'), '-encoding', 'UTF-8', '-cp', cp,
                        '-d', str(directory), *sources], check=True)
        subprocess.run([str(work/'jdk/bin/java'), '-Xbootclasspath/a:'+str(resources),
                        '-cp', str(directory)+os.pathsep+cp, 'HistoryMemoryTest',
                        'baseline' if baseline else 'verify'], check=True, timeout=30)


if __name__ == '__main__':
    work = Path(sys.argv[1]).resolve()
    run(work, Path(sys.argv[2]).resolve() if len(sys.argv)>2 else work/'src/build/compile/classes',
        len(sys.argv)>3 and sys.argv[3]=='baseline')
