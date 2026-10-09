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
        check(Options.autoLockMinutes()==2,"auto lock does not default to two minutes");
        for(String value:new String[]{"0","1","2","002","999"})check(Options.validAutoLockMinutes(value),"valid auto lock interval rejected");
        for(String value:new String[]{"","-1","+1","1000","1.5","abc","１２３"})check(!Options.validAutoLockMinutes(value),"invalid auto lock interval accepted");
        for(String pin:new String[]{"","0012","12345678"})check(Options.validLockPin(pin),"valid PIN rejected");
        for(String pin:new String[]{"1","123","123456789","abcd","123-","１２３４"})check(!Options.validLockPin(pin),"invalid PIN accepted");
        // Simulate an old RMS without the new field; upgrade leaves PIN disabled.
        ((Hashtable)field(Options.class,"options").get(null)).remove(new Integer(Options.OPTION_LOCK_PIN));
        ((Hashtable)field(Options.class,"options").get(null)).remove(new Integer(Options.OPTION_AUTOLOCK_MINUTES));
        Options.save();defaults();Options.load();check(Options.getString(Options.OPTION_LOCK_PIN).equals(""),"upgrade forces PIN");
        check(Options.autoLockMinutes()==2,"old RMS does not receive default auto lock interval");
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
        TextField auto=(TextField)field(c,"autoLockTextField").get(owner);
        check(form.items.contains(auto) && auto.getString().equals("2") && auto.getMaxSize()==3
                && auto.getConstraints()==TextField.NUMERIC,"numeric auto lock field/default missing from Interface");
        for(String value:new String[]{"1","3","999","0"}){
            auto.setString(value);method(c,"readInterfaceOptions").invoke(owner);Options.save();defaults();Options.load();
            check(Options.autoLockMinutes()==Integer.parseInt(value),"auto lock interval/off not retained in RMS");
        }
        auto.setString("999");Jimm.display.setCurrent(form);((CommandListener)owner).commandAction(JimmUI.cmdBack,form);
        check(Options.autoLockMinutes()==0,"Back saved changed auto lock interval");
        method(c,"showInterfaceOptions").invoke(owner);auto=(TextField)field(c,"autoLockTextField").get(owner);
        for(String invalid:new String[]{"","-1","1000","abc"}){
            Jimm.display.setCurrent(form);auto.setString(invalid);((CommandListener)owner).commandAction(JimmUI.cmdSave,form);
            check(Jimm.display.getCurrent() instanceof Alert && Jimm.display.returnTo==form,"bad auto lock interval not reported on same form");
            check(Options.autoLockMinutes()==0,"invalid auto lock interval partially saved preferences");
        }
        for(long bad:new long[]{-1,1000,Long.MAX_VALUE}){
            Options.setLong(Options.OPTION_AUTOLOCK_MINUTES,bad);check(Options.autoLockMinutes()==2,"corrupt interval does not use safe default");
        }
        System.out.println("PASS: optional masked numeric PIN in Interface; 4-8 digit validation, leading zeros, RMS upgrade/save, cancel and disable");
        System.out.println("PASS: numeric auto lock field defaults/upgrades to two minutes; 0 disables; RMS persistence, Back, validation and corrupt-value fallback");
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
        check(buffer()==null,"input allocated before first digit");SplashCanvas.unlock(true);check(SplashCanvas.pinLocked(),"programmatic unlock bypasses PIN");
        Graphics graphics=new Graphics();method(SplashCanvas.class,"paint",Graphics.class).invoke(screen,graphics);
        check(graphics.strings.contains("Введите PIN"),"PIN prompt not ready immediately on lock");
        check(!graphics.strings.contains("Для разблокировки нажмите и удерживайте клавишу #") && field(SplashCanvas.class,"t1").get(null)==null,"PIN prompt schedules legacy hint timer");
        hold();check(SplashCanvas.locked() && buffer()==null && !field(SplashCanvas.class,"pinWrong").getBoolean(null),"# bypasses PIN, allocates input or reports empty PIN");
        press('0');check(buffer().length==8 && field(SplashCanvas.class,"pinLength").getInt(null)==1,"first digit lost or buffer not lazy/bounded");
        method(SplashCanvas.class,"keyRepeated",Integer.TYPE).invoke(screen,(int)'0');
        method(SplashCanvas.class,"keyReleased",Integer.TYPE).invoke(screen,(int)'0');
        check(field(SplashCanvas.class,"pinLength").getInt(null)==1,"hold/release duplicates PIN digit");
        digits("01");SplashCanvas.messageAvailable();
        check(field(SplashCanvas.class,"pinLength").getInt(null)==3,"incoming message changes partial PIN input");
        graphics=new Graphics();method(SplashCanvas.class,"paint",Graphics.class).invoke(screen,graphics);
        check(graphics.strings.contains("***") && !graphics.strings.contains("001"),"PIN not masked on canvas");
        press('3');check(SplashCanvas.locked() && field(SplashCanvas.class,"pinWrong").getBoolean(null),"wrong PIN unlocks or lacks automatic feedback");
        check(field(SplashCanvas.class,"pinLength").getInt(null)==0,"wrong PIN not cleared");erased(buffer());
        digits("001");press(42);press('1');char[] old=buffer();press('2');
        check(!SplashCanvas.locked() && buffer()==null && previous.activated==2,"correct PIN/backspace requires # or did not unlock");erased(old);
        SplashCanvas.lock();digits("00");old=buffer();press(-22);
        check(SplashCanvas.locked() && buffer()==null,"right key does not clear input while keeping lock");erased(old);
        graphics=new Graphics();method(SplashCanvas.class,"paint",Graphics.class).invoke(screen,graphics);
        check(graphics.strings.contains("Введите PIN"),"clear hides ready PIN prompt");
        digits("00");check(field(SplashCanvas.class,"pinLength").getInt(null)==2,"typing after clear needs # or keeps old digits");
        old=buffer();method(SplashCanvas.class,"hideNotify").invoke(screen);
        check(SplashCanvas.locked() && buffer()==null,"background transition removes lock or keeps input");erased(old);
        SplashCanvas.show();check(field(SplashCanvas.class,"pinLength").getInt(null)==0,"background return keeps partial PIN");
        graphics=new Graphics();method(SplashCanvas.class,"paint",Graphics.class).invoke(screen,graphics);
        check(graphics.strings.contains("Введите PIN"),"background return requires # to show PIN prompt");
        digits("0012");check(!SplashCanvas.locked(),"direct PIN cannot unlock after background");
        Options.setString(Options.OPTION_LOCK_PIN,"12345678");SplashCanvas.lock();digits("12345679");
        check(SplashCanvas.locked() && field(SplashCanvas.class,"pinLength").getInt(null)==0,"8-digit wrong PIN is accepted or not cleared");erased(buffer());
        digits("1234567");check(SplashCanvas.locked() && buffer().length==8,"partial 8-digit PIN unlocks or allocates oversized buffer");
        old=buffer();press('8');check(!SplashCanvas.locked(),"8-digit PIN requires # or is rejected");erased(old);
        Options.setString(Options.OPTION_LOCK_PIN,"");SplashCanvas.lock();digits("0012");
        check(SplashCanvas.locked() && buffer()==null,"digits unlock without configured PIN");hold();
        check(!SplashCanvas.locked(),"switch back to no PIN breaks legacy hold #");
        System.out.println("PASS: PIN prompt ready on lock/background/clear; first digit retained, auto unlock at 4/8 digits, leading zeros, mask/retry/backspace, ignored #/repeat/release, lazy wiped buffer and legacy hold # without PIN");
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
        Jimm.display.setCurrent(screen);digits("0012");SplashCanvas.resetLastTask();
        check(!SplashCanvas.locked(),"PIN cannot unlock after reconnect/warning");
        System.out.println("PASS: reconnect, connection completion, warning alerts, real exception handler and queued/direct Back retain PIN lock");
    }
    static final class IdleList extends DrawControls.TextList {
        IdleList(){super("idle");}
        protected void keyPressed(int key){}
        protected void keyReleased(int key){}
        protected void keyRepeated(int key){}
    }
    static final class ListScreen implements JimmScreen {
        final IdleList list=new IdleList();
        public void activate(){list.activate(Jimm.display);JimmUI.setLastScreen(this,false);}
        public boolean isScreenActive(){return list.isActive();}
    }
    static Object canvas()throws Exception{return field(DrawControls.VirtualList.class,"virtualCanvas").get(null);}
    static void idle(long milliseconds)throws Exception{field(canvas().getClass(),"lastKeyTime").setLong(null,System.currentTimeMillis()-milliseconds);}
    static void tick(){MainThread.showTime();Display.flush();}
    static void autoLock() throws Exception {
        defaults();screen=new SplashCanvas("test");
        Constructor ctor=MainThread.class.getDeclaredConstructor();ctor.setAccessible(true);ctor.newInstance();
        DrawControls.VirtualList.setDisplay(Jimm.display);
        ((Vector)field(JimmUI.class,"lastScreens").get(null)).clear();ListScreen owner=new ListScreen();owner.activate();
        int scheduled=Jimm.Clock.scheduled;
        idle(119000);tick();check(!SplashCanvas.locked(),"two-minute auto lock fired early");
        idle(121000);DrawControls.VirtualList.setBottomText("network update");MainThread.showTime();
        check(!SplashCanvas.locked(),"clock locks outside UI queue");Display.flush();
        check(SplashCanvas.locked() && Jimm.display.getCurrent()==screen,"existing clock tick did not auto lock idle list");
        tick();SplashCanvas.unlock(false);tick();
        check(!SplashCanvas.locked() && owner.isScreenActive(),"unlock immediately relocks or loses previous screen");
        Options.setLong(Options.OPTION_AUTOLOCK_MINUTES,0);idle(86400000);tick();check(!SplashCanvas.locked(),"disabled auto lock fires");
        Options.setLong(Options.OPTION_AUTOLOCK_MINUTES,1);idle(61000);tick();check(SplashCanvas.locked(),"changed one-minute timeout ignored");SplashCanvas.unlock(false);
        Options.setLong(Options.OPTION_AUTOLOCK_MINUTES,2);
        for(Displayable exempt:new Displayable[]{new Form("settings"),new TextBox("message","draft",100,0),
                new Alert("warning","test",null,AlertType.WARNING),new Canvas(),screen}){
            Jimm.display.setCurrent(exempt);idle(300000);tick();
            check(!SplashCanvas.locked() && Jimm.display.getCurrent()==exempt,"auto lock interrupts editor/form/media/login");
            idle(300000);owner.activate();tick();check(!SplashCanvas.locked(),"return from exempt screen immediately auto locks");
        }
        idle(300000);method(canvas().getClass(),"keyPressed",Integer.TYPE).invoke(canvas(),1234);tick();
        check(!SplashCanvas.locked(),"key press does not restart idle countdown");
        idle(300000);((Runnable)canvas()).run();tick();check(!SplashCanvas.locked(),"held key repeat does not restart countdown");
        idle(300000);method(canvas().getClass(),"keyReleased",Integer.TYPE).invoke(canvas(),1234);tick();
        check(!SplashCanvas.locked(),"key release does not restart countdown");
        Display.foreground=false;idle(121000);tick();
        check(SplashCanvas.locked() && !Display.foreground,"hidden list skips auto lock or forces foreground");
        Display.foreground=true;SplashCanvas.unlock(false);
        Options.setString(Options.OPTION_LOCK_PIN,"0012");idle(121000);tick();
        check(SplashCanvas.pinLocked(),"auto lock bypasses configured PIN");digits("001");tick();
        check(SplashCanvas.pinLocked() && field(SplashCanvas.class,"pinLength").getInt(null)==3,"clock tick resets active PIN entry");
        digits("2");tick();check(!SplashCanvas.locked() && owner.isScreenActive(),"direct PIN unlock cannot return from auto lock");
        check(Jimm.Clock.scheduled==scheduled,"auto lock schedules an extra background timer task");
        System.out.println("PASS: existing queued clock locks after idle; live timeout/off, key press/hold/release, editors/forms/media/login exemptions, hidden list, PIN and return screen; no extra timer task");
    }
    public static void main(String[] args) throws Exception {
        try{settings();keys();reconnect();autoLock();}
        finally{
            Jimm.getTimerRef().cancel();
            for(String name:new String[]{"t1","t2"}){Timer timer=(Timer)field(SplashCanvas.class,name).get(null);if(timer!=null)timer.cancel();}
            Object canvas=field(DrawControls.VirtualList.class,"virtualCanvas").get(null);
            ((Timer)field(canvas.getClass(),"repeatTimer").get(canvas)).cancel();
        }
    }
}
