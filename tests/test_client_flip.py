"""Actual cover adapter, clock and UI keylock; optional vendor API is simulated.

Usage: python tests/test_client_flip.py BUILD_WORK [CLASSES]
Both API transitions and a JVM without any Vodafone class are exercised.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import struct
import zipfile

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from tests.test_client_lock import make_lock_stubs


VENDOR_STUB = '''package com.vodafone.system;
public class DeviceControl {
 public static int state,calls,instances;public static boolean fail;
 public static DeviceControl getDefaultDeviceControl(){instances++;return new DeviceControl();}
 public int getDeviceState(int selector){
  if(selector!=7)throw new AssertionError("wrong physical selector");
  calls++;if(fail)throw new RuntimeException("unavailable");return state;
 }
}'''


def packaged_adapter(work):
    jar = work/'out/TeleMotoMax.jar'
    with zipfile.ZipFile(jar) as archive:
        classes = {name: archive.read(name) for name in archive.namelist() if name.endswith('.class')}
    assert 'jimm/VodafoneFlipState.class' in classes, 'reflection adapter stripped/renamed'
    assert not any(name.startswith('com/vodafone/') for name in classes), 'vendor stubs packaged'
    assert all(struct.unpack('>HH',data[4:8]) == (3,45) for data in classes.values()), 'wrong CLDC class version'
    assert [name for name,data in classes.items() if b'com/vodafone/system/DeviceControl' in data] == ['jimm/VodafoneFlipState.class'], 'optimizer moved optional vendor dependency outside adapter'
    checker = '''import java.lang.reflect.*;
public class PackagedFlipCheck {
 public static void main(String[] args)throws Exception {
  if(args[0].equals("absent")){
   try{Class.forName("jimm.VodafoneFlipState").newInstance();throw new AssertionError("API present");}
   catch(NoClassDefFoundError expected){System.out.println("PASS: packaged optional adapter reports missing native API");}return;
  }
  Class c=Class.forName("jimm.VodafoneFlipState");Object reader=c.newInstance();Method get=null;
  for(Method m:c.getDeclaredMethods())if(!Modifier.isStatic(m.getModifiers()) && m.getReturnType()==Integer.TYPE && m.getParameterTypes().length==0)get=m;
  if(get==null)throw new AssertionError("optimized getter lost");get.setAccessible(true);
  Class api=Class.forName("com.vodafone.system.DeviceControl");Field state=api.getField("state");
  for(int i=0;i<2;i++){state.setInt(null,i);if(((Integer)get.invoke(reader)).intValue()!=i)throw new AssertionError("bad packaged getter");}
  if(api.getField("instances").getInt(null)!=1)throw new AssertionError("uncached device");
  System.out.println("PASS: real obfuscated JAR loads adapter by name, keeps constructor and invokes physical selector with cached device");
 }
}'''
    libs = [p for p in sorted((work/'wtk/lib').glob('*.jar')) if p.name != 'tmm-vendor-stubs.jar']
    for mode in ('native','absent'):
        with tempfile.TemporaryDirectory(prefix='tmm-packaged-flip-') as temp:
            directory = Path(temp)
            source = directory/'PackagedFlipCheck.java';source.write_text(checker)
            sources = [str(source)]
            if mode == 'native':
                path=directory/'com/vodafone/system/DeviceControl.java';path.parent.mkdir(parents=True)
                path.write_text(VENDOR_STUB);sources.append(str(path))
            subprocess.run([str(work/'jdk/bin/javac'),'-d',str(directory),*sources],check=True)
            cp=os.pathsep.join(str(p) for p in [directory,jar,*libs])
            subprocess.run([str(work/'jdk/bin/java'),'-cp',cp,'PackagedFlipCheck',mode],check=True,timeout=15)


def run(work, classes):
    libs = [p for p in sorted((work/'wtk/lib').glob('*.jar')) if p.name != 'tmm-vendor-stubs.jar']
    cp = os.pathsep.join(str(p) for p in [classes, *libs])
    for mode in ('native', 'absent'):
        stubs = make_lock_stubs()
        if mode == 'native':
            stubs['com/vodafone/system/DeviceControl.java'] = VENDOR_STUB
        with tempfile.TemporaryDirectory(prefix='tmm-flip-'+mode+'-') as temp:
            directory = Path(temp)
            resources = directory/'resources'; resources.mkdir()
            for name in ['RU.lng', 'langlist.lng']:
                shutil.copy2(work/'src/build/res'/name, resources/name)
            sources = []
            for name, source in stubs.items():
                path = directory/name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source); sources.append(str(path))
            sources.extend(str(root/'tests/java'/name) for name in ['ClientLockTest.java', 'ClientFlipTest.java'])
            subprocess.run([str(work/'jdk/bin/javac'), '-encoding', 'UTF-8', '-cp', cp,
                            '-d', str(directory), *sources], check=True)
            subprocess.run([str(work/'jdk/bin/java'), '-Xbootclasspath/a:'+str(resources),
                            '-cp', str(directory)+os.pathsep+cp, 'ClientFlipTest', mode],
                           check=True, timeout=25)
    packaged_adapter(work)


if __name__ == '__main__':
    work = Path(sys.argv[1]).resolve()
    run(work, Path(sys.argv[2]).resolve() if len(sys.argv)>2 else work/'src/build/compile/classes')
