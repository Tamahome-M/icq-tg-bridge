import java.lang.reflect.*;
import java.util.*;
import javax.microedition.lcdui.*;
import jimm.*;
import jimm.comm.*;

public final class ClientLockTest {
    static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
    static Field field(Class c,String name) throws Exception {Field f=c.getDeclaredField(name);f.setAccessible(true);return f;}
    static Method method(Class c,String name,Class... args) throws Exception {Method m=c.getDeclaredMethod(name,args);m.setAccessible(true);return m;}
    static void defaults() throws Exception {
        field(Options.class,"options").set(null,new Hashtable());method(Options.class,"setDefaults").invoke(null);
        Options.setBoolean(Options.OPTION_DISPLAY_DATE,false);
    }
    static void settings() throws Exception {
        defaults();check(Options.getString(Options.OPTION_LOCK_PIN).equals(""),"PIN enabled by default");
        for(String pin:new String[]{"","0012","12345678"})check(Options.validLockPin(pin),"valid PIN rejected");
        for(String pin:new String[]{"1","123","123456789","abcd","123-","１２３４"})check(!Options.validLockPin(pin),"invalid PIN accepted");
        // Simulate an old RMS without the new field; upgrade leaves PIN disabled.
        ((Hashtable)field(Options.class,"options").get(null)).remove(new Integer(Options.OPTION_LOCK_PIN));
        Options.save();defaults();Options.load();check(Options.getString(Options.OPTION_LOCK_PIN).equals(""),"upgrade forces PIN");
        field(ContactList.class,"cItems").set(null,new Vector());field(ContactList.class,"gItems").set(null,new Vector());
        Class c=Class.forName("jimm.OptionsForm");Constructor ctor=c.getDeclaredConstructor();ctor.setAccessible(true);Object owner=ctor.newInstance();
        field(c,"currOptMode").setInt(owner,field(c,"OPTIONS_INTERFACE").getInt(null));
        field(c,"currOptType").setInt(owner,field(c,"TYPE_TOP_OPTIONS").getInt(null));
        field(c,"lastUILang").set(owner,Options.getString(Options.OPTION_UI_LANGUAGE));
        method(c,"showInterfaceOptions").invoke(owner);
        Form form=(Form)field(c,"optionsForm").get(owner);
        TextField input=(TextField)field(c,"lockPinTextField").get(owner);
        check(form.items.contains(input) && (input.getConstraints() & TextField.PASSWORD)!=0
            && (input.getConstraints() & TextField.CONSTRAINT_MASK)==TextField.NUMERIC && input.getMaxSize()==8,"PIN field missing, unmasked or nonnumeric");
        Jimm.display.setCurrent(form);input.setString("123");
        ((CommandListener)owner).commandAction(JimmUI.cmdSave,form);
        check(Jimm.display.getCurrent() instanceof Alert && Jimm.display.returnTo==form,"invalid PIN not reported on same form");
        check(Options.getString(Options.OPTION_LOCK_PIN).equals(""),"invalid PIN saved");
        Jimm.display.setCurrent(form);input.setString("0012");method(c,"readInterfaceOptions").invoke(owner);Options.save();defaults();Options.load();
        check(Options.getString(Options.OPTION_LOCK_PIN).equals("0012"),"PIN lost leading zeros or RMS save");
        input.setString("8765");Jimm.display.setCurrent(form);((CommandListener)owner).commandAction(JimmUI.cmdBack,form);
        check(Options.getString(Options.OPTION_LOCK_PIN).equals("0012"),"Back saved changed PIN");
        method(c,"showInterfaceOptions").invoke(owner);input=(TextField)field(c,"lockPinTextField").get(owner);
        input.setString("");method(c,"readInterfaceOptions").invoke(owner);Options.save();defaults();Options.load();
        check(Options.getString(Options.OPTION_LOCK_PIN).equals(""),"empty PIN did not disable protection");
        System.out.println("PASS: optional masked numeric PIN in Interface; 4-8 digit validation, leading zeros, RMS upgrade/save, cancel and disable");
    }
    static final class Previous implements JimmScreen {
        int activated;public void activate(){activated++;JimmUI.setLastScreen(this,false);}public boolean isScreenActive(){return false;}
    }
    static final class Task extends Action {
        Task(){super(true,false);}protected void init(){}protected boolean forward(Packet p){return false;}
        public boolean isCompleted(){return false;}public boolean isError(){return false;}public void onEvent(int event){}
    }
    static SplashCanvas screen;
    static void press(int key) throws Exception {method(SplashCanvas.class,"keyPressed",Integer.TYPE).invoke(screen,key);}
    static void digits(String text) throws Exception {for(int i=0;i<text.length();i++)press(text.charAt(i));}
    static void hold() throws Exception {
        press(35);field(SplashCanvas.class,"poundPressTime").setLong(null,System.currentTimeMillis()-1000);
        method(SplashCanvas.class,"keyReleased",Integer.TYPE).invoke(screen,35);
    }
    static char[] buffer() throws Exception {return (char[])field(SplashCanvas.class,"pinInput").get(null);}
    static void erased(char[] old) {for(char ch:old)check(ch==0,"PIN input buffer not erased");}
    static void keys() throws Exception {
        defaults();screen=new SplashCanvas("test");Previous previous=new Previous();
        Vector stack=(Vector)field(JimmUI.class,"lastScreens").get(null);stack.clear();stack.addElement(previous);
        SplashCanvas.lock();press(35);method(SplashCanvas.class,"keyReleased",Integer.TYPE).invoke(screen,35);
        check(SplashCanvas.locked(),"short # unlocks");hold();check(!SplashCanvas.locked(),"legacy hold # broken without PIN");
        Options.setString(Options.OPTION_LOCK_PIN,"0012");SplashCanvas.lock();
        check(buffer()==null,"input allocated before prompt");SplashCanvas.unlock(true);check(SplashCanvas.pinLocked(),"programmatic unlock bypasses PIN");
        hold();check(SplashCanvas.locked() && buffer().length==8,"hold # bypasses PIN or opens wrong buffer");
        digits("0013");SplashCanvas.messageAvailable();
        check(field(SplashCanvas.class,"pinLength").getInt(null)==4,"incoming message changes PIN input");
        Graphics graphics=new Graphics();method(SplashCanvas.class,"paint",Graphics.class).invoke(screen,graphics);
        check(graphics.strings.contains("****") && !graphics.strings.contains("0013"),"PIN not masked on canvas");
        press(35);check(SplashCanvas.locked() && field(SplashCanvas.class,"pinWrong").getBoolean(null),"wrong PIN unlocks or lacks feedback");
        check(field(SplashCanvas.class,"pinLength").getInt(null)==0,"wrong PIN not cleared");erased(buffer());
        digits("0013");press(42);press('2');char[] old=buffer();press(35);
        check(!SplashCanvas.locked() && buffer()==null && previous.activated==2,"correct PIN/backspace did not unlock");erased(old);
        SplashCanvas.lock();hold();digits("0012");old=buffer();press(-22);
        check(SplashCanvas.locked() && buffer()==null,"right key does not cancel input while keeping lock");erased(old);
        hold();digits("1234567890");check(field(SplashCanvas.class,"pinLength").getInt(null)==8,"PIN input exceeded limit");
        old=buffer();method(SplashCanvas.class,"hideNotify").invoke(screen);
        check(SplashCanvas.locked() && buffer()==null,"background transition removes lock or keeps input");erased(old);
        SplashCanvas.show();hold();check(field(SplashCanvas.class,"pinLength").getInt(null)==0,"background return keeps partial PIN");
        digits("0012");press(35);check(!SplashCanvas.locked(),"cannot unlock after background");
        Options.setString(Options.OPTION_LOCK_PIN,"12345678");SplashCanvas.lock();hold();digits("12345678");press(35);
        check(!SplashCanvas.locked(),"8-digit PIN rejected");
        System.out.println("PASS: real keypad/canvas; legacy hold, PIN masking/retry, erase/cancel, bounded lazy buffer, background wipe and 4/8 digit unlock");
    }
    static void reconnect() throws Exception {
        Options.setString(Options.OPTION_LOCK_PIN,"0012");SplashCanvas.lock();
        Constructor ctor=MainThread.class.getDeclaredConstructor();ctor.setAccessible(true);ctor.newInstance();
        SplashCanvas.addTimerTask("connecting",new Task(),true);
        check(SplashCanvas.pinLocked() && screen.commands.isEmpty() && screen.fullScreen,"reconnect removed PIN lock or shows cancel");
        MainThread.activateContactListMT(null);Display.flush();
        check(SplashCanvas.pinLocked() && Jimm.display.getCurrent()==screen,"connection completion exposes contacts");
        Alert alert=new Alert("warning","test",null,AlertType.WARNING);MainThread.activateMainMenu(alert);Display.flush();
        check(Jimm.display.getCurrent()==alert && Jimm.display.returnTo==screen && SplashCanvas.pinLocked(),"warning exposes menu after dismissal");
        Jimm.display.setCurrent(screen);MainThread.backToLastScreenMT();Display.flush();
        check(SplashCanvas.pinLocked() && Jimm.display.getCurrent()==screen,"queued Back exposes previous screen");
        JimmUI.backToLastScreen();check(Jimm.display.getCurrent()==screen,"direct Back bypasses PIN");
        JimmException.handleException(new JimmException(192,0,true));Display.flush();
        check(SplashCanvas.pinLocked() && Jimm.display.getCurrent() instanceof Alert && Jimm.display.returnTo==screen,"actual warning path bypasses PIN");
        Jimm.display.setCurrent(screen);hold();digits("0012");press(35);SplashCanvas.resetLastTask();
        check(!SplashCanvas.locked(),"PIN cannot unlock after reconnect/warning");
        System.out.println("PASS: reconnect, connection completion, warning alerts, real exception handler and queued/direct Back retain PIN lock");
    }
    public static void main(String[] args) throws Exception {
        try{settings();keys();reconnect();}
        finally{
            Jimm.getTimerRef().cancel();
            for(String name:new String[]{"t1","t2"}){Timer timer=(Timer)field(SplashCanvas.class,name).get(null);if(timer!=null)timer.cancel();}
            Object canvas=field(DrawControls.VirtualList.class,"virtualCanvas").get(null);
            ((Timer)field(canvas.getClass(),"repeatTimer").get(canvas)).cancel();
        }
    }
}
