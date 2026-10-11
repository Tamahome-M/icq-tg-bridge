"""Exercise actual Icq/TimerTasks ping thresholds without waiting real minutes.

Usage: python tests/test_client_pings.py BUILD_WORK [COMPILED_CLASSES]
Socket, settings and error UI are stubbed. The error handler records the
disconnect request and uses the real Icq.disconnect; settings/RMS have their
own coverage in test_client_ui and test_settings_navigation.
"""

from pathlib import Path
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_client_lifecycle import STUBS as BASE


def run(work: Path, classes: Path) -> None:
    stubs = dict(BASE)
    stubs["jimm/Options.java"] = stubs["jimm/Options.java"].replace(
        "public static int pingMissLimit() { return 3; }",
        "public static int limit=3; public static boolean keepalive=true; "
        "public static int pingMissLimit() { return limit; }",
    ).replace("key == 149 || key == 128", "key == 149 || (key == 128 && keepalive)")
    stubs["jimm/ConnLog.java"] = """package jimm;
public class ConnLog {
 public static String last;
 public static void note(String text) { last=text; }
}
"""
    stubs["jimm/JimmException.java"] = """package jimm;
public class JimmException extends Exception {
 public static final int ICQ_MAIN=2001,ICQ_BART=2002,ICQ_PEER=2003;
 public static int errors;
 private int code,type; private boolean critical;
 public JimmException(int c,int ext){code=c;critical=true;}
 public JimmException(int c,int ext,int t){code=c;type=t;critical=t==ICQ_MAIN;}
 public JimmException(int c,int ext,boolean show){code=c;}
 public int getErrCode(){return code;}
 public String getFullErrCode(){return "#"+code;}
 public int getTypeNetwork(){return type;}
 public boolean isCritical(){return critical;}
 public boolean isDisplayMsg(){return true;}
 public static String getErrDesc(int code,int ext){return "error";}
 public static javax.microedition.lcdui.Alert handleException(JimmException error){
  if(error.code!=120 || !error.critical || error.type!=ICQ_MAIN)
   throw new AssertionError("wrong watchdog error");
  errors++; jimm.comm.Icq.disconnect(true); return null;
 }
}
"""
    cp = os.pathsep.join(str(p) for p in [classes, *sorted((work / "wtk/lib").glob("*.jar"))])
    with tempfile.TemporaryDirectory(prefix="tmm-pings-") as directory:
        target = Path(directory)
        sources = []
        for name, source in stubs.items():
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
            sources.append(str(path))
        subprocess.run([str(work / "jdk/bin/javac"), "-encoding", "UTF-8", "-cp", cp,
                        "-d", str(target), *sources, str(ROOT / "tests/java/ClientPingTest.java")], check=True)
        subprocess.run([str(work / "jdk/bin/java"), "-cp", str(target) + os.pathsep + cp,
                        "ClientPingTest"], check=True, timeout=30)


if __name__ == "__main__":
    workspace = Path(sys.argv[1]).resolve()
    run(workspace, Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else workspace / "src/build/compile/classes")
