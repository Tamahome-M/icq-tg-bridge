"""Exercise compiled SplashCanvas/MainMenu/Options with a fake MIDP UI and RMS.

Usage: python3 tests/test_client_ui.py BUILD_WORK [COMPILED_CLASSES]
The classes and preprocessed language file must come from the same build.
Network, widgets and scheduling are stubbed; cancellation, status selection,
OSCAR status packets and loading old preferences use the real client classes.
"""

from pathlib import Path
import os
import json
import re
import subprocess
import sys
import tempfile
import struct

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.test_client_lifecycle import STUBS as BASE
from tests.test_video_settings import CHOICE


STUBS = {name: value for name, value in BASE.items()
         if name not in {"jimm/Options.java", "jimm/SplashCanvas.java"}}
STUBS["jimm/MainThread.java"] = """
package jimm;
public class MainThread {
 public static java.util.Vector messages=new java.util.Vector();
 public static void addMessageSerially(Object message){messages.addElement(message);}
 public static String refUin; public static int refId; public static byte[] ref;
 public static void setMessageRef(String uin,int id,byte[] value){refUin=uin;refId=id;ref=value;}
 public static void nativeQuoteResult(jimm.NativeQuote action,String error){action.showResult(error);}
 public static void resetContactsOffline(){}
}
"""
STUBS["jimm/Jimm.java"] = """
package jimm;
public class Jimm extends javax.microedition.midlet.MIDlet {
 public static final Jimm jimm=new Jimm();
 public static final String NAME="TeleMotoMax",VERSION="test";
 public static final String microeditionPlatform=System.getProperty("microedition.platform");
 public static final int cmdBack=2;
 public static String openedUrl;
 public static javax.microedition.lcdui.Display display=new javax.microedition.lcdui.Display();
 public static DrawControls.device.Device device=new DrawControls.device.Device(){public void setBackLightOnTime(boolean b,int n){}};
 public static class Clock extends java.util.Timer {
  public Clock(){super(true);}
  public void schedule(java.util.TimerTask task,long delay,long period){}
 }
 private static Clock timer=new Clock();
 public static java.util.Timer getTimerRef(){return timer;}
 public static int getPhoneVendor(){return 5;}
 public static void setBkltOn(boolean b){}
 public static void setBkltOff(){}
 public static void setMinimized(boolean b){}
 public void destroyApp(boolean b) throws javax.microedition.midlet.MIDletStateChangeException {}
}
"""
STUBS["javax/microedition/lcdui/Displayable.java"] = """
package javax.microedition.lcdui;
public class Displayable {
 public CommandListener listener;
 public java.util.Vector commands=new java.util.Vector();
 public void addCommand(Command c){if(!commands.contains(c))commands.addElement(c);}
 public void removeCommand(Command c){commands.removeElement(c);}
 public void setCommandListener(CommandListener l){listener=l;}
 public boolean isShown(){return jimm.Jimm.display.getCurrent()==this;}
 public int getWidth(){return 176;} public int getHeight(){return 200;}
}
"""
STUBS["javax/microedition/lcdui/Canvas.java"] = """
package javax.microedition.lcdui;
public class Canvas extends Displayable {
 public static final int KEY_POUND=35;
 public static String keyName;
 public boolean fullScreen;
 public void setFullScreenMode(boolean b){fullScreen=b;}
 public void repaint(){} public void serviceRepaints(){}
 public int getWidth(){return 176;} public int getHeight(){return fullScreen?220:200;}
 public String getKeyName(int key){if(keyName==null || key!=987)throw new IllegalArgumentException();return keyName;}
}
"""
STUBS["javax/microedition/lcdui/Display.java"] = """
package javax.microedition.lcdui;
public class Display {
 private Displayable current;
 public Displayable returnTo;
 public void setCurrent(Alert a,Displayable d){current=a;returnTo=d;}
 public void setCurrent(Displayable d){current=d;} public Displayable getCurrent(){return current;}
 public boolean flashBacklight(int n){return true;} public int numAlphaLevels(){return 256;}
}
"""
STUBS["javax/microedition/lcdui/Alert.java"] = """
package javax.microedition.lcdui;
public class Alert extends Displayable {
 public static final int FOREVER=-2;public String text; public AlertType type;
 public Alert(String title,String text,Image image,AlertType type){this.text=text;this.type=type;}
 public void setTimeout(int n){}
}
"""
STUBS["javax/microedition/lcdui/AlertType.java"] = """
package javax.microedition.lcdui;
public class AlertType {public static final AlertType INFO=new AlertType(),ERROR=new AlertType(),WARNING=new AlertType();}
"""
STUBS["javax/microedition/lcdui/Font.java"] = """
package javax.microedition.lcdui;
public class Font {
 public static final int FACE_SYSTEM=0,STYLE_PLAIN=0,STYLE_BOLD=1,SIZE_SMALL=8,SIZE_MEDIUM=0,SIZE_LARGE=16;
 public static Font getFont(int f,int s,int z){return new Font();}
 public static Font getDefaultFont(){return new Font();}
 public int getHeight(){return 12;} public int stringWidth(String s){return s.length()*6;}
}
"""
STUBS["javax/microedition/lcdui/Image.java"] = """
package javax.microedition.lcdui;
public class Image {public static Image createImage(String s) throws java.io.IOException {throw new java.io.IOException();}}
"""
STUBS["DrawControls/ImageList.java"] = """
package DrawControls;
public class ImageList {
 public void setScale(int i){} public void load(String s,int a,int b,int c,boolean d){}
 public javax.microedition.lcdui.Image elementAt(int i){return null;}
}
"""
STUBS["DrawControls/device/Device.java"] = """
package DrawControls.device;
public interface Device {void setBackLightOnTime(boolean b,int n);}
"""
STUBS["DrawControls/VirtualList.java"] = BASE["DrawControls/VirtualList.java"].replace(
    "public class VirtualList extends Displayable {", "public class VirtualList extends Displayable {\n"
    " public static final int CURSOR_MODE_DISABLED=0;\n"
    " public void setTopItem(int n){}\n"
    " public static void touch(){} public static void setMiniProgressBar(boolean b){}\n"
    " public static void setMpbPercent(int n){} public void setCyclingCursor(boolean b){}\n"
    " public void removeAllCommands(){commands.removeAllElements();}\n"
    " public void selectTextByIndex(int n){}\n"
    " public static void setFullScreenForCurrent(boolean b){} public static void setMirrorMenu(boolean b){}\n"
    " public static void setCapOffset(int n){}\n")
STUBS["DrawControls/TextList.java"] = BASE["DrawControls/TextList.java"].replace(
    "public TextList(String caption) {}", "public TextList(String caption) {}\n"
    " public void selectTextByIndex(int n){selected=n;}\n"
    " public int getCurrIndex(){return selected;}\n")
STUBS["jimm/JimmUI.java"] = """
package jimm;
import DrawControls.*;
import javax.microedition.lcdui.*;
public class JimmUI {
 public static final Command cmdBack=new Command("Back",2,1),cmdSelect=new Command("Select",4,1),
 cmdMenu=new Command("Menu",1,1),cmdCancel=new Command("Cancel",3,1),cmdList=new Command("List",1,1);
 public static void addMessageText(TextList l,String s,int color,int index){l.labels.addElement(s);}
 public static int returned;
 public static void setColorScheme(VirtualList l,boolean a,int b,boolean c){}
 public static void backToLastScreen(){returned++;jimm.Jimm.display.setCurrent(null);}
 public static boolean isControlActive(VirtualList o){return o!=null && o==jimm.Jimm.display.getCurrent();}
 public static int getCommandType(Command c,int tag){return 0;}
 public static StatusInfo findStatus(int t,int n){return null;}
 public static void addTextListItem(TextList l,String s,Image i,int value,boolean a,int b,int c){l.labels.addElement(jimm.util.ResourceBundle.getString(s));}
 public static void fillStatusesInList(TextList l){l.labels.addElement("status_online");l.labels.addElement("status_away");}
}
"""
STUBS["jimm/util/ResourceBundle.java"] = BASE["jimm/util/ResourceBundle.java"].replace(
    "public class ResourceBundle {", "public class ResourceBundle {\n public static String[] langAvailable={\"RU\"};\n")
STUBS["javax/microedition/rms/RecordStore.java"] = """
package javax.microedition.rms;
public class RecordStore {
 public static java.util.Hashtable stores=new java.util.Hashtable();
 private java.util.Vector records=new java.util.Vector();
 public static RecordStore openRecordStore(String s,boolean create) throws RecordStoreException {
  RecordStore r=(RecordStore)stores.get(s);
  if(r==null){if(!create)throw new RecordStoreException();r=new RecordStore();stores.put(s,r);}return r;
 }
 public int getNumRecords(){return records.size();}
 public byte[] getRecord(int id){return (byte[])records.elementAt(id-1);}
 public int addRecord(byte[] b,int o,int n){byte[] v=new byte[n];if(n>0)System.arraycopy(b,o,v,0,n);records.addElement(v);return records.size();}
 public void setRecord(int id,byte[] b,int o,int n){byte[] v=new byte[n];System.arraycopy(b,o,v,0,n);records.setElementAt(v,id-1);}
 public void closeRecordStore(){}
}
"""
STUBS["javax/microedition/lcdui/Item.java"] = "package javax.microedition.lcdui; public abstract class Item {public String label; public String getLabel(){return label;}}"
STUBS["javax/microedition/lcdui/TextField.java"] = """
package javax.microedition.lcdui;
public class TextField extends Item {
 private String value; public TextField(String l,String v,int m,int c){label=l;value=v;}
 public String getString(){return value;} public void setString(String v){value=v;}
}
"""
STUBS["javax/microedition/lcdui/Form.java"] = """
package javax.microedition.lcdui;
public class Form extends Displayable {
 public java.util.Vector items=new java.util.Vector();
 public Form(String title){} public int append(Item i){items.addElement(i);return items.size()-1;}
 public void setItemStateListener(ItemStateListener l){}
}
"""
STUBS["javax/microedition/lcdui/ChoiceGroup.java"] = CHOICE.replace(
    "private int selected;", "private int selected; private java.util.Hashtable flags=new java.util.Hashtable();").replace(
    "public ChoiceGroup(String label,int type) {this.type=type;}", "public ChoiceGroup(String label,int type) {this.type=type;this.label=label;}\n"
    " public ChoiceGroup(String label,int type,String[] labels,Image[] images){this(label,type);for(int i=0;i<labels.length;i++)append(labels[i],null);}").replace(
    "return selected==i;", "return type==2 ? Boolean.TRUE.equals(flags.get(new Integer(i))) : selected==i;").replace(
    "if(value)selected=i;", "flags.put(new Integer(i),Boolean.valueOf(value));if(value)selected=i;")


def run(work: Path, classes: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    classpath = os.pathsep.join(str(p) for p in [classes, *sorted((work / "wtk/lib").glob("*.jar"))])
    # LangsTask compresses all literal language keys before javac. Use the
    # preprocessed language file from this build to name actual menu entries.
    alphabet = "_0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    keys = re.findall(r'^"([^"\n]+)"', (work / "src/build/init/src/lng/RU.lang").read_text(), re.M)
    mappings, counter = [], 0
    for key in dict.fromkeys(keys):
        if key.startswith(("error_", "lang_")):
            continue
        value, short = counter, ""
        while True:
            short += alphabet[value % len(alphabet)]
            value //= len(alphabet)
            if not value:
                break
        counter += 1
        mappings.append(f"keys.put({json.dumps(short)},{json.dumps(key)});")
    stubs = dict(STUBS)
    stubs["jimm/util/ResourceBundle.java"] = """
package jimm.util;
public class ResourceBundle {
 public static String[] langAvailable={"RU"};
 private static java.util.Hashtable keys=new java.util.Hashtable();
 static {MAPPINGS}
 public static String getString(String s){String v=(String)keys.get(s);return v==null?s:v;}
 public static String getString(String s,int flags){return getString(s);}
 public static String remove(String s){return getString(s);}
 public static String key(String s){java.util.Enumeration k=keys.keys();while(k.hasMoreElements()){
  String v=(String)k.nextElement();if(s.equals(keys.get(v)))return v;}return s;}
}
""".replace("MAPPINGS", "".join(mappings))
    with tempfile.TemporaryDirectory(prefix="tmm-client-ui-") as temp:
        directory = Path(temp)
        sources = []
        for name, source in stubs.items():
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
            sources.append(str(path))
        # Feed actual server-built packets to the client's ActionListener.
        from bridge.oscar import blocks
        from bridge.oscar.proto import tlv
        cookie = bytes(range(8))
        sender = blocks.user_info("1000037")
        token = bytes(range(16))
        def message(body, extra=b""):
            return cookie + struct.pack(">H", 2) + sender + tlv(5, body) + extra
        (directory / "plain.bin").write_bytes(message(blocks.channel2_message(cookie, "Привет"),
                                                     tlv(0x9001, bytes([2]) + token)+tlv(0x9002, (2**63+12345).to_bytes(8,"big"))))
        (directory / "url.bin").write_bytes(message(blocks.channel2_message(cookie, "[видео]", "http://bridge.example/v/token"),tlv(0x9002,(44).to_bytes(8,"big"))))
        (directory / "own.bin").write_bytes(cookie+bytes([7])+b"1000070"+(2**63+12345).to_bytes(8,"big"))
        away = bytearray(blocks.channel2_message(cookie, ""))
        offset = away.index(bytes([0x27, 0x11])) + 4 + 45
        away[offset:offset+2] = struct.pack("<H", 1000)
        (directory / "status.bin").write_bytes(message(bytes(away)))
        # Use the real server error builder; the actual BART action and history
        # viewer must deliver its UTF-8 reason instead of an empty history page.
        import asyncio
        from bridge.oscar.server import Session
        async def history_error():
            session = object.__new__(Session)
            async def capture(family, subtype, data=b"", **kwargs):
                (directory / "history-error.bin").write_bytes(data)
            session.send_snac = capture
            await session.send_error(0x10, 1, 77, "Слишком много запросов истории. Повторите позже.")
        asyncio.run(history_error())
        history_rows = [("[07.10 23:19] Сергей: первое", "", False, 0, 10001),
                        ("[07.10 23:19] Сергей: второе", "", False, 0, 10002)]
        (directory / "history-page.bin").write_bytes(b"\xff\x01" + blocks.history_records(
            history_rows, 4096, lambda _: None, threads=True, quotes=True))
        subprocess.run([str(work / "jdk/bin/javac"), "-encoding", "UTF-8", "-cp", classpath,
                        "-d", str(directory), *sources, str(root / "tests/java/ClientUiTest.java"),
                        str(root / "tests/java/NativeQuoteTest.java"), str(root / "tests/java/HistoryErrorTest.java")], check=True)
        subprocess.run([str(work / "jdk/bin/java"), "-cp", str(directory) + os.pathsep + classpath,
                        "ClientUiTest", str(directory)], check=True, timeout=30)
        subprocess.run([str(work / "jdk/bin/java"), "-cp", str(directory) + os.pathsep + classpath,
                        "NativeQuoteTest"], check=True, timeout=30)
        subprocess.run([str(work / "jdk/bin/java"), "-cp", str(directory) + os.pathsep + classpath,
                        "HistoryErrorTest", str(directory)], check=True, timeout=30)


if __name__ == "__main__":
    work = Path(sys.argv[1]).resolve()
    run(work, Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else work / "src/build/compile/classes")
