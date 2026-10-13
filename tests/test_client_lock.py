"""Real startup progress, PIN settings, lock canvas and queued navigation.

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
    stubs['jimm/Jimm.java'] = stubs['jimm/Jimm.java'].replace(
        'public Clock(){super(true);}', 'public static int scheduled;public Clock(){super(true);}').replace(
        'public void schedule(java.util.TimerTask task,long delay,long period){}',
        'public void schedule(java.util.TimerTask task,long delay,long period){scheduled++;}'
        'public void schedule(java.util.TimerTask task,long delay){scheduled++;}')
    stubs['javax/microedition/lcdui/Display.java'] = stubs['javax/microedition/lcdui/Display.java'].replace(
        'private Displayable current;', 'public static boolean foreground=true,deferScreens,failScreen;public static int screenChanges;public Displayable pendingScreen;private Displayable current;').replace(
        'current=d;', 'if(failScreen){failScreen=false;throw new OutOfMemoryError("screen transition");}screenChanges++;if(deferScreens)pendingScreen=d;else current=d;')
    stubs['javax/microedition/lcdui/Canvas.java'] = stubs['javax/microedition/lcdui/Canvas.java'].replace(
        'public void repaint(){}', '''public static boolean threadedRepaint,suspendRepaint;
 public static int repaints,repaintWaits;public static volatile Throwable paintFailure;
 private volatile Thread painter;
 public void repaint(){
  if(!threadedRepaint)return;
  repaints++;if(suspendRepaint)return;
  painter=new Thread(new Runnable(){public void run(){try{
   java.lang.reflect.Method method=Canvas.this.getClass().getDeclaredMethod("paint",Graphics.class);
   method.setAccessible(true);method.invoke(Canvas.this,new Graphics());
  }catch(Throwable failure){paintFailure=failure instanceof java.lang.reflect.InvocationTargetException?failure.getCause():failure;paintFailure.printStackTrace();}}});
  painter.setDaemon(true);painter.start();
 }
 public void awaitPaint() throws InterruptedException{if(painter!=null){painter.join(1000);if(painter.isAlive())throw new AssertionError("paint never finishes");}}
''').replace(
        'public void serviceRepaints(){}', '''public static boolean forbidRepaintWait;
 public void serviceRepaints(){
  repaintWaits++;
  if(forbidRepaintWait||suspendRepaint)throw new AssertionError("wait for suspended repaint");
  try{awaitPaint();}catch(InterruptedException failure){throw new AssertionError(failure);}
 }''')
    stubs['javax/microedition/lcdui/Displayable.java'] = stubs['javax/microedition/lcdui/Displayable.java'].replace(
        'jimm.Jimm.display.getCurrent()==this', 'jimm.Jimm.display.getCurrent()==this && Display.foreground')
    stubs['javax/microedition/lcdui/TextBox.java'] = '''package javax.microedition.lcdui;
public class TextBox extends Displayable {public TextBox(String title,String text,int max,int constraints){}}
'''
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
 public int getClipY(){return 0;}public void setColor(int c){}public void setColor(int r,int g,int b){}public void setFont(Font f){font=f;}
 public Font getFont(){return font;}public void drawString(String s,int x,int y,int flags){strings.addElement(s);}
 public void drawImage(Image i,int x,int y,int flags){}public void fillRect(int x,int y,int w,int h){}
 public void drawRect(int x,int y,int w,int h){}public void drawLine(int x,int y,int xx,int yy){}
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
        sources.extend(str(root/'tests/java'/name) for name in ['ClientStartupTest.java', 'ClientLockTest.java'])
        subprocess.run([str(work/'jdk/bin/javac'), '-encoding', 'UTF-8', '-cp', cp,
                        '-d', str(directory), *sources], check=True)
        for name in ['ClientStartupTest', 'ClientLockTest']:
            subprocess.run([str(work/'jdk/bin/java'), '-Xbootclasspath/a:'+str(resources),
                            '-cp', str(directory)+os.pathsep+cp, name], check=True, timeout=25)


if __name__ == '__main__':
    work = Path(sys.argv[1]).resolve()
    run(work, Path(sys.argv[2]).resolve() if len(sys.argv)>2 else work/'src/build/compile/classes')
