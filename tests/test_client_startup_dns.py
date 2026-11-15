"""Startup DNS cache/pinning policy with deterministic DNS and connection fixtures.

Compiles the production policy directly; no phone/network or full build needed.
Usage: python tests/test_client_startup_dns.py /tmp/tmm-v8-build
"""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
STUBS = {
    'jimm/Options.java': '''package jimm;
public class Options {
 public static final int OPTION_STARTUP_DNS=177, OPTION_DNS_SERVER=38, OPTION_SRV_HOST=2;
 public static boolean enabled=true; public static String host="bridge.example,legacy.example",dns="1.1.1.1";
 public static boolean getBoolean(int key){return enabled;}
 public static String getString(int key){return key==OPTION_DNS_SERVER?dns:host;}
}''',
    'jimm/ConnLog.java': 'package jimm; public class ConnLog {public static void note(String s){}}',
    'jimm/JimmException.java': '''package jimm; public class JimmException extends Exception {
 public int code;public JimmException(int c,int e){code=c;}public JimmException(int c,int e,int n){code=c;}public JimmException(int c,int e,boolean b){code=c;}
}''',
    'jimm/comm/connections/Connection.java': '''package jimm.comm.connections;
public class Connection {int typeNetwork=2001;String startupDnsAddress;boolean startupDnsFailed;volatile boolean closed; boolean getInputCloseFlag(){return closed;}}
''',
    'jimm/comm/connections/DnsResolver.java': '''package jimm.comm.connections;
public class DnsResolver {
 public static volatile int calls,cancels;public static volatile boolean blocked,fail;public static String requestedHost,requestedDns;
 public int[] lookup(String h,String d)throws java.io.IOException{calls++;requestedHost=h;requestedDns=d;
  while(blocked && cancels==0)try{Thread.sleep(5);}catch(Exception e){}
  if(fail || cancels>0)throw new java.io.IOException();return new int[]{0x01020304,0x05060708};}
 public void cancel(){cancels++;}
 public static boolean isIPv4(String s){return "9.8.7.6".equals(s);}
 public static String ipv4(int i){return ((i>>>24)&255)+"."+((i>>>16)&255)+"."+((i>>>8)&255)+"."+(i&255);}
}''',
}


def run(work):
    with tempfile.TemporaryDirectory(prefix='tmm-startup-dns-') as temp:
        directory = Path(temp)
        sources = []
        for path, source in STUBS.items():
            target = directory / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source)
            sources.append(str(target))
        sources += [str(ROOT/'telemotomax/src/jimm/comm/connections/StartupDns.java'),
                    str(ROOT/'tests/java/StartupDnsTest.java')]
        subprocess.run([str(work/'jdk/bin/javac'), '-encoding', 'UTF-8', '-d', str(directory), *sources], check=True)
        for case in ('disabled', 'pin', 'failure', 'cancel', 'deadline', 'literal', 'snapshot'):
            subprocess.run([str(work/'jdk/bin/java'), '-cp', str(directory),
                            'jimm.comm.connections.StartupDnsTest', case], check=True, timeout=10)
    run_retry(work)


def run_retry(work):
    stubs = {
        'jimm/Options.java': 'package jimm; public class Options {public static final int OPTION_RECONNECT=149; public static boolean auto; public static boolean getBoolean(int k){return auto;}}',
        'jimm/ConnLog.java': STUBS['jimm/ConnLog.java'],
        'jimm/ContactList.java': 'package jimm; public class ContactList {public static void beforeConnect(){}}',
        'jimm/comm/Icq.java': '''package jimm.comm; public class Icq {
 public static volatile int calls; public static boolean disconnected,connected,failImmediately=true;
 public static boolean isDisconnected(){return disconnected;}public static boolean isConnected(){return connected;}public static boolean isConnecting(){return false;}
 public static void connect(boolean b){calls++;if(calls==1&&failImmediately)jimm.Threads.reconnect(0);else jimm.comm.connections.StartupDns.next=false;}
}''',
        'jimm/comm/connections/StartupDns.java': 'package jimm.comm.connections; public class StartupDns {public static boolean next=true; public static boolean needsNextAddress(){return next;}}',
    }
    with tempfile.TemporaryDirectory(prefix='tmm-startup-dns-retry-') as temp:
        directory = Path(temp)
        sources = []
        for path, source in stubs.items():
            target = directory/path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source)
            sources.append(str(target))
        sources += [str(ROOT/'telemotomax/src/jimm/Threads.java'), str(ROOT/'tests/java/StartupDnsRetryTest.java')]
        subprocess.run([str(work/'jdk/bin/javac'), '-encoding', 'UTF-8', '-d', str(directory), *sources], check=True)
        for case in ('next', 'cancel', 'fatal', 'connected', 'regular', 'auto', 'auto_cancel', 'auto_fatal',
                     'sleeping_fatal', 'sleeping_cancel', 'sleeping_manual', 'replacement'):
            subprocess.run([str(work/'jdk/bin/java'), '-cp', str(directory), 'StartupDnsRetryTest', case], check=True, timeout=10)


if __name__ == '__main__':
    run(Path(sys.argv[1]).resolve())
