"""Regression scenarios from the 1.15 audit, using real client classes.

MIDP and native microphone/thread allocation are injected; no phone is required.
Usage: python tests/test_client_audit_fixes.py BUILD_WORK [CLASSES]
"""
from pathlib import Path
import sys, os, subprocess, shutil, ast
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tests.test_client_faults import ui_stubs
def run(WORK, CLASSES):
    import tempfile
    temp=tempfile.TemporaryDirectory(prefix='tmm-audit-fixes-')
    OUT=Path(temp.name)
    s=ui_stubs()
    s['jimm/Jimm.java']=s['jimm/Jimm.java'].replace('public static void setBkltOn', 'public static void wakeBacklight(){}public static void setBkltOn')
    s['javax/microedition/lcdui/TextBox.java']="""package javax.microedition.lcdui;
    public class TextBox extends Displayable {
     private String text;private int max;public int caret;
     public TextBox(String t,String v,int m,int c){max=m;setString(v);}
     public void setTitle(String t){}public void setConstraints(int c){}
     public String getString(){return text;}public int size(){return text.length();}
     public void setString(String v){text=v==null?\"\":v;caret=text.length();}
     public int getMaxSize(){return max;}public int getCaretPosition(){return caret;}
     public void insert(String v,int at){text=text.substring(0,at)+v+text.substring(at);}
    }"""
    s['jimm/JimmException.java']="""package jimm;
    public class JimmException extends Exception {
     public static final int ICQ_MAIN=2001,ICQ_BART=2002,ICQ_PEER=2003;public static int errors;
     public JimmException(int a,int b){super(\"injected error\");}public JimmException(int a,int b,int c){this(a,b);}public JimmException(int a,int b,boolean c){this(a,b);}
     public boolean isCritical(){return false;}public int getErrCode(){return 140;}
     public static javax.microedition.lcdui.Alert handleException(JimmException e){errors++;return null;}
    }"""
    for n in ast.walk(ast.parse((ROOT/'tests/test_client_media_lifecycle.py').read_text())):
     if isinstance(n,ast.Assign) and isinstance(n.value,ast.Constant):
      for target in n.targets:
       if isinstance(target,ast.Subscript) and isinstance(target.slice,ast.Constant) and target.slice.value=='javax/microedition/media/Manager.java':
        s['javax/microedition/media/Manager.java']=n.value.value
    manager=s['javax/microedition/media/Manager.java']
    manager=manager.replace('public static volatile Gate gate;', 'public static int setupFailure;public static boolean capture;public static byte[] recorded;public static int commits;public static volatile Gate gate;')
    manager=manager.replace('starts++;state=STARTED;', 'if(setupFailure==3)throw new OutOfMemoryError("start");starts++;state=STARTED;')
    manager=manager.replace('public Control getControl(String name){return null;}', 'public Control getControl(String name){step(5);return capture?new Recorder():null;}')
    manager=manager.replace(' public static Fake make()', """ public static class Recorder implements javax.microedition.media.control.RecordControl {
      private OutputStream out;
      public void setRecordStream(OutputStream stream){if(setupFailure==2)throw new OutOfMemoryError("record stream");out=stream;}
      public void setRecordLocation(String p){}public String getContentType(){return "audio/amr";}
      public void startRecord(){step(7);if(setupFailure==4)throw new OutOfMemoryError("start record");}
      public void stopRecord(){}public int setRecordSizeLimit(int n){return n;}public void reset(){}
      public void commit()throws IOException {commits++;step(8);if(recorded!=null)out.write(recorded);}
     }
     public static Fake make()""")
    s['javax/microedition/media/Manager.java']=manager
    cp=os.pathsep.join(map(str,[CLASSES,*sorted((WORK/'wtk/lib').glob('*.jar'))]))
    sources=[]
    for name,source in s.items():
     path=OUT/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(source);sources.append(str(path))
    resources=OUT/'resources';resources.mkdir(exist_ok=True)
    for name in ['RU.lng','langlist.lng']:shutil.copy2(WORK/'src/build/res'/name,resources/name)
    sources.append(str(ROOT/'tests/java/ClientAuditFixesTest.java'))
    from bridge.oscar import blocks
    (OUT/'search.bin').write_bytes(blocks.search_result(1000001, 'Чат Ceph', '', '', '', last_one=True))
    subprocess.run([str(WORK/'jdk/bin/javac'),'-encoding','UTF-8','-cp',cp,'-d',str(OUT),*sources],check=True)
    subprocess.run([str(WORK/'jdk/bin/java'),'-Xbootclasspath/a:'+str(resources),'-cp',str(OUT)+os.pathsep+cp,'jimm.ClientAuditFixesTest',str(OUT/'search.bin')],check=True,timeout=40)

    temp.cleanup()


if __name__ == '__main__':
    work = Path(sys.argv[1]).resolve()
    run(work, Path(sys.argv[2]).resolve() if len(sys.argv)>2 else work/'src/build/compile/classes')
