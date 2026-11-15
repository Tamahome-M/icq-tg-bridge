"""Exercise the real camera/recorder with blocked MMAPI calls and cancellation.

Usage: python tests/test_client_capture_lifecycle.py BUILD_WORK [baseline]
Only the two capture sources are compiled; the device build is not modified.
"""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
STUBS = {
    'jimm/Jimm.java': '''package jimm; public class Jimm {
 public static javax.microedition.lcdui.Display display=new javax.microedition.lcdui.Display();
 private static java.util.Timer timer=new java.util.Timer(true);
 public static java.util.Timer getTimerRef(){return timer;} public static void wakeBacklight(){}
}''',
    'jimm/JimmUI.java': '''package jimm; public class JimmUI {
 public static javax.microedition.lcdui.Command cmdBack;
}''',
    'jimm/MainThread.java': '''package jimm; public class MainThread {
 public static void activateScreenMT(JimmScreen s){if(s!=null)s.activate();else Jimm.display.setCurrent(null);}
}''',
    'jimm/Options.java': '''package jimm; public class Options {
 public static final int OPTION_CAMERA_SIZE=1; public static String getString(int n){return "";}
}''',
    'jimm/ConnLog.java': 'package jimm; public class ConnLog {public static void note(String s){}}',
    'jimm/util/ResourceBundle.java': 'package jimm.util; public class ResourceBundle {public static String getString(String s){return s;}}',
    'DrawControls/VirtualList.java': 'package DrawControls; public class VirtualList {public static void touch(){}}',
    'jimm/CameraHud.java': '''package jimm; import javax.microedition.lcdui.*; public class CameraHud {
 public static final int REC=0,WARN=1,DIM=2;public static Font FONT;
 public static String mmss(int n){return ""+n;}public static void top(Graphics g,int w,String l,String r,int c){}
 public static void bottom(Graphics g,int w,int h,String a,String b){} public static void recDot(Graphics g,int a,int b,int c){}
 public static void box(Graphics g,int w,int h,String s,String[] d){}
}''',
    'jimm/TempFiles.java': '''package jimm; public class TempFiles {
 public static boolean memory;public static java.util.Hashtable files=new java.util.Hashtable();
 public static String writableUrl(String n){if(memory)return null;String p="file:///"+n;javax.microedition.media.Manager.step(9);files.put(p,Boolean.TRUE);return p;}
 public static void remove(String p){if(p!=null)files.remove(p);}
}''',
    'jimm/comm/Icq.java': '''package jimm.comm; public class Icq {
 public static int sent;public static class Upload {boolean active=true;public Upload(String u){}
 public boolean isActive(){return active;}public void cancel(){active=false;}public void onPart(int n,int t){}
 public boolean matches(String u,long r){return true;}}
 public static void sendVideo(String u,byte[] b,int s,String t,Upload x){javax.microedition.media.Manager.step(10);if(x.isActive())sent++;}
 public static void sendVideoStream(String u,java.io.InputStream in,long n,int s,String t,Upload x){if(x.isActive())sent++;}
 public static void sendPhoto(String u,byte[] b,Upload x){if(x.isActive())sent++;}
}''',
    'javax/microedition/lcdui/Displayable.java': '''package javax.microedition.lcdui; public class Displayable {
 public void addCommand(Command c){} public void setCommandListener(CommandListener l){}
 public boolean isShown(){return jimm.Jimm.display.getCurrent()==this;}
}''',
    'javax/microedition/lcdui/Canvas.java': '''package javax.microedition.lcdui; public class Canvas extends Displayable {
 public static final int FIRE=8,KEY_NUM5=53;public void setFullScreenMode(boolean f){}public void repaint(){}
 public int getWidth(){return 240;}public int getHeight(){return 320;}public int getGameAction(int k){return FIRE;}
}''',
    'javax/microedition/lcdui/Display.java': '''package javax.microedition.lcdui; public class Display {
 private Displayable current; public void setCurrent(Displayable d){current=d;}public Displayable getCurrent(){return current;}
}''',
    'javax/microedition/io/Connector.java': '''package javax.microedition.io; public class Connector {
 public static final int READ=1,READ_WRITE=3;
 public static Connection open(final String path,int mode) {
  return (Connection)java.lang.reflect.Proxy.newProxyInstance(javax.microedition.io.file.FileConnection.class.getClassLoader(),
   new Class[]{javax.microedition.io.file.FileConnection.class},new java.lang.reflect.InvocationHandler(){
    public Object invoke(Object p,java.lang.reflect.Method m,Object[] a){String n=m.getName();
     if(n.equals("exists"))return Boolean.valueOf(jimm.TempFiles.files.containsKey(path));
     if(n.equals("delete"))jimm.TempFiles.files.remove(path);
     if(n.equals("fileSize"))return Long.valueOf(3);
     if(n.equals("openInputStream"))return new java.io.ByteArrayInputStream(new byte[]{1,2,3});
     Class t=m.getReturnType();if(t==Boolean.TYPE)return Boolean.FALSE;if(t==Integer.TYPE)return Integer.valueOf(0);if(t==Long.TYPE)return Long.valueOf(0);return null;
    }});
 }
}''',
    'javax/microedition/media/Manager.java': '''package javax.microedition.media;
import java.lang.reflect.*;import java.io.*;import java.util.*;
import javax.microedition.media.control.*;
public class Manager {
 public static class Gate {public final java.util.concurrent.CountDownLatch entered=new java.util.concurrent.CountDownLatch(1),release=new java.util.concurrent.CountDownLatch(1);
  public void await(){entered.countDown();try{release.await();}catch(Exception e){throw new AssertionError(e);}}}
 public static volatile Gate gate;public static volatile int stage; public static volatile Thread worker;public static Vector created=new Vector();
 public static void step(int s){if(stage==s && gate!=null){Gate g=gate;gate=null;worker=Thread.currentThread();g.await();}}
 public static String[] getSupportedContentTypes(String protocol){return new String[]{"video/3gpp"};}
 public static Player createPlayer(String path){worker=Thread.currentThread();step(1);State s=new State();created.addElement(s);return s.player;}
 public static class State implements InvocationHandler {
  public volatile int state=Player.UNREALIZED,starts,commits,recordStarts;public String path;OutputStream sink;
  public final Player player=(Player)Proxy.newProxyInstance(Player.class.getClassLoader(),new Class[]{Player.class},this);
  public final VideoControl video=(VideoControl)Proxy.newProxyInstance(VideoControl.class.getClassLoader(),new Class[]{VideoControl.class},this);
  public final RecordControl record=(RecordControl)Proxy.newProxyInstance(RecordControl.class.getClassLoader(),new Class[]{RecordControl.class},this);
  public Object invoke(Object p,Method m,Object[] a)throws Throwable {
   String n=m.getName();if(n.equals("realize")){step(2);if(state!=Player.CLOSED)state=Player.REALIZED;}
   else if(n.equals("getControl")){if(a[0].equals("RecordControl")){step(5);return record;}return video;}
   else if(n.equals("setDisplaySize"))step(3);
   else if(n.equals("start")){step(4);if(state==Player.CLOSED)throw new IllegalStateException("closed");starts++;state=Player.STARTED;}
   else if(n.equals("close"))state=Player.CLOSED;
   else if(n.equals("getState"))return Integer.valueOf(state);
   else if(n.equals("setRecordLocation")){path=(String)a[0];step(6);jimm.TempFiles.files.put(path,Boolean.TRUE);}
   else if(n.equals("setRecordStream")){sink=(OutputStream)a[0];step(6);}
   else if(n.equals("startRecord")){step(7);if(state==Player.CLOSED)throw new IllegalStateException("closed");recordStarts++;}
   else if(n.equals("commit")){step(8);commits++;if(sink!=null)sink.write(new byte[]{1,2,3});}
   else if(n.equals("getContentType"))return "video/3gpp";
   Class t=m.getReturnType();if(t==Boolean.TYPE)return Boolean.FALSE;if(t==Integer.TYPE)return Integer.valueOf(0);if(t==Long.TYPE)return Long.valueOf(0);return null;
  }
 }
}''',
}


def run(work, baseline=False):
    cp = os.pathsep.join(map(str, [work/'src/build/compile/classes', *sorted((work/'wtk/lib').glob('*.jar'))]))
    with tempfile.TemporaryDirectory(prefix='tmm-capture-lifecycle-') as temp:
        directory = Path(temp)
        sources = []
        stubs = dict(STUBS)
        for name in ('CameraShot', 'VideoRecorder'):
            path = 'telemotomax/src/jimm/' + name + '.java'
            stubs['jimm/' + name + '.java'] = (subprocess.check_output(['git', 'show', 'HEAD:'+path], cwd=ROOT).decode()
                if baseline else (ROOT/path).read_text())
        for name, source in stubs.items():
            path = directory/name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source); sources.append(str(path))
        sources.append(str(ROOT/'tests/java/ClientCaptureLifecycleTest.java'))
        subprocess.run([str(work/'jdk/bin/javac'), '-encoding', 'UTF-8', '-cp', cp,
                        '-d', str(directory), *sources], check=True)
        subprocess.run([str(work/'jdk/bin/java'), '-cp', str(directory)+os.pathsep+cp,
                        'jimm.ClientCaptureLifecycleTest', 'baseline' if baseline else 'verify'], check=True, timeout=35)


if __name__ == '__main__':
    run(Path(sys.argv[1]).resolve(), len(sys.argv)>2 and sys.argv[2]=='baseline')
