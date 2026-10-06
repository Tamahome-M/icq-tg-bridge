"""Run client lifecycle regressions against a build.sh workspace (requires JDK 8).

Usage: python3 tests/test_client_lifecycle.py /tmp/telemotomax-build
An optional second argument selects another compiled client for regression checks.
The client classes are real; only UI, settings and the MIDlet timer are stubbed.
"""

from pathlib import Path
import os
import subprocess
import sys
import tempfile


STUBS = {
    "jimm/Jimm.java": """
package jimm;
public class Jimm {
    public static final Jimm jimm = new Jimm();
    private static java.util.Timer timer = new java.util.Timer(true);
    public static java.util.Timer getTimerRef() { return timer; }
    public void cancelTimer() { timer.cancel(); timer = new java.util.Timer(true); }
}
""",
    "jimm/Options.java": """
package jimm;
public class Options {
    public static int getInt(int key) { return 0; }
    public static long getLong(int key) { return 0; }
    public static String getString(int key) { return "3600"; }
    public static boolean getBoolean(int key) { return key == 149 || key == 128; }
}
""",
    "jimm/MainThread.java": """
package jimm;
public class MainThread {
    public static void resetContactsOffline() { }
}
""",
    "jimm/SplashCanvas.java": """
package jimm;
public class SplashCanvas {
    public static void setLastErrCode(String text) { }
}
""",
    "jimm/util/ResourceBundle.java": """
package jimm.util;
public class ResourceBundle {
    public static String getString(String key) { return key; }
    public static String remove(String key) { return key; }
}
""",
}


def run(work: Path, client: Path | None = None) -> None:
    root = Path(__file__).resolve().parents[1]
    classes = client or work / "src/build/compile/classes"
    api = sorted((work / "wtk/lib").glob("*.jar"))
    classpath = os.pathsep.join(str(path) for path in [classes, *api])
    with tempfile.TemporaryDirectory(prefix="tmm-lifecycle-") as directory:
        temporary = Path(directory)
        sources = []
        for name, source in STUBS.items():
            path = temporary / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
            sources.append(str(path))
        subprocess.run(
            [str(work / "jdk/bin/javac"), "-encoding", "UTF-8", "-cp", classpath,
             "-d", str(temporary), *sources,
             str(root / "tests/java/ClientLifecycleTest.java")],
            check=True,
        )
        subprocess.run(
            [str(work / "jdk/bin/java"), "-cp",
             str(temporary) + os.pathsep + classpath, "ClientLifecycleTest"],
            check=True, timeout=30,
        )


if __name__ == "__main__":
    run(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else None)
