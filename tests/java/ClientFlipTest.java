import java.lang.reflect.*;
import java.util.*;
import javax.microedition.lcdui.*;
import jimm.*;

public final class ClientFlipTest {
    static void check(boolean ok,String why){ClientLockTest.check(ok,why);}
    static Field field(Class c,String name)throws Exception{return ClientLockTest.field(c,name);}
    static Class vendor()throws Exception{return Class.forName("com.vodafone.system.DeviceControl");}
    static void cover(int value)throws Exception{field(vendor(),"state").setInt(null,value);FlipState.poll();}
    static void age(long value)throws Exception{field(FlipState.class,"closedAt").setLong(null,System.currentTimeMillis()-value);}
    static TimerTask clock()throws Exception{
        Constructor c=Class.forName("jimm.JimmUI$ClockTask").getDeclaredConstructor();c.setAccessible(true);
        return (TimerTask)c.newInstance();
    }
    static int events()throws Exception{
        String[] lines=(String[])field(ConnLog.class,"lines").get(null);int n=0;
        for(String line:lines)if(line!=null)n++;return n;
    }
    static void unlock()throws Exception{ClientLockTest.hold();check(!SplashCanvas.locked(),"legacy # did not unlock cover keylock");}
    static void setup()throws Exception{
        ClientLockTest.defaults();ClientLockTest.screen=new SplashCanvas("test");
        Constructor c=MainThread.class.getDeclaredConstructor();c.setAccessible(true);c.newInstance();
        DrawControls.VirtualList.setDisplay(Jimm.display);
        ((Vector)field(JimmUI.class,"lastScreens").get(null)).clear();
    }
    static void absence()throws Exception{
        setup();ClientLockTest.ListScreen owner=new ClientLockTest.ListScreen();owner.activate();
        for(int i=0;i<100;i++)FlipState.poll();
        check(!FlipState.supported() && !FlipState.closed() && !FlipState.notificationLocked(),"absent API invents state");
        check(events()==1,"absent API retries/logs every tick");
        ClientLockTest.idle(121000);ClientLockTest.tick();
        check(SplashCanvas.locked(),"absent API loses existing idle keylock");
        SplashCanvas.unlock(false);
        System.out.println("PASS: no Vodafone runtime class: actual optional adapter fails safely once; old idle keylock still works");
    }
    static void nativeCover()throws Exception{
        setup();ClientLockTest.ListScreen owner=new ClientLockTest.ListScreen();owner.activate();
        cover(0);check(FlipState.supported() && !FlipState.closed(),"open physical state not detected");
        check(events()==0,"initial cover state still writes a debug event");
        ClientLockTest.idle(86400000);ClientLockTest.tick();
        check(!SplashCanvas.locked(),"open cover still locks from key inactivity");
        Class f=Class.forName("jimm.OptionsForm");Constructor ctor=f.getDeclaredConstructor();ctor.setAccessible(true);
        Object form=ctor.newInstance();ClientLockTest.method(f,"showInterfaceOptions").invoke(form);
        TextField timeout=(TextField)field(f,"autoLockTextField").get(form);
        check(timeout.getLabel().indexOf("после закрытия")>=0 && timeout.getString().equals("2"),"physical timeout label/default wrong");
        cover(1);check(FlipState.notificationLocked() && !SplashCanvas.locked(),"close does not switch alerts before keylock");
        check(events()==0,"cover transition still writes a debug event");
        age(119000);ClientLockTest.tick();check(!SplashCanvas.locked(),"closed timer fired early");
        int records=events();int instances=field(vendor(),"instances").getInt(null);
        for(int i=0;i<1000;i++)FlipState.poll();
        check(events()==records && instances==1 && field(vendor(),"instances").getInt(null)==1,"poll allocates device or repeats logs");
        age(121000);TimerTask task=clock();task.run();
        check(!SplashCanvas.locked() && !Display.queued.isEmpty(),"timer locks outside UI queue");
        // Open after scheduling, before the UI gets to the deadline event.
        field(vendor(),"state").setInt(null,0);Display.flush();
        check(!SplashCanvas.locked() && !FlipState.closed(),"stale close event locks after opening");
        cover(1);ClientLockTest.tick();check(!SplashCanvas.locked(),"new close retained previous deadline");
        Options.setLong(Options.OPTION_AUTOLOCK_MINUTES,0);age(86400000);ClientLockTest.tick();
        check(!SplashCanvas.locked() && FlipState.notificationLocked(),"off suppresses closed alerts or still locks");
        Options.setLong(Options.OPTION_AUTOLOCK_MINUTES,999);age(998*60000L);ClientLockTest.tick();
        check(!SplashCanvas.locked(),"large minute value overflowed");
        age(999*60000L+1000);ClientLockTest.tick();check(SplashCanvas.locked(),"999-minute deadline ignored");
        cover(0);check(SplashCanvas.locked() && FlipState.notificationLocked(),"opening bypasses keylock");
        MainThread.backToLastScreenMT();Display.flush();JimmUI.backToLastScreen();
        check(Jimm.display.getCurrent()==ClientLockTest.screen,"queued navigation bypasses keylock without PIN");
        SplashCanvas.unlock(false);check(SplashCanvas.locked(),"programmatic unlock bypasses cover keylock");
        SplashCanvas.addTimerTask("connecting",null,true);
        check(SplashCanvas.locked(),"reconnect bypasses cover keylock without PIN");
        SplashCanvas.resetLastTask();unlock();check(owner.isScreenActive(),"keylock lost previous list");
        Options.setLong(Options.OPTION_AUTOLOCK_MINUTES,2);cover(1);age(61000);ClientLockTest.tick();
        check(!SplashCanvas.locked(),"saved two-minute delay ignored");
        Options.setLong(Options.OPTION_AUTOLOCK_MINUTES,1);ClientLockTest.tick();check(SplashCanvas.locked(),"changed deadline not applied");
        cover(0);unlock();Options.setLong(Options.OPTION_AUTOLOCK_MINUTES,2);
        for(Displayable before:new Displayable[]{new TextBox("draft","unsent text",100,0),new Form("settings"),new Canvas()}){
            Jimm.display.setCurrent(before);cover(1);age(121000);ClientLockTest.tick();
            check(SplashCanvas.locked(),"cover deadline skips editor/settings/media");
            cover(0);unlock();
            check(Jimm.display.getCurrent()==before && field(SplashCanvas.class,"flipReturnScreen").get(null)==null,"unlock loses editor or retains return screen");
            if(before instanceof TextBox)check(((TextBox)before).getString().equals("unsent text"),"keylock lost draft");
        }
        Jimm.display.setCurrent(new Canvas());cover(1);age(121000);ClientLockTest.tick();
        MainThread.activateScreenMT(owner);Display.flush();
        check(Jimm.display.getCurrent()==ClientLockTest.screen,"finished media bypasses cover keylock");
        cover(0);unlock();check(owner.isScreenActive(),"unlock restores a media canvas already closed by download completion");
        owner.activate();Options.setString(Options.OPTION_LOCK_PIN,"0012");
        cover(1);age(121000);ClientLockTest.tick();cover(0);
        check(SplashCanvas.pinLocked(),"cover-open bypasses PIN");
        ClientLockTest.digits("0012");check(!SplashCanvas.locked() && owner.isScreenActive(),"cover lock cannot unlock with PIN");
        Options.setString(Options.OPTION_LOCK_PIN,"");
        TimerTask steady=clock();steady.run();Display.flush();
        for(int i=0;i<100;i++)steady.run();
        check(Display.queued.isEmpty(),"one-second poll adds one-second UI work");
        JimmUI.startTaskForTimeString();Timer first=(Timer)field(JimmUI.class,"uiClock").get(null);
        JimmUI.startTaskForTimeString();check(first!=field(JimmUI.class,"uiClock").get(null),"second start retains same timer");
        JimmUI.stopTaskForTimeString();check(field(JimmUI.class,"uiClock").get(null)==null,"exit retains clock timer");
        System.out.println("PASS: raw cover state; immediate alert profile; close-only timeout/off/999 minutes; reopening cancels or preserves PIN/keylock; queued race; drafts/forms/media restored; bounded poll/log/UI work and timer lifecycle");
        cover(1);age(121000);field(vendor(),"fail").setBoolean(null,true);ClientLockTest.tick();
        check(!FlipState.supported() && !FlipState.closed() && !SplashCanvas.locked(),"getter failure retains closed state or instantly locks");
        records=events();int calls=field(vendor(),"calls").getInt(null);
        for(int i=0;i<100;i++)FlipState.poll();
        check(calls==field(vendor(),"calls").getInt(null) && events()==records,"failed API keeps retrying/logging");
        ClientLockTest.idle(121000);ClientLockTest.tick();check(SplashCanvas.locked(),"API failure loses idle fallback");
        System.out.println("PASS: API failure clears closed countdown/profile, disables native calls once, starts a fresh idle fallback");
    }
    public static void main(String[] args)throws Exception{
        try{if(args[0].equals("absent"))absence();else nativeCover();}
        finally{
            JimmUI.stopTaskForTimeString();Jimm.getTimerRef().cancel();
            Object canvas=ClientLockTest.canvas();((Timer)field(canvas.getClass(),"repeatTimer").get(canvas)).cancel();
        }
    }
}
