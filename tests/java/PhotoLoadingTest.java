
import java.io.*;
import java.lang.reflect.*;
import java.util.*;
import jimm.*;
import jimm.comm.*;
import jimm.comm.connections.*;
import jimm.util.ResourceBundle;
public class PhotoLoadingTest {
 static void check(boolean b,String m){if(!b)throw new AssertionError(m);}
 static Field f(Class c,String n)throws Exception{Field x=c.getDeclaredField(n);x.setAccessible(true);return x;}
 static byte[] hex(String text){byte[] b=new byte[text.length()/2];for(int i=0;i<b.length;i++)b[i]=(byte)Integer.parseInt(text.substring(i*2,i*2+2),16);return b;}
 static Packet next(SOCKETConnection c)throws Exception{
  long until=System.currentTimeMillis()+5000;
  while(c.available()==0 && System.currentTimeMillis()<until)Thread.sleep(5);
  check(c.available()>0,"no packet; state="+c.getState());return c.getPacket();
 }
 static PhotoViewer viewer()throws Exception{
  Constructor constructor=PhotoViewer.class.getDeclaredConstructor(JimmScreen.class);constructor.setAccessible(true);
  PhotoViewer viewer=(PhotoViewer)constructor.newInstance(new Object[]{null});
  f(PhotoViewer.class,"status").set(viewer,"loading");f(PhotoViewer.class,"current").set(null,viewer);
  return viewer;
 }
 static void decoded(PhotoViewer viewer)throws Exception{
  long until=System.currentTimeMillis()+5000;
  while("loading".equals(f(PhotoViewer.class,"status").get(viewer)) && System.currentTimeMillis()<until)Thread.sleep(5);
  check(!"loading".equals(f(PhotoViewer.class,"status").get(viewer)),"JPEG decoder did not finish");
 }
 static void failures(byte[] jpeg)throws Exception{
  for(int mode=1;mode<=2;mode++){
   javax.microedition.lcdui.Image.mode=mode;
   javax.microedition.lcdui.Image.calls=0;
   PhotoViewer viewer=viewer();viewer.onBart(jpeg);decoded(viewer);
   check(f(PhotoViewer.class,"image").get(viewer)==null,"failed decoder kept a bitmap");
   check((mode==1?"photo_memory":"photo_format").equals(f(PhotoViewer.class,"status").get(viewer)),"decoder failure reason was hidden");
   check(javax.microedition.lcdui.Image.calls==(mode==1?2:1),"decoder failure retried too often or not at all");
  }
  javax.microedition.lcdui.Image.mode=0;
  PhotoViewer viewer=viewer();viewer.onBart(null);
  check("photo_download_failed".equals(f(PhotoViewer.class,"status").get(viewer)),"download failure reported as decode failure");
  RequestBartAction action=new RequestBartAction("1000001",RequestBartAction.BART_PHOTO,new byte[16],viewer);
  f(RequestBartAction.class,"state").setInt(action,RequestBartAction.STATE_CLI_REQ_SENT);
  String reason="Картинка недоступна на сервере";byte[] text=reason.getBytes("UTF-8");
  ByteArrayOutputStream body=new ByteArrayOutputStream();DataOutputStream error=new DataOutputStream(body);
  error.writeShort(1);error.writeShort(0x9003);error.writeShort(text.length);error.write(text);
  Method forward=RequestBartAction.class.getDeclaredMethod("forward",Packet.class);forward.setAccessible(true);
  forward.invoke(action,new SnacPacket(0x10,1,77,new byte[0],body.toByteArray()));
  check(action.isCompleted() && ("photo_download_failed: "+reason).equals(f(PhotoViewer.class,"status").get(viewer)),"server failure reason lost on photo screen");
  viewer=viewer();action=new RequestBartAction("1000001",RequestBartAction.BART_PHOTO,new byte[16],viewer);
  f(RequestBartAction.class,"lastActivity").set(action,new Date(0));
  check(action.isError(),"expired request did not fail");
  check("photo_download_failed: media_timeout".equals(f(PhotoViewer.class,"status").get(viewer)),"timeout reason lost on photo screen");
  String previous=ConnLog.text();action.isError();
  check(previous.equals(ConnLog.text()),"failed action notified its photo viewer twice");
  check(previous.indexOf("JPEG")>=0 && previous.indexOf("media_timeout")>=0,"photo diagnostics absent from connection log");
  viewer.onBartError("Ошибка загрузки: повторите запрос. ДлинноеСловоБезПробеловДляПроверкиПереносаСтрок");
  javax.microedition.lcdui.Graphics graphics=new javax.microedition.lcdui.Graphics();
  Method paint=PhotoViewer.class.getDeclaredMethod("paint",javax.microedition.lcdui.Graphics.class);paint.setAccessible(true);paint.invoke(viewer,graphics);
  check(graphics.lines.size()>1,"long error was clipped to one line");StringBuffer shown=new StringBuffer();
  for(int i=0;i<graphics.lines.size();i++){
   String line=(String)graphics.lines.elementAt(i);check(line.length()*6<=164,"photo error exceeds V3 screen width");
   shown.append(line.replace(" ",""));
  }
  check(shown.toString().equals(((String)f(PhotoViewer.class,"status").get(viewer)).replace(" ","")),"wrapped photo error lost text");
  PhotoViewer old=viewer();PhotoViewer current=viewer();old.onBart(jpeg);old.onBartError("old request");
  check("loading".equals(f(PhotoViewer.class,"status").get(current)),"closed viewer changed the current screen");
  System.out.println("PASS: photo decoder OOM/format errors, server UTF-8 reason, timeout once, readable V3-width error, connection log and closed-viewer guard");
 }
 static boolean hasImage(DrawControls.TextList card)throws Exception{
  Vector lines=(Vector)f(DrawControls.TextList.class,"lines").get(card);
  for(int i=0;i<lines.size();i++){
   Object line=lines.elementAt(i);Vector items=(Vector)f(line.getClass(),"items").get(line);
   for(int j=0;j<items.size();j++){
    Object item=items.elementAt(j);if(f(item.getClass(),"image").get(item)!=null)return true;
   }
  }
  return false;
 }
 static ContactItem contact(String uin)throws Exception{
  ContactItem item=new ContactItem(1,1,uin,"contact",false,true);
  ((Vector)f(ContactList.class,"cItems").get(null)).addElement(item);
  return item;
 }
 static DrawControls.TextList card(ContactItem item)throws Exception{
  DrawControls.TextList card=JimmUI.getInfoTextList("card",false);
  f(JimmUI.class,"uiBigTextIndex").setInt(null,0);
  String[] data=new String[JimmUI.UI_LAST_ID];data[JimmUI.UI_UIN]=item.getStringValue(ContactItem.CONTACTITEM_UIN);
  data[JimmUI.UI_NAME]="kept contact text";JimmUI.showUserInfo(data);return card;
 }
 static void memory(byte[] jpeg)throws Exception{
  f(ContactList.class,"cItems").set(null,new Vector());
  final ContactItem item=contact("1000001");
  final byte[] hash=new byte[16];hash[0]=1;
  item.setBytesArray(ContactItem.CONTACTITEM_BUDDYICON_HASH,hash);
  ContactList.update("1000001",new javax.microedition.lcdui.Image(),hash);
  final DrawControls.TextList card=card(item);
  check(hasImage(card),"test contact card did not retain its avatar");
  final String text=card.getTextByIndex(0,false,0);
  check(text.indexOf("kept contact text")>=0,"test contact text missing");
  javax.microedition.lcdui.Image.beforeDecode=new Runnable(){public void run(){
   try{
    check(item.getImage(ContactItem.CONTACTITEM_BUDDYICON)==null,"avatar retained during photo decode");
    check(!hasImage(card),"contact card retained the decoded avatar during photo decode");
    check(item.iconReady(),"evicted avatar cannot be requested again");
   }catch(Exception e){throw new AssertionError(e);}
  }};
  PhotoViewer viewer=viewer();viewer.onBart(jpeg);decoded(viewer);
  check(f(PhotoViewer.class,"image").get(viewer)!=null,"photo failed after avatar eviction");
  check(text.equals(card.getTextByIndex(0,false,0)),"avatar eviction removed contact text");
  javax.microedition.lcdui.Image.beforeDecode=null;
  check(ConnLog.text().indexOf("JPEG 176x132")>=0,"photo dimensions absent from diagnostics");
  // Expiry of the avatar cache must also remove the card's independent reference.
  ContactList.update("1000001",new javax.microedition.lcdui.Image(),hash);
  DrawControls.TextList expired=card(item);
  Method drop=ContactList.class.getDeclaredMethod("dropIcons",Integer.TYPE);drop.setAccessible(true);drop.invoke(null,0);
  check(!hasImage(expired) && item.getImage(ContactItem.CONTACTITEM_BUDDYICON)==null,"expired avatar retained in cache/card");
  check(text.equals(expired.getTextByIndex(0,false,0)),"expiry removed contact text");
  // Replacing the cached owner must not retain the old bitmap in its card.
  ContactList.update("1000001",new javax.microedition.lcdui.Image(),hash);
  DrawControls.TextList replaced=card(item);contact("1000002");
  ContactList.update("1000002",new javax.microedition.lcdui.Image(),hash);
  check(!hasImage(replaced),"evicted avatar retained in the old card");
  ContactList.class.getDeclaredMethod("releaseAvatars").invoke(null);
  javax.microedition.lcdui.Image.mode=3;javax.microedition.lcdui.Image.calls=0;
  viewer=viewer();viewer.onBart(jpeg);decoded(viewer);
  check(f(PhotoViewer.class,"image").get(viewer)!=null && f(PhotoViewer.class,"status").get(viewer)==null,"transient OOM did not recover");
  check(javax.microedition.lcdui.Image.calls==2,"transient OOM did not retry exactly once");
  System.out.println("PASS: avatar/card bitmap eviction before decoding, expiry/owner eviction, contact text retained, avatars re-requestable and transient OOM recovery");
 }
 static void dimensions(byte[] jpeg)throws Exception{
  Method size=PhotoViewer.class.getDeclaredMethod("jpegSize",byte[].class);size.setAccessible(true);
  check(((Integer)size.invoke(null,(Object)jpeg)).intValue()==(176<<16|132),"wrong JPEG dimensions");
  byte[][] bad={new byte[0],new byte[]{(byte)255,(byte)216},new byte[]{(byte)255,(byte)216,(byte)255},
   new byte[]{(byte)255,(byte)216,(byte)255,(byte)192,0,7,8,0},
   new byte[]{(byte)255,(byte)216,(byte)255,(byte)254,0,1},
   new byte[]{(byte)255,(byte)216,(byte)255,(byte)218}};
  for(int i=0;i<bad.length;i++)check(((Integer)size.invoke(null,(Object)bad[i])).intValue()==0,"invalid JPEG header read past bounds");
  // Marker fill byte and a standalone marker before a complete SOF segment.
  byte[] filled={(byte)255,(byte)216,(byte)255,1,(byte)255,(byte)255,(byte)192,0,7,8,0,(byte)132,0,(byte)176};
  check(((Integer)size.invoke(null,(Object)filled)).intValue()==(176<<16|132),"JPEG marker fill/standalone header not handled");
  System.out.println("PASS: JPEG dimensions parsed without bitmap allocation; truncated/invalid headers bounded");
 }
 static void serial(byte[] jpeg)throws Exception{
  javax.microedition.lcdui.Image.calls=0;javax.microedition.lcdui.Image.maxActive=0;
  javax.microedition.lcdui.Image.entered=new java.util.concurrent.CountDownLatch(1);
  javax.microedition.lcdui.Image.proceed=new java.util.concurrent.CountDownLatch(1);
  PhotoViewer old=viewer();old.onBart(jpeg);
  check(javax.microedition.lcdui.Image.entered.await(2,java.util.concurrent.TimeUnit.SECONDS),"first decoder did not start");
  PhotoViewer current=viewer();current.onBart(jpeg);
  Thread.sleep(100);
  check(javax.microedition.lcdui.Image.calls==1,"two photo decoders allocated bitmaps simultaneously");
  javax.microedition.lcdui.Image.proceed.countDown();decoded(current);
  check(f(PhotoViewer.class,"image").get(old)==null,"closed viewer retained its late bitmap");
  check(f(PhotoViewer.class,"image").get(current)!=null,"new viewer failed after prior decoder finished");
  check(javax.microedition.lcdui.Image.maxActive==1,"more than one native photo decoder active");
  javax.microedition.lcdui.Image.entered=null;javax.microedition.lcdui.Image.proceed=null;
  System.out.println("PASS: rapid photo switching serializes native decoders and drops late bitmap");
 }
 static void avatar(SnacPacket photo)throws Exception{
  byte[] body=(byte[])photo.getDataRef().clone();int marker=1+(body[0]&255);
  byte[] hash=Arrays.copyOfRange(body,marker+4,marker+20);
  RequestBuddyIconAction action=new RequestBuddyIconAction("1000001",hash);
  f(RequestBuddyIconAction.class,"state").setInt(action,RequestBuddyIconAction.STATE_CLI_REQBUDDYICON_SENT);
  Method forward=RequestBuddyIconAction.class.getDeclaredMethod("forward",Packet.class);forward.setAccessible(true);
  check(!((Boolean)forward.invoke(action,photo)).booleanValue(),"avatar action consumed a photo response");
  body[marker]=0;body[marker+1]=1;
  byte[] wrong=(byte[])body.clone();wrong[marker+4]^=1;
  check(!((Boolean)forward.invoke(action,new SnacPacket(0x10,7,6,new byte[0],wrong))).booleanValue(),"avatar action consumed a mismatched hash");
  wrong=(byte[])body.clone();wrong[1+((body[0]&255)-1)]='2';
  check(!((Boolean)forward.invoke(action,new SnacPacket(0x10,7,6,new byte[0],wrong))).booleanValue(),"avatar action consumed another contact's reply");
  byte[][] incomplete={new byte[0],new byte[]{7},Arrays.copyOf(body,marker+20),Arrays.copyOf(body,body.length-1)};
  for(int i=0;i<incomplete.length;i++)
   check(!((Boolean)forward.invoke(action,new SnacPacket(0x10,7,6,new byte[0],incomplete[i]))).booleanValue(),"avatar accepted a truncated reply");
  SnacPacket reply=new SnacPacket(0x10,7,6,new byte[0],body);
  MainThread.updatedIcon=null;
  check(((Boolean)forward.invoke(action,reply)).booleanValue() && action.isCompleted(),"matching avatar did not complete");
  check(MainThread.updatedIcon!=null,"avatar was not decoded");
  check(javax.microedition.lcdui.Image.lastSource==body && javax.microedition.lcdui.Image.lastOffset>0,"avatar copied the packet/JPEG");
  javax.microedition.lcdui.Image.mode=1;MainThread.updatedIcon=null;
  action=new RequestBuddyIconAction("1000001",hash);
  f(RequestBuddyIconAction.class,"state").setInt(action,RequestBuddyIconAction.STATE_CLI_REQBUDDYICON_SENT);
  forward.invoke(action,reply);
  check(action.isCompleted() && MainThread.updatedIcon==null,"avatar OOM escaped or killed the action");
  javax.microedition.lcdui.Image.mode=0;
  System.out.println("PASS: avatar uses the original JPEG range, ignores photo/hash/contact mismatches and truncated replies, and survives decoder OOM");
 }
 public static void main(String[] args)throws Exception{
  SOCKETConnection conn=new SOCKETConnection(JimmException.ICQ_BART);
  try{
   f(Options.class,"options").set(null,new Hashtable());Method defaults=Options.class.getDeclaredMethod("setDefaults");defaults.setAccessible(true);defaults.invoke(null);
   Options.setBoolean(Options.OPTION_ENCRYPTION,Boolean.parseBoolean(args[4]));Options.setString(Options.OPTION_ENCRYPTION_PSK,"1234");
   conn.connect(args[0]);check(next(conn) instanceof ConnectPacket,"no BART hello");
   conn.sendPacket(new ConnectPacket(hex(args[1])));check(next(conn) instanceof SnacPacket,"no service ready");
   f(Icq.class,"bartC").set(null,conn);Icq.noteBartUse();
   final PhotoViewer viewer=viewer();
   final byte[][] data={null};final int[] notified={0};
   RequestBartAction.Listener listener=new RequestBartAction.Listener(){public void onBart(byte[] bytes){data[0]=bytes;notified[0]++;viewer.onBart(bytes);}};
   Method init=RequestBartAction.class.getDeclaredMethod("init");init.setAccessible(true);
   Method forward=RequestBartAction.class.getDeclaredMethod("forward",Packet.class);forward.setAccessible(true);
   byte[] expected=java.nio.file.Files.readAllBytes(java.nio.file.Paths.get(args[3]));
   for(int i=0;i<2;i++){
    f(PhotoViewer.class,"status").set(viewer,"loading");f(PhotoViewer.class,"image").set(viewer,null);
    RequestBartAction action=new RequestBartAction("1000001",RequestBartAction.BART_PHOTO,hex(args[2]),listener);
    init.invoke(action);forward.invoke(action,next(conn));
    check(action.isCompleted() && notified[0]==i+1,"BART did not notify success");
    check(Arrays.equals(expected,data[0]),"JPEG bytes changed in transport/parser");
    decoded(viewer);
    check(f(PhotoViewer.class,"image").get(viewer)!=null && f(PhotoViewer.class,"status").get(viewer)==null,"PhotoViewer failed JPEG decoding");
   }
   System.out.println("PASS: actual BART socket, RequestBartAction, JPEG bytes and PhotoViewer, secure="+args[4]+", bytes="+expected.length);
   f(PhotoViewer.class,"status").set(viewer,"loading");
   RequestBartAction ranged=new RequestBartAction("1000001",RequestBartAction.BART_PHOTO,hex(args[2]),viewer);
   init.invoke(ranged);SnacPacket response=(SnacPacket)next(conn);forward.invoke(ranged,response);decoded(viewer);
   check(javax.microedition.lcdui.Image.lastSource==response.getDataRef(),"photo made a separate JPEG payload copy");
   check(javax.microedition.lcdui.Image.lastOffset>0,"photo did not pass the JPEG offset to the decoder");
   check(Arrays.equals(expected,Arrays.copyOfRange(javax.microedition.lcdui.Image.lastSource,
    javax.microedition.lcdui.Image.lastOffset,javax.microedition.lcdui.Image.lastOffset+javax.microedition.lcdui.Image.lastLength)),"ranged photo JPEG bytes changed");
   check(f(PhotoViewer.class,"image").get(viewer)!=null,"ranged photo failed decoding");
   System.out.println("PASS: photo decoder uses the original SNAC body and JPEG range without a payload copy");
   memory(expected);avatar(response);dimensions(expected);serial(expected);failures(expected);
  }finally{
   conn.forceDisconnect();Jimm.getTimerRef().cancel();
   Timer timer=(Timer)f(ContactList.class,"iconTimer").get(null);if(timer!=null)timer.cancel();
   timer=(Timer)f(ContactList.class,"soundTimer").get(null);if(timer!=null)timer.cancel();
   timer=(Timer)f(DrawControls.TextList.class,"aniTimer").get(null);if(timer!=null)timer.cancel();
   Object canvas=f(DrawControls.VirtualList.class,"virtualCanvas").get(null);
   ((Timer)f(canvas.getClass(),"repeatTimer").get(canvas)).cancel();
  }
 }
}
