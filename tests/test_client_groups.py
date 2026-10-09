"""Actual contact tree and presence updates with fake MIDP widgets."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from tests.test_client_performance import make_stubs


def run(work,classes):
    stubs=make_stubs()
    stubs['javax/microedition/lcdui/Image.java']=stubs['javax/microedition/lcdui/Image.java'].replace(
        'public class Image {', 'public class Image { public int getHeight(){return 12;}public int getWidth(){return 12;}')
    stubs['DrawControls/ImageList.java']=stubs['DrawControls/ImageList.java'].replace(
        'elementAt(int i){return null;}', 'elementAt(int i){return new javax.microedition.lcdui.Image();}')
    stubs['javax/microedition/rms/RecordStore.java']=stubs['javax/microedition/rms/RecordStore.java'].replace(
        'public static RecordStore openRecordStore',
        'public static String[] listRecordStores(){String[] keys=new String[stores.size()];int i=0;'
        'for(java.util.Enumeration e=stores.keys();e.hasMoreElements();)keys[i++]=(String)e.nextElement();return keys;}'
        'public static void deleteRecordStore(String name){stores.remove(name);} public static RecordStore openRecordStore')
    cp=os.pathsep.join(str(p) for p in [classes,*sorted((work/'wtk/lib').glob('*.jar'))])
    with tempfile.TemporaryDirectory(prefix='tmm-groups-') as temp:
        directory=Path(temp);resources=directory/'resources';resources.mkdir()
        for name in ['RU.lng','langlist.lng']:shutil.copy2(work/'src/build/res'/name,resources/name)
        sources=[]
        for name,source in stubs.items():
            path=directory/name;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(source);sources.append(str(path))
        sources.append(str(root/'tests/java/ClientGroupsTest.java'))
        subprocess.run([str(work/'jdk/bin/javac'),'-encoding','UTF-8','-cp',cp,'-d',str(directory),*sources],check=True)
        subprocess.run([str(work/'jdk/bin/java'),'-Xbootclasspath/a:'+str(resources),
                        '-cp',str(directory)+os.pathsep+cp,'ClientGroupsTest'],check=True,timeout=25)


if __name__=='__main__':
    work=Path(sys.argv[1]).resolve()
    run(work,Path(sys.argv[2]).resolve() if len(sys.argv)>2 else work/'src/build/compile/classes')
