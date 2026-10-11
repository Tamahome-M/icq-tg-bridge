package jimm;

import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.TimeUnit;
import javax.microedition.lcdui.*;
import javax.microedition.media.*;
import jimm.comm.RequestBartAction;

public final class ClientMediaLifecycleTest {
    static boolean baseline;
    static final byte[] CLIP=new byte[4000];
    static void check(boolean ok,String message){if(!ok)throw new AssertionError(message);}
    static Field f(Class type,String name)throws Exception{Field field=type.getDeclaredField(name);field.setAccessible(true);return field;}
    static Object call(Object object,String name,Class[] args,Object... values)throws Exception{
        Method method=object.getClass().getDeclaredMethod(name,args);method.setAccessible(true);return method.invoke(object,values);
    }
    static final class Back implements JimmScreen {
        int returns;
        public void activate(){returns++;Jimm.display.setCurrent(null);}public boolean isScreenActive(){return false;}
    }
    static MediaPlayer open(int type,Back back){
        if(type==RequestBartAction.BART_VOICE)MediaPlayer.showVoice("1000037",new byte[16],back);
        else MediaPlayer.show("1000037",new byte[16],back);
        return (MediaPlayer)Jimm.display.getCurrent();
    }
    static void close(MediaPlayer p){p.commandAction(JimmUI.cmdBack,p);}
    static void start(MediaPlayer screen,Manager.Fake player)throws Exception{
        call(screen,"start",new Class[]{Player.class},player);
    }
    static void join(Thread worker)throws Exception{check(worker!=null,"no playback worker");worker.join(2500);check(!worker.isAlive(),"playback worker did not finish");}
    static Manager.Fake ready(MediaPlayer screen)throws Exception{
        long until=System.currentTimeMillis()+2500;
        while(System.currentTimeMillis()<until){
            Manager.Fake p=(Manager.Fake)f(MediaPlayer.class,"player").get(screen);
            if(p!=null && p.state==Player.STARTED)return p;
            Thread.sleep(5);
        }
        throw new AssertionError("player did not become ready: "+f(MediaPlayer.class,"status").get(screen));
    }
    static void pulse(MediaPlayer p)throws Exception{
        TimerTask task=(TimerTask)f(MediaPlayer.class,"clockTask").get(p);check(task!=null,"media clock missing");task.run();Display.flush();
    }
    static void threadCount()throws Exception{
        Jimm.getTimerRef();Class.forName("jimm.MediaPlayer");
        java.lang.management.ThreadMXBean threads=java.lang.management.ManagementFactory.getThreadMXBean();
        long before=threads.getTotalStartedThreadCount();
        MediaPlayer screen=open(RequestBartAction.BART_VOICE,new Back());Manager.Fake player=Manager.make();start(screen,player);
        long count=threads.getTotalStartedThreadCount()-before;
        System.out.println("METRIC actual media housekeeping threads: "+count);
        if(!baseline)check(count==0,"waiting/time/backlight still create private threads");
        close(screen);check(player.state==Player.CLOSED,"close retained player");
    }
    static void clock()throws Exception{
        if(baseline)return;
        Back back=new Back();MediaPlayer screen=open(RequestBartAction.BART_VOICE,back);
        TimerTask first=(TimerTask)f(MediaPlayer.class,"clockTask").get(screen);
        for(int i=0;i<100;i++)first.run();check(Display.queued.size()==1,"busy UI accumulates clock callbacks");
        f(MediaPlayer.class,"waitingSince").setLong(screen,System.currentTimeMillis()-4200);Display.flush();
        check(f(MediaPlayer.class,"waited").getInt(screen)==4,"wait counter depends on UI tick count");
        screen.onBartProgress(1,3);String status=(String)f(MediaPlayer.class,"status").get(screen);first.run();Display.flush();
        check(status.equals(f(MediaPlayer.class,"status").get(screen)),"waiting clock overwrote multipart progress");
        check(f(first.getClass(),"owner").get(first)==null,"cancelled waiting task retains the screen");
        Manager.Fake player=Manager.make();start(screen,player);TimerTask active=(TimerTask)f(MediaPlayer.class,"clockTask").get(screen);
        check(active!=null && active!=first,"playback did not restart the shared clock");
        int paints=screen.paints;pulse(screen);check(screen.paints==paints+1,"running voice clock did not redraw");
        call(screen,"toggle",new Class[0]);paints=screen.paints;pulse(screen);check(screen.paints==paints,"paused voice repaints continuously");
        call(screen,"toggle",new Class[0]);pulse(screen);screen.playerUpdate(player,PlayerListener.END_OF_MEDIA,null);
        paints=screen.paints;pulse(screen);check(screen.paints==paints,"finished voice repaints continuously");
        call(screen,"toggle",new Class[0]);check(player.state==Player.STARTED && !f(MediaPlayer.class,"finished").getBoolean(screen),"replay failed");
        player.at=4000000;call(screen,"rewind",new Class[0]);check(player.at==0,"rewind failed");
        int lights=Jimm.lights;f(MediaPlayer.class,"lastLight").setLong(screen,System.currentTimeMillis()-4100);pulse(screen);
        check(Jimm.lights==lights+1,"active player lost backlight renewal");
        Jimm.display.setCurrent(null);paints=screen.paints;lights=Jimm.lights;f(MediaPlayer.class,"lastLight").setLong(screen,0);
        active.run();check(Display.queued.isEmpty() && screen.paints==paints && Jimm.lights==lights,"hidden player redraws or lights the display");
        screen.activate();active.run();check(Display.queued.size()==1,"visible player clock did not resume");
        close(screen);paints=screen.paints;Display.flush();active.run();
        check(player.state==Player.CLOSED && screen.paints==paints && f(active.getClass(),"owner").get(active)==null,
            "stale clock callback changed closed media or retained it");
        close(screen);check(back.returns==1,"repeated close returned twice");
        System.out.println("PASS: shared clock coalesces UI work; elapsed wait/progress, pause/end/replay/rewind, hidden display and stale/duplicate close");
        Jimm.clock.fail=true;screen=open(RequestBartAction.BART_VOICE,new Back());player=Manager.make();start(screen,player);
        check(player.state==Player.STARTED && f(MediaPlayer.class,"clockTask").get(screen)==null,"timer OOM broke playback");
        close(screen);Jimm.clock.fail=false;
        System.out.println("PASS: timer allocation failure preserves playback without creating a replacement thread");
        screen=open(RequestBartAction.BART_VOICE,new Back());
        TimerTask queueTask=(TimerTask)f(MediaPlayer.class,"clockTask").get(screen);Display.fail=true;queueTask.run();Display.fail=false;
        check(f(MediaPlayer.class,"clockTask").get(screen)==null && f(queueTask.getClass(),"owner").get(queueTask)==null
            && !f(MediaPlayer.class,"clockQueued").getBoolean(screen),"UI queue OOM escaped the shared timer or retained the screen");
        player=Manager.make();start(screen,player);Canvas.failRepaint=true;pulse(screen);
        check(player.state==Player.STARTED && f(MediaPlayer.class,"clockTask").get(screen)==null,"clock repaint OOM broke playback or escaped UI callback");
        close(screen);
        System.out.println("PASS: clock queue/repaint OOM cannot terminate the shared timer or playback");
    }
    static void latePlayer(int stage)throws Exception{
        Manager.created.removeAllElements();Manager.Gate gate=new Manager.Gate();Manager.gate=gate;Manager.stage=stage;
        Back back=new Back();MediaPlayer screen=open(RequestBartAction.BART_VOICE,back);screen.onBart(CLIP);
        check(gate.entered.await(2,TimeUnit.SECONDS),"player did not enter blocked stage "+stage);
        close(screen);gate.release.countDown();join(Manager.worker);Manager.stage=0;
        boolean leaked=false;
        for(Object item:Manager.created){Manager.Fake player=(Manager.Fake)item;if(player.state!=Player.CLOSED || player.starts!=0)leaked=true;}
        System.out.println("METRIC player after Back, blocked stage "+stage+": leak/start="+leaked);
        if(!baseline)check(!leaked && back.returns==1 && f(MediaPlayer.class,"current").get(null)==null && TempFiles.files.isEmpty(),
            "late setup reopened player, retained file or navigated after Back");
        call(screen,"stop",new Class[0]);
    }
    static void replaceWhileWriting(boolean streamed)throws Exception{
        Manager.created.removeAllElements();Manager.Gate gate=new Manager.Gate();TempFiles.writeGate=gate;
        MediaPlayer old=open(RequestBartAction.BART_VOICE,new Back());
        if(streamed)check(old.onBartPart(CLIP,0,CLIP.length,1,2),"stream part refused");else old.onBart(CLIP);
        check(gate.entered.await(2,TimeUnit.SECONDS),"writer did not block");Thread writer=TempFiles.writer;close(old);
        MediaPlayer current=open(RequestBartAction.BART_VOICE,new Back());current.onBart(CLIP);
        Manager.Fake player=ready(current);
        check(player!=null,"replacement did not open");String path=(String)f(MediaPlayer.class,"filePath").get(current);
        gate.release.countDown();join(writer);
        check(TempFiles.files.containsKey(path) && player.state==Player.STARTED && f(MediaPlayer.class,"current").get(null)==current,
            "old writer deleted or closed the replacement's file/player");
        close(current);check(TempFiles.files.isEmpty(),"closed writers retain temporary clips");
        System.out.println("PASS: cancelled "+(streamed?"stream":"whole clip")+" writer cannot delete the replacement's unique file");
    }
    static void failures()throws Exception{
        Manager.oom=true;MediaPlayer screen=open(RequestBartAction.BART_VOICE,new Back());Manager.Fake player=Manager.make();
        try{start(screen,player);throw new AssertionError("OOM not propagated");}catch(InvocationTargetException e){check(e.getCause() instanceof OutOfMemoryError,"wrong decoder error");}
        check(player.state==Player.CLOSED && f(MediaPlayer.class,"player").get(screen)==null,"decoder OOM retained its native player");
        close(screen);Manager.oom=false;
        Manager.failFile=true;screen=open(RequestBartAction.BART_VOICE,new Back());screen.onBart(CLIP);ready(screen);join(Manager.worker);
        close(screen);Manager.failFile=false;
        Manager.failFile=true;screen=open(RequestBartAction.BART_VOICE,new Back());
        check(screen.onBartPart(CLIP,0,CLIP.length,1,1),"streamed fallback part refused");screen.onBartDone(true);ready(screen);
        join(TempFiles.writer);check(TempFiles.files.isEmpty(),"stream fallback retained its failed file");close(screen);Manager.failFile=false;
        TempFiles.available=false;screen=open(RequestBartAction.BART_VOICE,new Back());
        check(!screen.onBartPart(CLIP,0,CLIP.length,1,1),"missing root accepted streaming parts");screen.onBart(CLIP);ready(screen);
        close(screen);TempFiles.available=true;
        screen=open(RequestBartAction.BART_VIDEO,new Back());screen.onBart(null);
        check(f(MediaPlayer.class,"clockTask").get(screen)==null,"failed response retains waiting task");close(screen);
        System.out.println("PASS: decoder OOM frees native player; whole/streamed file errors and absent root retain memory fallback without leaked files; failed response releases waiting task");
    }
    public static void main(String[] args)throws Exception{
        baseline=args[0].equals("baseline");
        try{
            threadCount();clock();latePlayer(1);
            if(!baseline){latePlayer(2);latePlayer(3);latePlayer(4);replaceWhileWriting(false);replaceWhileWriting(true);failures();}
        }finally{
            Manager.Gate gate=Manager.gate;if(gate!=null)gate.release.countDown();
            gate=TempFiles.writeGate;if(gate!=null)gate.release.countDown();
            MediaPlayer current=(MediaPlayer)f(MediaPlayer.class,"current").get(null);if(current!=null)close(current);
            Jimm.getTimerRef().cancel();
        }
    }
}
