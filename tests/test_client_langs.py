"""Build-tool regression: missing translations and selected language labels."""
from pathlib import Path
import os
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def pairs(path):
    data = path.read_bytes()
    count, = struct.unpack_from('>H', data)
    offset = 2
    result = {}
    for _ in range(count):
        row = []
        for _ in range(2):
            size, = struct.unpack_from('>H', data, offset)
            offset += 2
            row.append(data[offset:offset+size].decode('utf-8'))
            offset += size
        result[row[0]] = row[1]
    assert offset == len(data)
    return result


def run(work):
    cp = str(work/'ant/lib/ant.jar')
    with tempfile.TemporaryDirectory(prefix='tmm-langs-') as temp:
        directory = Path(temp)
        source = directory/'src'; source.mkdir()
        languages = directory/'lang'; languages.mkdir()
        output = directory/'out'; output.mkdir()
        (source/'Client.java').write_text('class Client { String label = "fallback"; String title = "title"; }')
        (languages/'EN.lang').write_text('"title" "Title"\n"fallback" "Bento"\n"lang_EN" "English"\n"lang_RU" "Russian"\n')
        (languages/'RU.lang').write_text('"title" "Название"\n"lang_EN" "Английский"\n"lang_RU" "Русский"\n')
        runner = directory/'LangTest.java'
        runner.write_text('''import langs.LangsTask; public class LangTest {
 public static void main(String[] args) { LangsTask task = new LangsTask();
 task.setLanguages("RU"); task.setIdealLang("EN"); task.setInDir(args[0]);
 task.setOutDir(args[1]); task.setSrcDir(args[2]); task.execute();
 }}''')
        subprocess.run([str(work/'jdk/bin/javac'), '-encoding', 'UTF-8', '-cp', cp,
                        '-d', str(directory), str(ROOT/'telemotomax/util/langs/src/langs/LangsTask.java'),
                        str(runner)], check=True)
        subprocess.run([str(work/'jdk/bin/java'), '-cp', str(directory)+os.pathsep+cp,
                        'LangTest', str(languages), str(output), str(source)],
                       check=True, stdout=subprocess.DEVNULL, timeout=15)
        packed = pairs(output/'RU.lng')
        key = next(key for key, value in packed.items() if value == 'Bento')
        client = (source/'Client.java').read_text()
        assert f'"{key}"' in client and '"fallback"' not in client, 'fallback key was not rewritten before packing'
        assert packed['lang_RU'] == 'Русский' and 'lang_EN' not in packed, 'unselected language labels retained'
        actual = pairs(work/'src/build/res/RU.lng')
        assert [key for key in actual if key.startswith('lang_')] == ['lang_RU']
        assert 'WA Bento' in actual.values(), 'real Bento fallback lost'
        assert b'bento_scheme' not in (work/'src/build/compile/classes/jimm/Options.class').read_bytes(), 'real client still uses an untranslated key'
    print('PASS: fallback keys are rewritten before packing; RU includes Bento and only its selected language label')


if __name__ == '__main__':
    run(Path(sys.argv[1]).resolve())
