"""Real compiled OptionsForm and JimmUI return stack; MIDP UI/queue stubbed.
Usage: python tests/test_settings_navigation.py BUILD_WORK [COMPILED_CLASSES]
"""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from tests.test_client_ui import STUBS


def run(work: Path, classes: Path):
    stubs = dict(STUBS)
    stubs.pop('jimm/JimmUI.java')  # Test the real compiled navigation stack.
    stubs['jimm/util/ResourceBundle.java'] = stubs['jimm/util/ResourceBundle.java'].replace(
        'public class ResourceBundle {',
        'public class ResourceBundle {public static String getString(String s,int flags){return getString(s);}')
    stubs['javax/microedition/lcdui/Display.java'] = stubs['javax/microedition/lcdui/Display.java'].replace(
        'private Displayable current;', 'public static boolean foreground=true; private Displayable current;')
    stubs['javax/microedition/lcdui/Displayable.java'] = stubs['javax/microedition/lcdui/Displayable.java'].replace(
        'return jimm.Jimm.display.getCurrent()==this;',
        'return Display.foreground && jimm.Jimm.display.getCurrent()==this;')
    stubs['DrawControls/VirtualList.java'] = stubs['DrawControls/VirtualList.java'].replace(
        'return jimm.Jimm.display.getCurrent()==this;', 'return isShown();').replace(
        'public void setMode(int mode) {}', '''public void setMode(int mode) {}
 public void setColors(int a,int b,int c,int d,int e,int f){}
 public static int checkTextColor(int n){return n;}
 public void setFullScreen(boolean b){} public void setFontSize(int n){}''')
    stubs['DrawControls/TextList.java'] = stubs['DrawControls/TextList.java'].replace(
        'public TextList(String caption) {}',
        'public TextList(String caption) {} public void setIndexedColor(int a,int b){}')
    stubs['DrawControls/device/Device.java'] = stubs['DrawControls/device/Device.java'].replace(
        'void setBackLightOnTime', 'boolean featureSupported(int n); void setBackLightOnTime')
    stubs['jimm/Jimm.java'] = stubs['jimm/Jimm.java'].replace(
        'public void setBackLightOnTime',
        'public boolean featureSupported(int n){return false;} public void setBackLightOnTime')
    stubs['javax/microedition/lcdui/Form.java'] = stubs['javax/microedition/lcdui/Form.java'].replace(
        'public void setItemStateListener',
        'public void deleteAll(){items.removeAllElements();} public void delete(int n){items.removeElementAt(n);}'
        ' public int size(){return items.size();} public void setItemStateListener')
    # Hold callSerially until the test changes visibility; do not replace the
    # real JimmUI.backToLastScreen implementation with a navigation stub.
    stubs['jimm/MainThread.java'] = '''package jimm;
 public class MainThread {public static boolean pending;
 public static void backToLastScreenMT(){pending=true;}
 public static void flush(){if(pending){pending=false;JimmUI.backToLastScreen();}}}'''
    stubs['jimm/MainMenu.java'] = '''package jimm;
 import DrawControls.*;
 public class MainMenu implements JimmScreen {
 public static final ImageList menuIcons=new ImageList();
 public static final TextList menu=new TextList("main");
 private static final MainMenu root=new MainMenu();
 public static void activateMenu(){menu.activate(Jimm.display);JimmUI.setLastScreen(root,true);}
 public void activate(){activateMenu();}public boolean isScreenActive(){return menu.isActive();}}'''
    cp = os.pathsep.join(str(p) for p in [classes, *sorted((work/'wtk/lib').glob('*.jar'))])
    with tempfile.TemporaryDirectory(prefix='tmm-settings-navigation-') as temp:
        directory = Path(temp)
        sources = []
        for name, source in stubs.items():
            path = directory/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
            sources.append(str(path))
        path = root/'tests/java/SettingsNavigationTest.java'
        subprocess.run([str(work/'jdk/bin/javac'), '-encoding', 'UTF-8', '-cp', cp,
                        '-d', str(directory), *sources, str(path)], check=True)
        subprocess.run([str(work/'jdk/bin/java'), '-cp', str(directory)+os.pathsep+cp,
                        'SettingsNavigationTest'], check=True, timeout=15)

if __name__ == '__main__':
    work = Path(sys.argv[1]).resolve()
    run(work, Path(sys.argv[2]).resolve() if len(sys.argv)>2 else work/'src/build/compile/classes')
