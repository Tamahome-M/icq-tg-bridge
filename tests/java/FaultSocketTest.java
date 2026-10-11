import java.io.*;
import java.lang.reflect.*;
import java.util.concurrent.*;
import jimm.*;
import jimm.comm.*;
import jimm.comm.connections.*;
public class FaultSocketTest {
 static Field f(Class c,String n)throws Exception{Field f=c.getDeclaredField(n);f.setAccessible(true);return f;}
 static final class Handle implements javax.microedition.io.SocketConnection {
  public void close(){}public InputStream openInputStream(){return null;}public OutputStream openOutputStream(){return null;}
  public DataInputStream openDataInputStream(){return null;}public DataOutputStream openDataOutputStream(){return null;}
  public void setSocketOption(byte o,int v){}public int getSocketOption(byte o){return 0;}
  public String getLocalAddress(){return "localhost";}public int getLocalPort(){return 0;}public String getAddress(){return "localhost";}public int getPort(){return 0;}
 }
 static void test(String name,byte[] data)throws Exception{
  final SOCKETConnection conn=new SOCKETConnection();
  f(SOCKETConnection.class,"is").set(conn,new ByteArrayInputStream(data));
  f(SOCKETConnection.class,"os").set(conn,new ByteArrayOutputStream());f(SOCKETConnection.class,"sc").set(conn,new Handle());
  f(Icq.class,"c").set(null,conn);f(Icq.class,"thread").set(null,new Thread());f(Icq.class,"connected").setBoolean(null,true);
  Thread receiver=new Thread(conn);f(Connection.class,"rcvThread").set(conn,receiver);JimmException.errors=0;
  receiver.start();receiver.join(2000);if(receiver.isAlive())throw new AssertionError("receiver hung");
  if(JimmException.errors!=1 || Icq.isConnected())throw new AssertionError("silent truncated packet: "+name);
 }
 public static void main(String[] args)throws Exception{
  test("before header",new byte[0]);
  test("inside SNAC header",new byte[]{42,2,0,1,0,12,0,1});
  test("inside SNAC body",new byte[]{42,2,0,1,0,12,0,1,0,2,0,0,0,0,0,0,1});
  test("inside non-SNAC body",new byte[]{42,1,0,1,0,4,0});
  final SOCKETConnection conn=new SOCKETConnection();
  final CountDownLatch done=new CountDownLatch(1),cancelled=new CountDownLatch(1);
  Thread connecting=new Thread(){public void run(){try{conn.connect("blocked:5190");}catch(JimmException expected){}finally{done.countDown();}}};
  f(Icq.class,"c").set(null,conn);f(Icq.class,"thread").set(null,connecting);
  connecting.start();
  if(!javax.microedition.io.Connector.entered.await(2,TimeUnit.SECONDS))throw new AssertionError("native open did not block");
  new Thread(){public void run(){Icq.disconnect(true);cancelled.countDown();}}.start();
  boolean quick=cancelled.await(500,TimeUnit.MILLISECONDS);
  javax.microedition.io.Connector.resume.countDown();
  if(!done.await(2,TimeUnit.SECONDS))throw new AssertionError("cancelled open did not finish");
  if(!quick||conn.getState()||!javax.microedition.io.Connector.closed)throw new AssertionError("Cancel blocked or resurrected socket");
  System.out.println("PASS: EOF in each frame section and Cancel during native open");
  System.exit(0);
 }
}
