"""Real vibration settings/RMS and MainThread message dispatch; fake MIDP motor.

Usage: python tests/test_client_vibration.py BUILD_WORK [CLASSES]
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
    # Isolate the existing roster/message gates. Vibration decisions and
    # queued delivery use the real MainThread, Options and SplashCanvas.
    stubs['jimm/ContactList.java'] = '''package jimm;
public class ContactList {
 public static boolean accepted=true,reading=false,lastAlertAllowed=true;
 public static boolean addMessage(jimm.comm.Message m){return accepted;}
 public static boolean readingChat(String uin){return reading;}
}'''
    stubs['javax/microedition/lcdui/Display.java'] = stubs['javax/microedition/lcdui/Display.java'].replace(
        'private Displayable current;', '''public static java.util.Vector vibrations=new java.util.Vector();
 public boolean vibrate(int milliseconds){vibrations.addElement(new Integer(milliseconds));return true;}
 private Displayable current;''')
    stubs['javax/microedition/lcdui/Gauge.java'] = '''package javax.microedition.lcdui;
public class Gauge extends Item {
 private int value;public Gauge(String label,boolean interactive,int max,int initial){this.label=label;value=initial;}
 public int getValue(){return value;}public void setValue(int v){value=v;}
}'''
    cp = os.pathsep.join(str(p) for p in [classes, *sorted((work/'wtk/lib').glob('*.jar'))])
    with tempfile.TemporaryDirectory(prefix='tmm-vibration-') as temp:
        directory = Path(temp); resources = directory/'resources'; resources.mkdir()
        for name in ['RU.lng', 'langlist.lng']:
            shutil.copy2(work/'src/build/res'/name, resources/name)
        sources = []
        for name, source in stubs.items():
            path = directory/name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source); sources.append(str(path))
        sources.append(str(root/'tests/java/ClientVibrationTest.java'))
        subprocess.run([str(work/'jdk/bin/javac'), '-encoding', 'UTF-8', '-cp', cp,
                        '-d', str(directory), *sources], check=True)
        subprocess.run([str(work/'jdk/bin/java'), '-Xbootclasspath/a:'+str(resources),
                        '-cp', str(directory)+os.pathsep+cp, 'ClientVibrationTest'], check=True, timeout=25)


if __name__ == '__main__':
    work = Path(sys.argv[1]).resolve()
    run(work, Path(sys.argv[2]).resolve() if len(sys.argv)>2 else work/'src/build/compile/classes')
