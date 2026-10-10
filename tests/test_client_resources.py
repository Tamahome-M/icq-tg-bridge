"""Real CLDC transport/BART and zero-copy media buffer, with desktop allocation meter.

The JCE oracle and MXBean are test-only; neither is included in the phone JAR.
Usage: python tests/test_client_resources.py BUILD_WORK [COMPILED_CLASSES]
"""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_client_ui import STUBS


def run(work, classes):
    cp = os.pathsep.join(map(str, [classes, *sorted((work / "wtk/lib").glob("*.jar"))]))
    with tempfile.TemporaryDirectory(prefix="tmm-resource-java-") as temp:
        directory = Path(temp)
        sources = []
        stubs = dict(STUBS)
        stubs.pop("jimm/MediaPlayer.java")
        for name, source in stubs.items():
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
            sources.append(str(path))
        sources.append(str(ROOT / "tests/java/ClientResourceTest.java"))
        subprocess.run([str(work / "jdk/bin/javac"), "-encoding", "UTF-8", "-cp", cp,
                        "-d", str(directory), *sources], check=True)
        subprocess.run([str(work / "jdk/bin/java"), "-XX:-DoEscapeAnalysis", "-cp",
                        str(directory) + os.pathsep + cp, "jimm.ClientResourceTest"],
                       check=True, timeout=30)


if __name__ == "__main__":
    work = Path(sys.argv[1]).resolve()
    run(work, Path(sys.argv[2]).resolve() if len(sys.argv) > 2
        else work / "src/build/compile/classes")
