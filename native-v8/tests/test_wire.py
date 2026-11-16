"""Bounded real OSCAR codecs, under ASan/UBSan on the host."""
from pathlib import Path
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='tmm-native-wire-') as folder:
    binary = Path(folder)/'wire-test'
    subprocess.run(['g++','-std=c++98','-Wall','-Wextra','-fno-rtti','-fsanitize=address,undefined','-fno-omit-frame-pointer',
                    '-I',str(ROOT/'native-v8/src'),str(ROOT/'native-v8/tests/wire_test.cpp'),str(ROOT/'native-v8/src/oscar.cpp'),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=25)
