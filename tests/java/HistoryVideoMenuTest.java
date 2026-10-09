import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.Vector;
import DrawControls.TextList;
import jimm.HistoryViewer;
import jimm.Jimm;
import jimm.JimmScreen;
import jimm.JimmUI;
import jimm.MediaPlayer;

/** Real HistoryViewer and VideoMenu classes; UI and transport endpoints are spies. */
public final class HistoryVideoMenuTest {
    private static final class Back implements JimmScreen {
        public void activate() {}
        public boolean isScreenActive() {return false;}
    }
    private static void check(boolean ok, String message) {
        if (!ok) throw new AssertionError(message);
    }
    private static void set(Object target,String name,Object value) throws Exception {
        Field field=HistoryViewer.class.getDeclaredField(name);
        field.setAccessible(true);field.set(target,value);
    }
    private static Vector vector(Object value) {
        Vector values=new Vector();values.addElement(value);return values;
    }
    public static void main(String[] args) throws Exception {
        String url="http://host:8080/s/session/v/Abc_123-token4567";
        String text="[видео]("+url+") 0:24\n[07.10 13:08] Автор: подпись";
        byte[] token=new byte[16];token[0]=42;
        Constructor ctor=HistoryViewer.class.getDeclaredConstructor(new Class[]{JimmScreen.class,String.class,String.class});
        ctor.setAccessible(true);
        HistoryViewer viewer=(HistoryViewer)ctor.newInstance(new Object[]{new Back(),"123","Чат"});
        TextList history=new TextList("Чат");
        set(viewer,"list",history);set(viewer,"videoUrls",vector(url));set(viewer,"tokens",vector(token));
        set(viewer,"kinds",new byte[]{2});set(viewer,"threads",vector(null));
        Method append=HistoryViewer.class.getDeclaredMethod("appendLine",new Class[]{TextList.class,String.class,int.class,int.class});append.setAccessible(true);
        append.invoke(null,new Object[]{history,text,new Integer(2),new Integer(0)});
        check(history.headers.isEmpty(),"labelled video URL was misclassified as a history header");
        check(JimmUI.bodies.contains(text),"history must send the video label to the shared message renderer");
        Method more=HistoryViewer.class.getDeclaredMethod("checkMore",new Class[0]);more.setAccessible(true);
        more.invoke(viewer,new Object[0]);
        Field moreCommand=HistoryViewer.class.getDeclaredField("cmdMore");moreCommand.setAccessible(true);
        check(history.commands.contains(moreCommand.get(null)),"More must remain a history command");
        // Exercise the actual command handler of the history screen.
        Field command=Class.forName("jimm.ChatTextList").getDeclaredField("cmdPlayVideo");command.setAccessible(true);
        viewer.activate();
        viewer.commandAction((javax.microedition.lcdui.Command)command.get(null),null);
        check(Jimm.display.getCurrent() instanceof TextList,"history must show the client's selector");
        TextList menu=(TextList)Jimm.display.getCurrent();
        check(menu!=history && menu.labels.size()==2,"history must offer player and browser together");
        check(Jimm.openedUrl==null && MediaPlayer.playedToken==null,"opening history's menu must not start playback");
        menu.callbacks.vlKeyPress(menu,-5,3); // release/repeat of the parent key
        check(Jimm.openedUrl==null && MediaPlayer.playedToken==null,"parent key event must not choose Watch");
        menu.choose(1);
        check(url.equals(Jimm.openedUrl) && MediaPlayer.playedToken==null,"history browser choice must not request native video");
        Jimm.openedUrl=null;
        viewer.vlItemClicked(history);
        menu=(TextList)Jimm.display.getCurrent();menu.choose(0);
        check(MediaPlayer.playedToken==token,"history Watch must use the selected record's token");
        MediaPlayer.playedToken=null;
        viewer.commandAction((javax.microedition.lcdui.Command)command.get(null),null);
        menu=(TextList)Jimm.display.getCurrent();menu.listener.commandAction(JimmUI.cmdBack,null);
        menu.choose(0); // stale callback after Back
        check(MediaPlayer.playedToken==null && Jimm.openedUrl==null,"Back must cancel even if a stale callback arrives");
        check(history.commands.contains(moreCommand.get(null)),"video selector must not change More");
        set(viewer,"videoUrls",vector(null));history.clear();
        JimmUI.bodies.removeAllElements();append.invoke(null,new Object[]{history,"[07.10 13:08] Автор: обычное сообщение",new Integer(1),new Integer(0)});
        check(history.headers.contains("[07.10 13:08] Автор:"),"ordinary history headers must keep their formatting");
        System.out.println("PASS: server history hides video URLs, shows both choices and waits for explicit selection");
    }
}
