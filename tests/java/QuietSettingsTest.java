package jimm;

import java.lang.reflect.*;
import java.util.*;
import javax.microedition.lcdui.*;
import javax.microedition.rms.RecordStore;
import DrawControls.VirtualList;
import jimm.comm.*;
import jimm.comm.connections.Connection;

public final class QuietSettingsTest {
    static void check(boolean b,String reason){if(!b)throw new AssertionError(reason);}
    static Field f(Class c,String name)throws Exception{return QuietMessagesTest.f(c,name);}
    static Method m(Class c,String name,Class... args)throws Exception{return QuietMessagesTest.m(c,name,args);}
    static class Socket extends Connection {
        Vector packets=new Vector();boolean fail;
        public void sendPacket(Packet packet)throws JimmException{if(fail)throw new JimmException(120,1,false);packets.addElement(packet);}
        public void forceDisconnect(){}
    }
    static class Back implements JimmScreen {
        int calls;Displayable display=new Form("chat");
        public void activate(){calls++;Jimm.display.setCurrent(display);}
        public boolean isScreenActive(){return Jimm.display.getCurrent()==display;}
    }
    static Back back=new Back();static Socket socket=new Socket();
    static void account(String host,String port,String owner)throws Exception{
        f(Icq.class,"connected").setBoolean(null,false);
        Options.setString(Options.OPTION_SRV_HOST,host);Options.setString(Options.OPTION_SRV_PORT,port);
        Options.setString(Options.OPTION_UIN1,owner);Options.setInt(Options.OPTION_CURR_ACCOUNT,0);
    }
    static QuietDelivery open(String uin)throws Exception{
        QuietDelivery.show(uin,"Public",back);Display.flush();
        check(Jimm.display.getCurrent() instanceof Form,"quiet menu did not open a native form");
        return (QuietDelivery)((Form)Jimm.display.getCurrent()).listener;
    }
    static ChoiceGroup mode(QuietDelivery q)throws Exception{return (ChoiceGroup)f(QuietDelivery.class,"mode").get(q);}
    static String status(QuietDelivery q)throws Exception{return ((StringItem)f(QuietDelivery.class,"status").get(q)).getText();}
    static void command(QuietDelivery q,String name)throws Exception{
        Command c=name.equals("back")?JimmUI.cmdBack:(Command)f(QuietDelivery.class,name).get(q);
        q.commandAction(c,(Displayable)f(QuietDelivery.class,"form").get(q));Display.flush();
    }
    static void save(QuietDelivery q,boolean value)throws Exception{mode(q).setSelectedIndex(value?1:0,true);command(q,"save");}
    static void forget()throws Exception{f(QuietDelivery.class,"loadedScope").set(null,null);}
    static int[] payload(Socket s)throws Exception{
        check(!s.packets.isEmpty(),"no quiet-list packet");
        SnacPacket packet=(SnacPacket)s.packets.lastElement();
        check(packet.getFamily()==1 && packet.getCommand()==0xf3,"quiet settings used wrong wire/ICBM/BART");
        byte[] data=packet.getDataRef();int count=Util.getWord(data,0);
        check(data.length==2+4*count,"quiet list framing changed");int[] values=new int[count];
        for(int i=0;i<count;i++)values[i]=(int)Util.getDWord(data,2+4*i);return values;
    }
    static void sync(String host,String port,String owner)throws Exception{
        socket.packets.removeAllElements();f(Icq.class,"c").set(null,socket);QuietDelivery.sync(socket,host,port,owner);
    }
    static void uiAndPersistence()throws Exception{
        account("bridge","5190","100500");
        QuietDelivery q=open("1000037");
        check(mode(q).getType()==Choice.POPUP && mode(q).size()==2,"delivery selector is not a two-item dropdown");
        check(mode(q).getString(0).equals("Обычная доставка") && mode(q).getString(1).equals("Без оповещений"),"delivery labels wrong");
        check(mode(q).getSelectedIndex()==0 && socket.packets.isEmpty(),"opening setting queried server or invented quiet state");
        int writes=RecordStore.writes;mode(q).setSelectedIndex(1,true);command(q,"back");
        check(back.calls==1 && RecordStore.writes==writes && socket.packets.isEmpty(),"cancel saved or sent setting");
        q=open("1000037");check(mode(q).getSelectedIndex()==0,"cancel retained unsaved choice");
        save(q,true);check(status(q).indexOf("следующем подключении")>=0 && socket.packets.isEmpty(),"offline choice not saved/deferred");
        command(q,"back");forget();q=open("1000037");
        check(mode(q).getSelectedIndex()==1,"quiet choice did not survive RMS reload");
        sync("bridge","5190","100500");check(Arrays.equals(payload(socket),new int[]{1000037}),"initial snapshot lost local choice");
        f(Icq.class,"connected").setBoolean(null,true);
        q=open("1000088");save(q,true);
        check(Arrays.equals(payload(socket),new int[]{1000037,1000088}) && status(q).indexOf("передано мосту")>=0,"live change did not publish complete list");
        socket.fail=true;save(q,false);socket.fail=false;
        check(status(q).indexOf("следующем подключении")>=0,"send failure claimed bridge received the setting");
        forget();q=open("1000088");check(mode(q).getSelectedIndex()==0,"send failure reverted persisted choice");
        save(q,true); // restore two values
        RecordStore.failWrite=true;save(q,false);RecordStore.failWrite=false;
        check(status(q).indexOf("передано мосту")<0,"RMS write failure claimed success");
        forget();q=open("1000088");check(mode(q).getSelectedIndex()==1,"failed RMS write changed local truth");
        forget();RecordStore.failRead=true;q=open("1000037");
        check(!f(QuietDelivery.class,"loaded").getBoolean(q),"RMS read failure showed a guessed value");
        RecordStore.failRead=false;command(q,"retry");check(mode(q).getSelectedIndex()==1,"RMS retry failed");
        System.out.println("PASS: local dropdown, cancel, persisted choices/reload, complete online snapshot, offline/send/RMS failures and retry");
    }
    static void scopesAndReconnect()throws Exception{
        // Editing configured credentials during a live connection must keep the active chat's scope.
        Options.setString(Options.OPTION_SRV_HOST,"other");Options.setString(Options.OPTION_UIN1,"200500");
        QuietDelivery q=open("1000037");check(mode(q).getSelectedIndex()==1,"live form switched to edited credentials");
        // Icq.c can switch concurrently; updates still target the captured session socket.
        Socket newer=new Socket();f(Icq.class,"c").set(null,newer);socket.packets.removeAllElements();save(q,false);
        check(newer.packets.isEmpty() && payload(socket).length==1,"old form wrote its list into a replacement socket");
        QuietDelivery.sync(newer,"other","5190","200500");newer.packets.removeAllElements();save(q,true);
        check(newer.packets.isEmpty() && status(q).indexOf("следующем подключении")>=0,"old form leaked account choices after reconnect");
        account("other","5190","200500");q=open("1000037");check(mode(q).getSelectedIndex()==0,"different host/owner inherited whitelist");
        save(q,true);account("other","5191","200500");q=open("1000037");check(mode(q).getSelectedIndex()==0,"different port inherited whitelist");
        account("other","5190","300500");q=open("1000037");check(mode(q).getSelectedIndex()==0,"different owner inherited whitelist");
        check("Aa".hashCode()=="BB".hashCode(),"hash-collision fixture invalid");
        account("Aa","5190","100500");q=open("1000099");save(q,true);
        account("BB","5190","100500");q=open("1000099");check(mode(q).getSelectedIndex()==0,"scope uses collision-prone hash identity");
        account("Aa","5190","100500");forget();q=open("1000099");check(mode(q).getSelectedIndex()==1,"distinct scope overwrote saved list");
        QuietDelivery.disconnected();check(f(QuietDelivery.class,"sessionConnection").get(null)==null,"closed socket retained by settings");
        System.out.println("PASS: host/port/owner isolation, hash collision, live settings edits, replaced socket and old form after reconnect");
    }
    static void staleLogin()throws Exception{
        final java.util.concurrent.CountDownLatch entered=new java.util.concurrent.CountDownLatch(1),release=new java.util.concurrent.CountDownLatch(1);
        final Throwable[] error=new Throwable[1];
        final Socket old=new Socket(){public void sendPacket(Packet packet)throws JimmException{
            entered.countDown();try{check(release.await(5,java.util.concurrent.TimeUnit.SECONDS),"stale socket fixture timed out");}catch(InterruptedException e){throw new AssertionError(e);}super.sendPacket(packet);
        }};
        Thread previous=new Thread(new Runnable(){public void run(){try{QuietDelivery.sync(old,"stale","5190","100500");}catch(Throwable e){error[0]=e;}}});
        f(Icq.class,"c").set(null,old);f(Icq.class,"thread").set(null,previous);previous.start();
        check(entered.await(5,java.util.concurrent.TimeUnit.SECONDS),"old sync did not reach socket");
        Socket replacement=new Socket();f(Icq.class,"c").set(null,replacement);f(Icq.class,"thread").set(null,Thread.currentThread());
        QuietDelivery.sync(replacement,"replacement","5190","200500");
        release.countDown();previous.join(5000);check(!previous.isAlive() && error[0]==null,"old sync did not finish normally");
        check(f(QuietDelivery.class,"sessionConnection").get(null)==replacement,"stale handshake overwrote replacement session socket");
        String expected=(String)m(QuietDelivery.class,"scope",String.class,String.class,String.class).invoke(null,"replacement","5190","200500");
        check(expected.equals(f(QuietDelivery.class,"sessionScope").get(null)),"stale handshake overwrote replacement account scope");
        System.out.println("PASS: delayed old connection sync cannot overwrite replacement session identity/socket");
    }
    static void limitsAndLogin()throws Exception{
        account("limit","5190","100500");
        String scope=(String)m(QuietDelivery.class,"scope",String.class,String.class,String.class).invoke(null,"limit","5190","100500");
        Method persist=m(QuietDelivery.class,"persist",String.class,Integer.TYPE,Boolean.TYPE);
        for(int i=0;i<256;i++)persist.invoke(null,scope,1000001+i,true);
        try{persist.invoke(null,scope,1000999,true);throw new AssertionError("257th quiet chat accepted");}
        catch(InvocationTargetException expected){check(expected.getCause() instanceof java.io.IOException,"limit failed unexpectedly");}
        sync("limit","5190","100500");check(payload(socket).length==256,"limit corrupted full list");
        int writes=RecordStore.writes;persist.invoke(null,scope,1000001,true);check(RecordStore.writes==writes,"duplicate choice rewrites RMS");
        for(int i=0;i<256;i++)persist.invoke(null,scope,1000001+i,false);
        sync("limit","5190","100500");check(payload(socket).length==0,"empty list not transmitted");
        // Exercise actual ConnectAction's READY stage, not merely the helper.
        account("first,backup","5190","100500");QuietDelivery q=open("1000037");save(q,true);
        ConnectAction action=new ConnectAction("100500","secret","first","5190");
        Options.setString(Options.OPTION_SRV_HOST,"edited-during-login");
        f(ConnectAction.class,"connection").set(action,socket);
        f(ConnectAction.class,"state").setInt(action,ConnectAction.STATE_CLI_STATUS_INFO_SENT);
        socket.packets.removeAllElements();
        m(ConnectAction.class,"forward",Packet.class).invoke(action,new SnacPacket(1,15,1,new byte[0],new byte[0]));
        check(socket.packets.size()==3,"login did not send sync, READY and offline request");
        SnacPacket first=(SnacPacket)socket.packets.elementAt(0),ready=(SnacPacket)socket.packets.elementAt(1);
        check(first.getFamily()==1 && first.getCommand()==0xf3 && Util.getWord(first.getDataRef(),0)==1,"quiet snapshot missing/wrong before READY, or host-list scope changed");
        check(ready.getFamily()==SnacPacket.CLI_READY_FAMILY && ready.getCommand()==SnacPacket.CLI_READY_COMMAND,"READY order changed");
        ConnectAction failed=new ConnectAction("100500","secret","first","5190");f(ConnectAction.class,"connection").set(failed,socket);
        f(ConnectAction.class,"state").setInt(failed,ConnectAction.STATE_CLI_STATUS_INFO_SENT);
        socket.packets.removeAllElements();socket.fail=true;
        try{m(ConnectAction.class,"forward",Packet.class).invoke(failed,new SnacPacket(1,15,1,new byte[0],new byte[0]));throw new AssertionError("failed initial sync allowed login");}
        catch(InvocationTargetException expected){check(expected.getCause() instanceof JimmException,"sync failure was not a connection error");}
        socket.fail=false;check(socket.packets.isEmpty(),"READY/offline request sent despite failed list sync");
        System.out.println("PASS: 256 unique limit, idempotent setting, explicit empty replacement, actual sync-before-READY and failed-sync login abort");
    }
    public static void main(String[] args)throws Exception{
        try{
            f(Options.class,"options").set(null,new Hashtable());m(Options.class,"setDefaults").invoke(null);
            new MainThread();new Icq();new SplashCanvas();new ContactList();new ChatHistory();VirtualList.setDisplay(Jimm.display);
            f(Icq.class,"c").set(null,socket);f(Icq.class,"thread").set(null,Thread.currentThread());
            uiAndPersistence();scopesAndReconnect();staleLogin();limitsAndLogin();
        }finally{QuietMessagesTest.finish();}
    }
}
