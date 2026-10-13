"""Real incoming-message storage and delayed roster alert during startup silence.

Usage: python tests/test_client_startup_alerts.py BUILD_WORK [CLASSES]
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from tests.test_client_faults import ui_stubs


def run(work, classes):
    stubs = ui_stubs(audio=True)
    stubs['javax/microedition/lcdui/Display.java'] = stubs['javax/microedition/lcdui/Display.java'].replace(
        'private Displayable current;', 'public static int vibrations;public boolean vibrate(int duration){vibrations++;return true;}private Displayable current;')
    cp = os.pathsep.join(str(p) for p in [classes,*sorted((work/'wtk/lib').glob('*.jar'))])
    with tempfile.TemporaryDirectory(prefix='tmm-startup-alerts-') as temp:
        directory = Path(temp);resources = directory/'resources';resources.mkdir()
        for name in ('RU.lng','langlist.lng','message.mp3','msg_low.mp3','tg.mp3','typing.mp3'):
            shutil.copy2(work/'src/build/res'/name,resources/name)
        sources = []
        for name,source in stubs.items():
            path = directory/name;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(source);sources.append(str(path))
        sources.append(str(root/'tests/java/StartupAlertsTest.java'))
        subprocess.run([str(work/'jdk/bin/javac'),'-encoding','UTF-8','-cp',cp,'-d',str(directory),*sources],check=True)
        subprocess.run([str(work/'jdk/bin/java'),'-Xbootclasspath/a:'+str(resources),'-cp',str(directory)+os.pathsep+cp,
                        'jimm.StartupAlertsTest'],check=True,timeout=25)


if __name__ == '__main__':
    work = Path(sys.argv[1]).resolve()
    run(work,Path(sys.argv[2]).resolve() if len(sys.argv)>2 else work/'src/build/compile/classes')
