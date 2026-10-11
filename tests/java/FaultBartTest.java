package jimm.comm;

import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.*;
import jimm.*;
import jimm.comm.connections.*;

public class FaultBartTest {
 static Field f(Class c,String n)throws Exception{Field f=c.getDeclaredField(n);f.setAccessible(true);return f;}
 static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
 static final class Ready implements Icq.BartConnectListener {
  final CountDownLatch done=new CountDownLatch(1); boolean failed;
  public void onBartConnected(){done.countDown();}
  public void onBartConnectFailed(JimmException e){failed=true;done.countDown();}
 }
 static final class Sink implements RequestBartAction.Listener {
  public void onBart(byte[] data){}
 }
 public static void main(String[] args)throws Exception{
  new Icq();f(Icq.class,"thread").set(null,new Thread());
  Ready old=new Ready();Icq.connectBart("old",old);
  check(SOCKETConnection.oldEntered.await(2,TimeUnit.SECONDS),"old connect not paused");
  Icq.disconnect(true);f(Icq.class,"thread").set(null,new Thread());
  Ready next=new Ready();Icq.connectBart("new",next);
  check(next.done.await(2,TimeUnit.SECONDS)&&!next.failed,"new connection not ready");
  Connection live=Icq.bartC;SOCKETConnection.oldResume.countDown();Thread.sleep(80);
  check(Icq.bartC==live&&live.getState(),"old connect replaced/closed new");
  check(old.done.getCount()==1,"stale callback delivered");
  Ready joined=new Ready();int opens=SOCKETConnection.opened;Icq.connectBart("another",joined);
  check(joined.done.await(2,TimeUnit.SECONDS)&&Icq.bartC==live&&SOCKETConnection.opened==opens,"joining handshake opened another service");
  RequestBartAction a=new RequestBartAction("1000001",RequestBartAction.BART_PHOTO,new byte[16],new Sink());
  RequestBartAction b=new RequestBartAction("1000002",RequestBartAction.BART_HISTORY,new byte[16],new Sink());
  f(RequestBartAction.class,"state").setInt(a,RequestBartAction.STATE_CLI_COOKIE_SENT);
  f(RequestBartAction.class,"state").setInt(b,RequestBartAction.STATE_CONNECTION_ESTB);
  a.forward(new SnacPacket(1,3,0,new byte[0],new byte[0]));
  check(!b.isError()&&f(RequestBartAction.class,"state").getInt(b)==RequestBartAction.STATE_CLI_REQ_SENT,"joined request waited for an already-consumed hello");
  check(SOCKETConnection.packets.size()==3,"shared handshake lost/duplicated request");
  RequestBartAction failed=new RequestBartAction("1000001",RequestBartAction.BART_PHOTO,new byte[16],new Sink());
  RequestBartAction video=new RequestBartAction("1000002",RequestBartAction.BART_VIDEO,new byte[16],new Sink());
  f(RequestBartAction.class,"state").setInt(failed,RequestBartAction.STATE_CLI_REQ_SENT);
  f(RequestBartAction.class,"state").setInt(video,RequestBartAction.STATE_CLI_REQ_SENT);
  f(RequestBartAction.class,"lastActivity").setLong(failed,0);
  Vector actions=new Vector();actions.addElement(failed);actions.addElement(video);f(Icq.class,"actAction").set(null,actions);
  check(failed.isError(),"deadline did not fail request");
  check(Icq.bartC==live&&live.getState(),"photo timeout closed live video");
  video.onEvent(Action.ON_CANCEL);check(!video.isBartPending(),"cancelled request retained callback");
  check(Icq.bartC==null,"unused abandoned service not closed");
  int sent=SOCKETConnection.packets.size();video.init();
  check(video.isError()&&!video.isBartPending()&&SOCKETConnection.packets.size()==sent,"queued Cancel restarted a removed request");
  System.out.println("PASS: stale service ownership, isolated timeout and request cancellation");System.exit(0);
 }
}
