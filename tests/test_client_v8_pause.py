"""Real V8 MIDlet lifecycle and keylock with a suspended UI queue.

Usage: python tests/test_client_v8_pause.py V8_BUILD [CLASSES]
No Vodafone API is present. Only MIDP widgets/device side effects are stubbed;
Jimm, FlipState, Options, SplashCanvas, JimmUI and MainThread are the real client.
"""
from pathlib import Path
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from tests.test_client_lock import make_lock_stubs


def run(work, classes):
    stubs = make_lock_stubs()
    stubs.pop('jimm/Jimm.java')
    stubs.pop('DrawControls/device/Device.java')
    stubs['javax/microedition/midlet/MIDlet.java'] = '''package javax.microedition.midlet;
public abstract class MIDlet {
 public static int pauses;
 public void notifyPaused(){pauses++;}public void notifyDestroyed(){}
 public String getAppProperty(String name){return null;}
 public boolean platformRequest(String url){return false;}
}'''
    stubs['javax/microedition/lcdui/Display.java'] = stubs['javax/microedition/lcdui/Display.java'].replace(
        'private Displayable current;', 'public static int selections;public static boolean failGetCurrentOnce;public static java.util.Vector selected=new java.util.Vector(); private Displayable current;').replace(
        'public void setCurrent(Displayable d){current=d;}',
        'public void setCurrent(Displayable d){selections++;selected.addElement(d);current=d;}').replace(
        'public Displayable getCurrent(){return current;}',
        'public Displayable getCurrent(){if(failGetCurrentOnce){failGetCurrentOnce=false;throw new IllegalStateException("native current screen unavailable");}return current;}')
    libs = [p for p in sorted((work/'wtk/lib').glob('*.jar')) if p.name != 'tmm-vendor-stubs.jar']
    cp = os.pathsep.join(str(p) for p in [classes, *libs])
    with tempfile.TemporaryDirectory(prefix='tmm-v8-pause-') as temp:
        directory = Path(temp)
        resources = directory/'resources'
        resources.mkdir()
        for name in ('RU.lng', 'langlist.lng'):
            shutil.copy2(work/'src/build/res'/name, resources/name)
        sources = []
        for name, source in stubs.items():
            path = directory/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
            sources.append(str(path))
        sources.append(str(root/'tests/java/ClientV8PauseTest.java'))
        subprocess.run([str(work/'jdk/bin/javac'), '-encoding', 'UTF-8', '-cp', cp,
                        '-d', str(directory), *sources], check=True)
        subprocess.run([str(work/'jdk/bin/java'), '-Xbootclasspath/a:'+str(resources),
                        '-cp', str(directory)+os.pathsep+cp, 'ClientV8PauseTest'], check=True, timeout=25)
    with zipfile.ZipFile(work/'out/TeleMotoMax.jar') as jar:
        packaged = {n: jar.read(n) for n in jar.namelist() if n.endswith('.class')}
    assert not any(n.startswith('com/vodafone/') for n in packaged), 'V8 includes vendor stubs'
    assert not any(b'com/vodafone/system/DeviceControl' in body for body in packaged.values()), 'V8 still links V3 cover API'
    assert all(struct.unpack('>HH', data[4:8]) == (3,45) for data in packaged.values()), 'V8 is not CLDC bytecode'
    print('PASS: packaged V8 has no Vodafone dependency or API stubs; CLDC 45.3')


if __name__ == '__main__':
    work = Path(sys.argv[1]).resolve()
    run(work, Path(sys.argv[2]).resolve() if len(sys.argv)>2 else work/'src/build/compile/classes')
