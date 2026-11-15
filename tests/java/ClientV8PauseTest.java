import java.lang.reflect.*;
import java.util.*;
import javax.microedition.lcdui.*;
import jimm.*;
import DrawControls.VirtualList;
import DrawControls.device.Device;

/** The actual MIDlet callbacks, including return with the UI timer suspended. */
public final class ClientV8PauseTest {
    static SplashCanvas screen;
    static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
    static Field field(Class type,String name)throws Exception{
        Field result=type.getDeclaredField(name);result.setAccessible(true);return result;
    }
    static Method method(Class type,String name,Class... args)throws Exception{
        Method result=type.getDeclaredMethod(name,args);result.setAccessible(true);return result;
    }
    static void age(long millis)throws Exception{field(FlipState.class,"closedAt").setLong(null,System.currentTimeMillis()-millis);}
    static void pause(){Display.foreground=false;Jimm.jimm.pauseApp();}
    static void resume()throws Exception{Display.foreground=true;Jimm.jimm.startApp();}
    static TimerTask clock()throws Exception{
        Constructor ctor=Class.forName("jimm.JimmUI$ClockTask").getDeclaredConstructor();ctor.setAccessible(true);
        return (TimerTask)ctor.newInstance();
    }
    static void key(int value)throws Exception{method(SplashCanvas.class,"keyPressed",Integer.TYPE).invoke(screen,value);}
    static void pin(String value)throws Exception{for(int i=0;i<value.length();i++)key(value.charAt(i));}
    static void unlock()throws Exception{
        key('#');field(SplashCanvas.class,"poundPressTime").setLong(null,System.currentTimeMillis()-1000);
        method(SplashCanvas.class,"keyReleased",Integer.TYPE).invoke(screen,(int)'#');
        check(!SplashCanvas.locked(),"legacy # cannot unlock resumed keylock");
    }
    static void noApiLog()throws Exception{
        String[] lines=(String[])field(ConnLog.class,"lines").get(null);
        for(String line:lines)if(line!=null)check(line.indexOf("API недоступен")<0 && line.indexOf("NoClassDefFoundError")<0,"V8 attempts absent Vodafone API");
    }
    static void setup()throws Exception{
        Jimm.jimm=new Jimm();Jimm.display=new Display();Jimm.VERSION="test";
        field(MessageAlerts.class,"quietUntil").setLong(null,-1);
        Jimm.device=new Device(){
            public boolean featureSupported(int value){return false;}
            public void changeBackLightIntensity(boolean value){}
            public void setBackLightOn(boolean value){}public void setBackLightOff(){}
            public void setBackLightOnTime(boolean use,int value){}public void inverseBackLight(){}
        };
        field(Options.class,"options").set(null,new Hashtable());method(Options.class,"setDefaults").invoke(null);
        Options.setBoolean(Options.OPTION_DISPLAY_DATE,false);
        screen=new SplashCanvas("test");
        Constructor ctor=MainThread.class.getDeclaredConstructor();ctor.setAccessible(true);ctor.newInstance();
        VirtualList.setDisplay(Jimm.display);
        ((Vector)field(JimmUI.class,"lastScreens").get(null)).clear();
    }
    static void lifecycle()throws Exception{
        setup();
        try{Class.forName("com.vodafone.system.DeviceControl");throw new AssertionError("test accidentally includes Vodafone API");}
        catch(ClassNotFoundException expected){}
        check(FlipState.supported() && !FlipState.closed(),"V8 lifecycle tracking not ready initially");
        for(int i=0;i<100;i++)check(!FlipState.poll(),"V8 poll fabricates hardware transitions");
        noApiLog();
        Class formClass=Class.forName("jimm.OptionsForm");
        Constructor formCtor=formClass.getDeclaredConstructor();formCtor.setAccessible(true);Object form=formCtor.newInstance();
        method(formClass,"showInterfaceOptions").invoke(form);
        TextField interval=(TextField)field(formClass,"autoLockTextField").get(form);
        check(interval.getLabel().indexOf("после ухода в фон")>=0 && interval.getLabel().indexOf("закрытия")<0
            && interval.getString().equals("2"),"V8 settings still describe a physical lid sensor or wrong default");
        TextBox draft=new TextBox("draft","несохранённый текст",100,0);Jimm.display.setCurrent(draft);
        pause();check(FlipState.closed() && FlipState.notificationLocked(),"pause does not immediately select locked alerts");
        age(61000);long original=field(FlipState.class,"closedAt").getLong(null);pause();
        check(field(FlipState.class,"closedAt").getLong(null)==original,"repeated pause restarts deadline");
        resume();check(!FlipState.closed() && !FlipState.notificationLocked() && !SplashCanvas.locked(),"early resume does not cancel countdown");
        check(Jimm.display.getCurrent()==draft && draft.getString().equals("несохранённый текст"),"resume loses native editor draft");
        pause();check(!FlipState.lockDue(),"new pause reuses cancelled deadline");age(121000);
        int selections=Display.selections;
        for(int i=0;i<100;i++){JimmUI.checkAutoLock();clock().run();}
        check(Display.selections==selections && !SplashCanvas.locked(),"background timer changes display or steals focus");
        // Neither the timer's UI work nor a pending redraw is allowed to do the
        // lock while hidden. The lifecycle callback must check elapsed time.
        resume();
        check(SplashCanvas.locked() && Jimm.display.getCurrent()==screen && !FlipState.closed(),"overdue resume with suspended UI misses keylock");
        check(FlipState.notificationLocked(),"resumed keylock selects ordinary alerts");
        Display.flush();check(SplashCanvas.locked(),"delayed clock work bypasses resumed lock");
        unlock();check(Jimm.display.getCurrent()==draft && draft.getString().equals("несохранённый текст"),"unlock loses suspended editor");
        System.out.println("PASS: real pause/start callbacks, immediate alert profile, repeated pause, early cancellation, suspended timer, overdue resume and draft restoration");
    }
    static void deadlines()throws Exception{
        TextBox draft=new TextBox("draft","keep",100,0);Jimm.display.setCurrent(draft);
        Options.setLong(Options.OPTION_AUTOLOCK_MINUTES,0);pause();age(86400000);resume();
        check(!SplashCanvas.locked() && Jimm.display.getCurrent()==draft,"disabled background keylock still locks");
        Options.setLong(Options.OPTION_AUTOLOCK_MINUTES,999);pause();age(998*60000L);resume();
        check(!SplashCanvas.locked(),"999-minute threshold overflows or fires early");
        pause();age(999*60000L+1000);resume();check(SplashCanvas.locked(),"999-minute deadline ignored");unlock();
        Options.setLong(Options.OPTION_AUTOLOCK_MINUTES,2);pause();age(61000);
        Options.setLong(Options.OPTION_AUTOLOCK_MINUTES,1);resume();check(SplashCanvas.locked(),"return ignores updated timeout");unlock();
        Options.setLong(Options.OPTION_AUTOLOCK_MINUTES,2);
        // A queued clock event from before pause must not open the keylock while
        // the device's native dialog/background owns focus.
        clock().run();pause();age(121000);int selections=Display.selections;Display.flush();
        check(Display.selections==selections && !SplashCanvas.locked(),"stale queued UI work activates hidden application");
        resume();check(SplashCanvas.locked(),"stale UI event consumes overdue deadline");unlock();
        System.out.println("PASS: timeout off, 999 minutes, changed settings and pre-pause queued UI work");
    }
    static void pinAndScreens()throws Exception{
        Options.setString(Options.OPTION_LOCK_PIN,"0012");
        TextBox draft=new TextBox("draft","private",100,0);Jimm.display.setCurrent(draft);
        SplashCanvas.lockAfterFlip();check(SplashCanvas.pinLocked(),"test PIN lock not active");
        pause();resume();check(SplashCanvas.pinLocked() && Jimm.display.getCurrent()==screen,"early return bypasses existing PIN");
        pin("0012");check(!SplashCanvas.locked() && Jimm.display.getCurrent()==draft,"PIN cannot restore paused editor");
        pause();age(121000);resume();check(SplashCanvas.pinLocked(),"overdue return omits PIN");
        pin("0013");check(SplashCanvas.pinLocked(),"wrong PIN accepted after resume");
        pin("0012");check(!SplashCanvas.locked() && Jimm.display.getCurrent()==draft,"correct PIN fails after resume");
        Options.setString(Options.OPTION_LOCK_PIN,"");
        for(Displayable before:new Displayable[]{new Form("settings"),new Canvas()}){
            Jimm.display.setCurrent(before);pause();resume();check(Jimm.display.getCurrent()==before,"short pause discards settings/media screen");
            pause();age(121000);resume();check(SplashCanvas.locked(),"overdue resume skips settings/media");
            unlock();check(Jimm.display.getCurrent()==before,"unlock discards settings/media screen");
        }
        noApiLog();
        check(field(MessageAlerts.class,"quietUntil").getLong(null)==-1,"resume restarts startup notification silence");
        Alert alert=new Alert("system","preserve",null,AlertType.INFO);Jimm.display.setCurrent(alert);pause();resume();
        check(Jimm.display.getCurrent()==alert,"early resume discards existing alert");
        System.out.println("PASS: existing PIN survives resume, wrong/correct PIN, settings/media restoration and absent vendor API");
    }
    static void scheduling()throws Exception{
        JimmUI.startTaskForTimeString();
        Timer timer=(Timer)field(JimmUI.class,"uiClock").get(null);
        Object queue=field(Timer.class,"queue").get(timer);
        TimerTask[] entries=(TimerTask[])field(queue.getClass(),"queue").get(queue);
        TimerTask task=null;
        synchronized(queue){for(TimerTask value:entries)if(value!=null && value.getClass().getName().equals("jimm.JimmUI$ClockTask"))task=value;}
        check(task!=null,"UI clock not scheduled");
        check(Math.abs(field(TimerTask.class,"period").getLong(task))==10000,"V8 still wakes timer every second to poll absent hardware");
        JimmUI.stopTaskForTimeString();check(field(JimmUI.class,"uiClock").get(null)==null,"clock timer not released");
        System.out.println("PASS: V8 clock remains at ten seconds, without a per-second vendor poll");
    }
    static void faultFallback()throws Exception{
        Options.setString(Options.OPTION_LOCK_PIN,"0012");Options.setLong(Options.OPTION_AUTOLOCK_MINUTES,2);
        TextBox draft=new TextBox("private","do not expose",100,0);Jimm.display.setCurrent(draft);
        pause();age(121000);Display.selected.clear();Display.failGetCurrentOnce=true;
        resume();
        check(!Display.failGetCurrentOnce,"test did not reach failing native getCurrent");
        check(SplashCanvas.pinLocked() && !FlipState.closed() && Jimm.display.getCurrent()==screen,
            "expired PIN deadline falls back to an unlocked screen when getCurrent fails");
        for(Object selected:Display.selected)check(selected==screen,"failed resume selects a menu or private content before applying PIN");
        check(FlipState.notificationLocked(),"failed resume clears locked notification profile");
        System.out.println("PASS: native getCurrent failure on overdue return still applies PIN before exposing any screen");
    }
    public static void main(String[] args)throws Exception{
        try{lifecycle();deadlines();pinAndScreens();scheduling();faultFallback();}
        finally{
            JimmUI.stopTaskForTimeString();Jimm.getTimerRef().cancel();
            Object canvas=field(VirtualList.class,"virtualCanvas").get(null);
            if(canvas!=null)((Timer)field(canvas.getClass(),"repeatTimer").get(canvas)).cancel();
        }
    }
}
