
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
   PhotoViewer viewer=viewer();viewer.onBart(jpeg);decoded(viewer);
   check(f(PhotoViewer.class,"image").get(viewer)==null,"failed decoder kept a bitmap");
   check((mode==1?"photo_memory":"photo_format").equals(f(PhotoViewer.class,"status").get(viewer)),"decoder failure reason was hidden");
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
   failures(expected);
  }finally{conn.forceDisconnect();Jimm.getTimerRef().cancel();}
 }
}
