"""Real notification settings, RMS migration and player routing with fake MIDP audio.

Usage: python tests/test_client_notifications.py BUILD_WORK [CLASSES]
The fake player consumes the actual packaged MP3 bytes. Only MIDP playback/UI
and scheduling are stubbed; Options, OptionsForm, ContactList and Util are real.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from tests.test_client_ui import STUBS


def run(work, classes):
    stubs = dict(STUBS)
    stubs.pop('jimm/util/ResourceBundle.java')
    stubs['DrawControls/device/Device.java'] = stubs['DrawControls/device/Device.java'].replace(
        'void setBackLightOnTime', 'boolean featureSupported(int n); void setBackLightOnTime')
    stubs['jimm/Jimm.java'] = stubs['jimm/Jimm.java'].replace(
        'public void setBackLightOnTime', 'public boolean featureSupported(int n){return false;} public void setBackLightOnTime')
    stubs['javax/microedition/lcdui/Gauge.java'] = '''package javax.microedition.lcdui;
public class Gauge extends Item {
 private int value; public Gauge(String label,boolean interactive,int max,int initial){this.label=label;value=initial;}
 public int getValue(){return value;} public void setValue(int v){value=v;}
}'''
    stubs['javax/microedition/media/Manager.java'] = '''package javax.microedition.media;
import java.io.*;
import java.util.*;
import javax.microedition.media.control.VolumeControl;
public class Manager {
 public static Vector started=new Vector(); public static int toneCount,toneVolume,toneNote;
 public static Player createPlayer(InputStream in,String type) throws IOException {
  if(in==null)throw new IOException("missing packaged sound");
  ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buf=new byte[1024];int n;
  while((n=in.read(buf))>=0)out.write(buf,0,n);in.close();return new Sound(out.toByteArray(),type);
 }
 public static void playTone(int note,int duration,int volume){toneCount++;toneVolume=volume;toneNote=note;}
 public static class Sound implements Player,VolumeControl {
  public byte[] bytes;public String type;public int volume,state=UNREALIZED;private PlayerListener listener;
  Sound(byte[] bytes,String type){this.bytes=bytes;this.type=type;}
  public void realize(){state=REALIZED;}public void prefetch(){state=PREFETCHED;}
  public void start(){state=STARTED;started.addElement(this);}public void stop(){state=PREFETCHED;}
  public void deallocate(){}public void close(){state=CLOSED;}
  public void finish(){if(listener!=null)listener.playerUpdate(this,PlayerListener.END_OF_MEDIA,null);}
  public long setMediaTime(long t){return t;}public long getMediaTime(){return 0;}
  public int getState(){return state;}public long getDuration(){return 1000000;}
  public String getContentType(){return type;}public void setLoopCount(int n){}
  public void addPlayerListener(PlayerListener l){listener=l;}public void removePlayerListener(PlayerListener l){listener=null;}
  public Control getControl(String name){return name.equals("VolumeControl")?this:null;}
  public Control[] getControls(){return new Control[]{this};}
  public void setMute(boolean b){}public boolean isMuted(){return false;}
  public int setLevel(int n){volume=n;return n;}public int getLevel(){return volume;}
 }
}'''
    cp = os.pathsep.join(str(p) for p in [classes, *sorted((work/'wtk/lib').glob('*.jar'))])
    with tempfile.TemporaryDirectory(prefix='tmm-notifications-') as temp:
        directory = Path(temp)
        resources = directory/'resources'; resources.mkdir()
        for name in ['RU.lng', 'langlist.lng', 'message.mp3', 'msg_low.mp3', 'tg.mp3', 'typing.mp3']:
            shutil.copy2(work/'src/build/res'/name, resources/name)
        sources = []
        for name, source in stubs.items():
            path = directory/name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source); sources.append(str(path))
        sources.append(str(root/'tests/java/NotificationProfilesTest.java'))
        subprocess.run([str(work/'jdk/bin/javac'), '-encoding', 'UTF-8', '-cp', cp,
                        '-d', str(directory), *sources], check=True)
        subprocess.run([str(work/'jdk/bin/java'), '-Xbootclasspath/a:'+str(resources),
                        '-cp', str(directory)+os.pathsep+cp, 'NotificationProfilesTest',
                        str(resources)], check=True, timeout=25)


if __name__ == '__main__':
    work = Path(sys.argv[1]).resolve()
    run(work, Path(sys.argv[2]).resolve() if len(sys.argv)>2 else work/'src/build/compile/classes')
