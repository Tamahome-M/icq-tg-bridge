package jimm.comm;

import java.lang.reflect.*;
import java.util.*;
import jimm.*;
import DrawControls.VirtualList;
import javax.microedition.lcdui.Display;

/** Bad notification packets must not take down the main network loop. */
public final class CommAuditPacketTest {
 static Field f(Class c,String name)throws Exception{Field f=c.getDeclaredField(name);f.setAccessible(true);return f;}
 static void check(boolean b,String text){if(!b)throw new AssertionError(text);}
 static int failures;
 static ActionListener listener=new ActionListener();static Vector tasks;
 static byte[] uin(){return new byte[]{'1','0','0','0','0','3','7'};}
 static void drain()throws Exception{tasks.removeAllElements();Display.queued.removeAllElements();f(MainThread.class,"queueScheduled").setBoolean(null,false);f(MainThread.class,"queuedBytes").setInt(null,0);}
 static SnacPacket packet(int family,int command,byte[] data){return new SnacPacket(family,command,123,new byte[0],data);}
 static void prefixes(String name,int family,int command,byte[] valid)throws Exception{
  int tested=0,unchecked=0;
  for(int cut=0;cut<valid.length;cut++){
   byte[] truncated=new byte[cut];System.arraycopy(valid,0,truncated,0,cut);drain();
   try{listener.forward(packet(family,command,truncated));}
   catch(JimmException error){check(!error.isCritical(),"truncated "+name+" causes disconnect at "+cut);}
   catch(RuntimeException error){if(unchecked++==0)System.out.println("FAIL: "+name+" unchecked "+error.getClass().getName()+" at prefix "+cut);failures++;}
   if(!tasks.isEmpty()){failures++;System.out.println("FAIL: truncated "+name+" dispatched a notification at "+cut);}tested++;
  }
  drain();listener.forward(packet(family,command,valid));
  System.out.println((unchecked==0?"PASS: ":"FAIL: ")+tested+" truncated "+name+" packets rejected without unchecked exceptions or callbacks");
 }
 static void notifications()throws Exception{
  byte[] who=uin();
  byte[] receipt=new byte[60+who.length];Util.putDWord(receipt,0,42);Util.putDWord(receipt,4,2);Util.putWord(receipt,8,2);receipt[10]=(byte)who.length;
  System.arraycopy(who,0,receipt,11,who.length);Util.putWord(receipt,58+who.length,1,false);
  prefixes("message receipt",4,11,receipt);check(tasks.size()==2,"valid delivery receipt was lost");
  byte[] typing=new byte[13+who.length];Util.putWord(typing,8,1);typing[10]=(byte)who.length;System.arraycopy(who,0,typing,11,who.length);Util.putWord(typing,11+who.length,2);
  prefixes("typing",4,20,typing);check(tasks.size()==2,"valid typing was lost");
  byte[] uploaded=new byte[2+who.length];uploaded[0]=(byte)who.length;System.arraycopy(who,0,uploaded,1,who.length);
  prefixes("upload response",16,3,uploaded);
  prefixes("offline error",21,1,new byte[]{0,1});
  byte[] added=new byte[1+who.length];added[0]=(byte)who.length;System.arraycopy(who,0,added,1,who.length);
  prefixes("contact-added notice",SnacPacket.SRV_ADDEDYOU_FAMILY,SnacPacket.SRV_ADDEDYOU_COMMAND,added);
  check(tasks.size()==2,"valid contact-added notice lost");
  byte[] reason="No thanks".getBytes("UTF-8");
  byte[] auth=new byte[3+who.length+reason.length];auth[0]=(byte)who.length;System.arraycopy(who,0,auth,1,who.length);Util.putWord(auth,1+who.length,reason.length);System.arraycopy(reason,0,auth,3+who.length,reason.length);
  prefixes("authorization request",SnacPacket.SRV_AUTHREQ_FAMILY,SnacPacket.SRV_AUTHREQ_COMMAND,auth);
  check(tasks.size()==2,"valid authorization request lost");
  byte[] denied=new byte[4+who.length+reason.length];denied[0]=(byte)who.length;System.arraycopy(who,0,denied,1,who.length);Util.putWord(denied,2+who.length,reason.length);System.arraycopy(reason,0,denied,4+who.length,reason.length);
  prefixes("authorization reply",SnacPacket.SRV_AUTHREPLY_FAMILY,SnacPacket.SRV_AUTHREPLY_COMMAND,denied);
  check(tasks.size()==2,"valid authorization reply lost");SystemNotice notice=(SystemNotice)((Object[])tasks.elementAt(1))[0];
  if(!"No thanks".equals(notice.getText())){failures++;System.out.println("FAIL: authorization rejection includes length bytes or loses text");}
  check(failures==0,"notification parser failures: "+failures);
  drain();
 }
 public static void main(String[] args)throws Exception{
  try{
   f(Options.class,"options").set(null,new Hashtable());Method defaults=Options.class.getDeclaredMethod("setDefaults");defaults.setAccessible(true);defaults.invoke(null);
   Options.setInt(Options.OPTION_TYPING_MODE,2);Options.setBoolean(Options.OPTION_DELIV_MES_INFO,true);
   Constructor ctor=MainThread.class.getDeclaredConstructor();ctor.setAccessible(true);ctor.newInstance();new Icq();new ContactList();new ChatHistory();new SplashCanvas();VirtualList.setDisplay(Jimm.display);
   tasks=(Vector)f(MainThread.class,"mainThreadTasks").get(null);notifications();
  }finally{
   Jimm.getTimerRef().cancel();Object canvas=f(VirtualList.class,"virtualCanvas").get(null);((Timer)f(canvas.getClass(),"repeatTimer").get(canvas)).cancel();
  }
 }
}
