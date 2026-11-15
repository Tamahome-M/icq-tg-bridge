"""Actual OSCAR login/socket/error handling with deterministic DNS and native I/O.

The retry scheduler is captured here; its real implementation has separate gate tests.
Usage: python tests/test_client_dns_integration.py BUILD_WORK
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_client_faults import ui_stubs
from tests.test_client_startup_dns import STUBS as DNS_STUBS

CONNECTOR = '''package javax.microedition.io;
import java.io.*;
public class Connector {
 public static final int READ_WRITE=3;
 public static String fail,last; public static final java.util.Vector opened=new java.util.Vector();
 public static Connection open(String url,int mode)throws IOException {
  last=url;opened.addElement(url);if(url.equals(fail))throw new IOException("simulated unavailable route");
  return new Socket();
 }
 public static final class Socket implements SocketConnection {
  boolean closed;
  public InputStream openInputStream(){return new InputStream(){
   public int read()throws IOException{synchronized(Socket.this){while(!closed)try{Socket.this.wait();}catch(InterruptedException e){throw new IOException();}return -1;}}
  };}
  public OutputStream openOutputStream(){return new ByteArrayOutputStream();}
  public DataInputStream openDataInputStream(){return new DataInputStream(openInputStream());}
  public DataOutputStream openDataOutputStream(){return new DataOutputStream(openOutputStream());}
  public synchronized void close(){closed=true;notifyAll();}
  public void setSocketOption(byte n,int v){}public int getSocketOption(byte n){return 0;}
  public String getLocalAddress(){return "127.0.0.1";}public int getLocalPort(){return 10;}
  public String getAddress(){return "native.example";}public int getPort(){return 5190;}
 }
}'''


def run(work):
    classes = work / 'src/build/compile/classes'
    cp = os.pathsep.join(map(str, [classes, *sorted((work/'wtk/lib').glob('*.jar'))]))
    stubs = ui_stubs()
    stubs['javax/microedition/io/Connector.java'] = CONNECTOR
    stubs['jimm/comm/connections/DnsResolver.java'] = DNS_STUBS['jimm/comm/connections/DnsResolver.java']
    stubs['jimm/Threads.java'] = '''package jimm;
public class Threads {
 public static final long SLOW_RECONNECT_MS=60000;public static int requested;
 public static void reconnect(){requested++;}public static void reconnect(long ms){requested++;}
 public static void cancelReconnect(){}
 public static void checkReconnect(){}
}'''
    with tempfile.TemporaryDirectory(prefix='tmm-dns-integration-') as temp:
        folder = Path(temp)
        resources = folder/'resources'; resources.mkdir()
        for name in ('RU.lng', 'langlist.lng'):
            shutil.copy2(work/'src/build/res'/name, resources/name)
        sources = []
        for name, source in stubs.items():
            target = folder/name; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source); sources.append(str(target))
        subprocess.run([str(work/'jdk/bin/javac'), '-encoding', 'UTF-8', '-cp', cp,
                        '-d', str(folder), *sources,
                        str(ROOT/'tests/java/StartupDnsIntegrationTest.java')], check=True)
        for mode in ('choose', 'bos', 'auth', 'cancel', 'disabled', 'dns_failure'):
            subprocess.run([str(work/'jdk/bin/java'), '-Xbootclasspath/a:'+str(resources),
                            '-cp', str(folder)+os.pathsep+cp,
                            'jimm.comm.StartupDnsIntegrationTest', mode], check=True, timeout=20)


if __name__ == '__main__':
    run(Path(sys.argv[1]).resolve())
