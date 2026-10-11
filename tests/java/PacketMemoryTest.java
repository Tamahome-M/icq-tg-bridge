package jimm.comm;

import java.io.*;
import java.lang.reflect.*;
import java.util.*;
import javax.microedition.lcdui.*;
import DrawControls.*;
import jimm.*;
import jimm.comm.connections.Connection;

public final class PacketMemoryTest {
    static boolean baseline; static Vector tasks; static volatile Object sink;
    static final int ROUNDS=4096;
    static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
    static Field f(Class type,String name)throws Exception{Field field=type.getDeclaredField(name);field.setAccessible(true);return field;}
    static Method m(Class type,String name,Class... args)throws Exception{Method method=type.getDeclaredMethod(name,args);method.setAccessible(true);return method;}
    static byte[] blob(DataInputStream in)throws Exception{byte[] data=new byte[in.readInt()];in.readFully(data);return data;}
    static byte[] read(String path)throws Exception{DataInputStream in=new DataInputStream(new FileInputStream(path));byte[] b=new byte[in.available()];in.readFully(b);in.close();return b;}
    static class Socket extends Connection {
        Packet last; int count;
        public void sendPacket(Packet packet){last=packet;count++;}
        public void forceDisconnect(){}
        void clear(){last=null;count=0;}
    }
    static Socket socket=new Socket();
    static class Case {
        String name,text,url;byte[] packet,token,ref,ack;int kind,state;
        Case(DataInputStream in)throws Exception{
            name=new String(blob(in),"UTF-8");packet=blob(in);text=new String(blob(in),"UTF-8");url=new String(blob(in),"UTF-8");
            kind=in.readUnsignedByte();state=in.readUnsignedByte();token=blob(in);ref=blob(in);ack=blob(in);
        }
    }
    static Message queued(){
        check(tasks.size()==2 && tasks.elementAt(1) instanceof Object[],"one packet did not schedule exactly one message");
        Object[] args=(Object[])tasks.elementAt(1);check(args.length==1 && args[0] instanceof Message,"message task payload changed");return (Message)args[0];
    }
    static void packets(String dir)throws Exception{
        DataInputStream in=new DataInputStream(new FileInputStream(dir+"/messages.bin"));int count=in.readUnsignedShort();
        ActionListener listener=new ActionListener();Case benchmark=null,plain=null;
        for(int i=0;i<count;i++){
            Case c=new Case(in);if(c.name.equals("benchmark"))benchmark=c;
            if(c.name.equals("c2-4"))plain=c;
            if(baseline && c.state==3)continue;
            tasks.removeAllElements();socket.clear();SnacPacket packet=new SnacPacket(4,7,1,new byte[0],c.packet.clone());
            try{listener.forward(packet);check(c.state!=3,"malformed packet was accepted: "+c.name);}
            catch(JimmException error){check(c.state==3 && !error.isCritical(),"unexpected/critical parse error: "+c.name);}
            if(c.state!=1){check(tasks.isEmpty() && socket.count==0,"ignored/malformed packet queued a message or ACK: "+c.name);continue;}
            Message message=queued();check(c.text.equals(message.getText()),"text changed: "+c.name);
            check(c.url.length()==0 || message instanceof UrlMessage && c.url.equals(((UrlMessage)message).getUrl()),"browser URL changed: "+c.name);
            int kind=baseline && message instanceof UrlMessage?0:c.kind;
            check(message.getAttachKind()==kind,"media kind changed: "+c.name);
            check(kind==0?message.getAttachToken()==null:Arrays.equals(c.token,message.getAttachToken()),"media token changed: "+c.name);
            check(c.ref.length==0?message.getMessageRef()==null:Arrays.equals(c.ref,message.getMessageRef()),"64-bit reference changed: "+c.name);
            check(socket.count==(c.ack.length==0?0:1),"ACK count changed: "+c.name);
            if(c.ack.length>0){SnacPacket response=(SnacPacket)socket.last;check(response.getFamily()==4 && response.getCommand()==11 && Arrays.equals(c.ack,response.getDataRef()),"ACK bytes changed: "+c.name);}
            Arrays.fill(packet.getDataRef(),(byte)0);
            check(c.text.equals(message.getText()) && (kind==0 || Arrays.equals(c.token,message.getAttachToken()))
                && (c.ref.length==0 || Arrays.equals(c.ref,message.getMessageRef())),"message retained a mutable packet range: "+c.name);
        }
        in.close();check(benchmark!=null && plain!=null,"allocation fixture missing");
        measure(listener,plain,"ordinary");measure(listener,benchmark,"with ignored TLVs");
        tasks.removeAllElements();socket.clear();
        System.out.println("PASS: real channel 1/2/4 and extended messages, media, quotes, exact ACKs, immutable ownership and malformed nested boundaries");
    }
    static void measure(ActionListener listener,Case example,String name)throws Exception{
        SnacPacket packet=new SnacPacket(4,7,1,new byte[0],example.packet);
        for(int i=0;i<1024;i++){tasks.removeAllElements();socket.clear();listener.forward(packet);}
        com.sun.management.ThreadMXBean meter=meter();long id=Thread.currentThread().getId(),before=meter.getThreadAllocatedBytes(id);
        for(int i=0;i<ROUNDS;i++){tasks.removeAllElements();socket.clear();listener.forward(packet);}
        long allocated=meter.getThreadAllocatedBytes(id)-before;
        System.out.println("METRIC desktop: 4096 incoming 900-char messages "+name+" = "+allocated+" allocated bytes");
        if(!baseline)check(allocated<ROUNDS*9000L,"incoming parser still allocates copies of large ignored/body/text TLVs");
    }
    static com.sun.management.ThreadMXBean meter(){
        com.sun.management.ThreadMXBean meter=(com.sun.management.ThreadMXBean)java.lang.management.ManagementFactory.getThreadMXBean();
        meter.setThreadAllocatedMemoryEnabled(true);return meter;
    }
    static class CountedContact extends ContactItem {
        int uinReads;
        CountedContact(int id){super(id,1,String.valueOf(1000000+id),"contact",false,true);}
        public synchronized String getStringValue(int key){if(key==CONTACTITEM_UIN)uinReads++;return super.getStringValue(key);}
    }
    static void contacts(String dir)throws Exception{
        IdentityHashMap arrays=new IdentityHashMap();Vector contacts=new Vector();
        for(int i=0;i<97;i++){
            ContactItem c=new ContactItem(i+1,1,String.valueOf(1000001+i),"contact",false,true);contacts.addElement(c);
            for(int key:new int[]{ContactItem.CONTACTITEM_BUDDYICON_HASH,ContactItem.CONTACTITEM_BUDDYICON_HASH_READY}){
                byte[] b=c.getBytesArray(key);if(b!=null)arrays.put(b,Boolean.TRUE);
            }
            check(!c.iconReady(),"unknown avatar is requested");
        }
        System.out.println("METRIC 97 contacts: empty avatar arrays="+arrays.size());
        if(!baseline)check(arrays.isEmpty(),"unadvertised avatar hashes retain per-contact arrays");
        ContactItem c=(ContactItem)contacts.firstElement();byte[] hash=new byte[16];hash[0]=1;
        c.setBytesArray(ContactItem.CONTACTITEM_BUDDYICON_HASH,hash);check(c.iconReady(),"advertised avatar cannot be requested");
        c.setBytesArray(ContactItem.CONTACTITEM_BUDDYICON_HASH_READY,hash);check(!c.iconReady(),"downloaded avatar is requested again");
        c.setBytesArray(ContactItem.CONTACTITEM_BUDDYICON_HASH_READY,null);check(c.iconReady(),"evicted avatar cannot be requested again");
        ByteArrayOutputStream out=new ByteArrayOutputStream();DataOutputStream data=new DataOutputStream(out);c.saveToStream(data);
        ContactItem loaded=new ContactItem();DataInputStream input=new DataInputStream(new ByteArrayInputStream(out.toByteArray()));input.readByte();loaded.loadFromStream(input);
        check(loaded.getUIN()==c.getUIN() && !loaded.iconReady() && loaded.getIntValue(ContactItem.CONTACTITEM_STATUS)==ContactList.STATUS_OFFLINE,"RMS contact runtime reset changed");
        ContactItem idle=(ContactItem)contacts.lastElement();for(int i=0;i<1024;i++)idle.setStatusImage();
        com.sun.management.ThreadMXBean meter=meter();long id=Thread.currentThread().getId(),before=meter.getThreadAllocatedBytes(id);
        for(int i=0;i<ROUNDS;i++)idle.setStatusImage();long allocated=meter.getThreadAllocatedBytes(id)-before;
        System.out.println("METRIC desktop: 4096 caption updates without open chat = "+allocated+" allocated bytes");
        if(!baseline)check(allocated==0,"contact without a chat still allocates caption lookups/images");
        new ContactList();f(ContactList.class,"cItems").set(null,new Vector());f(ContactList.class,"gItems").set(null,new Vector());
        ConnectAction action=new ConnectAction("100500","pass","host","5190");f(ConnectAction.class,"state").setInt(action,ConnectAction.STATE_CLI_CHECKROSTER_SENT);
        byte[] roster=read(dir+"/roster.bin"),snapshot=roster.clone();action.forward(new SnacPacket(0x13,6,1,new byte[0],roster));
        check(Arrays.equals(snapshot,roster),"roster parser modified its source packet");
        Vector parsed=(Vector)f(ContactList.class,"cItems").get(null);check(parsed.size()==97,"roster lost contacts");
        byte[] serverData=read(dir+"/server-data.bin");
        for(int i=0;i<97;i++){
            ContactItem item=(ContactItem)parsed.elementAt(i);check(("Контакт "+i).equals(item.getStringValue(ContactItem.CONTACTITEM_NAME)),"nickname changed in zero-copy roster");
            check(i==0?Arrays.equals(serverData,item.getBytesArray(ContactItem.CONTACTITEM_SS_DATA)):item.getBytesArray(ContactItem.CONTACTITEM_SS_DATA)==null,"server-side contact TLVs changed");
            check(item.getBooleanValue(ContactItem.CONTACTITEM_NO_AUTH)==(i==1),"authorization flag changed");
        }
        Vector counted=new Vector();for(int i=1;i<=3;i++)counted.addElement(new CountedContact(i));
        f(ContactList.class,"cItems").set(null,counted);
        ContactList.update(0,0,new ContactListItem[0],new Vector());int reads=0;
        for(Object item:counted)reads+=((CountedContact)item).uinReads;
        System.out.println("METRIC empty privacy list: unnecessary contact UIN reads="+reads);
        if(!baseline)check(reads==0,"empty privacy data still builds a lookup table for all contacts");
        Vector privacy=new Vector();privacy.addElement("1000002");privacy.addElement(new int[]{ContactItem.CONTACTITEM_VIS_ID,122});
        ContactList.update(0,0,new ContactListItem[0],privacy);
        check(((ContactItem)counted.elementAt(1)).getIntValue(ContactItem.CONTACTITEM_VIS_ID)==122
            && ((ContactItem)counted.firstElement()).getIntValue(ContactItem.CONTACTITEM_VIS_ID)==0,"nonempty privacy data lost its correct contact mapping");
        System.out.println("PASS: lazy avatar hashes, eviction/RMS reset, inactive captions and actual 97-contact roster/nickname/server data/authorization parsing");
    }
    static void textAndOptions()throws Exception{
        String[] cases={"", "plain", "Ж 😀", "a\r\nb\rc\n", "\r\r\n", "\0a\0\r", "a\n\n", "\r", "\n", "\0"};
        for(String value:cases){
            check(value.replace("\r","").replace("\0","").equals(Util.removeCr(value)),"CR/NUL cleanup changed");
            check(value.replace("\r","").replace("\n","\r\n").equals(Util.restoreCrLf(value)),"outgoing CRLF restoration changed");
        }
        String value=new String(new char[900]).replace('\0','Ж');com.sun.management.ThreadMXBean meter=meter();long id=Thread.currentThread().getId();
        for(int i=0;i<1024;i++){sink=Util.removeCr(value);sink=Util.restoreCrLf(value);}
        long before=meter.getThreadAllocatedBytes(id);
        for(int i=0;i<ROUNDS;i++){sink=Util.removeCr(value);sink=Util.restoreCrLf(value);}
        long allocated=meter.getThreadAllocatedBytes(id)-before;
        System.out.println("METRIC desktop: 4096 CR cleanup + CRLF restoration without line breaks = "+allocated+" allocated bytes");
        if(!baseline)check(allocated==0,"unchanged text is still copied during line-ending cleanup");
        Hashtable options=(Hashtable)f(Options.class,"options").get(null);IdentityHashMap booleans=new IdentityHashMap();int count=0;
        for(Enumeration e=options.elements();e.hasMoreElements();){Object v=e.nextElement();if(v instanceof Boolean){booleans.put(v,Boolean.TRUE);count++;}}
        System.out.println("METRIC options: boolean settings="+count+", Boolean objects="+booleans.size());
        if(!baseline)check(booleans.size()<=2,"boolean settings retain individual wrapper objects");
        Options.save();f(Options.class,"options").set(null,new Hashtable());m(Options.class,"setDefaults").invoke(null);Options.load();
        check(Options.getBoolean(Options.OPTION_DELIV_MES_INFO),"shared booleans changed RMS settings");
        System.out.println("PASS: CR/NUL/CRLF text matches independent reference; unchanged text avoids allocations; boolean settings survive RMS");
    }
    public static void main(String[] args)throws Exception{
        baseline=args[1].equals("baseline");
        try{
            f(Options.class,"options").set(null,new Hashtable());m(Options.class,"setDefaults").invoke(null);
            Constructor ctor=MainThread.class.getDeclaredConstructor();ctor.setAccessible(true);ctor.newInstance();
            tasks=(Vector)f(MainThread.class,"mainThreadTasks").get(null);new Icq();f(Icq.class,"c").set(null,socket);
            packets(args[0]);contacts(args[0]);textAndOptions();
        }finally{
            Jimm.getTimerRef().cancel();Object canvas=f(VirtualList.class,"virtualCanvas").get(null);((Timer)f(canvas.getClass(),"repeatTimer").get(canvas)).cancel();
            for(String name:new String[]{"iconTimer","soundTimer"}){Timer timer=(Timer)f(ContactList.class,name).get(null);if(timer!=null)timer.cancel();}
        }
    }
}
