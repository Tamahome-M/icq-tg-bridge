package jimm;

import java.io.*;
import java.lang.reflect.*;
import java.util.Arrays;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import jimm.comm.*;
import jimm.comm.connections.*;

public final class ClientResourceTest {
    static void check(boolean ok, String text) { if (!ok) throw new AssertionError(text); }
    static Field field(Class type, String name) throws Exception {
        Field f = type.getDeclaredField(name); f.setAccessible(true); return f;
    }
    static void macs() throws Exception {
        for (int k : new int[]{32, 129}) {
            byte[] key = new byte[k], header = new byte[10];
            for (int i=0;i<k;i++) key[i]=(byte)(i*7);
            for (int i=0;i<10;i++) header[i]=(byte)(i*13);
            SecureCrypto.RecordMac records = new SecureCrypto.RecordMac(key);
            Mac oracle = Mac.getInstance("HmacSHA256"); oracle.init(new SecretKeySpec(key,"HmacSHA256"));
            for (int n : new int[]{0,1,15,55,63,64,65,511,1023,1024}) {
                byte[] data = new byte[n+5]; for(int i=0;i<data.length;i++) data[i]=(byte)(i*11);
                oracle.update(header); oracle.update(data,0,n); byte[] expected=oracle.doFinal();
                for(int outLength : new int[]{16,32}) {
                    byte[] out = new byte[outLength]; records.calculate(header,data,n,out);
                    check(Arrays.equals(out,Arrays.copyOf(expected,outLength)),"cached HMAC mismatch");
                }
            }
        }
        final Throwable[] errors = new Throwable[4]; Thread[] threads = new Thread[4];
        for(int t=0;t<4;t++) {
            final int index=t;
            threads[t]=new Thread(){public void run(){try{
                byte[] key=new byte[32],h=new byte[10],d=new byte[1024],out=new byte[16];key[0]=(byte)index;
                SecureCrypto.RecordMac mac=new SecureCrypto.RecordMac(key);
                byte[] expected=Arrays.copyOf(SecureCrypto.recordMac(key,h,d,d.length),16);
                for(int i=0;i<300;i++){mac.calculate(h,d,d.length,out);check(Arrays.equals(out,expected),"parallel MAC state leaked");}
            }catch(Throwable e){errors[index]=e;}}};threads[t].start();
        }
        for(int t=0;t<4;t++){threads[t].join(5000);check(!threads[t].isAlive(),"MAC lock deadlocked");if(errors[t]!=null)throw new AssertionError(errors[t]);}
        check(!SecureCrypto.equal(new byte[1],Integer.MAX_VALUE,new byte[1],1),"MAC bounds overflow");
        com.sun.management.ThreadMXBean meter=(com.sun.management.ThreadMXBean)java.lang.management.ManagementFactory.getThreadMXBean();
        byte[] key=new byte[32],header=new byte[10],data=new byte[1024],out=new byte[16];
        SecureCrypto.RecordMac cached=new SecureCrypto.RecordMac(key);long id=Thread.currentThread().getId();
        for(int i=0;i<2000;i++){cached.calculate(header,data,1024,out);SecureCrypto.recordMac(key,header,data,1024);}
        long before=meter.getThreadAllocatedBytes(id);
        for(int i=0;i<4096;i++)SecureCrypto.recordMac(key,header,data,1024);
        long old=meter.getThreadAllocatedBytes(id)-before;before=meter.getThreadAllocatedBytes(id);
        for(int i=0;i<4096;i++)cached.calculate(header,data,1024,out);
        long now=meter.getThreadAllocatedBytes(id)-before;
        check(now==0 && old>100000,"record HMAC still allocates per call");
        System.out.println("METRIC desktop JVM, escape analysis disabled: 4096 record MACs allocated "+old+" -> "+now+" bytes");
        System.out.println("PASS: record HMAC matches independent JCE, partial buffers, long keys, four parallel streams; no per-record allocation");
    }
    static final class TestConnection extends Connection {
        public void forceDisconnect(){notifyToDisconnect();}
        boolean offer(byte[] data) throws Exception {if(!waitForPacketSpace(data.length))return false;queuePacket(data);return true;}
    }
    static void packets() throws Exception {
        final TestConnection queue=new TestConnection();check(queue.getPacket()==null,"empty connection failed");
        byte[] a=new byte[8000];a[0]=42;a[1]=5;Util.putWord(a,4,a.length-6);
        queue.offer(a);queue.offer(a);final boolean[] done={false},accepted={false};
        Thread producer=new Thread(){public void run(){try{accepted[0]=queue.offer(new byte[8000]);done[0]=true;}catch(Exception e){throw new AssertionError(e);}}};
        producer.start();Thread.sleep(40);check(!done[0] && queue.available()==2,"receive queue is unbounded");
        queue.getPacket();producer.join(1000);check(done[0] && accepted[0] && queue.available()==2,"dequeue did not wake receiver");
        done[0]=false;accepted[0]=true;
        producer=new Thread(){public void run(){try{accepted[0]=queue.offer(new byte[8000]);done[0]=true;}catch(Exception e){throw new AssertionError(e);}}};
        producer.start();Thread.sleep(40);queue.forceDisconnect();producer.join(1000);
        check(done[0] && !accepted[0] && queue.available()==0,"cancel retained packets or blocked receiver");
        System.out.println("PASS: receive queue backpressure, dequeue wakeup and cancellation release");
    }
    static final class PausedInput extends InputStream {
        final java.util.concurrent.CountDownLatch entered=new java.util.concurrent.CountDownLatch(1),eof=new java.util.concurrent.CountDownLatch(1);
        boolean closed;
        public int read(){return -1;}
        public int read(byte[] data,int off,int length){entered.countDown();try{eof.await();}catch(Exception e){throw new AssertionError(e);}return -1;}
        public void close(){closed=true;}
    }
    static final class TrackedOutput extends ByteArrayOutputStream {boolean closed;public void close(){closed=true;}}
    static final class SocketHandle implements javax.microedition.io.SocketConnection {
        boolean closed;
        public void close(){closed=true;}
        public InputStream openInputStream(){return null;}public OutputStream openOutputStream(){return null;}
        public DataInputStream openDataInputStream(){return null;}public DataOutputStream openDataOutputStream(){return null;}
        public void setSocketOption(byte o,int v){}public int getSocketOption(byte o){return 0;}
        public String getLocalAddress(){return "localhost";}public int getLocalPort(){return 0;}
        public String getAddress(){return "localhost";}public int getPort(){return 0;}
    }
    static void receiverReuse() throws Exception {
        field(Options.class,"options").set(null,new java.util.Hashtable());
        Method defaults=Options.class.getDeclaredMethod("setDefaults");defaults.setAccessible(true);defaults.invoke(null);
        Options.setInt(Options.OPTION_CONN_PROP,0);
        SOCKETConnection conn=new SOCKETConnection();PausedInput oldInput=new PausedInput();
        TrackedOutput oldOutput=new TrackedOutput();SocketHandle oldSocket=new SocketHandle();
        field(SOCKETConnection.class,"is").set(conn,oldInput);field(SOCKETConnection.class,"os").set(conn,oldOutput);field(SOCKETConnection.class,"sc").set(conn,oldSocket);
        Thread old=new Thread(conn);field(Connection.class,"rcvThread").set(conn,old);old.start();
        check(oldInput.entered.await(2,java.util.concurrent.TimeUnit.SECONDS),"old receiver did not read");
        PausedInput currentInput=new PausedInput();TrackedOutput currentOutput=new TrackedOutput();SocketHandle currentSocket=new SocketHandle();
        field(Connection.class,"rcvThread").set(conn,new Thread());
        field(SOCKETConnection.class,"is").set(conn,currentInput);field(SOCKETConnection.class,"os").set(conn,currentOutput);field(SOCKETConnection.class,"sc").set(conn,currentSocket);
        field(Connection.class,"state").setBoolean(conn,true);oldInput.eof.countDown();old.join(2000);
        check(!old.isAlive() && oldInput.closed && oldOutput.closed && oldSocket.closed,"old receiver leaked its streams");
        check(conn.getState() && !currentInput.closed && !currentOutput.closed && !currentSocket.closed
            && field(SOCKETConnection.class,"is").get(conn)==currentInput,"old receiver closed or reset reused connection");
        conn.forceDisconnect();
        System.out.println("PASS: delayed old receiver releases only its own streams; reused connection stays open and connected");
    }
    static void media() throws Exception {
        byte[] amr={0,0,'#','!','A','M','R',10,1};
        check(".amr".equals(MediaPlayer.temporarySuffix(RequestBartAction.BART_VOICE,amr,2,7)),"legacy AMR suffix lost");
        check(".3gp".equals(MediaPlayer.temporarySuffix(RequestBartAction.BART_VOICE,new byte[32],0,32)),"3GP voice saved as AMR");
        check(".3gp".equals(MediaPlayer.temporarySuffix(RequestBartAction.BART_VIDEO,amr,2,7)),"video suffix changed");
        final MediaBuffer buffer=new MediaBuffer();final ByteArrayOutputStream bytes=new ByteArrayOutputStream();
        final boolean[] result={false};Thread writer=new Thread(){public void run(){try{result[0]=buffer.writeTo(bytes);}catch(Exception e){throw new AssertionError(e);}}};
        byte[] part=new byte[14020];Arrays.fill(part,(byte)7);
        check(buffer.put(part,10,14000),"first media part refused");
        check(field(MediaBuffer.class,"pending").get(buffer)==part,"media payload copied");
        final boolean[] second={false};Thread producer=new Thread(){public void run(){second[0]=buffer.put(new byte[]{9,8,6},1,1);}};
        producer.start();Thread.sleep(40);check(!second[0],"media buffer grows without writer");writer.start();producer.join(1000);
        check(second[0],"writer did not wake producer");buffer.finish(true);writer.join(1000);
        check(result[0] && bytes.size()==14001 && bytes.toByteArray()[14000]==8,"media ranges/order/completion lost");
        final MediaBuffer cancelled=new MediaBuffer();cancelled.put(part,0,1);
        producer=new Thread(){public void run(){second[0]=cancelled.put(part,0,1);}};producer.start();Thread.sleep(40);
        cancelled.finish(false);producer.join(1000);cancelled.finish(true);
        check(!producer.isAlive() && !second[0] && !cancelled.writeTo(bytes)
            && field(MediaBuffer.class,"pending").get(cancelled)==null,"cancel retained a part or became success");
        System.out.println("PASS: zero-copy media ranges, one pending part, writer backpressure, cancellation and completion");
    }
    static final class Sink implements RequestBartAction.PartSink {
        int parts,done,full;boolean ok;
        public boolean onBartPart(byte[] b,int o,int n,int part,int total){parts++;return part==1;}
        public void onBartDone(boolean success){done++;ok=success;}
        public void onBart(byte[] b){full++;}
        public void onBartProgress(int part,int total){}
    }
    static byte[] reply(int type,int part,int total,int size) throws Exception {
        ByteArrayOutputStream bytes=new ByteArrayOutputStream();DataOutputStream out=new DataOutputStream(bytes);
        out.writeByte(7);out.writeBytes("1000001");out.writeShort(type);out.writeByte(part);out.writeByte(16);out.write(new byte[16]);
        out.writeByte(0);out.writeShort(type);out.writeByte(total);out.writeByte(16);out.write(new byte[16]);out.writeShort(size);out.write(new byte[size]);
        return bytes.toByteArray();
    }
    static RequestBartAction request(RequestBartAction.Listener sink) throws Exception {
        RequestBartAction r=new RequestBartAction("1000001",RequestBartAction.BART_VIDEO,new byte[16],sink);
        field(RequestBartAction.class,"state").setInt(r,RequestBartAction.STATE_CLI_REQ_SENT);return r;
    }
    static void forward(RequestBartAction r,byte[] data)throws Exception{
        Method f=RequestBartAction.class.getDeclaredMethod("forward",Packet.class);f.setAccessible(true);
        f.invoke(r,new SnacPacket(0x10,7,1,new byte[0],data));
    }
    static void multipart() throws Exception {
        Sink sink=new Sink();RequestBartAction r=request(sink);
        forward(r,reply(RequestBartAction.BART_VIDEO,1,3,10));forward(r,reply(RequestBartAction.BART_VIDEO,2,3,10));
        check(r.isCompleted() && !r.isError() && sink.done==1 && !sink.ok && sink.full==0,"failed file prefix replaced by truncated memory tail");
        r.isError();check(sink.done==1,"sink notified twice");
        for(byte[] malformed : new byte[][]{new byte[0],new byte[20],reply(RequestBartAction.BART_VIDEO,2,3,1),reply(RequestBartAction.BART_VIDEO,1,0,1)}) {
            sink=new Sink();r=request(sink);
            try{forward(r,malformed);throw new AssertionError("malformed BART accepted");}
            catch(InvocationTargetException e){check(e.getCause() instanceof JimmException && !((JimmException)e.getCause()).isCritical(),"malformed BART crashed or disconnected main session");}
            check(r.isError(),"malformed BART left pending action");
        }
        final int[] range={0};RequestBartAction.RangeListener listener=new RequestBartAction.RangeListener(){
            public void onBart(byte[] b){throw new AssertionError("range listener got copy");}
            public void onBart(byte[] b,int o,int n){range[0]=n;check(b.length==20 && n==13 && o==0,"multipart range mismatch");}
        };
        r=request(listener);forward(r,reply(RequestBartAction.BART_VIDEO,1,2,10));forward(r,reply(RequestBartAction.BART_VIDEO,2,2,3));
        check(r.isCompleted() && range[0]==13,"range response not completed");
        final int[] errors={0};RequestBartAction.ErrorListener capture=new RequestBartAction.ErrorListener(){
            public void onBart(byte[] b){throw new AssertionError("error returned as bytes");}
            public void onBartError(String message){errors[0]++;}
        };
        RequestBartAction first=request(capture),second=request(capture);
        Packet error=new SnacPacket(0x10,1,field(RequestBartAction.class,"requestId").getInt(second),new byte[0],new byte[]{0,1});
        Method dispatch=RequestBartAction.class.getDeclaredMethod("forward",Packet.class);dispatch.setAccessible(true);
        check(!((Boolean)dispatch.invoke(first,error)).booleanValue() && errors[0]==0 && !first.isCompleted(),"foreign BART error consumed");
        RequestBuddyIconAction icon=new RequestBuddyIconAction("1000001",new byte[16]);
        field(RequestBuddyIconAction.class,"state").setInt(icon,RequestBuddyIconAction.STATE_CLI_REQBUDDYICON_SENT);
        Method avatar=RequestBuddyIconAction.class.getDeclaredMethod("forward",Packet.class);avatar.setAccessible(true);
        check(!((Boolean)avatar.invoke(icon,error)).booleanValue() && !icon.isCompleted(),"avatar consumed a photo/history error");
        Packet ownError=new SnacPacket(0x10,1,field(RequestBuddyIconAction.class,"requestId").getInt(icon),new byte[0],new byte[]{0,1});
        check(((Boolean)avatar.invoke(icon,ownError)).booleanValue() && icon.isCompleted(),"avatar ignored its own error");
        check(((Boolean)dispatch.invoke(second,error)).booleanValue() && second.isCompleted() && errors[0]==1,"own BART error lost");
        System.out.println("PASS: malformed/order/total BART checks, failed streaming stays failed, multipart range avoids trim copy");
    }
    public static void main(String[] args) throws Exception {
        try{macs();packets();receiverReuse();media();multipart();}
        catch(Throwable error){error.printStackTrace();System.exit(1);}
        finally{Jimm.getTimerRef().cancel();}
    }
}
