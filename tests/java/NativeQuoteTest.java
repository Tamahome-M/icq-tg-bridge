import java.lang.reflect.*;
import java.util.*;
import javax.microedition.lcdui.*;
import DrawControls.TextList;
import jimm.*;
import jimm.comm.*;
import jimm.comm.connections.Connection;

/** Exercise the actual client's native-quote selection, packets and history reader. */
public final class NativeQuoteTest {
    static void check(boolean b,String s){if(!b)throw new AssertionError(s);}
    static Field field(Class c,String n)throws Exception{Field f=c.getDeclaredField(n);f.setAccessible(true);return f;}
    static Method method(Class c,String n,Class... args)throws Exception{Method m=c.getDeclaredMethod(n,args);m.setAccessible(true);return m;}
    static class Socket extends Connection {
        Vector packets=new Vector();public void sendPacket(Packet p){packets.addElement(p);}public void forceDisconnect(){}
    }
    static NativeQuote queued()throws Exception{return (NativeQuote)((Vector)field(Icq.class,"reqAction").get(null)).lastElement();}
    static boolean reply(NativeQuote a,int requestId,byte[] data)throws Exception{
        return ((Boolean)method(NativeQuote.class,"forward",Packet.class).invoke(a,new SnacPacket(0x10,0x0a,requestId,new byte[0],data))).booleanValue();
    }
    static void run()throws Exception{
        field(Options.class,"options").set(null,new Hashtable());method(Options.class,"setDefaults").invoke(null);new SplashCanvas("test");
        new Icq();method(Icq.class,"setConnected").invoke(null);field(Icq.class,"reqAction").set(null,new Vector());
        Socket socket=new Socket();field(Icq.class,"c").set(null,socket);
        TextList menu=new TextList("chat");Jimm.display.setCurrent(menu);
        byte[] ref=new byte[]{(byte)0x80,0,0,0,0,0,0x30,0x39};
        NativeQuote.updateMenu(menu,null);check(menu.commands.isEmpty(),"quote without source reference");
        NativeQuote.select("1000037",ref);NativeQuote.updateMenu(menu,ref);
        check(menu.commands.contains(NativeQuote.cmdSelect) && menu.commands.contains(NativeQuote.cmdPaste),"source or destination command missing");
        NativeQuote.paste("1000070");NativeQuote action=queued();NativeQuote.paste("1000070");
        check(((Vector)field(Icq.class,"reqAction").get(null)).size()==1,"double menu press forwarded twice");
        method(NativeQuote.class,"init").invoke(action);
        SnacPacket packet=(SnacPacket)socket.packets.lastElement();byte[] data=packet.getData();
        check(packet.getFamily()==0x10 && packet.getCommand()==9,"wrong quote request");
        check(Util.byteArrayToString(data,1,7).equals("1000070") && Util.byteArrayToString(data,9,7).equals("1000037"),"source/destination were swapped");
        check(Arrays.equals(ref,Arrays.copyOfRange(data,16,24)),"native ID narrowed to 32 bits");
        check(!reply(action,(int)packet.getReference()+1,new byte[]{0}) && !action.isCompleted(),"unrelated response completed quote");
        check(reply(action,(int)packet.getReference(),new byte[]{0}) && action.isCompleted(),"quote ACK ignored");
        NativeQuote.updateMenu(menu,ref);check(!menu.commands.contains(NativeQuote.cmdPaste),"successful source was not consumed");
        check(Jimm.display.getCurrent() instanceof Alert,"quote result missing");
        check(((Alert)Jimm.display.getCurrent()).type==AlertType.INFO && Jimm.display.returnTo==menu,"result replaced destination screen");
        Jimm.display.setCurrent(menu);NativeQuote.select("1000037",ref);NativeQuote.paste("1000070");action=queued();method(NativeQuote.class,"init").invoke(action);
        packet=(SnacPacket)socket.packets.lastElement();reply(action,(int)packet.getReference(),new byte[]{1,'n','o'});
        NativeQuote.updateMenu(menu,ref);check(menu.commands.contains(NativeQuote.cmdPaste),"failed quote lost the selection");
        NativeQuote.paste("1000070");action=queued();method(NativeQuote.class,"init").invoke(action);packet=(SnacPacket)socket.packets.lastElement();
        NativeQuote.select("1000099",new byte[]{1,2,3,4,5,6,7,8});reply(action,(int)packet.getReference(),new byte[]{0});
        NativeQuote.updateMenu(menu,null);check(menu.commands.contains(NativeQuote.cmdPaste),"late success cleared a new selection");
        NativeQuote.paste("1000070");NativeQuote.disconnected();NativeQuote.updateMenu(menu,null);
        check(menu.commands.contains(NativeQuote.cmdPaste),"disconnect left quote permanently pending");

        // The history validator must consume discussion UIN and all eight bytes of the ID.
        byte[] record=new byte[3+1+4+8];Util.putWord(record,0,1);record[2]='x';record[3]=0x30;Util.putDWord(record,4,1000123);System.arraycopy(ref,0,record,8,8);
        Method fits=method(HistoryViewer.class,"fits",byte[].class,Integer.TYPE);
        check(((Boolean)fits.invoke(null,record,0)).booleanValue(),"new history reference flag rejected");
        check(!((Boolean)fits.invoke(null,Arrays.copyOf(record,record.length-1),0)).booleanValue(),"truncated history ID accepted");
        Constructor ctor=HistoryViewer.class.getDeclaredConstructor(JimmScreen.class,String.class,String.class);ctor.setAccessible(true);
        HistoryViewer viewer=(HistoryViewer)ctor.newInstance(null,"1000037","history");field(HistoryViewer.class,"current").set(null,viewer);
        TextList history=new TextList("history");field(HistoryViewer.class,"list").set(viewer,history);
        method(HistoryViewer.class,"render",byte[].class).invoke(viewer,record);
        Vector refs=(Vector)field(HistoryViewer.class,"refs").get(viewer);
        check(refs.size()==1 && Arrays.equals(ref,(byte[])refs.firstElement()),"history record lost its reference");
        viewer.commandAction(NativeQuote.cmdSelect,history);
        NativeQuote.updateMenu(menu,null);check(menu.commands.contains(NativeQuote.cmdPaste),"history source not usable in another chat");
        System.out.println("PASS: native quote menus, cross-chat source packet, 64-bit ID, ACK/errors/disconnect/double press; history reference parser and selection");
    }
    public static void main(String[]args)throws Exception{
        try{run();}finally{
            Jimm.getTimerRef().cancel();
            ((Timer)field(ContactList.class,"iconTimer").get(null)).cancel();
            ((Timer)field(ContactList.class,"soundTimer").get(null)).cancel();
        }
    }
}
