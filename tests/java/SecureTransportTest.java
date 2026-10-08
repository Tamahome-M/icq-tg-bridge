import java.io.*;
import java.lang.reflect.*;
import java.util.Arrays;
import jimm.Options;
import jimm.comm.*;
import jimm.comm.connections.*;

public final class SecureTransportTest {
    static void check(boolean ok,String message){if(!ok)throw new AssertionError(message);}
    static byte[] bytes(DataInputStream in) throws Exception {
        byte[] data=new byte[in.readInt()];in.readFully(data);return data;
    }
    static SecureTransport streams(byte[] wire,OutputStream out,byte[] keys) throws Exception {
        Constructor c=SecureTransport.class.getDeclaredConstructor(InputStream.class,OutputStream.class,byte[].class);
        c.setAccessible(true);return (SecureTransport)c.newInstance(new ByteArrayInputStream(wire),out,keys);
    }
    static void readAll(InputStream in,byte[] out) throws Exception {
        int got=0;while(got<out.length){int n=in.read(out,got,Math.min(73,out.length-got));check(n>0,"truncated record");got+=n;}
    }
    static void vectors(String path) throws Exception {
        DataInputStream in=new DataInputStream(new FileInputStream(path));
        byte[] psk=bytes(in);int count=in.readInt();
        for(int i=0;i<count;i++){
            byte[] data=bytes(in),sha=bytes(in),authKey=bytes(in),mac=bytes(in),nonce=bytes(in);int counter=in.readInt();byte[] encrypted=bytes(in);
            check(Arrays.equals(SecureCrypto.sha256(data),sha),"SHA-256 oracle mismatch");
            check(Arrays.equals(SecureCrypto.hmac(authKey,data,null,null),mac),"HMAC oracle mismatch");
            byte[] actual=(byte[])data.clone();new SecureCrypto.ChaCha().crypt(psk,nonce,counter,actual,actual.length);
            check(Arrays.equals(actual,encrypted),"ChaCha20 oracle mismatch");
        }
        byte[] request=bytes(in),response=bytes(in),keys=bytes(in),plain=bytes(in),clientWire=bytes(in),serverWire=bytes(in);
        check(Arrays.equals(SecureCrypto.keys(psk,request,response),keys),"HKDF oracle mismatch");
        ByteArrayOutputStream out=new ByteArrayOutputStream();SecureTransport transport=streams(serverWire,out,keys);
        check(transport.input.available()==1,"encrypted available must only signal readiness");
        byte[] got=new byte[plain.length];readAll(transport.input,got);check(Arrays.equals(got,plain),"server records mismatch");
        check(transport.input.read()==-1,"record EOF lost");
        transport.output.write(plain);transport.output.flush();check(Arrays.equals(out.toByteArray(),clientWire),"client records mismatch");
        byte[] bad=(byte[])serverWire.clone();bad[bad.length-1]^=1;
        try{readAll(streams(bad,new ByteArrayOutputStream(),keys).input,got);throw new AssertionError("bad MAC accepted");}
        catch(SecureTransport.Failure expected){check(expected.code==184,"wrong integrity error");}
        try{streams(new byte[]{(byte)255,(byte)255},new ByteArrayOutputStream(),keys).input.read();throw new AssertionError("oversize record accepted");}
        catch(SecureTransport.Failure expected){}
        byte[] first=SecureTransport.nextNonce(),second=SecureTransport.nextNonce();
        check(!Arrays.equals(SecureCrypto.slice(first,0,8),SecureCrypto.slice(second,0,8)),"RMS counter did not advance");
        check(SecureTransport.parseKey("000102030405060708090A0B0C0D0E0F101112131415161718191A1B1C1D1E1F").length==32,"uppercase PSK rejected");
        try{SecureTransport.parseKey("short");throw new AssertionError("short PSK accepted");}catch(SecureTransport.Failure expected){}
        for(int code=180;code<=184;code++)check(!Icq.isNotCriticalConnectionError(code),"encryption error triggers automatic retries");
        check(Icq.isNotCriticalConnectionError(118),"temporary timeout lost reconnect");
        in.close();System.out.println("PASS: real CLDC SHA-256/HMAC/ChaCha20/HKDF match independent Python crypto; records, MAC, bounds, RMS counter");
    }
    static Packet waitPacket(SOCKETConnection socket) throws Exception {
        long until=System.currentTimeMillis()+5000;
        while(socket.available()==0 && System.currentTimeMillis()<until)Thread.sleep(5);
        check(socket.available()>0,"receiver did not deliver packet");return socket.getPacket();
    }
    static void socket(String address) throws Exception {
        Field options=Options.class.getDeclaredField("options");options.setAccessible(true);options.set(null,new java.util.Hashtable());
        Method defaults=Options.class.getDeclaredMethod("setDefaults");defaults.setAccessible(true);defaults.invoke(null);
        Options.setBoolean(Options.OPTION_ENCRYPTION,true);
        Options.setString(Options.OPTION_ENCRYPTION_PSK,"000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f");
        SOCKETConnection conn=new SOCKETConnection();
        try {
            for(int attempt=0;attempt<2;attempt++){
                conn.connect(address);check(waitPacket(conn) instanceof ConnectPacket,"protected OSCAR hello lost");
                // Packet.parse intentionally ignores channel 5; the receiver
                // still queues the frame and the main loop observes activity.
                for(int i=0;i<3;i++){conn.sendPacket(new PingPacket());check(waitPacket(conn)==null,"keepalive parsing changed");}
                conn.forceDisconnect();if(attempt==0)Thread.sleep(1000); // same socket object, like auth -> BOS
            }
        }finally{conn.forceDisconnect();}
        System.out.println("PASS: actual SOCKETConnection negotiates with real Python Session, encrypted receiver, pings and socket reuse");
    }
    static void cancel(String address) throws Exception {
        final SOCKETConnection conn=new SOCKETConnection();
        final boolean[] failed={false};javax.microedition.io.Connector.written=0;
        Thread worker=new Thread(){public void run(){try{conn.connect(address);}catch(Exception expected){failed[0]=true;}}};
        worker.start();long until=System.currentTimeMillis()+5000;
        while(javax.microedition.io.Connector.written<44 && System.currentTimeMillis()<until)Thread.sleep(5);
        check(javax.microedition.io.Connector.written>=44,"handshake request not sent");
        conn.forceDisconnect();worker.join(2000);
        check(!worker.isAlive() && failed[0],"cancel did not stop pending handshake");
        System.out.println("PASS: cancellation closes socket while waiting for encryption handshake");
    }
    public static void main(String[] args) throws Exception {
        try{vectors(args[0]);if(args.length>1)socket(args[1]);if(args.length>2)cancel(args[2]);}
        finally{jimm.Jimm.getTimerRef().cancel();}
    }
}
