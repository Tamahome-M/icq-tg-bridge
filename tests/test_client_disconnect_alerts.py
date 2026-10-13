"""Actual error recovery and tone playback, with native MIDP and retry scheduling faked.

Usage: python tests/test_client_disconnect_alerts.py BUILD_WORK [CLASSES]
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
    stubs['jimm/Threads.java'] = '''package jimm;
public class Threads {
 public static final long SLOW_RECONNECT_MS=60000;
 public static int retries;
 public static void reconnect(){retries++;}
 public static void reconnect(long delay){retries++;}
 public static void checkReconnect(){}
}'''
    cp = os.pathsep.join(str(p) for p in [classes, *sorted((work/'wtk/lib').glob('*.jar'))])
    with tempfile.TemporaryDirectory(prefix='tmm-disconnect-alerts-') as temp:
        directory = Path(temp)
        resources = directory/'resources'
        resources.mkdir()
        for name in ('RU.lng', 'langlist.lng', 'message.mp3', 'msg_low.mp3', 'tg.mp3', 'typing.mp3'):
            shutil.copy2(work/'src/build/res'/name, resources/name)
        sources = []
        for name, source in stubs.items():
            path = directory/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
            sources.append(str(path))
        sources.append(str(root/'tests/java/DisconnectAlertsTest.java'))
        subprocess.run([str(work/'jdk/bin/javac'), '-encoding', 'UTF-8', '-cp', cp,
                        '-d', str(directory), *sources], check=True)
        subprocess.run([str(work/'jdk/bin/java'), '-Xbootclasspath/a:'+str(resources),
                        '-cp', str(directory)+os.pathsep+cp, 'jimm.DisconnectAlertsTest'],
                       check=True, timeout=25)


if __name__ == '__main__':
    work = Path(sys.argv[1]).resolve()
    run(work, Path(sys.argv[2]).resolve() if len(sys.argv)>2 else work/'src/build/compile/classes')
