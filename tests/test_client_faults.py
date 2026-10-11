"""Fault injection on real client classes: UI, socket, deadlines and media.

Usage: python tests/test_client_faults.py BUILD_WORK [CLASSES]
Only MIDP/native APIs are stubbed; no real network or phone is required.
"""
from pathlib import Path
import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_client_performance import make_stubs
from tests.test_client_lifecycle import STUBS as LIFECYCLE


def ui_stubs(audio=False):
    stubs = make_stubs()
    stubs.pop('jimm/ChatTextList.java')
    stubs['javax/microedition/lcdui/Display.java'] = stubs['javax/microedition/lcdui/Display.java'].replace(
        'queued.addElement(r);', 'if(fail)throw new OutOfMemoryError("UI scheduling");queued.addElement(r);').replace(
        'public static java.util.Vector queued=', 'public static boolean fail;public static java.util.Vector queued=')
    stubs['javax/microedition/lcdui/Font.java'] = stubs['javax/microedition/lcdui/Font.java'].replace(
        'public static long measured;', 'public static Runnable beforeMeasure;public static long measured;').replace(
        'int width=0;measured+=length;', 'if(beforeMeasure!=null){Runnable once=beforeMeasure;beforeMeasure=null;once.run();}int width=0;measured+=length;')
    stubs['javax/microedition/lcdui/Form.java'] = stubs['javax/microedition/lcdui/Form.java'].replace(
        'public void setItemStateListener', 'public void deleteAll(){items.removeAllElements();}public int size(){return items.size();}public void setItemStateListener')
    stubs['javax/microedition/lcdui/Canvas.java'] = stubs['javax/microedition/lcdui/Canvas.java'].replace(
        'public void repaint(){}', 'public void repaint(){}public void repaint(int x,int y,int w,int h){}')
    stubs['javax/microedition/lcdui/Image.java'] = stubs['javax/microedition/lcdui/Image.java'].replace(
        'public class Image {', 'public class Image {public int getWidth(){return 12;}public int getHeight(){return 12;}')
    stubs['DrawControls/ImageList.java'] = stubs['DrawControls/ImageList.java'].replace(
        'elementAt(int i){return null;}', 'elementAt(int i){return new javax.microedition.lcdui.Image();}')
    stubs['javax/microedition/rms/RecordStore.java'] = stubs['javax/microedition/rms/RecordStore.java'].replace(
        'public static RecordStore openRecordStore', 'public static String[] listRecordStores(){return new String[0];}public static void deleteRecordStore(String n){stores.remove(n);}public static RecordStore openRecordStore')
    if audio:
        # Use the same functional MMAPI fixture as notification routing tests.
        for node in ast.walk(ast.parse((ROOT/'tests/test_client_notifications.py').read_text())):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                for target in node.targets:
                    if isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant):
                        if target.slice.value == 'javax/microedition/media/Manager.java':
                            manager = node.value.value
        stubs['javax/microedition/media/Manager.java'] = manager.replace(
            'public static Vector started=', 'public static boolean failCreate;public static int attempts;public static Vector started=').replace(
            'if(in==null)', 'attempts++;if(failCreate)throw new OutOfMemoryError("native audio");if(in==null)')
        stubs['javax/microedition/lcdui/Image.java'] = stubs['javax/microedition/lcdui/Image.java'].replace(
            'public class Image {', '''public class Image {
public static final java.util.concurrent.CountDownLatch entered=new java.util.concurrent.CountDownLatch(1),
 resume=new java.util.concurrent.CountDownLatch(1),avatarEntered=new java.util.concurrent.CountDownLatch(1);
public static int active,maxActive,calls;
public static Image createImage(byte[] b,int off,int len){
 boolean first;synchronized(Image.class){first=++calls==1;active++;maxActive=Math.max(maxActive,active);}
 if(first){entered.countDown();try{resume.await(3,java.util.concurrent.TimeUnit.SECONDS);}catch(Exception e){throw new AssertionError(e);}}
 else avatarEntered.countDown();
 synchronized(Image.class){active--;}return new Image();
}
''')
    return stubs


def run(work, classes):
    cp = os.pathsep.join(map(str, [classes, *sorted((work/'wtk/lib').glob('*.jar'))]))
    loop = dict(LIFECYCLE)
    loop['jimm/comm/connections/SOCKETConnection.java'] = '''package jimm.comm.connections;
public class SOCKETConnection extends Connection {
 public static int opened;public static final java.util.Vector packets=new java.util.Vector();
 public static final java.util.concurrent.CountDownLatch oldEntered=new java.util.concurrent.CountDownLatch(1),oldResume=new java.util.concurrent.CountDownLatch(1);
 public SOCKETConnection(){}public SOCKETConnection(int n){}
 public void connect(String host){opened++;if(host.equals("old")){oldEntered.countDown();try{oldResume.await(3,java.util.concurrent.TimeUnit.SECONDS);}catch(Exception e){throw new AssertionError(e);}}state=true;}
 public void sendPacket(jimm.comm.Packet packet){packets.addElement(packet);}
 public void forceDisconnect(){state=false;notifyToDisconnect();}
}'''
    loop['jimm/ConnLog.java'] = 'package jimm;public class ConnLog{public static void note(String s){}}'
    socket = dict(LIFECYCLE)
    socket['jimm/JimmException.java'] = '''package jimm;public class JimmException extends Exception {
public static final int ICQ_MAIN=2001,ICQ_BART=2002,ICQ_PEER=2003;public static int errors;private int code;
public JimmException(int c,int e){code=c;}public JimmException(int c,int e,int n){code=c;}public JimmException(int c,int e,boolean b){code=c;}
public int getErrCode(){return code;}public boolean isCritical(){return true;}public boolean isDisplayMsg(){return true;}public String getFullErrCode(){return "error";}
public static javax.microedition.lcdui.Alert handleException(JimmException e){errors++;return null;}}
'''
    socket['jimm/ConnLog.java'] = loop['jimm/ConnLog.java']
    socket['javax/microedition/io/Connector.java'] = '''package javax.microedition.io;
import java.io.*;
public class Connector {
 public static final int READ=1,WRITE=2,READ_WRITE=3;
 public static final java.util.concurrent.CountDownLatch entered=new java.util.concurrent.CountDownLatch(1),resume=new java.util.concurrent.CountDownLatch(1);
 public static volatile boolean closed;
 public static Connection open(String url,int mode)throws IOException{
  entered.countDown();try{resume.await(3,java.util.concurrent.TimeUnit.SECONDS);}catch(Exception e){throw new IOException();}
  return new SocketConnection(){
   public void close(){closed=true;}
   public InputStream openInputStream(){return new ByteArrayInputStream(new byte[0]);}public OutputStream openOutputStream(){return new ByteArrayOutputStream();}
   public DataInputStream openDataInputStream(){return new DataInputStream(openInputStream());}public DataOutputStream openDataOutputStream(){return new DataOutputStream(openOutputStream());}
   public void setSocketOption(byte n,int v){}public int getSocketOption(byte n){return 0;}
   public String getLocalAddress(){return "local";}public int getLocalPort(){return 0;}public String getAddress(){return "host";}public int getPort(){return 5190;}
  };
 }
}'''
    cases = [
        ('jimm.FaultUiTest', ui_stubs(), ['RU.lng','langlist.lng']),
        ('jimm.FaultMediaTest', ui_stubs(True), ['RU.lng','langlist.lng','message.mp3']),
        ('FaultSocketTest', socket, []),
        ('FaultLoopTest', loop, []),
        ('jimm.comm.FaultBartTest', loop, []),
    ]
    if (classes/'jimm/FileDownloader.class').exists():
        files = ui_stubs()
        files['javax/microedition/io/Connector.java'] = '''package javax.microedition.io;
public class Connector {
 public static final int READ=1,WRITE=2,READ_WRITE=3;
 public static Connection open(String url,int mode)throws java.io.IOException{return jimm.NativeFiles.open(url);}
}'''
        files['javax/microedition/io/file/FileSystemRegistry.java'] = '''package javax.microedition.io.file;
public class FileSystemRegistry {public static java.util.Enumeration listRoots(){java.util.Vector r=new java.util.Vector();r.addElement("c/");return r.elements();}}
'''
        files['jimm/NativeFiles.java'] = '''package jimm;
import java.io.*;import java.lang.reflect.*;import java.util.*;import java.util.concurrent.*;
public class NativeFiles {
 public static Hashtable files=new Hashtable();public static volatile Gate gate;
 public static class Gate {public final CountDownLatch entered=new CountDownLatch(1),resume=new CountDownLatch(1);}
 public static javax.microedition.io.Connection open(final String initial){
  InvocationHandler handler=new InvocationHandler(){String path=initial;
   public Object invoke(Object proxy,Method method,Object[] args)throws Throwable{
    String name=method.getName();
    if(name.equals("exists"))return Boolean.valueOf(files.containsKey(path));
    if(name.equals("create")||name.equals("mkdir")){if(files.containsKey(path))throw new IOException("exists");files.put(path,new byte[0]);return null;}
    if(name.equals("delete")){files.remove(path);return null;}
    if(name.equals("rename")){String next=path.substring(0,path.lastIndexOf('/')+1)+(String)args[0];if(files.containsKey(next))throw new IOException("exists");files.put(next,files.remove(path));path=next;return null;}
    if(name.equals("fileSize")){byte[] bytes=(byte[])files.get(path);return Long.valueOf(bytes==null?0:bytes.length);}
    if(name.equals("openOutputStream")){
     final String target=path;final Gate pause=gate;gate=null;
     return new ByteArrayOutputStream(){boolean waited;
      public void write(byte[] b,int off,int len){
       if(pause!=null&&!waited){waited=true;pause.entered.countDown();try{pause.resume.await(3,TimeUnit.SECONDS);}catch(Exception e){throw new AssertionError(e);}}
       super.write(b,off,len);files.put(target,toByteArray());
      }
     };
    }
    if(name.equals("openInputStream"))return new ByteArrayInputStream((byte[])files.get(path));
    if(method.getReturnType()==Boolean.TYPE)return Boolean.FALSE;
    if(method.getReturnType()==Integer.TYPE)return Integer.valueOf(0);
    if(method.getReturnType()==Long.TYPE)return Long.valueOf(0);
    return null;
   }
  };
  return (javax.microedition.io.Connection)Proxy.newProxyInstance(NativeFiles.class.getClassLoader(),new Class[]{javax.microedition.io.file.FileConnection.class},handler);
 }
}'''
        cases.append(('jimm.FaultDownloadTest', files, ['RU.lng','langlist.lng']))
    for name, stubs, resources in cases:
        with tempfile.TemporaryDirectory(prefix='tmm-faults-') as temp:
            directory = Path(temp)
            pack = directory/'resources'; pack.mkdir()
            for resource in resources:
                shutil.copy2(work/'src/build/res'/resource, pack/resource)
            sources = []
            for path, source in stubs.items():
                target = directory/path; target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source); sources.append(str(target))
            sources.append(str(ROOT/'tests/java'/(name.split('.')[-1]+'.java')))
            subprocess.run([str(work/'jdk/bin/javac'), '-encoding','UTF-8','-cp',cp,
                            '-d',str(directory),*sources], check=True)
            args = []
            if name == 'jimm.FaultMediaTest':
                # Language preparation rewrites literal resource keys in classes.
                splash = (work/'src/build/init/src/jimm/SplashCanvas.java').read_text()
                args.append(re.search(r'cancelByKey = canCancel && "([^"]+)"', splash)[1])
            subprocess.run([str(work/'jdk/bin/java'),'-XX:-DoEscapeAnalysis',
                            '-Xbootclasspath/a:'+str(pack),'-cp',str(directory)+os.pathsep+cp,name,*args],
                           check=True, timeout=25)


if __name__ == '__main__':
    workspace = Path(sys.argv[1]).resolve()
    run(workspace, Path(sys.argv[2]).resolve() if len(sys.argv)>2 else workspace/'src/build/compile/classes')
