package jimm;

import java.io.*;
import java.lang.reflect.*;
import java.util.*;
import javax.microedition.lcdui.*;
import javax.microedition.media.Manager;
import DrawControls.*;
import jimm.comm.*;
import jimm.comm.connections.Connection;

public final class QuietMessagesTest {
    static boolean v8;
    static void check(boolean b,String text){if(!b)throw new AssertionError(text);}
    static Field f(Class c,String name)throws Exception{Field f=c.getDeclaredField(name);f.setAccessible(true);return f;}
    static Method m(Class c,String name,Class... args)throws Exception{Method m=c.getDeclaredMethod(name,args);m.setAccessible(true);return m;}
    static class Socket extends Connection {
        Vector packets=new Vector();
        public void sendPacket(Packet p){packets.addElement(p);}
        public void forceDisconnect(){}
    }
    static Socket socket=new Socket();
    static byte[] blob(DataInputStream in)throws Exception{byte[] b=new byte[in.readInt()];in.readFully(b);return b;}
    static void wire(String path)throws Exception{
        check(Icq.CAP_TMM.length==16 && Icq.CAP_TMM[6]==(v8?1:0),"capability leaks to legacy client or has wrong bit");
        try{Message.class.getMethod("isSilent");check(v8,"legacy message retains quiet implementation");}
        catch(NoSuchMethodException absent){check(!v8,"V8 quiet flag missing");}
        Vector tasks=(Vector)f(MainThread.class,"mainThreadTasks").get(null);
        jimm.comm.ActionListener listener=new jimm.comm.ActionListener();
        Method forward=m(jimm.comm.ActionListener.class,"forward",Packet.class);
        DataInputStream in=new DataInputStream(new FileInputStream(path));int count=in.readUnsignedShort();
        for(int i=0;i<count;i++){
            String name=new String(blob(in),"UTF-8");byte[] packet=blob(in);boolean quiet=in.readBoolean();byte[] ack=blob(in);
            tasks.removeAllElements();Display.queued.removeAllElements();socket.packets.removeAllElements();
            forward.invoke(listener,new SnacPacket(4,7,1,new byte[0],packet));
            check(tasks.size()==2,"packet did not queue exactly one message: "+name);
            Message message=(Message)((Object[])tasks.elementAt(1))[0];
            check("Тихое сообщение".equals(message.getText()),"text lost: "+name);
            if(v8)check(((Boolean)Message.class.getMethod("isSilent").invoke(message)).booleanValue()==quiet,"quiet flag parse: "+name);
            check(socket.packets.size()==(ack.length==0?0:1),"ACK suppressed by quiet flag: "+name);
            if(ack.length!=0)check(Arrays.equals(ack,((SnacPacket)socket.packets.firstElement()).getDataRef()),"ACK changed: "+name);
        }
        tasks.removeAllElements();Display.queued.removeAllElements();f(MainThread.class,"queueScheduled").setBoolean(null,false);f(MainThread.class,"queuedBytes").setInt(null,0);in.close();
        System.out.println("PASS: channel 1/2 exact silent TLV, malformed/unknown values ignored, text and ACKs preserved; variant capability");
    }
    static PlainMessage message(String uin,boolean quiet)throws Exception{
        PlainMessage message=new PlainMessage(uin,"100500",1,"message",false);
        if(v8)Message.class.getMethod("setSilent",Boolean.TYPE).invoke(message,Boolean.valueOf(quiet));return message;
    }
    static void notifications()throws Exception{
        String uin="1000037";
        ContactItem contact=new ContactItem(37,7,uin,"Quiet public",false,true);
        ContactListGroupItem parent=new ContactListGroupItem(6,"Telegram");
        ContactListGroupItem group=new ContactListGroupItem(7,"Telegram/Publics");group.setParent(parent);
        ((Vector)f(ContactList.class,"cItems").get(null)).addElement(contact);
        Vector groups=(Vector)f(ContactList.class,"gItems").get(null);groups.addElement(parent);groups.addElement(group);
        ContactList.activateList();
        ChatHistory.getChatHistoryAt(uin); // Must not create or select a chat yet.
        if(!v8){
            ChatHistory.openChat(contact);Display.flush();
            Class chat=Class.forName("jimm.ChatTextList");
            try{f(chat,"cmdQuietDelivery");throw new AssertionError("legacy quiet menu retained");}catch(NoSuchFieldException expected){}
            return;
        }
        f(MessageAlerts.class,"quietUntil").setLong(null,-1);
        f(ContactList.class,"lastLoginTime").setLong(null,0);
        f(ContactList.class,"lastMessageAlert").setLong(null,0);
        Options.setBoolean(Options.OPTION_CREEPING_LINE,true);
        Options.setLong(Options.OPTION_MESS_UNLOCKED_MODE,1);
        Options.setInt(Options.OPTION_MESS_NOTIF_MODE,1);
        Options.setLong(Options.OPTION_VIBRA_UNLOCKED_MS,100);
        Options.setLong(Options.OPTION_VIBRA_LOCKED_MS,100);
        SplashCanvas.lock();int before=f(SplashCanvas.class,"availableMessages").getInt(null);
        int players=Manager.created,flashes=Display.flashes;
        f(ContactList.class,"treeBuilt").setBoolean(null,false);
        for(int i=0;i<3;i++){MainThread.addMessageSerially(message(uin,true));Display.flush();}
        check(contact.isContainingUnreadMessages(),"silent message lost unread flag");
        check(contact.getLeftImage(false)==JimmUI.eventPlainMessageImg,"silent message lacks normal new-message icon");
        check(group.getMessCount()==1 && parent.getMessCount()==1,"silent unread group counters missing or counted messages instead of chats");
        check(f(SplashCanvas.class,"availableMessages").getInt(null)==before+3,"lockscreen lost unread count");
        check(ChatHistory.getChatHistoryAt(uin).messageCount()==3,"quiet texts not retained");
        check(!ContactList.lastAlertAllowed && f(ContactList.class,"lastMessageAlert").getLong(null)==0,"quiet message consumes burst gate");
        check(Manager.created==players && Manager.toneCount==0 && Manager.started.isEmpty() && Display.vibrations==0,"quiet delivery allocated audio, sounded or vibrated");
        check(f(JimmUI.class,"flashTimerTask").get(null)==null,"quiet message starts creeping-line timer");
        check(Display.flashes==flashes && Jimm.raised==0,"quiet delivery wakes display");
        check(!f(ContactList.class,"needPlayMessNotif").getBoolean(null),"silent message retained delayed roster sound");
        f(ContactList.class,"treeBuilt").setBoolean(null,true);
        MainThread.addMessageSerially(message(uin,false));Display.flush();
        check(Manager.toneCount==1 && Display.vibrations==1,"normal message immediately after quiet batch did not alert");
        check(f(ContactList.class,"lastMessageAlert").getLong(null)>0,"normal message did not consume burst gate");
        SplashCanvas.unlock(true);Display.flush();
        MainThread.addMessageSerially(message(uin,true));Display.flush();
        check(f(JimmUI.class,"flashTimerTask").get(null)==null,"quiet message starts foreground ticker");
        MainThread.addMessageSerially(message(uin,false));Display.flush();
        check(f(JimmUI.class,"flashTimerTask").get(null)!=null,"normal message ticker disabled");
        ChatTextList chat=ChatHistory.getChatHistoryAt(uin);chat.buildMenu();
        check("Получать без оповещений".equals(((Command)f(ChatTextList.class,"cmdQuietDelivery").get(null)).getLabel()),"quiet menu lacks requested translation");
        System.out.println("PASS: silent messages keep text, unread icon and nested-group/lockscreen counters without audio/vibration/ticker/wakeup; next ordinary message alerts");
    }
    static void finish()throws Exception{
        Jimm.getTimerRef().cancel();
        for(String name:new String[]{"soundTimer","iconTimer"})try{Timer timer=(Timer)f(ContactList.class,name).get(null);if(timer!=null)timer.cancel();}catch(NoSuchFieldException absent){}
        Object canvas=f(VirtualList.class,"virtualCanvas").get(null);((Timer)f(canvas.getClass(),"repeatTimer").get(canvas)).cancel();
    }
    public static void main(String[] args)throws Exception{
        v8=args[1].equals("v8");
        try{
            f(Options.class,"options").set(null,new Hashtable());m(Options.class,"setDefaults").invoke(null);
            Options.setBoolean(Options.OPTION_DISPLAY_DATE,false);
            new MainThread();new Icq();new SplashCanvas();new ContactList();new ChatHistory();
            f(Icq.class,"c").set(null,socket);VirtualList.setDisplay(Jimm.display);
            wire(args[0]);notifications();
        }finally{finish();}
    }
}
