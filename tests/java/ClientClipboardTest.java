import java.lang.reflect.*;
import java.util.*;
import javax.microedition.lcdui.*;
import jimm.*;

public final class ClientClipboardTest {
    static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
    static Field field(Class c,String name) throws Exception {Field f=c.getDeclaredField(name);f.setAccessible(true);return f;}
    public static void main(String[] args) throws Exception {
        field(Options.class,"options").set(null,new Hashtable());
        Method defaults=Options.class.getDeclaredMethod("setDefaults");defaults.setAccessible(true);defaults.invoke(null);
        Options.setInt(Options.OPTION_TYPING_MODE,0);
        Constructor ctor=JimmUI.class.getDeclaredConstructor();ctor.setAccessible(true);ctor.newInstance();
        ContactItem contact=new ContactItem(1,1,"1000001","Test",false,true);
        Command paste=(Command)field(JimmUI.class,"cmdPasteText").get(null);
        JimmUI.clearClipBoardText();JimmUI.writeMessage(contact,"draft");
        TextBox editor=(TextBox)Jimm.display.getCurrent();
        check(!editor.commands.contains(paste),"Paste displayed with empty clipboard");
        JimmUI.setClipBoardText(true,"12:34","Source","text 😀\nsecond line");
        String copied=JimmUI.getClipBoardText();
        JimmUI.writeMessage(contact,"AB");editor=(TextBox)Jimm.display.getCurrent();editor.caret=1;
        check(editor.commands.contains(paste),"Copy has no Paste command");
        editor.listener.commandAction(paste,editor);
        check(editor.getString().equals("A"+copied+"B"),"Paste overwrites draft or ignores caret/Unicode");
        check(JimmUI.getClipBoardText().equals(copied),"Paste consumes buffer");
        char[] chars=new char[editor.getMaxSize()-copied.length()+1];Arrays.fill(chars,'x');
        String draft=new String(chars);editor.setString(draft);Jimm.display.setCurrent(editor);
        editor.listener.commandAction(paste,editor);
        check(editor.getString().equals(draft) && JimmUI.getClipBoardText().equals(copied),"Overflow truncates draft or buffer");
        check(Jimm.display.getCurrent() instanceof Alert && Jimm.display.returnTo==editor,"Overflow has no return to editor");
        JimmUI.clearClipBoardText();JimmUI.writeMessage(contact,"keep");
        check(!editor.commands.contains(paste),"Reused editor retains stale Paste command");
        System.out.println("PASS: Copy buffer is available in editor; Paste preserves draft, caret, Unicode and buffer; overflow is visible and reversible; empty/stale menu removed");
        System.exit(0);
    }
}
