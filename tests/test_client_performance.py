"""Real client translations, text layout, UI task batching and lazy timers.

Usage: python tests/test_client_performance.py BUILD_WORK [CLASSES] [baseline]
The optional baseline mode records layout/measurement counts from older classes.
MIDP drawing and scheduling are stubbed; the client implementations are real.
"""
from pathlib import Path
import os, shutil, subprocess, sys, tempfile

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from tests.test_client_ui import STUBS


def make_stubs():
    stubs = dict(STUBS)
    for name in ['jimm/JimmUI.java', 'jimm/MainThread.java', 'jimm/util/ResourceBundle.java',
                 'DrawControls/TextList.java', 'DrawControls/VirtualList.java',
                 'DrawControls/VirtualListCommands.java']:
        stubs.pop(name)
    stubs['DrawControls/device/Device.java'] = stubs['DrawControls/device/Device.java'].replace(
        'void setBackLightOnTime', 'boolean featureSupported(int n); void setBackLightOnTime')
    stubs['jimm/Jimm.java'] = stubs['jimm/Jimm.java'].replace(
        'public void setBackLightOnTime', 'public boolean featureSupported(int n){return false;} public void setBackLightOnTime')
    stubs['javax/microedition/lcdui/Display.java'] = stubs['javax/microedition/lcdui/Display.java'].replace(
        'private Displayable current;', '''public static java.util.Vector queued=new java.util.Vector();
 public void callSerially(Runnable r){queued.addElement(r);}
 public static void flush(){while(!queued.isEmpty()){Runnable r=(Runnable)queued.elementAt(0);queued.removeElementAt(0);r.run();}}
 private Displayable current;''')
    stubs['javax/microedition/lcdui/Font.java'] = '''package javax.microedition.lcdui;
public class Font {
 public static final int FACE_SYSTEM=0,STYLE_PLAIN=0,STYLE_BOLD=1,SIZE_SMALL=8,SIZE_MEDIUM=0,SIZE_LARGE=16;
 public static long measured; public static int strings;
 public static Font getFont(int f,int s,int z){return new Font();}public static Font getDefaultFont(){return new Font();}
 public int getHeight(){return 12;}
 public int charWidth(char c){return c=='W'||c=='Ж'?10:c=='i'||c=='l'?3:6;}
 public int stringWidth(String s){strings++;return substringWidth(s,0,s.length());}
 public int substringWidth(String s,int offset,int length){int width=0;measured+=length;for(int i=0;i<length;i++)width+=charWidth(s.charAt(offset+i));return width;}
}'''
    return stubs


def run(work, classes, baseline):
    stubs = make_stubs()
    cp = os.pathsep.join(str(p) for p in [classes, *sorted((work/'wtk/lib').glob('*.jar'))])
    with tempfile.TemporaryDirectory(prefix='tmm-performance-') as temp:
        directory = Path(temp)
        # Old ResourceBundle uses bootstrap Object/Hashtable resource lookup;
        # append only resources so old and new clients read the same real pack.
        resources = directory/'resources';resources.mkdir()
        for name in ['RU.lng', 'langlist.lng']:
            shutil.copy2(work/'src/build/res'/name, resources/name)
        sources = []
        for name, source in stubs.items():
            path = directory/name;path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source);sources.append(str(path))
        sources.append(str(root/'tests/java/ClientPerformanceTest.java'))
        subprocess.run([str(work/'jdk/bin/javac'), '-encoding', 'UTF-8', '-cp', cp,
                        '-d', str(directory), *sources], check=True)
        subprocess.run([str(work/'jdk/bin/java'), '-Xbootclasspath/a:'+str(resources),
                        '-cp', str(directory)+os.pathsep+cp, 'ClientPerformanceTest',
                        str(resources/'RU.lng'), 'baseline' if baseline else 'verify'],
                       check=True, timeout=20)


if __name__ == '__main__':
    work = Path(sys.argv[1]).resolve()
    run(work, Path(sys.argv[2]).resolve() if len(sys.argv)>2 else work/'src/build/compile/classes',
        len(sys.argv)>3 and sys.argv[3]=='baseline')
