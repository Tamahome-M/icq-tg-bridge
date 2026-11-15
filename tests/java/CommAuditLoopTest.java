package jimm.comm;

import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.*;
import jimm.*;
import jimm.comm.connections.*;

/** init() failure must terminate its callback just like an active action error. */
public final class CommAuditLoopTest {
 static Field f(Class c,String n)throws Exception{Field v=c.getDeclaredField(n);v.setAccessible(true);return v;}
 static void check(boolean value,String text){if(!value)throw new AssertionError(text);}
 static final class Login extends ConnectAction {
  final CountDownLatch ready=new CountDownLatch(1);
  Login(){super("100500","test","host","5190",true);}
  protected void init(){try{f(Icq.class,"connected").setBoolean(null,true);ready.countDown();}catch(Exception e){throw new AssertionError(e);}}
  public boolean isCompleted(){return ready.getCount()==0;}public boolean isError(){return false;}
  protected boolean forward(Packet p){return false;}public void onEvent(int e){}
 }
 static final class FailInit extends Action {
  final CountDownLatch entered=new CountDownLatch(1),terminated=new CountDownLatch(1);int events;
  FailInit(){super(false,true);}
  protected void init()throws JimmException{entered.countDown();throw new JimmException(120,53,false);}
  protected boolean forward(Packet p){return false;}public boolean isCompleted(){return false;}public boolean isError(){return false;}
  public void onEvent(int e){if(e==ON_ERROR){events++;terminated.countDown();}}
 }
 static final class BrokenService extends Connection {
  BrokenService(){state=true;}
  public void sendPacket(Packet packet)throws JimmException{throw new JimmException(120,3,JimmException.ICQ_BART);}
  public void forceDisconnect(){state=false;notifyToDisconnect();}
 }
 static final class Result implements RequestBartAction.ErrorListener {
  final CountDownLatch failed=new CountDownLatch(1);int calls;
  public void onBart(byte[] data){if(data==null){calls++;failed.countDown();}}
  public void onBartError(String reason){calls++;failed.countDown();}
 }
 static final class FailedBart extends RequestBartAction {
  FailedBart(Result result){super("1000037",BART_HISTORY,new byte[16],result);}
  protected void init()throws JimmException{
   try{super.init();}
   // Suppress only the native popup in this desktop loop fixture.
   catch(JimmException error){throw new JimmException(error.getErrCode(),53,false);}
  }
 }
 static final class Marker extends Action {
  final CountDownLatch started=new CountDownLatch(1);Marker(){super(false,true);}
  protected void init(){started.countDown();}protected boolean forward(Packet p){return false;}
  public boolean isCompleted(){return started.getCount()==0;}public boolean isError(){return false;}
 }
 public static void main(String[] args)throws Exception{
  try{
   new Icq();Login login=new Login();Icq.requestAction(login);check(login.ready.await(2,TimeUnit.SECONDS),"login fixture stuck");
   FailInit failed=new FailInit();Marker after=new Marker();Icq.requestAction(failed);Icq.requestAction(after);
   check(failed.entered.await(2,TimeUnit.SECONDS),"failing action not initialized");
   check(after.started.await(2,TimeUnit.SECONDS),"init failure stopped following request");
   check(failed.terminated.await(250,TimeUnit.MILLISECONDS) && failed.events==1,"init failure removed request without notifying its listener");
   check(Icq.isConnected(),"optional action failure disconnected main session");
   Icq.bartC=new BrokenService();f(Icq.class,"bartReady").setBoolean(null,true);Icq.noteBartUse();
   Result result=new Result();FailedBart bart=new FailedBart(result);Marker next=new Marker();Icq.requestAction(bart);Icq.requestAction(next);
   check(next.started.await(2,TimeUnit.SECONDS),"failed BART init blocked following action");
   check(result.failed.await(250,TimeUnit.MILLISECONDS) && result.calls==1,"real BART send failure left history listener waiting");
   check(!bart.isBartPending() && Icq.isConnected(),"failed optional BART action remains pending or disconnects BOS");
   System.out.println("PASS: noncritical init failure terminates action exactly once and the live session continues with the next request");
  }finally{Icq.disconnect(true);Jimm.getTimerRef().cancel();}
 }
}
