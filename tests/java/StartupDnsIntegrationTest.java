package jimm.comm;

import java.lang.reflect.*;
import java.util.*;
import jimm.*;
import jimm.comm.connections.*;
import javax.microedition.io.Connector;
import DrawControls.VirtualList;

/** DNS policy is exercised through real login init, sockets and error handler. */
public final class StartupDnsIntegrationTest {
 static Field field(Class c,String n)throws Exception{Field f=c.getDeclaredField(n);f.setAccessible(true);return f;}
 static void check(boolean ok,String text){if(!ok)throw new AssertionError(text);}
 static void eq(String expected,String actual){check(expected.equals(actual),expected+" != "+actual);}
 static final class Login extends ConnectAction {
  Login(){super("100500","test","bridge.example","5190",true);}
  void open()throws JimmException{super.init();}
 }
 static SOCKETConnection install()throws Exception{
  Icq.disconnect(true);
  SOCKETConnection socket=new SOCKETConnection();Icq.c=socket;
  field(Icq.class,"thread").set(null,Thread.currentThread());
  Icq.setDisconnected(false);return socket;
 }
 static void fail(Login action)throws Exception{
  try{action.open();throw new AssertionError("expected socket failure");}
  catch(JimmException e){check(e.getErrCode()==120,"unexpected error "+e.getErrCode());JimmException.handleException(e);}
 }
 static void setup(boolean enabled)throws Exception{
  field(Options.class,"options").set(null,new Hashtable());
  Method defaults=Options.class.getDeclaredMethod("setDefaults");defaults.setAccessible(true);defaults.invoke(null);
  Options.setString(Options.OPTION_SRV_HOST,"bridge.example,legacy.example");
  Options.setBoolean(Options.OPTION_STARTUP_DNS,enabled);
  Options.setBoolean(Options.OPTION_RECONNECT,false);
  Constructor constructor=MainThread.class.getDeclaredConstructor();constructor.setAccessible(true);constructor.newInstance();
  new Icq();new ContactList();new ChatHistory();new SplashCanvas();VirtualList.setDisplay(Jimm.display);
  StartupDns.start();
 }
 static void pinAndReconnect(SOCKETConnection socket)throws Exception{
  check(field(StartupDns.class,"pinned").get(null)==null,"TCP open alone pinned an unverified login");
  Icq.setConnected(); // exactly the full-login hook used by ConnectAction
  Threads.requested=0;
  JimmException.handleException(new JimmException(120,0));
  check(Threads.requested==0,"pinned address fell back with autoreconnect disabled");
  socket=install();new Login().open();eq("socket://5.6.7.8:5190",Connector.last);
  Icq.rotateServersList();
  eq("bridge.example,legacy.example",Options.getString(Options.OPTION_SRV_HOST));
  SOCKETConnection bart=new SOCKETConnection(JimmException.ICQ_BART);
  try{
   bart.connect("BRIDGE.EXAMPLE.:7777");eq("socket://5.6.7.8:7777",Connector.last);
   bart.forceDisconnect();bart.connect("service.example:4444");eq("socket://service.example:4444",Connector.last);
  }finally{bart.forceDisconnect();}
  StartupDns.start();check(DnsResolver.calls==1,"reconnect/service/resume queried DNS again");
 }
 public static void main(String[] args)throws Exception{
  try{
   String mode=args[0];if(mode.equals("dns_failure"))DnsResolver.fail=true;
   setup(!mode.equals("disabled"));SOCKETConnection socket=install();Login login=new Login();
   if(mode.equals("disabled")){
    login.open();eq("socket://bridge.example:5190",Connector.last);
    check(DnsResolver.calls==0,"disabled option queried DNS");
    Icq.rotateServersList();eq("legacy.example,bridge.example",Options.getString(Options.OPTION_SRV_HOST));
   }else if(mode.equals("dns_failure")){
    try{login.open();throw new AssertionError("DNS failure hidden");}
    catch(JimmException e){check(e.getErrCode()==195,"DNS error code lost");JimmException.handleException(e);}
    check(Connector.opened.isEmpty() && Threads.requested==0,"DNS failure escaped into native lookup/retries");
   }else if(mode.equals("choose")){
    Connector.fail="socket://1.2.3.4:5190";fail(login);
    check(Threads.requested==1,"first route failure didn't schedule next IP with auto disabled");
    socket=install();new Login().open();eq("socket://5.6.7.8:5190",Connector.last);
    pinAndReconnect(socket);
   }else if(mode.equals("bos")){
    login.open();eq("socket://1.2.3.4:5190",Connector.last);
    socket.forceDisconnect();Connector.fail="socket://1.2.3.4:443";
    try{socket.connect("bridge.example:443");throw new AssertionError("expected BOS failure");}
    catch(JimmException e){JimmException.handleException(e);}
    check(Threads.requested==1,"BOS failure lost login candidate ownership");
    socket=install();new Login().open();eq("socket://5.6.7.8:5190",Connector.last);
    socket.forceDisconnect();socket.connect("bridge.example:443");eq("socket://5.6.7.8:443",Connector.last);
    pinAndReconnect(socket);
   }else{
    login.open();
    if(mode.equals("auth"))JimmException.handleException(new JimmException(111,0));
    else{login.onEvent(Action.ON_CANCEL);JimmException.handleException(new JimmException(120,0));}
    check(Threads.requested==0,"auth error/manual Cancel switched IP");
    socket=install();new Login().open();eq("socket://1.2.3.4:5190",Connector.last);
   }
   System.out.println("PASS actual DNS/login/socket/error integration: "+mode);
  }finally{
   Icq.disconnect(true);StartupDns.destroy();Jimm.getTimerRef().cancel();
   Object canvas=field(VirtualList.class,"virtualCanvas").get(null);
   if(canvas!=null)((Timer)field(canvas.getClass(),"repeatTimer").get(canvas)).cancel();
  }
 }
}
