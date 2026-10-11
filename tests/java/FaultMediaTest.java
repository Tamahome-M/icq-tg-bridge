package jimm;

import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.*;
import javax.microedition.lcdui.*;
import javax.microedition.media.Manager;
import jimm.comm.*;
import jimm.comm.connections.Connection;

public class FaultMediaTest {
 static Field f(Class c,String n)throws Exception{Field f=c.getDeclaredField(n);f.setAccessible(true);return f;}
 static Object call(Class c,String n,Class[] types,Object o,Object... args)throws Exception{
  Method m=c.getDeclaredMethod(n,types);m.setAccessible(true);return m.invoke(o,args);
 }
 static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
 static final class Previous implements JimmScreen {
  final Displayable screen=new Form("previous");int returns;
  public void activate(){returns++;Jimm.display.setCurrent(screen);}
  public boolean isScreenActive(){return Jimm.display.getCurrent()==screen;}
 }
 static final class Wire extends Connection {
  int sent,closed;final Vector packets=new Vector();
  public void forceDisconnect(){closed++;}
  public void sendPacket(Packet packet){sent++;packets.addElement(packet);}
 }
 static void drain(){while(!Display.queued.isEmpty()){Runnable r=(Runnable)Display.queued.elementAt(0);Display.queued.removeElementAt(0);r.run();}}
 static void notification()throws Exception{
  Manager.failCreate=true;
  call(ContactList.class,"playSound",new Class[]{String.class,Integer.TYPE},null,"message.mp3",1);
  check(f(ContactList.class,"playerFree").getBoolean(null),"player OOM left reservation");
  Manager.failCreate=false;int attempts=Manager.attempts;
  call(ContactList.class,"playSound",new Class[]{String.class,Integer.TYPE},null,"message.mp3",1);
  check(Manager.attempts>attempts,"later sound not attempted");
  call(ContactList.class,"finishSound",new Class[]{javax.microedition.media.Player.class},null,f(ContactList.class,"soundPlayer").get(null));
 }
 static void upload()throws Exception{
  final Wire old=new Wire();f(Icq.class,"c").set(null,old);f(Icq.class,"thread").set(null,new Thread());f(Icq.class,"connected").setBoolean(null,true);
  Icq.Upload one=new Icq.Upload("1000001");Icq.sendVoice("1000001",new byte[]{1,2,3},1,"audio/amr",one);
  long id=((SnacPacket)old.packets.lastElement()).getReference();
  check(id!=0&&one.matches("1000001",id)&&!one.matches("1000001",id+1),"ACK not tied to upload");
  Wire replacement=new Wire();f(Icq.class,"c").set(null,replacement);f(Icq.class,"thread").set(null,new Thread());
  try{Icq.sendVoice("1000001",new byte[]{4},1,"audio/amr",one);throw new AssertionError("old upload accepted");}catch(JimmException expected){}
  check(replacement.sent==0&&!one.matches("1000001",id),"old upload reached new session");
  Icq.Upload cancelled=new Icq.Upload("1000001");cancelled.cancel();
  try{Icq.sendVoice("1000001",new byte[]{4},1,"audio/amr",cancelled);throw new AssertionError("cancel ignored");}catch(JimmException expected){}
  check(replacement.sent==0,"cancelled data sent");
  Icq.Upload stream=new Icq.Upload("1000001");byte[] bytes=new byte[Icq.PHOTO_PART+7];Arrays.fill(bytes,(byte)23);
  Icq.sendVideoStream("1000001",new java.io.ByteArrayInputStream(bytes),bytes.length,2,"video/3gpp",stream);
  check(replacement.sent==2,"stream not sent in parts");stream.cancel();
  Icq.Upload shortStream=new Icq.Upload("1000001");
  try{Icq.sendVideoStream("1000001",new java.io.ByteArrayInputStream(new byte[1]),100,2,"video/3gpp",shortStream);throw new AssertionError("short file padded");}catch(java.io.IOException expected){}
  shortStream.cancel();
 }
 static void cancelLogin(String key)throws Exception{
  Wire socket=new Wire();f(Icq.class,"c").set(null,socket);f(Icq.class,"thread").set(null,new Thread());f(Icq.class,"connected").setBoolean(null,false);
  new SplashCanvas();ConnectAction action=new ConnectAction("100500","test","host","5190",false);
  SplashCanvas.addTimerTask(key,action,true);
  call(SplashCanvas.class,"keyPressed",new Class[]{Integer.TYPE},f(SplashCanvas.class,"_this").get(null),-22);
  check(Icq.isDisconnected()&&socket.closed==1,"hidden Motorola Cancel did not disconnect: offline="+Icq.isDisconnected()+", closed="+socket.closed+", locked="+SplashCanvas.locked());
  Wire next=new Wire();f(Icq.class,"c").set(null,next);f(Icq.class,"thread").set(null,new Thread());
  check(!((Boolean)call(ConnectAction.class,"forward",new Class[]{Packet.class},action,new ConnectPacket())).booleanValue(),"cancelled login processed a late packet");
  check(!Icq.isConnected()&&next.sent==0,"cancelled login affected new session");
 }
 static void voice()throws Exception{
  Wire wire=new Wire();f(Icq.class,"c").set(null,wire);f(Icq.class,"thread").set(null,new Thread());f(Icq.class,"connected").setBoolean(null,true);
  Previous back=new Previous();VoiceRecorder.show("1000001",back);final VoiceRecorder rec=(VoiceRecorder)f(VoiceRecorder.class,"current").get(null);
  f(VoiceRecorder.class,"sending").setBoolean(rec,true);Icq.Upload transfer=new Icq.Upload("1000001");f(VoiceRecorder.class,"transfer").set(rec,transfer);
  Icq.sendVoice("1000001",new byte[]{1},1,"audio/amr",transfer);long id=((SnacPacket)wire.packets.lastElement()).getReference();
  VoiceRecorder.voiceSent("1000001",true,id+1);check(!f(VoiceRecorder.class,"done").getBoolean(rec),"wrong voice ACK accepted");
  VoiceRecorder.voiceSent("1000001",true,id);check(f(VoiceRecorder.class,"done").getBoolean(rec),"voice ACK ignored");
  java.util.TimerTask delayed=(java.util.TimerTask)f(VoiceRecorder.class,"returnTask").get(rec);
  rec.commandAction(JimmUI.cmdBack,rec);drain();int before=back.returns;
  Options.setString(Options.OPTION_LOCK_PIN,"1234");f(SplashCanvas.class,"isLocked").setBoolean(null,true);SplashCanvas.show();
  delayed.run();drain();check(back.returns==before&&SplashCanvas.pinLocked()&&Jimm.display.getCurrent()!=back.screen,"old voice callback bypassed PIN");
  f(SplashCanvas.class,"isLocked").setBoolean(null,false);
 }
 static void images()throws Exception{
  Constructor ctor=PhotoViewer.class.getDeclaredConstructor(JimmScreen.class);ctor.setAccessible(true);
  PhotoViewer photo=(PhotoViewer)ctor.newInstance(new Previous());f(PhotoViewer.class,"current").set(null,photo);
  photo.onBart(new byte[]{1,2,3,4});check(Image.entered.await(2,TimeUnit.SECONDS),"photo decoder not entered");
  f(SplashCanvas.class,"isLocked").setBoolean(null,true);SplashCanvas.show();photo.commandAction(JimmUI.cmdBack,null);drain();
  check(SplashCanvas.pinLocked()&&Jimm.display.getCurrent()==f(SplashCanvas.class,"_this").get(null),"photo Back bypassed PIN");
  RequestBuddyIconAction avatar=new RequestBuddyIconAction("1000001",new byte[16]);f(RequestBuddyIconAction.class,"state").setInt(avatar,4);
  byte[] payload=new byte[52];payload[0]=7;System.arraycopy("1000001".getBytes("UTF-8"),0,payload,1,7);
  Util.putWord(payload,8,1);payload[11]=16;Util.putWord(payload,49,1);
  call(RequestBuddyIconAction.class,"forward",new Class[]{Packet.class},avatar,new SnacPacket(0x10,7,0,new byte[0],payload));
  Thread.sleep(40);check(Image.maxActive==1,"parallel native decoders");Image.resume.countDown();
  check(Image.avatarEntered.await(2,TimeUnit.SECONDS),"avatar worker not released");drain();check(Image.maxActive==1,"decoders overlapped");
  f(SplashCanvas.class,"isLocked").setBoolean(null,false);
 }
 public static void main(String[] args){try{
  f(Options.class,"options").set(null,new Hashtable());call(Options.class,"setDefaults",new Class[0],null);
  Constructor c=MainThread.class.getDeclaredConstructor();c.setAccessible(true);c.newInstance();new Icq();new ContactList();new SplashCanvas();
  notification();upload();cancelLogin(args[0]);voice();images();
  System.out.println("PASS: native audio OOM, operation/session ACKs, stream EOF, login Cancel, delayed PIN callback and serialized image decoders");
 }catch(Throwable e){e.printStackTrace();System.exit(1);}System.exit(0);}
}
