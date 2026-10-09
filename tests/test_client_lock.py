"""Real PIN settings, lock canvas and queued navigation with fake MIDP widgets.

Usage: python tests/test_client_lock.py BUILD_WORK [CLASSES]
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
    stubs['javax/microedition/lcdui/Form.java'] = stubs['javax/microedition/lcdui/Form.java'].replace(
        'public void setItemStateListener',
        'public void deleteAll(){items.clear();} public int size(){return items.size();}'
        ' public void setItemStateListener')
    stubs['javax/microedition/lcdui/TextField.java'] = '''package javax.microedition.lcdui;
public class TextField extends Item {
 public static final int NUMERIC=2,PASSWORD=65536,CONSTRAINT_MASK=65535;
 private String value;private int constraints,max;
 public TextField(String label,String value,int max,int constraints){this.label=label;this.value=value;this.max=max;this.constraints=constraints;}
 public String getString(){return value;}public void setString(String value){this.value=value;}
 public int getConstraints(){return constraints;}public int getMaxSize(){return max;}
}'''
    stubs['javax/microedition/lcdui/Graphics.java'] = '''package javax.microedition.lcdui;
public class Graphics {
 public java.util.Vector strings=new java.util.Vector();private Font font=Font.getDefaultFont();
 public int getClipY(){return 0;}public void setColor(int c){}public void setFont(Font f){font=f;}
 public Font getFont(){return font;}public void drawString(String s,int x,int y,int flags){strings.addElement(s);}
 public void drawImage(Image i,int x,int y,int flags){}public void fillRect(int x,int y,int w,int h){}
 public void drawRect(int x,int y,int w,int h){}
}'''
    cp = os.pathsep.join(str(p) for p in [classes, *sorted((work/'wtk/lib').glob('*.jar'))])
    with tempfile.TemporaryDirectory(prefix='tmm-pin-') as temp:
        directory = Path(temp); resources = directory/'resources'; resources.mkdir()
        for name in ['RU.lng', 'langlist.lng']:
            shutil.copy2(work/'src/build/res'/name, resources/name)
        sources = []
        for name, source in stubs.items():
            path = directory/name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source); sources.append(str(path))
        sources.append(str(root/'tests/java/ClientLockTest.java'))
        subprocess.run([str(work/'jdk/bin/javac'), '-encoding', 'UTF-8', '-cp', cp,
                        '-d', str(directory), *sources], check=True)
        subprocess.run([str(work/'jdk/bin/java'), '-Xbootclasspath/a:'+str(resources),
                        '-cp', str(directory)+os.pathsep+cp, 'ClientLockTest'], check=True, timeout=25)


if __name__ == '__main__':
    work = Path(sys.argv[1]).resolve()
    run(work, Path(sys.argv[2]).resolve() if len(sys.argv)>2 else work/'src/build/compile/classes')
