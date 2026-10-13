package jimm;

import java.lang.reflect.*;
import java.util.*;
import javax.microedition.lcdui.*;
import javax.microedition.media.Manager;
import jimm.comm.*;

public final class StartupAlertsTest {
    static void check(boolean ok,String message){if(!ok)throw new AssertionError(message);}
    static Field field(Class c,String name)throws Exception{Field f=c.getDeclaredField(name);f.setAccessible(true);return f;}
    public static void main(String[] args)throws Exception{
        try{
            field(Options.class,"options").set(null,new Hashtable());
            Method defaults=Options.class.getDeclaredMethod("setDefaults");defaults.setAccessible(true);defaults.invoke(null);
            Options.setBoolean(Options.OPTION_DISPLAY_DATE,false);
            Options.setLong(Options.OPTION_VIBRA_UNLOCKED_MS,100);
            new MainThread();new Icq();new SplashCanvas();new ContactList();new ChatHistory();
            DrawControls.VirtualList.setDisplay(Jimm.display);
            String uin="1000037";ContactItem contact=new ContactItem(37,0,uin,"test",false,true);
            ((Vector)field(ContactList.class,"cItems").get(null)).addElement(contact);
            int players=Manager.created;
            MessageAlerts.start();field(ContactList.class,"treeBuilt").setBoolean(null,false);
            for(int i=0;i<8;i++){
                MainThread.addMessageSerially(new PlainMessage(uin,"100500",1,"accumulated "+i,false));Display.flush();
            }
            check(ChatHistory.chatHistoryExists(uin) && contact.isContainingUnreadMessages(),"silent startup discards received messages/unread state");
            check(!ContactList.lastAlertAllowed && !field(ContactList.class,"needPlayMessNotif").getBoolean(null),"silent messages retain late roster sound");
            check(Manager.created==players && Manager.started.isEmpty() && Manager.toneCount==0 && Display.vibrations==0,
                "incoming startup batch allocates/plays sound or vibrates: created="+Manager.created+" started="+Manager.started.size()+" tones="+Manager.toneCount+" vibrations="+Display.vibrations);
            check(((Vector)field(ContactList.class,"soundQueue").get(null)).isEmpty() && field(ContactList.class,"soundTimer").get(null)==null,"silent startup starts sound queue/timer");
            long gate=field(ContactList.class,"lastMessageAlert").getLong(null);
            field(MessageAlerts.class,"quietUntil").setLong(null,System.currentTimeMillis()-1);
            ContactList.activateList();
            check(Manager.created==players && Manager.started.isEmpty(),"late roster activation replays silenced startup notification");
            check(field(ContactList.class,"lastMessageAlert").getLong(null)==gate,"silent batch consumed normal burst gate");
            MainThread.addMessageSerially(new PlainMessage(uin,"100500",1,"fresh message",false));Display.flush();
            check(Manager.started.size()==1 && Display.vibrations==1,"first fresh message after minute remains silent");
            ((Manager.Sound)Manager.started.lastElement()).finish();
            check(((Vector)field(ContactList.class,"soundQueue").get(null)).isEmpty(),"startup notifications remain queued");
            System.out.println("PASS: actual MainThread/ContactList/ChatHistory retain accumulated messages and unread markers, allocate no audio/timer, suppress delayed roster flag; first fresh post-minute message plays/vibrates normally");
        }finally{
            Jimm.getTimerRef().cancel();
            Timer sound=(Timer)field(ContactList.class,"soundTimer").get(null);if(sound!=null)sound.cancel();
            Object canvas=field(DrawControls.VirtualList.class,"virtualCanvas").get(null);
            ((Timer)field(canvas.getClass(),"repeatTimer").get(canvas)).cancel();
        }
    }
}
