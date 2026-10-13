package jimm;

import java.io.*;
import java.lang.reflect.*;
import java.util.*;
import javax.microedition.lcdui.*;
import jimm.comm.*;
import jimm.comm.connections.Connection;

public final class ClientContactNamesTest {
    static final int TG=1000002,MAX=1000003,EXPRESS=1000004;
    static Hashtable packets=new Hashtable();
    static void check(boolean ok,String reason){if(!ok)throw new AssertionError(reason);}
    static Field field(Class c,String name)throws Exception{Field f=c.getDeclaredField(name);f.setAccessible(true);return f;}
    static void invoke(Class c,String name)throws Exception{Method m=c.getDeclaredMethod(name);m.setAccessible(true);m.invoke(null);}
    static class Wire extends Connection {
        int sends;public void sendPacket(Packet p){sends++;}public void forceDisconnect(){}
    }
    static Wire wire=new Wire();
    static class Receiver extends ActionListener {void receive(Packet p)throws JimmException{forward(p);}}
    static Receiver listener=new Receiver();
    static Message receive(String label)throws Exception{
        Object[] row=(Object[])packets.get(label);byte[] data=((byte[])row[1]).clone();
        boolean offline=((Boolean)row[0]).booleanValue();
        Packet packet=offline?new FromIcqSrvPacket(0,0,0,1,"100500",0x41,new byte[0],data)
                             :new SnacPacket(4,7,1,new byte[0],data);
        listener.receive(packet);
        Vector tasks=(Vector)field(MainThread.class,"mainThreadTasks").get(null);
        check(tasks.size()==2,"message did not queue exactly one UI task: "+label);
        Message message=(Message)((Object[])tasks.elementAt(1))[0];
        Arrays.fill(data,(byte)0); // Names must own their text, never keep the receive buffer.
        Display.flush();
        check(message.getSenderName()==null,"UI message still retains redundant sender name");
        check(((Vector)field(Icq.class,"reqAction").get(null)).isEmpty(),"name lookup queued a profile/roster request");
        return message;
    }
    static void reset()throws Exception{
        field(ContactList.class,"cItems").set(null,new Vector());field(ContactList.class,"gItems").set(null,new Vector());
        invoke(ContactList.class,"invalidateUinIndex");
        ((Hashtable)field(ChatHistory.class,"historyTable").get(null)).clear();
        ((Vector)field(ChatHistory.class,"historyUins").get(null)).removeAllElements();ChatHistory.currentChat=null;
        ((Vector)field(MainThread.class,"mainThreadTasks").get(null)).removeAllElements();
        field(MainThread.class,"queuedBytes").setInt(null,0);field(MainThread.class,"queueScheduled").setBoolean(null,false);
        Display.queued.removeAllElements();wire.sends=0;
    }
    static ContactItem contact(int uin){return ContactList.getItembyUIN(String.valueOf(uin));}
    static void named(int uin,String expected){
        ContactItem item=contact(uin);check(item!=null && expected.equals(item.getStringValue(ContactItem.CONTACTITEM_NAME)),"contact name not applied: "+expected);
        check(item.getBooleanValue(ContactItem.CONTACTITEM_IS_TEMP),"name lookup added contact to server roster");
        ChatTextList chat=ChatHistory.getChatHistoryAt(String.valueOf(uin));
        chat.activate();
        check(chat.ChatName.equals(expected) && chat.textList.getCaption().startsWith(expected),"chat title still shows UIN");
        if(chat.messageCount()==1)
            check(chat.textList.getTextByIndex(0,false,chat.textList.getCurrTextIndex()).contains(expected),"first message header still shows UIN");
    }
    static void run()throws Exception{
        reset();receive("live-tg");named(TG,"Мама");check(wire.sends==0,"plain names create network traffic");
        Message media=receive("live-max");named(MAX,"MAX: Друзья");
        check(media.getAttachKind()==1 && media.getAttachToken()!=null && wire.sends==1,"media token or delivery ACK lost");
        check(Arrays.equals(media.getMessageRef(),new byte[]{0,0,0,0,0,0,0,123}),"message reference lost beside sender name");
        Message link=receive("live-express");named(EXPRESS,"eXpress: Команда");
        check(link instanceof UrlMessage && ((UrlMessage)link).getUrl().equals("https://example.org/video") && wire.sends==2,"browser URL or ACK lost");
        reset();receive("offline");named(TG,"Мама");check(wire.sends==0,"offline names create network traffic");
        System.out.println("PASS: real bridge live channel 1/2, photo/browser URL and offline packets immediately name temporary contacts, chat titles and first headers; exact ACK counts, no profile requests");

        reset();receive("legacy");check(contact(TG).getStringValue(ContactItem.CONTACTITEM_NAME).equals(String.valueOf(TG)),"old bridge names fabricate an alias");
        ChatTextList open=ChatHistory.getChatHistoryAt(String.valueOf(TG));open.activate();receive("live-tg");named(TG,"Мама");
        check(ChatHistory.getChatHistoryAt(String.valueOf(TG))==open,"rename replaces an existing chat and loses history");
        reset();ContactItem custom=ContactList.createTempContact(String.valueOf(TG));custom.setStringValue(ContactItem.CONTACTITEM_NAME,"Мой псевдоним");
        receive("live-tg");check(custom.getStringValue(ContactItem.CONTACTITEM_NAME).equals("Мой псевдоним"),"automatic name overwrites local alias");
        for(String label:new String[]{"blank","invalid","oversize","control","truncated","offline-legacy","offline-invalid"}){
            reset();Message message=receive(label);
            check(contact(TG).getStringValue(ContactItem.CONTACTITEM_NAME).equals(String.valueOf(TG)),"bad/missing name applied: "+label);
            check(message.getText().length()>0,"optional name loses message text: "+label);
        }
        reset();try{receive("offline-broken");throw new AssertionError("bad offline text length accepted");}catch(JimmException expected){}
        System.out.println("PASS: open chat renamed in place; custom alias preserved; legacy/malformed/oversized names leave valid text intact; bad offline body rejected");
        Method size=MainThread.class.getDeclaredMethod("payloadBytes",Object[].class);size.setAccessible(true);
        PlainMessage queued=new PlainMessage(String.valueOf(TG),"100500",1,"text",false);queued.setSenderName("Мама");
        check(((Integer)size.invoke(null,new Object[]{new Object[]{queued}})).intValue()==16,"queue memory budget ignores sender name");
        System.out.println("PASS: sender name included in the bounded UI queue memory budget and released after use");
    }
    public static void main(String[] args)throws Exception{
        DataInputStream input=new DataInputStream(new FileInputStream(args[0]));int count=input.readUnsignedShort();
        for(int i=0;i<count;i++){byte[] label=new byte[input.readUnsignedShort()];input.readFully(label);
            boolean offline=input.readBoolean();byte[] body=new byte[input.readInt()];input.readFully(body);
            packets.put(new String(label,"UTF-8"),new Object[]{Boolean.valueOf(offline),body});}
        input.close();
        try{
            field(Options.class,"options").set(null,new Hashtable());invoke(Options.class,"setDefaults");
            Options.setBoolean(Options.OPTION_SILENT_MODE,true);Options.setBoolean(Options.OPTION_USE_GROUPS,false);
            Options.setBoolean(Options.OPTION_SHOW_NICK,true);
            Options.setBoolean(Options.OPTION_CL_HIDE_OFFLINE,false);Options.setLong(Options.OPTION_AUTOLOCK_MINUTES,0);
            Constructor ctor=MainThread.class.getDeclaredConstructor();ctor.setAccessible(true);ctor.newInstance();
            new Icq();field(Icq.class,"c").set(null,wire);field(Icq.class,"connected").setBoolean(null,true);
            new ContactList();new SplashCanvas();new ChatHistory();run();
        }finally{
            Jimm.getTimerRef().cancel();Object canvas=field(DrawControls.VirtualList.class,"virtualCanvas").get(null);
            ((Timer)field(canvas.getClass(),"repeatTimer").get(canvas)).cancel();
        }
    }
}
