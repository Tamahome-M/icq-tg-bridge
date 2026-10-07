import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import javax.microedition.lcdui.*;
import DrawControls.TextList;
import jimm.*;
import jimm.comm.*;

/** Actual server bytes -> BART action -> history viewer, including an older-page failure. */
public final class HistoryErrorTest {
    static void check(boolean value,String message){NativeQuoteTest.check(value,message);}
    static Field field(Class type,String name)throws Exception{return NativeQuoteTest.field(type,name);}
    static Method method(Class type,String name,Class... args)throws Exception{return NativeQuoteTest.method(type,name,args);}
    static class Capture implements RequestBartAction.ErrorListener {
        int calls; String reason;
        public void onBart(byte[] data){throw new AssertionError("error returned as history bytes");}
        public void onBartError(String text){calls++;reason=text;}
    }
    static RequestBartAction action(RequestBartAction.Listener listener)throws Exception {
        RequestBartAction action=new RequestBartAction("1000313",RequestBartAction.BART_HISTORY,new byte[16],listener);
        field(RequestBartAction.class,"state").setInt(action,RequestBartAction.STATE_CLI_REQ_SENT);
        return action;
    }
    static void error(RequestBartAction action,byte[] body)throws Exception {
        check(((Boolean)method(RequestBartAction.class,"forward",Packet.class).invoke(action,
              new SnacPacket(0x10,1,77,new byte[0],body))).booleanValue(),"history error ignored");
        check(action.isCompleted(),"history error left the request pending");
        check(field(RequestBartAction.class,"notified").getBoolean(action),"listener can be notified twice");
    }
    static HistoryViewer viewer(TextList list)throws Exception {
        Constructor constructor=HistoryViewer.class.getDeclaredConstructor(JimmScreen.class,String.class,String.class);
        constructor.setAccessible(true);
        HistoryViewer viewer=(HistoryViewer)constructor.newInstance(null,"1000313","Сергей");
        field(HistoryViewer.class,"list").set(viewer,list);
        field(HistoryViewer.class,"current").set(null,viewer);
        return viewer;
    }
    static void awaitError(HistoryViewer viewer)throws Exception {
        long until=System.currentTimeMillis()+5000;
        while(System.currentTimeMillis()<until && !(Jimm.display.getCurrent() instanceof Alert))Thread.sleep(10);
        check(Jimm.display.getCurrent() instanceof Alert,"reason was not shown on the phone");
        check(!field(HistoryViewer.class,"loading").getBoolean(viewer),"error left loading active");
    }
    static void run(String directory)throws Exception {
        field(Options.class,"options").set(null,new Hashtable());method(Options.class,"setDefaults").invoke(null);
        byte[] body=Files.readAllBytes(Paths.get(directory,"history-error.bin"));
        byte[] page=Files.readAllBytes(Paths.get(directory,"history-page.bin"));
        String reason="Слишком много запросов истории. Повторите позже.";
        Capture capture=new Capture();error(action(capture),body);
        check(capture.calls==1 && reason.equals(capture.reason),"UTF-8 reason lost");
        capture=new Capture();error(action(capture),new byte[]{0,1});
        check(capture.calls==1 && capture.reason==null,"legacy error needs a TLV");
        capture=new Capture();error(action(capture),Arrays.copyOf(body,body.length-1));
        check(capture.calls==1 && capture.reason==null,"truncated TLV accepted or crashed");
        final int[] plainCalls=new int[1];
        RequestBartAction.Listener plain=new RequestBartAction.Listener(){
            public void onBart(byte[] data){check(data==null,"ordinary listener received error text as media");plainCalls[0]++;}
        };
        error(action(plain),body);check(plainCalls[0]==1,"old listener contract broken");

        TextList list=new TextList("history");HistoryViewer viewer=viewer(list);
        Jimm.display.setCurrent(list);
        method(HistoryViewer.class,"render",byte[].class).invoke(viewer,page);
        Vector texts=(Vector)field(HistoryViewer.class,"texts").get(viewer);
        Vector refs=(Vector)field(HistoryViewer.class,"refs").get(viewer);
        Object first=texts.firstElement(),ref=refs.firstElement();
        field(HistoryViewer.class,"loading").setBoolean(viewer,true);
        error(action(viewer),body);awaitError(viewer);
        Alert alert=(Alert)Jimm.display.getCurrent();
        check(alert.type==AlertType.ERROR && reason.equals(alert.text),"wrong error dialog");
        check(Jimm.display.returnTo==list,"error returns to a different screen");
        check(texts.size()==2 && texts.firstElement()==first && refs.firstElement()==ref,"already loaded history was lost");
        check(field(HistoryViewer.class,"shown").getInt(viewer)==2,"error advanced the page offset");
        check(!field(HistoryViewer.class,"exhausted").getBoolean(viewer),"error marks history exhausted");
        check(list.commands.contains(field(HistoryViewer.class,"cmdMore").get(null)),"cannot retry older page");
        Jimm.display.setCurrent(list);
        method(HistoryViewer.class,"render",byte[].class).invoke(viewer,page);
        check(field(HistoryViewer.class,"shown").getInt(viewer)==4,"retry could not load history");

        list=new TextList("first error");viewer=viewer(list);Jimm.display.setCurrent(list);
        field(HistoryViewer.class,"loading").setBoolean(viewer,true);
        error(action(viewer),body);awaitError(viewer);
        texts=(Vector)field(HistoryViewer.class,"texts").get(viewer);
        check(texts.size()==1 && texts.firstElement().toString().indexOf(reason)>=0,"first error shown as no messages");
        check(field(HistoryViewer.class,"shown").getInt(viewer)==0,"failure counted as a message");
        System.out.println("PASS: server history error UTF-8, BART dispatch, legacy/truncated replies, visible reason, preserved history and retry");
    }
    public static void main(String[] args)throws Exception {
        try{run(args[0]);}
        finally{
            ((Timer)field(ContactList.class,"iconTimer").get(null)).cancel();
            ((Timer)field(ContactList.class,"soundTimer").get(null)).cancel();
        }
    }
}
