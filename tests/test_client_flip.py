"""Exercise real flip inference, ConnLog and UI scheduling with fake MIDP.

Usage: python tests/test_client_flip.py BUILD_WORK [CLASSES]
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


def run(work, classes):
    stubs = make_stubs()
    stubs['javax/microedition/lcdui/Display.java'] = stubs['javax/microedition/lcdui/Display.java'].replace(
        'queued.addElement(r);', 'if(fail)throw new OutOfMemoryError("UI scheduling");queued.addElement(r);').replace(
        'public static java.util.Vector queued=', 'public static boolean fail;public static java.util.Vector queued=').replace(
        'public Displayable getCurrent()', 'public synchronized Displayable getCurrent()')
    cp = os.pathsep.join(str(p) for p in [classes, *sorted((work/'wtk/lib').glob('*.jar'))])
    with tempfile.TemporaryDirectory(prefix='tmm-flip-test-') as temp:
        directory = Path(temp)
        resources = directory/'resources'; resources.mkdir()
        for name in ['RU.lng', 'langlist.lng']:
            shutil.copy2(work/'src/build/res'/name, resources/name)
        sources = []
        for name, source in stubs.items():
            path = directory/name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source); sources.append(str(path))
        sources.append(str(root/'tests/java/ClientFlipTest.java'))
        subprocess.run([str(work/'jdk/bin/javac'), '-encoding', 'UTF-8', '-cp', cp,
                        '-d', str(directory), *sources], check=True)
        subprocess.run([str(work/'jdk/bin/java'), '-Xbootclasspath/a:'+str(resources),
                        '-cp', str(directory)+os.pathsep+cp, 'jimm.ClientFlipTest'],
                       check=True, timeout=25)


if __name__ == '__main__':
    work = Path(sys.argv[1]).resolve()
    run(work, Path(sys.argv[2]).resolve() if len(sys.argv)>2 else work/'src/build/compile/classes')
