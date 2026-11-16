"""Compile DNS against CLDC/MIDP, then test the real class with a fake TCP transport."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run(work):
    jars = [work / "wtk/lib/cldcapi11.jar", work / "wtk/lib/midpapi20.jar"]
    cp = os.pathsep.join(map(str, jars))
    source = ROOT / "telemotomax/src/jimm/comm/connections/DnsResolver.java"
    with tempfile.TemporaryDirectory(prefix="tmm-dns-") as folder:
        folder = Path(folder)
        classes = folder / "classes"
        classes.mkdir()
        subprocess.run([str(work / "jdk/bin/javac"), "-encoding", "UTF-8", "-source", "1.3",
                        "-target", "1.1", "-Xlint:-options", "-bootclasspath", cp,
                        "-d", str(classes), str(source)], check=True)
        raw = (classes / "jimm/comm/connections/DnsResolver.class").read_bytes()
        assert raw[:8] == b"\xca\xfe\xba\xbe\x00\x03\x00\x2d", "CLDC 45.3 class version"
        connector = folder / "javax/microedition/io/Connector.java"
        connector.parent.mkdir(parents=True)
        connector.write_text('''package javax.microedition.io;
import java.io.IOException;
public final class Connector {
 public static final int READ_WRITE=3;
 public interface Factory { Connection open(String url,int mode,boolean timeouts)throws IOException; }
 public static Factory factory;
 public static Connection open(String url,int mode,boolean timeouts)throws IOException {
  if(factory==null)throw new AssertionError("Unexpected network");
  return factory.open(url,mode,timeouts);
 }
}
''')
        runtime_cp = os.pathsep.join([str(classes), cp])
        subprocess.run([str(work / "jdk/bin/javac"), "-encoding", "UTF-8", "-cp", runtime_cp,
                        "-d", str(classes), str(connector), str(ROOT / "tests/java/DnsResolverTest.java")], check=True)
        subprocess.run([str(work / "jdk/bin/java"), "-cp", runtime_cp, "DnsResolverTest"],
                       check=True, timeout=35)


if __name__ == "__main__":
    run(Path(sys.argv[1]).resolve())
