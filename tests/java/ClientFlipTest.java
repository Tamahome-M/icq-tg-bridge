package jimm;

import java.lang.reflect.*;
import java.util.*;
import javax.microedition.lcdui.*;

public final class ClientFlipTest {
    static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
    static Field field(Class c,String name)throws Exception{Field f=c.getDeclaredField(name);f.setAccessible(true);return f;}
    static void reset()throws Exception{
        field(FlipWatch.class,"state").setInt(null,0);
        field(FlipWatch.class,"lastTick").setLong(null,0);
        field(FlipWatch.class,"waitingSince").setLong(null,0);
        field(FlipWatch.class,"expected").setBoolean(null,false);
        Arrays.fill((String[])field(ConnLog.class,"lines").get(null),null);
        field(ConnLog.class,"next").setInt(null,0);
    }
    static int lines(){String s=ConnLog.text();return s.length()==0?0:s.split("\n").length;}
    static void regularTick(long begin,long end){for(long t=begin;t<=end;t+=10000)FlipWatch.tick(t);}
    static void stalled()throws Exception{
        reset();Jimm.display.setCurrent(new Canvas());
        FlipWatch.ui(1000,"очередь интерфейса",true);FlipWatch.tick(1000);FlipWatch.expectUI(1000);
        regularTick(11000,21000);FlipWatch.tick(30999);
        check(lines()==1 && !ConnLog.text().contains("закрыт"),"closed before thirty seconds");
        FlipWatch.tick(31000);
        check(ConnLog.text().contains("флип? закрыт: интерфейс молчит 30 с; таймер жив; isShown=да"),"missing guessed closure with true isShown");
        regularTick(41000,1011000);check(lines()==2,"idle closed state floods journal");
        FlipWatch.ui(1012000,"клавиша",false);
        check(lines()==3 && ConnLog.text().contains("флип? открыт: клавиша (1011 с)"),"missing reopening evidence/duration");
        for(int i=0;i<1000;i++)FlipWatch.ui(1012000+i,"отрисовка",false);
        check(lines()==3,"paint/key callbacks flood journal");
        FlipWatch.tick(1022000);FlipWatch.tick(1032000);check(lines()==3,"active UI judged closed too early");
        System.out.println("PASS: 30-second UI silence with live timer, true isShown, first key/paint recovery, transition-only journal");
    }
    static void healthy()throws Exception{
        reset();FlipWatch.tick(1000);
        for(long t=11000;t<1211000;t+=10000){
            FlipWatch.tick(t);FlipWatch.expectUI(t);FlipWatch.ui(t+1,"очередь интерфейса",true);
        }
        check(lines()==1 && !ConnLog.text().contains("закрыт"),"healthy serial callbacks guessed closed");
        regularTick(1211000,2011000);check(lines()==1,"no expected UI event guessed closed");
        // A delayed first timer tick alone cannot establish continued execution.
        reset();FlipWatch.expectUI(1000);FlipWatch.tick(101000);
        check(lines()==0,"first tick guesses closed after whole-VM startup pause");
        regularTick(111000,131000);check(ConnLog.text().contains("закрыт"),"fresh observation period never expires");
        reset();FlipWatch.ui(1000,"очередь",true);FlipWatch.tick(1000);FlipWatch.expectUI(1000);
        FlipWatch.tick(11000);FlipWatch.tick(131000);
        check(!ConnLog.text().contains("закрыт") && ConnLog.text().contains("неизвестно: задержка таймера"),"whole-VM pause guessed closed");
        regularTick(141000,161000);check(ConnLog.text().contains("молчит 30 с"),"gap does not restart observation");
        reset();FlipWatch.tick(101000);FlipWatch.expectUI(101000);FlipWatch.tick(111000);FlipWatch.tick(100000);
        check(ConnLog.text().contains("неизвестно") && !ConnLog.text().contains("закрыт"),"backward clock jump guessed closed");
        System.out.println("PASS: active queue and no pending event stay open; startup/timer pauses and backwards clock restart observation");
    }
    static void backgroundAndErrors()throws Exception{
        reset();FlipWatch.ui(1000,"клавиша",false);FlipWatch.background();FlipWatch.background();
        int n=lines();check(ConnLog.text().contains("неизвестно: приложение в фоне"),"explicit background reported closed");
        for(long t=1000;t<201000;t+=10000){FlipWatch.tick(t);FlipWatch.expectUI(t);FlipWatch.ui(t,"отрисовка",true);}
        check(lines()==n,"callbacks while backgrounded change flip guess");
        FlipWatch.resume();FlipWatch.ui(202000,"showNotify",false);
        check(ConnLog.text().endsWith("флип? открыт: showNotify; isShown=да"),"resume/showNotify does not restore observation");
        n=lines();FlipWatch.resume();check(lines()==n,"already active bring-up resets inference and floods journal");
        reset();FlipWatch.tick(1000);FlipWatch.expectUI(1000);FlipWatch.queueFailed();FlipWatch.queueFailed();
        regularTick(11000,101000);check(lines()==1 && ConnLog.text().contains("неизвестно: ошибка очереди"),"failed scheduling guessed closed or repeats");
        FlipWatch.expectUI(102000);FlipWatch.ui(102001,"очередь",true);
        check(lines()==2 && ConnLog.text().contains("открыт: очередь"),"scheduling recovery does not resume guesses");
        // Native visibility/OOM is optional diagnostic evidence, never fatal.
        reset();Jimm.display.setCurrent(new Canvas(){public boolean isShown(){throw new OutOfMemoryError("native visibility");}});
        FlipWatch.ui(1000,"клавиша",false);FlipWatch.tick(1000);FlipWatch.expectUI(1000);regularTick(11000,31000);
        Jimm.display.setCurrent(new Canvas());FlipWatch.ui(32000,"клавиша",false);
        check(ConnLog.text().contains("открыт: клавиша"),"diagnostic OOM prevents recovery");
        // Connection journal still retains exactly its original 24 entries.
        reset();for(int i=0;i<30;i++){FlipWatch.background();FlipWatch.resume();FlipWatch.ui(i,"клавиша",false);}
        check(lines()==24,"flip diagnostics grow the connection journal");
        System.out.println("PASS: background, failed scheduling, OOM, recovery and unchanged 24-entry journal capacity");
    }
    static void integration()throws Exception{
        reset();Jimm.display.setCurrent(new Canvas());
        Constructor ctor=MainThread.class.getDeclaredConstructor();ctor.setAccessible(true);ctor.newInstance();
        final int[] events={0};Runnable work=new Runnable(){public void run(){events[0]++;}};
        long t=System.currentTimeMillis();FlipWatch.tick(t);
        for(int i=0;i<64;i++)MainThread.runSerially(work);
        regularTick(t+10000,t+20000);FlipWatch.tick(t+31000);
        check(ConnLog.text().contains("закрыт"),"real full UI queue not observed");
        check(!SplashCanvas.locked(),"flip inference itself locks the app");
        MainThread.showTime();Display.flush();
        check(events[0]==64 && ConnLog.text().contains("открыт: очередь интерфейса"),"UI resume drops events or lacks reopening journal");
        check(!SplashCanvas.locked(),"inference UI recovery alters keylock");
        reset();Display.fail=true;MainThread.runSerially(work);
        check(ConnLog.text().contains("неизвестно: ошибка очереди интерфейса"),"real callSerially failure not reported");
        Display.fail=false;MainThread.showTime();Display.flush();
        check(events[0]==65 && ConnLog.text().contains("открыт: очередь интерфейса"),"failed callSerially cannot retry");
        System.out.println("PASS: real MainThread full queue, clock coalescing, callSerially OOM and event-preserving recovery; diagnostic never changes keylock");
    }
    public static void main(String[] args)throws Exception{
        try{
            field(Options.class,"options").set(null,new Hashtable());
            Method m=Options.class.getDeclaredMethod("setDefaults");m.setAccessible(true);m.invoke(null);
            Options.setLong(Options.OPTION_AUTOLOCK_MINUTES,0);
            stalled();healthy();backgroundAndErrors();integration();
        }finally{
            Jimm.getTimerRef().cancel();
            Object canvas=field(DrawControls.VirtualList.class,"virtualCanvas").get(null);
            ((Timer)field(canvas.getClass(),"repeatTimer").get(canvas)).cancel();
        }
    }
}
