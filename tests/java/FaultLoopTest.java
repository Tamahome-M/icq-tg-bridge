import java.lang.reflect.*;
import java.util.concurrent.*;
import jimm.*;
import jimm.comm.*;
import jimm.comm.connections.*;
public class FaultLoopTest {
 static Field f(Class c,String n)throws Exception{Field f=c.getDeclaredField(n);f.setAccessible(true);return f;}
 static final class Login extends ConnectAction {
  final CountDownLatch started=new CountDownLatch(1);
  Login(){super("100500","test","host","5190",true);}
  protected void init(){try{f(Icq.class,"connected").setBoolean(null,true);started.countDown();}catch(Exception e){throw new AssertionError(e);}}
  public boolean isCompleted(){return started.getCount()==0;}public boolean isError(){return false;}
  protected boolean forward(Packet p){return false;}public void onEvent(int e){}
 }
 static final class Timed extends Action {
  final CountDownLatch initialized=new CountDownLatch(1),failed=new CountDownLatch(1);
  public long getDeadline(){return began+50;}
  long began;Timed(){super(false,true);}
  protected void init(){began=System.currentTimeMillis();initialized.countDown();}
  protected boolean forward(Packet p){return false;}public boolean isCompleted(){return false;}
  public boolean isError(){boolean expired=began!=0 && System.currentTimeMillis()-began>=50;if(expired)failed.countDown();return expired;}
 }
 static final class Gate extends Connection {
  final CountDownLatch paused=new CountDownLatch(1),resume=new CountDownLatch(1);int outside;
  public void forceDisconnect(){resume.countDown();}
  public synchronized int available(){
   if(!Thread.holdsLock(Icq.getWaitObj()) && ++outside==2){paused.countDown();try{resume.await(3,TimeUnit.SECONDS);}catch(Exception e){}}
   return 0;
  }
 }
 static void wake(){synchronized(Icq.getWaitObj()){Icq.getWaitObj().notifyAll();}}
 public static void main(String[] args)throws Exception{
  new Icq();Login login=new Login();Icq.requestAction(login);
  if(!login.started.await(2,TimeUnit.SECONDS))throw new AssertionError("login not started");
  Timed timed=new Timed();Icq.requestAction(timed);wake();
  if(!timed.initialized.await(2,TimeUnit.SECONDS))throw new AssertionError("action not started");
  if(!timed.failed.await(2,TimeUnit.SECONDS))throw new AssertionError("quiet request missed its deadline");
  wake();if(!timed.failed.await(2,TimeUnit.SECONDS))throw new AssertionError("wake did not check deadline");
  System.out.println("AFTER UNRELATED WAKE: error notified=true");
  Thread.sleep(30);Gate gate=new Gate();f(Icq.class,"bartC").set(null,gate);wake();
  if(!gate.paused.await(2,TimeUnit.SECONDS))throw new AssertionError("loop gap not reached");
  Timed next=new Timed();Icq.requestAction(next);gate.resume.countDown();
  if(!next.initialized.await(2,TimeUnit.SECONDS))throw new AssertionError("queued request lost its wake");
  wake();if(!next.initialized.await(2,TimeUnit.SECONDS))throw new AssertionError("second wake did not initialize action");
  System.out.println("AFTER SECOND WAKE: initialized=true");Icq.disconnect(true);Jimm.jimm.cancelTimer();System.exit(0);
 }
}
