"""Actual JimmUI clipboard/editor command dispatch with fake MIDP widgets."""
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
    stubs['javax/microedition/lcdui/TextBox.java'] = '''package javax.microedition.lcdui;
public class TextBox extends Displayable {
 private String text;private int max;public int caret;
 public TextBox(String title,String text,int max,int constraints){this.max=max;setString(text);}
 public void setTitle(String title){}public void setConstraints(int constraints){}
 public String getString(){return text;}public int size(){return text.length();}
 public void setString(String value){text=value==null?"":value;caret=text.length();}
 public int getMaxSize(){return max;}public int getCaretPosition(){return caret;}
 public void insert(String value,int at){if(text.length()+value.length()>max)throw new IllegalArgumentException();
  text=text.substring(0,at)+value+text.substring(at);caret=at+value.length();}
}'''
    cp = os.pathsep.join(str(p) for p in [classes, *sorted((work/'wtk/lib').glob('*.jar'))])
    with tempfile.TemporaryDirectory(prefix='tmm-clipboard-') as temp:
        directory = Path(temp); resources = directory/'resources'; resources.mkdir()
        for name in ['RU.lng', 'langlist.lng']:
            shutil.copy2(work/'src/build/res'/name, resources/name)
        sources = []
        for name, source in stubs.items():
            path = directory/name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source); sources.append(str(path))
        sources.append(str(root/'tests/java/ClientClipboardTest.java'))
        subprocess.run([str(work/'jdk/bin/javac'), '-encoding', 'UTF-8', '-cp', cp,
                        '-d', str(directory), *sources], check=True)
        subprocess.run([str(work/'jdk/bin/java'), '-Xbootclasspath/a:'+str(resources),
                        '-cp', str(directory)+os.pathsep+cp, 'ClientClipboardTest'], check=True, timeout=25)


if __name__ == '__main__':
    work = Path(sys.argv[1]).resolve()
    run(work, Path(sys.argv[2]).resolve() if len(sys.argv)>2 else work/'src/build/compile/classes')
