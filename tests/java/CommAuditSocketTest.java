import java.io.*;
import java.lang.reflect.*;
import java.util.concurrent.*;
import jimm.*;
import jimm.comm.*;
import jimm.comm.connections.*;

/** Complete frames and their terminal EOF must reach the consumer in order. */
public final class CommAuditSocketTest {
 static Field f(Class c,String n)throws Exception{Field f=c.getDeclaredField(n);f.setAccessible(true);return f;}
 static void check(boolean b,String why){if(!b)throw new AssertionError(why);}
 static final class Handle implements javax.microedition.io.SocketConnection {
  public void close(){}public InputStream openInputStream(){return null;}public OutputStream openOutputStream(){return null;}
  public DataInputStream openDataInputStream(){return null;}public DataOutputStream openDataOutputStream(){return null;}
  public void setSocketOption(byte o,int v){}public int getSocketOption(byte o){return 0;}
  public String getLocalAddress(){return "localhost";}public int getLocalPort(){return 0;}public String getAddress(){return "localhost";}public int getPort(){return 0;}
 }
 static final class End extends ByteArrayInputStream {
  final CountDownLatch reached=new CountDownLatch(1),release;
  End(byte[] data,boolean block){super(data);release=new CountDownLatch(block?1:0);}
  public int read(byte[] data,int off,int len){
   int n=super.read(data,off,len);
   if(n==-1){reached.countDown();try{check(release.await(3,TimeUnit.SECONDS),"EOF gate timed out");}catch(InterruptedException e){throw new AssertionError(e);}}
   return n;
  }
  public void close(){release.countDown();}
 }
 static byte[] frame(int ref){return new SnacPacket(0x17,3,ref,new byte[0],new byte[]{0,1,0,1,55}).toByteArray();}
 static Thread start(SOCKETConnection conn,InputStream source)throws Exception{
  Method reopen=Connection.class.getDeclaredMethod("setInputCloseFlag",Boolean.TYPE);reopen.setAccessible(true);reopen.invoke(conn,false);
  f(SOCKETConnection.class,"is").set(conn,source);f(SOCKETConnection.class,"os").set(conn,new ByteArrayOutputStream());f(SOCKETConnection.class,"sc").set(conn,new Handle());
  f(Icq.class,"c").set(null,conn);f(Icq.class,"thread").set(null,new Thread());f(Icq.class,"connected").setBoolean(null,true);
  Thread receiver=new Thread(conn);f(Connection.class,"rcvThread").set(conn,receiver);JimmException.errors=0;receiver.start();return receiver;
 }
 static void join(Thread thread)throws Exception{thread.join(2000);check(!thread.isAlive(),"receiver failed to finish after EOF/cancel");}
 static void eof(SOCKETConnection conn)throws Exception{
  try{conn.getPacket();throw new AssertionError("EOF not delivered after its final frame");}
  catch(JimmException expected){check(expected.getErrCode()==120,"wrong deferred EOF error");}
  check(conn.available()==0 && f(Connection.class,"queuedBytes").getInt(conn)==0,"terminal event corrupted queue accounting");
 }
 static void ordered()throws Exception{
  SOCKETConnection conn=new SOCKETConnection();Thread receiver=start(conn,new ByteArrayInputStream(frame(123)));join(receiver);
  check(JimmException.errors==0 && Icq.isConnected(),"EOF disconnects session before its final complete frame is processed");
  Packet data=conn.getPacket();check(data instanceof SnacPacket && ((SnacPacket)data).getReference()==123,"last authorization reply was lost");eof(conn);conn.forceDisconnect();
  System.out.println("PASS: complete final frame delivered before EOF, without premature session teardown");
 }
 static void inFlight()throws Exception{
  SOCKETConnection conn=new SOCKETConnection();End source=new End(frame(234),true);Thread receiver=start(conn,source);
  check(source.reached.await(2,TimeUnit.SECONDS),"final frame not queued");
  check(((SnacPacket)conn.getPacket()).getReference()==234,"dequeued frame lost");
  source.release.countDown();join(receiver);
  check(JimmException.errors==0 && Icq.isConnected(),"EOF interrupts handler of an already dequeued final frame");eof(conn);conn.forceDisconnect();
  System.out.println("PASS: EOF also waits behind a dequeued frame whose handler is still running");
 }
 static void cancelAndReuse()throws Exception{
  byte[] one=frame(345),two=new byte[one.length*2];System.arraycopy(one,0,two,0,one.length);System.arraycopy(one,0,two,one.length,one.length);
  SOCKETConnection conn=new SOCKETConnection();End source=new End(two,false);Thread receiver=start(conn,source);
  check(source.reached.await(2,TimeUnit.SECONDS),"full queue EOF not reached");
  check(conn.available()==2,"terminal event exceeded the two-item receive limit");
  conn.forceDisconnect();join(receiver);check(conn.available()==0 && JimmException.errors==0,"cancel retained terminal event or reported stale EOF");
  receiver=start(conn,new ByteArrayInputStream(frame(456)));join(receiver);
  check(conn.available()==2 && ((SnacPacket)conn.getPacket()).getReference()==456,"reused connection retained old payload/EOF");eof(conn);conn.forceDisconnect();
  System.out.println("PASS: terminal event obeys queue bound, Cancel releases a full queue, reconnect has no stale frames/errors");
 }
 static void empty()throws Exception{
  SOCKETConnection conn=new SOCKETConnection();join(start(conn,new ByteArrayInputStream(new byte[0])));
  check(JimmException.errors==1 && !Icq.isConnected() && conn.available()==0,"empty EOF no longer reports immediate connection failure");
 }
 public static void main(String[] args)throws Exception{
  try{new Icq();ordered();inFlight();cancelAndReuse();empty();}
  finally{Icq.disconnect(true);Jimm.getTimerRef().cancel();}
 }
}
