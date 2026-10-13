package jimm;

import java.lang.reflect.*;
import java.util.*;
import javax.microedition.media.*;
import javax.microedition.media.control.ToneControl;
import jimm.comm.Icq;

public final class DisconnectAlertsTest {
    static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
    static Field field(Class c,String name)throws Exception{Field f=c.getDeclaredField(name);f.setAccessible(true);return f;}
    static Manager.Sound last(){return (Manager.Sound)Manager.started.lastElement();}
    static Vector queue()throws Exception{return (Vector)field(ContactList.class,"soundQueue").get(null);}
    static void connected()throws Exception{
        Icq.setDisconnected(false);Method m=Icq.class.getDeclaredMethod("setConnected");m.setAccessible(true);m.invoke(null);
    }
    static void loss(){JimmException.handleException(new JimmException(120,0,JimmException.ICQ_MAIN));}
    static void tone(int volume){
        Manager.Sound p=last();byte[] seq=p.sequence;
        check(p.type.equals("audio/x-tone-seq") && p.bytes.length==0 && p.volume==volume,"disconnect used sampled audio/wrong volume");
        check(seq!=null && seq.length==16 && seq[0]==ToneControl.VERSION && seq[1]==1 &&
            seq[2]==ToneControl.TEMPO && seq[4]==ToneControl.RESOLUTION,"invalid tone sequence header");
        int notes=0,previous=128,duration=0;
        for(int i=6;i<seq.length;i+=2){
            check(seq[i+1]>0,"invalid tone duration");duration+=seq[i+1];
            if(seq[i]>=0){check(seq[i]<previous,"notes do not descend");previous=seq[i];notes++;}
            else check(seq[i]==ToneControl.SILENCE,"invalid sequence event");
        }
        check(notes==3 && duration*240000/(seq[5]*seq[3]*4)==1000,"signal is not three notes/one second");
    }
    static void recovery()throws Exception{
        MessageAlerts.start();check(!MessageAlerts.allowed(),"startup mute fixture inactive");
        Options.setLong(Options.OPTION_DISCONNECT_VOL,30);
        int players=Manager.created,count=Manager.started.size(),retries=Threads.retries;
        connected();loss();tone(30);
        check(!Icq.isConnected() && !Icq.isDisconnected() && Threads.retries==retries+1,"sound broke reconnect recovery");
        check(Manager.created==players+1 && Manager.started.size()==count+1,"one loss starts extra players");
        for(int i=0;i<5;i++)loss();
        check(Manager.created==players+1 && queue().isEmpty(),"duplicate errors/login retries beep repeatedly");
        Manager.Sound sound=last();sound.finish();
        check(sound.state==Player.CLOSED && field(ContactList.class,"soundWatch").get(null)==null,"completed tone retains player/watch");
        connected();loss();tone(30);last().finish();
        check(Manager.started.size()==count+2,"next established session does not warn again");
        players=Manager.created;connected();Icq.disconnect(false);loss();
        check(Manager.created==players && queue().isEmpty(),"manual disconnect/cancel makes a warning");
        connected();JimmException.handleException(new JimmException(120,0,JimmException.ICQ_BART));
        JimmException.handleException(new JimmException(140,0,false));
        check(Icq.isConnected() && Manager.created==players,"avatar/media error sounds like main disconnect");
        Icq.disconnect(true);
        System.out.println("PASS: actual established-session loss plays three descending notes during startup silence; duplicates, failed retries, manual disconnect and service errors stay quiet; reconnect and player release preserved");
    }
    static void disabled()throws Exception{
        int players=Manager.created,count=Manager.started.size(),beeps=Manager.toneCount;
        for(int mode=0;mode<3;mode++){
            Options.setLong(Options.OPTION_DISCONNECT_SOUND,mode==0?0:1);
            Options.setBoolean(Options.OPTION_SILENT_MODE,mode==1);
            Options.setLong(Options.OPTION_DISCONNECT_VOL,mode==2?0:30);
            connected();loss();
        }
        check(Manager.created==players && Manager.started.size()==count && Manager.toneCount==beeps && queue().isEmpty(),"off/global silence/zero volume allocate or queue sound");
        Options.setBoolean(Options.OPTION_SILENT_MODE,false);Options.setLong(Options.OPTION_DISCONNECT_VOL,1000);
        connected();loss();tone(100);last().finish();
        System.out.println("PASS: disconnect off, global silence and zero volume allocate nothing; saved volume is clamped");
    }
    static void unsupported()throws Exception{
        Options.setLong(Options.OPTION_DISCONNECT_VOL,40);
        for(int mode=0;mode<3;mode++){
            Manager.noToneControl=mode==0;Manager.failToneSequence=mode==1;Manager.failToneCreate=mode==2;
            int count=Manager.started.size(),beeps=Manager.toneCount,players=Manager.tonePlayers.size(),retries=Threads.retries;
            connected();loss();
            check(Manager.started.size()==count && Manager.toneCount==beeps+1 && Manager.toneVolume==40,"unavailable sequencer does not fall back to one cheap beep");
            if(Manager.tonePlayers.size()>players)
                check(((Manager.Sound)Manager.tonePlayers.lastElement()).state==Player.CLOSED,"failed tone player leaked");
            check(Threads.retries==retries+1 && !Icq.isConnected() && queue().isEmpty() &&
                field(ContactList.class,"playerFree").getBoolean(null) && field(ContactList.class,"soundWatch").get(null)==null,"tone failure blocks recovery or leaves audio busy");
        }
        Manager.noToneControl=false;Manager.failToneSequence=false;Manager.failToneCreate=false;
        System.out.println("PASS: missing ToneControl, rejected sequence and native OutOfMemoryError close failed players, fall back without MP3 and preserve retry scheduling");
    }
    static void priority()throws Exception{
        field(MessageAlerts.class,"quietUntil").setLong(null,-1);
        Options.setLong(Options.OPTION_DISCONNECT_VOL,35);
        ContactList.playSoundNotification(ContactList.SOUND_TYPE_MESSAGE);Manager.Sound message=last();
        int count=Manager.started.size(),players=Manager.created;
        ContactList.playSoundNotification(ContactList.SOUND_TYPE_MESSAGE);
        connected();loss();
        for(int i=0;i<300;i++)ContactList.playSoundNotification(ContactList.SOUND_TYPE_MESSAGE);
        check(queue().size()==2 && queue().elementAt(0).equals(Manager.TONE_DEVICE_LOCATOR) &&
            Manager.started.size()==count && Manager.created==players,"message burst overwrites connection warning, grows queue or overlaps audio");
        message.finish();tone(35);Manager.Sound warning=last();
        check(queue().isEmpty() && Manager.started.size()==count+1,"queued warning does not start once");
        ContactList list=(ContactList)field(ContactList.class,"_this").get(null);
        list.playerUpdate(message,PlayerListener.END_OF_MEDIA,null);
        check(!field(ContactList.class,"playerFree").getBoolean(null),"stale MP3 end frees active tone player");
        ((TimerTask)field(ContactList.class,"soundWatch").get(null)).run();
        check(warning.state==Player.CLOSED && field(ContactList.class,"playerFree").getBoolean(null) && queue().isEmpty(),"missing tone END_OF_MEDIA retains native player");
        ContactList.playSoundNotification(ContactList.SOUND_TYPE_MESSAGE);last().finish();
        System.out.println("PASS: one existing player/timer/queue routes MP3 and tones; a 300-message burst cannot replace pending warning; stale callbacks and absent end events release the correct player");
    }
    public static void main(String[] args)throws Exception{
        try{
            field(Options.class,"options").set(null,new Hashtable());Method defaults=Options.class.getDeclaredMethod("setDefaults");defaults.setAccessible(true);defaults.invoke(null);
            Options.setBoolean(Options.OPTION_DISPLAY_DATE,false);Options.setBoolean(Options.OPTION_RECONNECT,true);
            new MainThread();new Icq();new SplashCanvas();new ContactList();new ChatHistory();
            DrawControls.VirtualList.setDisplay(Jimm.display);
            recovery();disabled();unsupported();priority();
        }finally{
            Jimm.getTimerRef().cancel();Timer sound=(Timer)field(ContactList.class,"soundTimer").get(null);if(sound!=null)sound.cancel();
            Object canvas=field(DrawControls.VirtualList.class,"virtualCanvas").get(null);
            ((Timer)field(canvas.getClass(),"repeatTimer").get(canvas)).cancel();
        }
    }
}
