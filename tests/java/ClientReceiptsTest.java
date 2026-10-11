package jimm;

import java.lang.reflect.*;
import java.util.*;
import javax.microedition.lcdui.*;
import DrawControls.*;
import jimm.comm.*;

public final class ClientReceiptsTest {
    static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
    static Field field(Class c,String name)throws Exception{Field f=c.getDeclaredField(name);f.setAccessible(true);return f;}
    static Method method(Class c,String name,Class... args)throws Exception{Method m=c.getDeclaredMethod(name,args);m.setAccessible(true);return m;}
    static Hashtable chats()throws Exception{return (Hashtable)field(ChatHistory.class,"historyTable").get(null);}
    static ChatTextList chat(String uin)throws Exception {
        ChatHistory.currentChat=null;Jimm.display.setCurrent((Displayable)null);
        ChatTextList chat=new ChatTextList("chat",new ContactItem(1,1,uin,"chat",false,true));chats().put(uin,chat);return chat;
    }
    static void add(ChatTextList chat,int id,boolean incoming){chat.addTextToForm("author","body "+id,"",120000+id,incoming,false,id);}
    static void flush(ChatTextList chat)throws Exception{method(ChatTextList.class,"flushDeferred").invoke(chat);}
    static boolean image(ChatTextList chat,int index,Image expected)throws Exception{
        Vector lines=(Vector)field(TextList.class,"lines").get(chat.textList);
        int first=field(ChatTextList.class,"firstMess").getInt(chat);
        for(Object line:lines){
            if(field(line.getClass(),"bigTextIndex").getInt(line)!=first+index)continue;
            int size=((Integer)method(line.getClass(),"size").invoke(line)).intValue();
            for(int i=0;i<size;i++){
                Object item=method(line.getClass(),"elementAt",int.class).invoke(line,i);
                Image[] images=(Image[])field(item.getClass(),"image").get(item);
                if(images!=null && images[0]==expected)return true;
            }
        }return false;
    }
    static byte[] packet(String uin,int id,boolean read)throws Exception{
        byte[] name=uin.getBytes("ASCII");byte[] data=new byte[(read?9:11)+name.length];
        Util.putDWord(data,0,id);Util.putDWord(data,4,1);
        if(!read)Util.putWord(data,8,1);
        data[read?8:10]=(byte)name.length;System.arraycopy(name,0,data,read?9:11,name.length);return data;
    }
    static void dispatch(byte[] data,boolean read)throws Exception {
        method(ActionListener.class,"forward",Packet.class).invoke(new ActionListener(),new SnacPacket(4,read?0x16:0x0c,1,new byte[0],data));
    }
    static void glyph()throws Exception{
        check(field(JimmUI.class,"imgMessRead").get(null)==null && Image.rgbCreates==0,"read bitmap allocated before any read receipt");
        Image first=JimmUI.imgMessDeliv;int[] original=first.pixels.clone();Image twice=JimmUI.messageReadImage();
        check(twice!=first && twice.getWidth()==first.getWidth() && twice.getHeight()==first.getHeight(),"read bitmap changes tile dimensions");
        check(!Arrays.equals(twice.pixels,original) && Arrays.equals(first.pixels,original),"double check unchanged or source sprite modified");
        int extra=0;for(int i=0;i<original.length;i++){
            if((original[i]>>>24)!=0)check(twice.pixels[i]==original[i],"original check lost its pixels");
            else if((twice.pixels[i]>>>24)!=0)extra++;
        }
        check(extra>0 && Image.rgbCreates==1 && JimmUI.messageReadImage()==twice,"second check absent or bitmap rebuilt");
        field(JimmUI.class,"imgMessRead").set(null,null);Image.failRGB=true;
        check(JimmUI.messageReadImage()==first,"bitmap OOM crashes UI instead of preserving receipt state");
        Image.failRGB=false;check(JimmUI.messageReadImage()!=first,"bitmap cannot be rebuilt after memory pressure");
        System.out.println("PASS: real check sprite gains a second check, stays transparent/same size, source unchanged; lazy cached bitmap and OOM fallback");
    }
    static void receipts()throws Exception{
        ChatTextList one=chat("1000001");add(one,77,false);add(one,77,true);
        dispatch(packet("1000001",77,false),false);
        check(((DeferredMessage)one.deferred.firstElement()).receiptState==0,"comm thread changes chat outside UI queue");
        Display.flush();
        check(((DeferredMessage)one.deferred.firstElement()).receiptState==1 && ((DeferredMessage)one.deferred.lastElement()).receiptState==0,"delivery touches incoming echo with same ID");
        dispatch(packet("1000001",77,true),true);Display.flush();
        dispatch(packet("1000001",77,false),false);Display.flush();
        check(((DeferredMessage)one.deferred.firstElement()).receiptState==2,"late delivery downgrades deferred read");
        flush(one);
        check(((MessData)one.getMessData().firstElement()).receiptState()==2 && ((MessData)one.getMessData().lastElement()).receiptState()==0,"deferred receipt not transferred to packed row data");
        check(image(one,0,JimmUI.messageReadImage()) && image(one,1,JimmUI.eventPlainMessageImg),"closed chat loses read icon or incoming echo changes");
        ChatHistory.currentChat=one;add(one,78,false);
        dispatch(packet("1000001",78,false),false);Display.flush();check(image(one,2,JimmUI.imgMessDeliv),"visible delivery check missing");
        dispatch(packet("1000001",78,true),true);Display.flush();check(image(one,2,JimmUI.messageReadImage()),"visible delivery does not advance to read");
        dispatch(packet("1000001",78,false),false);Display.flush();check(image(one,2,JimmUI.messageReadImage()),"late delivery overwrites visible read");
        add(one,79,false);dispatch(packet("1000001",79,true),true);Display.flush();
        check(image(one,3,JimmUI.messageReadImage()),"read-first message needs an earlier delivery event");
        check(((MessData)one.getMessData().elementAt(3)).getMessId()==79 && one.textList.getTextByIndex(0,false,3).indexOf("body 79")>=0,"receipt bits corrupt ID/text offset");
        ChatTextList two=chat("1000002");add(two,77,false);
        dispatch(packet("1000001",77,true),true);Display.flush();
        check(((DeferredMessage)two.deferred.firstElement()).receiptState==0,"same cookie ID marks another chat");
        int count=chats().size();dispatch(packet("1000999",77,true),true);Display.flush();check(chats().size()==count,"receipt opens missing chat");
        Options.setInt(Options.OPTION_CHAT_MESSAGES,1);ChatHistory.currentChat=one;add(one,80,false);
        dispatch(packet("1000001",77,true),true);Display.flush();check(one.messageCount()==1,"receipt restores evicted messages");
        Options.setInt(Options.OPTION_CHAT_MESSAGES,15);
        System.out.println("PASS: parser queues UI; deferred/visible delivery->read, read-first, duplicate/stale events, incoming echo IDs, other/missing chats, packed offsets and evicted messages");
    }
    static void malformed()throws Exception {
        ChatTextList chat=chat("1000003");add(chat,90,false);byte[] read=packet("1000003",90,true),ack=packet("1000003",90,false);
        for(int size=0;size<read.length;size++)dispatch(Arrays.copyOf(read,size),true);
        for(int size=0;size<ack.length;size++)dispatch(Arrays.copyOf(ack,size),false);
        byte[] invalid=read.clone();invalid[9]='x';dispatch(invalid,true);
        invalid=read.clone();invalid[8]=0;dispatch(invalid,true);
        invalid=Arrays.copyOf(read,read.length+1);dispatch(invalid,true);
        Display.flush();check(((DeferredMessage)chat.deferred.firstElement()).receiptState==0,"truncated/bogus receipt accepted");
        Options.setBoolean(Options.OPTION_DELIV_MES_INFO,false);dispatch(read,true);dispatch(ack,false);Display.flush();
        check(((DeferredMessage)chat.deferred.firstElement()).receiptState==0,"disabled receipts still change message");
        Options.setBoolean(Options.OPTION_DELIV_MES_INFO,true);dispatch(ack,false);Display.flush();
        check(((DeferredMessage)chat.deferred.firstElement()).receiptState==1,"malformed packet breaks later normal ACK");
        System.out.println("PASS: truncated ACK/read bodies, invalid recipient/length/trailing bytes and disabled preference ignored; next valid ACK still works");
    }
    public static void main(String[] args)throws Exception{
        System.setProperty("tmm.checks",args[0]);
        try{
            field(Options.class,"options").set(null,new Hashtable());method(Options.class,"setDefaults").invoke(null);
            Options.setBoolean(Options.OPTION_DELIV_MES_INFO,true);
            Constructor ctor=MainThread.class.getDeclaredConstructor();ctor.setAccessible(true);ctor.newInstance();
            glyph();receipts();malformed();
        }finally{
            Jimm.getTimerRef().cancel();Object canvas=field(VirtualList.class,"virtualCanvas").get(null);
            ((Timer)field(canvas.getClass(),"repeatTimer").get(canvas)).cancel();
        }
        System.exit(0);
    }
}
