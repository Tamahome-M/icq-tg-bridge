"""Real DNS preferences and RMS migration; only MIDP widgets/storage are fake.

Usage: python tests/test_startup_dns_settings.py BUILD_WORK [CLASSES]
Navigation/save/cancel is also covered by test_settings_navigation.py.
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
    stubs = dict(STUBS)
    stubs['javax/microedition/lcdui/Form.java'] = stubs['javax/microedition/lcdui/Form.java'].replace(
        'public void setItemStateListener',
        'public void deleteAll(){items.removeAllElements();} public void delete(int i){items.removeElementAt(i);}'
        ' public int size(){return items.size();} public void setItemStateListener')
    cp = os.pathsep.join(map(str, [classes, *sorted((work/'wtk/lib').glob('*.jar'))]))
    with tempfile.TemporaryDirectory(prefix='tmm-dns-settings-') as temp:
        directory = Path(temp)
        sources = []
        for name, source in stubs.items():
            path = directory/name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source); sources.append(str(path))
        sources.append(str(ROOT/'tests/java/StartupDnsSettingsTest.java'))
        subprocess.run([str(work/'jdk/bin/javac'), '-encoding', 'UTF-8', '-cp', cp,
                        '-d', str(directory), *sources], check=True)
        subprocess.run([str(work/'jdk/bin/java'), '-cp', str(directory)+os.pathsep+cp,
                        'StartupDnsSettingsTest'], check=True, timeout=25)
    permission = 'javax.microedition.io.Connector.socket'
    descriptors = list((work/'out').glob('*.jad'))
    assert descriptors, 'built JAD missing'
    for descriptor in descriptors:
        attrs = dict(line.split(': ', 1) for line in descriptor.read_text().splitlines() if ': ' in line)
        assert permission in attrs.get('MIDlet-Permissions-Opt', '').split(','), 'optional TCP permission missing'
        assert 'javax.microedition.io.Connector.datagram' not in attrs.get('MIDlet-Permissions-Opt', '').split(','), 'unused UDP permission retained'
        assert permission not in attrs.get('MIDlet-Permissions', '').split(','), 'TCP became required for installation'
    print('PASS: DNS uses existing optional client TCP permission in built JAD')


if __name__ == '__main__':
    work = Path(sys.argv[1]).resolve()
    run(work, Path(sys.argv[2]).resolve() if len(sys.argv)>2 else work/'src/build/compile/classes')
