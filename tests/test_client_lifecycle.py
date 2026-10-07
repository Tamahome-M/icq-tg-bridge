"""Run client lifecycle regressions against a build.sh workspace (requires JDK 8).

Usage: python3 tests/test_client_lifecycle.py /tmp/telemotomax-build
An optional second argument selects another compiled client for regression checks.
The client classes are real; only UI, settings and the MIDlet API/timer are stubbed.
Builds with VideoLink also check labelled links and the browser request.
"""

from pathlib import Path
import os
import subprocess
import sys
import tempfile


STUBS = {
    "jimm/Jimm.java": """
package jimm;
public class Jimm extends javax.microedition.midlet.MIDlet {
    public static final Jimm jimm = new Jimm();
    public static String openedUrl;
    public static javax.microedition.lcdui.Display display = new javax.microedition.lcdui.Display();
    private static java.util.Timer timer = new java.util.Timer(true);
    public static java.util.Timer getTimerRef() { return timer; }
    public void cancelTimer() { timer.cancel(); timer = new java.util.Timer(true); }
}
""",
    "jimm/Options.java": """
package jimm;
public class Options {
    public static int[] mediaSize(int key) { return null; }
    public static int getInt(int key) { return 0; }
    public static int mediaVideoKbps() { return getInt(118); }
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
    "javax/microedition/midlet/MIDlet.java": """
package javax.microedition.midlet;
public abstract class MIDlet {
    public final boolean platformRequest(String url) {
        jimm.Jimm.openedUrl = url;
        return false;
    }
}
""",
}

STUBS.update({
    "javax/microedition/lcdui/Command.java": """
package javax.microedition.lcdui;
public class Command { public static final int BACK=2; public Command(String s,int t,int p) {} }
""",
    "javax/microedition/lcdui/Displayable.java": """
package javax.microedition.lcdui;
public class Displayable { public CommandListener listener; public void addCommand(Command c) {} public void setCommandListener(CommandListener l) {listener=l;} }
""",
    "javax/microedition/lcdui/Display.java": """
package javax.microedition.lcdui;
public class Display { private Displayable current; public void setCurrent(Displayable d) {current=d;} public Displayable getCurrent() {return current;} }
""",
    "javax/microedition/lcdui/List.java": """
package javax.microedition.lcdui;
public class List extends Displayable {
 public static final int IMPLICIT=3;
 public static final Command SELECT_COMMAND=new Command("Select",1,1);
 public java.util.Vector labels=new java.util.Vector(); public int selected;
 public List(String title,int type) {}
 public int append(String label,Image image) {labels.addElement(label);return labels.size()-1;}
 public void addCommand(Command c) {}
 public void setCommandListener(CommandListener l) {listener=l;}
 public int getSelectedIndex() {return selected;}
 public void choose(int index) {selected=index;listener.commandAction(SELECT_COMMAND,this);}
}
""",
    "jimm/JimmUI.java": """
package jimm;
import DrawControls.TextList;
import DrawControls.VirtualList;
import javax.microedition.lcdui.Command;
public class JimmUI {
 public static final Command cmdBack=new Command("Back",2,1), cmdSelect=new Command("Select",4,1), cmdMenu=new Command("Menu",1,1);
 public static java.util.Vector bodies=new java.util.Vector();
 public static void setColorScheme(VirtualList list,boolean a,int b,boolean c) {}
 public static void addMessageText(TextList list,String text,int color,int index) {bodies.addElement(text);}
 public static void backToLastScreen() {}
}
""",
    "DrawControls/VirtualListCommands.java": """
package DrawControls;
public interface VirtualListCommands {
 void vlItemClicked(VirtualList list);
 void vlCursorMoved(VirtualList list);
 void vlKeyPress(VirtualList list,int key,int type);
}
""",
    "DrawControls/VirtualList.java": """
package DrawControls;
import javax.microedition.lcdui.*;
public class VirtualList extends Displayable {
 public static final int CURSOR_MODE_ENABLED=2,MENU_TYPE_LEFT_BAR=1,MENU_TYPE_RIGHT_BAR=2,MENU_TYPE_RIGHT=4;
 public java.util.Vector commands=new java.util.Vector();
 public VirtualListCommands callbacks;
 public void setMode(int mode) {}
 public void setVLCommands(VirtualListCommands value) {callbacks=value;}
 public void addCommandEx(Command command,int type) {commands.addElement(command);}
 public void removeCommandEx(Command command) {commands.removeElement(command);}
 public void activate(Display display) {display.setCurrent(this);}
 public boolean isActive() {return jimm.Jimm.display.getCurrent()==this;}
 public void repaint() {}
 public void lock() {}
 public void unlock() {}
 public void setCaption(String caption) {}
 public int getTextColor() {return 0;}
}
""",
    "DrawControls/TextList.java": """
package DrawControls;
import javax.microedition.lcdui.*;
public class TextList extends VirtualList {
 public java.util.Vector labels=new java.util.Vector(),headers=new java.util.Vector();
 public int selected;
 public TextList(String caption) {}
 public TextList addBigText(String label,int color,int style,int index) {labels.addElement(label);if(style==1)headers.addElement(label);return this;}
 public TextList doCRLF(int index) {return this;}
 public int getCurrTextIndex() {return selected;}
 public int getSize() {return labels.size();}
 public void setTopItem(int index) {}
 public void clear() {labels.removeAllElements();headers.removeAllElements();}
 public void choose(int index) {selected=index;listener.commandAction(jimm.JimmUI.cmdSelect,this);}
}
""",
    "jimm/ChatTextList.java": """
package jimm;
import javax.microedition.lcdui.Command;
public class ChatTextList {
 public static final Command cmdShowPhoto=new Command("Photo",8,1),cmdPlayVideo=new Command("Video",8,2),cmdPlayVoice=new Command("Voice",8,3),cmdGetFile=new Command("File",8,4);
 public static int getInOutColor(boolean incoming) {return 0;}
}
""",
    "jimm/MediaPlayer.java": """
package jimm;
public class MediaPlayer { public static String playedUin; public static byte[] playedToken; public static JimmScreen playedBack;
 public static void show(String uin,byte[] token,JimmScreen back) {playedUin=uin;playedToken=token;playedBack=back;} }
""",
})


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
        checks = ["ClientLifecycleTest"]
        if (classes / "jimm/VideoLink.class").exists():
            checks.append("VideoLinkTest")
        if (classes / "jimm/VideoMenu.class").exists():
            checks.append("VideoMenuTest")
            checks.append("HistoryVideoMenuTest")
        subprocess.run(
            [str(work / "jdk/bin/javac"), "-encoding", "UTF-8", "-cp", classpath,
             "-d", str(temporary), *sources,
             *[str(root / f"tests/java/{check}.java") for check in checks]],
            check=True,
        )
        for check in checks:
            subprocess.run(
                [str(work / "jdk/bin/java"), "-cp",
                 str(temporary) + os.pathsep + classpath, check],
                check=True, timeout=30,
            )


if __name__ == "__main__":
    run(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else None)
