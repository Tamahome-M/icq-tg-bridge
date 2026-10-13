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
        try{
            field(FlipWatch.class,"reportPending").setBoolean(null,false);
            field(FlipWatch.class,"pendingReason").set(null,null);
        }catch(NoSuchFieldException beforeDeferredReporting){}
        Arrays.fill((String[])field(ConnLog.class,"lines").get(null),null);
        field(ConnLog.class,"next").setInt(null,0);
    }
    // Allow the same regressions to reproduce UI-side blocking on 1.18.
    static void report(){
        try{Method m=FlipWatch.class.getDeclaredMethod("report");m.setAccessible(true);m.invoke(null);}
        catch(NoSuchMethodException beforeDeferredReporting){}
        catch(Exception failure){throw new AssertionError(failure);}
    }
    static String journal(){report();return ConnLog.text();}
    static int lines(){String s=journal();return s.length()==0?0:s.split("\n").length;}
    static void regularTick(long begin,long end){for(long t=begin;t<=end;t+=10000)FlipWatch.tick(t);}
    static void callbackUnderLock(Object lock,String why)throws Exception{
        Thread callback=new Thread(new Runnable(){public void run(){FlipWatch.ui(1000,"отрисовка",false);}});
        callback.setDaemon(true);boolean blocked;
        synchronized(lock){callback.start();callback.join(500);blocked=callback.isAlive();}
        callback.join(1000);check(!blocked,why);
    }
    static void callbacksDoNotWait()throws Exception{
        reset();callbackUnderLock(ConnLog.class,"paint callback waits for connection journal");
        reset();callbackUnderLock(Options.class,"paint callback reads date/settings while startup holds them");
        reset();callbackUnderLock(Jimm.display,"paint callback calls native display state");
        check(ConnLog.text().length()==0,"UI callback writes journal before timer");
        System.out.println("PASS: startup paint evidence never waits for journal, settings or native Display locks");
    }
    static void deferredReporting()throws Exception{
        reset();FlipWatch.ui(1000,"отрисовка",false);
        final Thread timer=new Thread(new Runnable(){public void run(){FlipWatch.tick(1000);}});timer.setDaemon(true);
        synchronized(ConnLog.class){
            timer.start();
            long deadline=System.currentTimeMillis()+1000;
            while(timer.getState()!=Thread.State.BLOCKED && timer.isAlive() && System.currentTimeMillis()<deadline)timer.join(10);
            check(timer.getState()==Thread.State.BLOCKED,"fixture did not block timer journal write");
            callbackUnderLock(new Object(),"journal writer retains FlipWatch lock and stalls UI");
        }
        timer.join(1000);check(!timer.isAlive(),"timer did not resume after journal release");
        reset();FlipWatch.ui(1000,"отрисовка",false);FlipWatch.background();FlipWatch.resume();FlipWatch.ui(2000,"клавиша",false);
        check(ConnLog.text().length()==0,"transitions write journal on UI thread");
        FlipWatch.tick(2000);check(lines()==1 && journal().contains("открыт: клавиша"),"quick transitions do not coalesce to latest state");
        // A journal failure remains optional and does not prevent later ticks.
        int saved=field(ConnLog.class,"next").getInt(null);
        field(ConnLog.class,"next").setInt(null,Integer.MAX_VALUE);
        try{FlipWatch.background();FlipWatch.tick(3000);}finally{field(ConnLog.class,"next").setInt(null,saved);}
        FlipWatch.resume();FlipWatch.ui(4000,"клавиша",false);FlipWatch.tick(4000);
        check(journal().contains("открыт: клавиша"),"failed journal prevents diagnostic recovery");
        System.out.println("PASS: timer journal write releases watcher lock; rapid transitions coalesce; logging failure does not stop ticks");
    }
    static void stalled()throws Exception{
        reset();Jimm.display.setCurrent(new Canvas());
        FlipWatch.ui(1000,"очередь интерфейса",true);FlipWatch.tick(1000);FlipWatch.expectUI(1000);
        regularTick(11000,21000);FlipWatch.tick(30999);
        check(lines()==1 && !journal().contains("закрыт"),"closed before thirty seconds");
        FlipWatch.tick(31000);
        check(journal().contains("флип? закрыт: интерфейс молчит 30 с; таймер жив"),"missing guessed closure");
        regularTick(41000,1011000);check(lines()==2,"idle closed state floods journal");
        FlipWatch.ui(1012000,"клавиша",false);
        check(lines()==3 && journal().contains("флип? открыт: клавиша (1011 с)"),"missing reopening evidence/duration");
        for(int i=0;i<1000;i++)FlipWatch.ui(1012000+i,"отрисовка",false);
        check(lines()==3,"paint/key callbacks flood journal");
        FlipWatch.tick(1022000);FlipWatch.tick(1032000);check(lines()==3,"active UI judged closed too early");
        System.out.println("PASS: 30-second UI silence with live timer, first key/paint recovery, transition-only journal");
    }
    static void healthy()throws Exception{
        reset();FlipWatch.tick(1000);
        for(long t=11000;t<1211000;t+=10000){
            FlipWatch.tick(t);FlipWatch.expectUI(t);FlipWatch.ui(t+1,"очередь интерфейса",true);
        }
        check(lines()==1 && !journal().contains("закрыт"),"healthy serial callbacks guessed closed");
        regularTick(1211000,2011000);check(lines()==1,"no expected UI event guessed closed");
        // A delayed first timer tick alone cannot establish continued execution.
        reset();FlipWatch.expectUI(1000);FlipWatch.tick(101000);
        check(lines()==0,"first tick guesses closed after whole-VM startup pause");
        regularTick(111000,131000);check(journal().contains("закрыт"),"fresh observation period never expires");
        reset();FlipWatch.ui(1000,"очередь",true);FlipWatch.tick(1000);FlipWatch.expectUI(1000);
        FlipWatch.tick(11000);FlipWatch.tick(131000);
        check(!journal().contains("закрыт") && journal().contains("неизвестно: задержка таймера"),"whole-VM pause guessed closed");
        regularTick(141000,161000);check(journal().contains("молчит 30 с"),"gap does not restart observation");
        reset();FlipWatch.tick(101000);FlipWatch.expectUI(101000);FlipWatch.tick(111000);FlipWatch.tick(100000);
        check(journal().contains("неизвестно") && !journal().contains("закрыт"),"backward clock jump guessed closed");
        System.out.println("PASS: active queue and no pending event stay open; startup/timer pauses and backwards clock restart observation");
    }
    static void backgroundAndErrors()throws Exception{
        reset();FlipWatch.ui(1000,"клавиша",false);FlipWatch.background();FlipWatch.background();
        int n=lines();check(journal().contains("неизвестно: приложение в фоне"),"explicit background reported closed");
        for(long t=1000;t<201000;t+=10000){FlipWatch.tick(t);FlipWatch.expectUI(t);FlipWatch.ui(t,"отрисовка",true);}
        check(lines()==n,"callbacks while backgrounded change flip guess");
        FlipWatch.resume();FlipWatch.ui(202000,"showNotify",false);
        check(journal().endsWith("флип? открыт: showNotify"),"resume/showNotify does not restore observation");
        n=lines();FlipWatch.resume();check(lines()==n,"already active bring-up resets inference and floods journal");
        reset();FlipWatch.tick(1000);FlipWatch.expectUI(1000);FlipWatch.queueFailed();FlipWatch.queueFailed();
        regularTick(11000,101000);check(lines()==1 && journal().contains("неизвестно: ошибка очереди"),"failed scheduling guessed closed or repeats");
        FlipWatch.expectUI(102000);FlipWatch.ui(102001,"очередь",true);
        check(lines()==2 && journal().contains("открыт: очередь"),"scheduling recovery does not resume guesses");
        // Native visibility must not be queried even while reporting.
        final int[] visibilityReads={0};
        reset();Jimm.display.setCurrent(new Canvas(){public boolean isShown(){visibilityReads[0]++;throw new OutOfMemoryError("native visibility");}});
        FlipWatch.ui(1000,"клавиша",false);FlipWatch.tick(1000);FlipWatch.expectUI(1000);regularTick(11000,31000);
        check(visibilityReads[0]==0,"diagnostics query native visibility");
        Jimm.display.setCurrent(new Canvas());FlipWatch.ui(32000,"клавиша",false);
        check(journal().contains("открыт: клавиша"),"diagnostics fail to resume after reopening");
        // Connection journal still retains exactly its original 24 entries.
        reset();for(int i=0;i<30;i++){FlipWatch.background();report();FlipWatch.resume();report();FlipWatch.ui(i,"клавиша",false);report();}
        check(lines()==24,"flip diagnostics grow the connection journal");
        System.out.println("PASS: background, failed scheduling, no native visibility reads, recovery and unchanged 24-entry journal capacity");
    }
    static void integration()throws Exception{
        reset();Jimm.display.setCurrent(new Canvas());
        Constructor ctor=MainThread.class.getDeclaredConstructor();ctor.setAccessible(true);ctor.newInstance();
        final int[] events={0};Runnable work=new Runnable(){public void run(){events[0]++;}};
        long t=System.currentTimeMillis();FlipWatch.tick(t);
        for(int i=0;i<64;i++)MainThread.runSerially(work);
        regularTick(t+10000,t+20000);FlipWatch.tick(t+31000);
        check(journal().contains("закрыт"),"real full UI queue not observed");
        check(!SplashCanvas.locked(),"flip inference itself locks the app");
        MainThread.showTime();Display.flush();
        check(events[0]==64 && journal().contains("открыт: очередь интерфейса"),"UI resume drops events or lacks reopening journal");
        check(!SplashCanvas.locked(),"inference UI recovery alters keylock");
        reset();Display.fail=true;MainThread.runSerially(work);
        check(journal().contains("неизвестно: ошибка очереди интерфейса"),"real callSerially failure not reported");
        Display.fail=false;MainThread.showTime();Display.flush();
        check(events[0]==65 && journal().contains("открыт: очередь интерфейса"),"failed callSerially cannot retry");
        System.out.println("PASS: real MainThread full queue, clock coalescing, callSerially OOM and event-preserving recovery; diagnostic never changes keylock");
    }
    public static void main(String[] args)throws Exception{
        try{
            field(Options.class,"options").set(null,new Hashtable());
            Method m=Options.class.getDeclaredMethod("setDefaults");m.setAccessible(true);m.invoke(null);
            Options.setLong(Options.OPTION_AUTOLOCK_MINUTES,0);
            callbacksDoNotWait();deferredReporting();stalled();healthy();backgroundAndErrors();integration();
        }finally{
            Jimm.getTimerRef().cancel();
            Object canvas=field(DrawControls.VirtualList.class,"virtualCanvas").get(null);
            ((Timer)field(canvas.getClass(),"repeatTimer").get(canvas)).cancel();
        }
    }
}
