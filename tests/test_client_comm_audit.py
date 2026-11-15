"""Regression checks of real packet listeners and action-loop failure paths.
Usage: python tests/test_client_comm_audit.py BUILD_WORK [CLASSES] [loop|packets]
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tests.test_client_faults import ui_stubs
from tests.test_client_lifecycle import STUBS


def run(work,classes,only=None):
    loop=dict(STUBS)
    loop['jimm/comm/connections/SOCKETConnection.java']='''package jimm.comm.connections;
public class SOCKETConnection extends Connection {public SOCKETConnection(){}public SOCKETConnection(int n){}public void connect(String h){state=true;}public void sendPacket(jimm.comm.Packet p){}public void forceDisconnect(){state=false;notifyToDisconnect();}}
'''
    loop['jimm/ConnLog.java']='package jimm;public class ConnLog {public static void note(String s){}}'
    socket=dict(STUBS)
    socket['jimm/ConnLog.java']=loop['jimm/ConnLog.java']
    socket['jimm/JimmException.java']='''package jimm;public class JimmException extends Exception {
public static final int ICQ_MAIN=2001,ICQ_BART=2002,ICQ_PEER=2003;public static int errors;private int code;
public JimmException(int c,int e){code=c;}public JimmException(int c,int e,int n){code=c;}public JimmException(int c,int e,boolean b){code=c;}
public int getErrCode(){return code;}public boolean isCritical(){return true;}public boolean isDisplayMsg(){return true;}public String getFullErrCode(){return "error";}
public static javax.microedition.lcdui.Alert handleException(JimmException e){errors++;return null;}}
'''
    cases=[('loop','jimm.comm.CommAuditLoopTest',loop,[]),('socket','CommAuditSocketTest',socket,[])]
    if only != 'loop':cases.append(('packets','jimm.comm.CommAuditPacketTest',ui_stubs(),['RU.lng','langlist.lng']))
    cp=os.pathsep.join(map(str,[classes,*sorted((work/'wtk/lib').glob('*.jar'))]))
    for short,name,stubs,resources in cases:
        if only and only!=short:continue
        with tempfile.TemporaryDirectory(prefix='tmm-comm-audit-') as temp:
            directory=Path(temp);pack=directory/'resources';pack.mkdir()
            for resource in resources:shutil.copy2(work/'src/build/res'/resource,pack/resource)
            sources=[]
            for path,source in stubs.items():
                target=directory/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(source);sources.append(str(target))
            sources.append(str(ROOT/'tests/java'/(name.split('.')[-1]+'.java')))
            subprocess.run([str(work/'jdk/bin/javac'),'-encoding','UTF-8','-cp',cp,'-d',str(directory),*sources],check=True)
            subprocess.run([str(work/'jdk/bin/java'),'-Xbootclasspath/a:'+str(pack),'-cp',str(directory)+os.pathsep+cp,name],check=True,timeout=20)

if __name__=='__main__':
    work=Path(sys.argv[1]).resolve()
    run(work,Path(sys.argv[2]).resolve() if len(sys.argv)>2 else work/'src/build/compile/classes',sys.argv[3] if len(sys.argv)>3 else None)
