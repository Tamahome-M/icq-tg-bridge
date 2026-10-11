"""Real media screen, shared clock and cancellation, with fake MIDP/file APIs.

Usage: python tests/test_client_media_lifecycle.py BUILD_WORK [CLASSES] [baseline]
The baseline records actual helper threads and a player created after Back.
"""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_client_ui import STUBS


def run(work, classes, baseline):
    stubs = dict(STUBS)
    stubs.pop('jimm/MediaPlayer.java')
    stubs['jimm/Jimm.java'] = '''package jimm;
public class Jimm {
 public static String openedUrl;
 public static int lights; public static javax.microedition.lcdui.Display display=new javax.microedition.lcdui.Display();
 public static class Clock extends java.util.Timer {
  public java.util.Vector tasks=new java.util.Vector(); public boolean fail;
  public Clock(){super(true);}
  public void schedule(java.util.TimerTask task,long delay,long period){if(fail)throw new OutOfMemoryError("timer");tasks.addElement(task);}
 }
 public static Clock clock=new Clock(); public static java.util.Timer getTimerRef(){return clock;}
 public static void wakeBacklight(){lights++;}public static void wakeBacklight(boolean force){lights++;}
}'''
    stubs['jimm/Options.java'] = '''package jimm;
public class Options {
 public static final int OPTION_MEDIA_MEM_KB=123;
 public static int getInt(int n){return 64;}
}'''
    stubs['jimm/comm/Icq.java'] = '''package jimm.comm;
public class Icq {public static void requestAction(Action a)throws jimm.JimmException{}}
'''
    stubs['jimm/comm/Action.java'] = 'package jimm.comm; public abstract class Action {}'
    stubs['jimm/comm/RequestBartAction.java'] = '''package jimm.comm;
public class RequestBartAction extends Action {
 public static final int BART_VIDEO=0x82,BART_VOICE=0x83;
 public interface Listener {void onBart(byte[] b);}
 public interface ProgressListener extends Listener {void onBartProgress(int part,int total);}
 public interface PartSink extends ProgressListener {boolean onBartPart(byte[] b,int off,int len,int part,int total);void onBartDone(boolean ok);}
 public RequestBartAction(String u,int t,byte[] token,Listener listener){}
}'''
    stubs['javax/microedition/lcdui/Display.java'] = '''package javax.microedition.lcdui;
public class Display {
 public static java.util.Vector queued=new java.util.Vector();public static boolean fail;private Displayable current;
 public void setCurrent(Displayable d){current=d;}public Displayable getCurrent(){return current;}
 public void callSerially(Runnable r){if(fail)throw new OutOfMemoryError("UI queue");queued.addElement(r);}
 public static void flush(){while(!queued.isEmpty()){Runnable r=(Runnable)queued.firstElement();queued.removeElementAt(0);r.run();}}
}'''
    stubs['javax/microedition/lcdui/Canvas.java'] = stubs['javax/microedition/lcdui/Canvas.java'].replace(
        'public void repaint(){}', 'public static boolean failRepaint;public int paints;public void repaint(){if(failRepaint){failRepaint=false;throw new OutOfMemoryError("repaint");}paints++;}')
    stubs['javax/microedition/media/Manager.java'] = '''package javax.microedition.media;
import java.io.*;
import java.util.*;
public class Manager {
 public static class Gate {
  public final java.util.concurrent.CountDownLatch entered=new java.util.concurrent.CountDownLatch(1),release=new java.util.concurrent.CountDownLatch(1);
  public void await(){entered.countDown();try{release.await();}catch(Exception e){throw new AssertionError(e);}}
 }
 public static volatile Gate gate;public static volatile int stage;
 public static volatile Thread worker;public static boolean failFile,oom;public static Vector created=new Vector();
 static void step(int s){if(stage==s && gate!=null){Gate g=gate;gate=null;g.await();}}
 public static Player createPlayer(String path)throws IOException {
  worker=Thread.currentThread();step(1);if(failFile)throw new IOException("file rejected");return make();
 }
 public static Player createPlayer(InputStream stream,String mime)throws IOException {worker=Thread.currentThread();return make();}
 public static String[] getSupportedContentTypes(String p){return new String[]{"audio/3gpp","video/3gpp"};}
 public static Fake make(){Fake p=new Fake();created.addElement(p);return p;}
 public static class Fake implements Player {
  public volatile int state=UNREALIZED;public int starts,closes,queries;public long at;public PlayerListener listener;
  public void realize(){step(2);if(oom)throw new OutOfMemoryError("decoder");if(state==CLOSED)throw new IllegalStateException("closed");state=REALIZED;}
  public void prefetch(){step(3);if(state==CLOSED)throw new IllegalStateException("closed");state=PREFETCHED;}
  public void start(){step(4);if(state==CLOSED)throw new IllegalStateException("closed");starts++;state=STARTED;}
  public void stop(){if(state!=CLOSED)state=PREFETCHED;}
  public void close(){closes++;state=CLOSED;}
  public void deallocate(){}public long setMediaTime(long value){at=value;return value;}
  public long getMediaTime(){queries++;return at;}public long getDuration(){return 5000000;}
  public int getState(){return state;}public String getContentType(){return "audio/3gpp";}public void setLoopCount(int n){}
  public void addPlayerListener(PlayerListener p){listener=p;}public void removePlayerListener(PlayerListener p){listener=null;}
  public Control getControl(String name){return null;}public Control[] getControls(){return new Control[0];}
 }
}'''
    stubs['jimm/TempFiles.java'] = '''package jimm;
import java.io.*;
import java.util.*;
import javax.microedition.media.Manager;
final class TempFiles {
 static String lastError="no root";static boolean available=true;
 static Hashtable files=new Hashtable();static volatile Manager.Gate writeGate;static volatile Thread writer;
 interface Files {
  String[] roots()throws IOException;void mkdir(String url)throws IOException;void recreate(String url)throws IOException;
  void remove(String url)throws IOException;boolean canWrite(String url)throws IOException;
  OutputStream out(String url)throws IOException;InputStream in(String url)throws IOException;long size(String url)throws IOException;
 }
 static final Files api=new Files(){
  public String[] roots(){return new String[]{"fake/"};}public void mkdir(String p){}public boolean canWrite(String p){return true;}
  public void recreate(String p){files.put(p,new byte[0]);}public void remove(String p){files.remove(p);}
  public OutputStream out(final String p){return new ByteArrayOutputStream(){
   public void write(byte[] b,int off,int len){writer=Thread.currentThread();Manager.Gate g=writeGate;writeGate=null;if(g!=null)g.await();super.write(b,off,len);files.put(p,toByteArray());}
  };}
  public InputStream in(String p){return new ByteArrayInputStream((byte[])files.get(p));}
  public long size(String p){byte[] b=(byte[])files.get(p);return b==null?0:b.length;}
 };
 static Files api(){return api;}static String apiName(){return "fake";}
 static String writableUrl(String name,boolean root){if(!available)return null;String p="file:///fake/"+name;files.put(p,new byte[0]);return p;}
 static OutputStream out(String p)throws IOException{return api.out(p);}static InputStream in(String p)throws IOException{return api.in(p);}
 static long size(String p){try{return api.size(p);}catch(Exception e){return -1;}}
 static void remove(String p){if(p!=null)files.remove(p);}
}'''
    cp = os.pathsep.join(map(str, [classes, *sorted((work/'wtk/lib').glob('*.jar'))]))
    with tempfile.TemporaryDirectory(prefix='tmm-media-lifecycle-') as temp:
        directory = Path(temp); sources = []
        for name, source in stubs.items():
            path = directory/name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source); sources.append(str(path))
        sources.append(str(ROOT/'tests/java/ClientMediaLifecycleTest.java'))
        subprocess.run([str(work/'jdk/bin/javac'), '-encoding', 'UTF-8', '-cp', cp,
                        '-d', str(directory), *sources], check=True)
        subprocess.run([str(work/'jdk/bin/java'), '-cp', str(directory)+os.pathsep+cp,
                        'jimm.ClientMediaLifecycleTest', 'baseline' if baseline else 'verify'], check=True, timeout=40)


if __name__ == '__main__':
    work = Path(sys.argv[1]).resolve()
    run(work, Path(sys.argv[2]).resolve() if len(sys.argv)>2 else work/'src/build/compile/classes',
        len(sys.argv)>3 and sys.argv[3]=='baseline')
