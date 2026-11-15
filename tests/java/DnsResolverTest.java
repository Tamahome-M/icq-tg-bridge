import java.io.*;
import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.*;
import javax.microedition.io.*;
import jimm.comm.connections.DnsResolver;

/** Real parser and lookup lifecycle; only MIDP UDP transport is replaced. */
public final class DnsResolverTest {
    interface Script { Reply[] reply(byte[] query, int number) throws Exception; }
    static final class Reply {
        byte[] data; String source; int offset;
        Reply(byte[] data) { this(data, "datagram://1.1.1.1:53"); }
        Reply(byte[] data, String source) { this.data=data; this.source=source; }
    }
    static final class Packet implements InvocationHandler {
        byte[] data; int offset,length; String address;
        Packet(byte[] bytes,int length,String address){data=bytes;this.length=length;this.address=address;}
        public Object invoke(Object proxy,Method m,Object[] args)throws Exception {
            String name=m.getName();
            if(name.equals("getData"))return data;
            if(name.equals("getOffset"))return Integer.valueOf(offset);
            if(name.equals("getLength"))return Integer.valueOf(length);
            if(name.equals("getAddress"))return address;
            if(name.equals("setData")){data=(byte[])args[0];offset=((Integer)args[1]).intValue();length=((Integer)args[2]).intValue();return null;}
            if(name.equals("setLength")){length=((Integer)args[0]).intValue();return null;}
            if(name.equals("setAddress")){address=args[0] instanceof String?(String)args[0]:((Datagram)args[0]).getAddress();return null;}
            if(name.equals("reset")){offset=length=0;return null;}
            throw new AssertionError("Unexpected datagram method "+name);
        }
        Datagram proxy(){return (Datagram)Proxy.newProxyInstance(getClass().getClassLoader(),new Class[]{Datagram.class},this);}
    }
    static final class UDP implements DatagramConnection {
        Script script; Vector received=new Vector(); int sends,receives; boolean closed;
        final CountDownLatch waiting=new CountDownLatch(1);
        UDP(Script script){this.script=script;}
        public int getMaximumLength(){return 512;}
        public int getNominalLength(){return 512;}
        public synchronized void close(){closed=true;notifyAll();}
        public synchronized void send(Datagram packet)throws IOException {
            if(closed)throw new IOException("closed");
            check(packet.getAddress().equals("datagram://1.1.1.1:53"),"destination reset after receive");
            byte[] query=Arrays.copyOfRange(packet.getData(),packet.getOffset(),packet.getOffset()+packet.getLength());
            check(query.length<=271 && word(query,2)==0x100 && word(query,4)==1,"bounded recursive A query");
            check(word(query,6)==0 && word(query,8)==0 && word(query,10)==0,"query has no EDNS or extra records");
            check(word(query,query.length-4)==1 && word(query,query.length-2)==1,"A/IN query");
            try { Reply[] replies=script.reply(query,++sends);for(int i=0;i<replies.length;i++)received.addElement(replies[i]); }
            catch(IOException e){throw e;}catch(Exception e){throw new AssertionError(e);}
        }
        public synchronized void receive(Datagram datagram)throws IOException {
            waiting.countDown();
            while(received.isEmpty()&&!closed)try{wait();}catch(InterruptedException e){throw new IOException("interrupted");}
            if(closed)throw new IOException("closed");
            receives++;
            check(datagram.getLength()==512,"receive capacity must be reset");
            Reply reply=(Reply)received.elementAt(0);received.removeElementAt(0);
            Packet p=(Packet)Proxy.getInvocationHandler(datagram);
            if(reply.offset!=0){p.data=new byte[reply.data.length+reply.offset];p.offset=reply.offset;}
            System.arraycopy(reply.data,0,p.data,p.offset,reply.data.length);
            p.length=reply.data.length;p.address=reply.source;
        }
        public Datagram newDatagram(byte[] b,int n,String a){return new Packet(b,n,a).proxy();}
        public Datagram newDatagram(byte[] b,int n){return newDatagram(b,n,"datagram://1.1.1.1:53");}
        public Datagram newDatagram(int n,String a){return newDatagram(new byte[n],n,a);}
        public Datagram newDatagram(int n){return newDatagram(new byte[n],n);}
    }
    static int checks;
    static void check(boolean ok,String detail){checks++;if(!ok)throw new AssertionError(detail);}
    static int word(byte[] b,int at){return ((b[at]&255)<<8)|(b[at+1]&255);}
    static void put(byte[] b,int at,int n){b[at]=(byte)(n>>8);b[at+1]=(byte)n;}
    static byte[] ptr(int n){return new byte[]{(byte)(0xc0|(n>>8)),(byte)n};}
    static byte[] name(String name)throws Exception {
        ByteArrayOutputStream out=new ByteArrayOutputStream();
        for(String part:name.split("\\.")){out.write(part.length());out.write(part.getBytes("US-ASCII"));}
        out.write(0);return out.toByteArray();
    }
    static byte[] cat(byte[]... parts)throws Exception{ByteArrayOutputStream out=new ByteArrayOutputStream();for(byte[] part:parts)out.write(part);return out.toByteArray();}
    static byte[] rr(byte[] owner,int type,byte[] data)throws Exception {
        ByteArrayOutputStream out=new ByteArrayOutputStream();out.write(owner);
        DataOutputStream d=new DataOutputStream(out);d.writeShort(type);d.writeShort(1);d.writeInt(60);d.writeShort(data.length);d.write(data);return out.toByteArray();
    }
    static byte[] ip(int n){return new byte[]{10,20,30,(byte)n};}
    static byte[] a(byte[] owner,int n)throws Exception{return rr(owner,1,ip(n));}
    static byte[] response(byte[] query,byte[][] answers,byte[][] extra)throws Exception {
        byte[] header=Arrays.copyOf(query,query.length);put(header,2,0x8180);put(header,6,answers.length);put(header,10,extra.length);
        ByteArrayOutputStream out=new ByteArrayOutputStream();out.write(header);for(byte[] a:answers)out.write(a);for(byte[] a:extra)out.write(a);return out.toByteArray();
    }
    static byte[] response(byte[] query,byte[]... answers)throws Exception{return response(query,answers,new byte[0][]);}
    static String asked(byte[] q){StringBuffer s=new StringBuffer();int at=12;while(q[at]!=0){int n=q[at++]&255;if(s.length()!=0)s.append('.');while(n-->0)s.append((char)q[at++]);}return s.toString();}
    static UDP install(Script script){final UDP udp=new UDP(script);Connector.factory=new Connector.Factory(){public Connection open(String url,int mode,boolean timeouts){check(url.equals("datagram://1.1.1.1:53")&&mode==Connector.READ_WRITE&&timeouts,"numeric DNS URL and timeout hint");return udp;}};return udp;}
    static void closed(DnsResolver resolver,UDP udp)throws Exception{check(udp.closed,"UDP closed");Field timer=DnsResolver.class.getDeclaredField("timer");timer.setAccessible(true);check(timer.get(resolver)==null,"deadline timer released");}
    static int[] resolve(String host,Script script)throws Exception{UDP udp=install(script);DnsResolver resolver=new DnsResolver();try{return resolver.lookup(host,"1.1.1.1");}finally{closed(resolver,udp);}}
    static void fails(Script script)throws Exception {
        UDP udp=install(script);DnsResolver r=new DnsResolver();try{r.lookup("bridge.example.org","1.1.1.1");throw new AssertionError("bad reply accepted");}catch(IOException expected){check(expected.getMessage()!=null,"visible DNS failure");}finally{closed(r,udp);}
    }
    static Script valid(){return new Script(){public Reply[] reply(byte[] q,int n)throws Exception{return new Reply[]{new Reply(response(q,a(ptr(12),1))) };}};}

    static void literals()throws Exception {
        for(String good:new String[]{"1.1.1.1","0.0.0.0","255.255.255.255","192.168.1.10"})check(DnsResolver.isIPv4(good),good);
        for(String bad:new String[]{"","1.1.1","1.1.1.1.","01.1.1.1","256.1.1.1","1.-1.1.1","example.org","1.1.1.1:53","::1"})check(!DnsResolver.isIPv4(bad),bad);
        check(!DnsResolver.isIPv4(null),"null literal");
        check(DnsResolver.ipv4(0xc0a80101).equals("192.168.1.1"),"unsigned IPv4 conversion");
        Connector.factory=new Connector.Factory(){public Connection open(String a,int b,boolean c){throw new AssertionError("literal or invalid input used network");}};
        check(new DnsResolver().lookup("192.168.1.1","1.1.1.1")[0]==0xc0a80101,"literal uses no UDP");
        for(String host:new String[]{"", "a..org", ".host", "http://host", "host:5190", "тест.рф", "a b", new String(new char[64]).replace('\0','a')+".org"}) {
            try{new DnsResolver().lookup(host,"1.1.1.1");throw new AssertionError("bad hostname");}catch(IOException expected){}
        }
        try{new DnsResolver().lookup("bridge.example.org","dns.google");throw new AssertionError("OS DNS server lookup");}catch(IOException expected){}
    }
    static void packets()throws Exception {
        int[] got=resolve("BrIdGe.Example.ORG.",new Script(){public Reply[] reply(byte[] q,int n)throws Exception{
            check(asked(q).equals("bridge.example.org"),"canonical query");
            return new Reply[]{new Reply(response(q,a(ptr(12),1),a(ptr(12),1),a(ptr(12),2),a(ptr(12),3),a(ptr(12),4),a(ptr(12),5)))};
        }});
        check(got.length==4&&got[0]==0x0a141e01&&got[3]==0x0a141e04,"four unique A records");
        got=resolve("bridge.example.org",new Script(){public Reply[] reply(byte[] q,int n)throws Exception{
            byte[] alias=cat(new byte[]{4,'e','d','g','e'},ptr(19));
            return new Reply[]{new Reply(response(q,rr(ptr(12),5,alias),a(ptr(q.length+12),7)))};
        }});
        check(got.length==1&&got[0]==0x0a141e07,"compressed CNAME and compressed owner");
        got=resolve("bridge.example.org",new Script(){public Reply[] reply(byte[] q,int n)throws Exception{
            if(n==1)return new Reply[]{new Reply(response(q,new byte[][]{rr(ptr(12),5,name("edge.example.org"))},new byte[][]{a(name("edge.example.org"),99)}))};
            check(n==2&&asked(q).equals("edge.example.org"),"CNAME startup exchange ignores additional A");
            return new Reply[]{new Reply(response(q,a(ptr(12),8)))};
        }});
        check(got[0]==0x0a141e08,"only matching answer A used");
        for(final String source:new String[]{"datagram://1.1.1.1:53","//1.1.1.1:53","1.1.1.1:53"})
            check(resolve("bridge.example.org",new Script(){public Reply[] reply(byte[] q,int n)throws Exception{Reply r=new Reply(response(q,a(ptr(12),9)),source);r.offset=3;return new Reply[]{r};}})[0]==0x0a141e09,"source forms and datagram offset");
        got=resolve("bridge.example.org",new Script(){public Reply[] reply(byte[] q,int n)throws Exception{
            byte[] valid=response(q,a(ptr(12),3)),wrongId=(byte[])valid.clone(),wrongQuestion=(byte[])valid.clone();wrongId[0]^=1;wrongQuestion[13]='x';
            return new Reply[]{new Reply(valid,"datagram://9.9.9.9:53"),new Reply(valid,"datagram://1.1.1.1:123"),new Reply(wrongId),new Reply(wrongQuestion),new Reply(valid)};
        }});
        check(got[0]==0x0a141e03,"foreign source/id/question ignored");
        got=resolve("bridge.example.org",new Script(){public Reply[] reply(byte[] q,int n)throws Exception{return new Reply[]{new Reply(response(q,rr(ptr(12),1,new byte[4]),rr(ptr(12),1,new byte[]{-1,-1,-1,-1}),rr(ptr(12),1,new byte[]{(byte)224,1,2,3}),a(ptr(12),4)))};}});
        check(got.length==1&&got[0]==0x0a141e04,"zero/broadcast/multicast filtered");
    }
    static void rejection()throws Exception {
        for(final int kind:new int[]{0,1,2,3,4,5,6,7,8,9,10,11,12,13,14})fails(new Script(){public Reply[] reply(byte[] q,int n)throws Exception{
            byte[] b=response(q,a(ptr(12),1));
            switch(kind){
            case 0:put(b,2,0x8380);break; // TC
            case 1:put(b,2,0x0180);break; // QR absent
            case 2:put(b,2,0x8980);break; // non-query opcode
            case 3:put(b,2,0x8183);break; // NXDOMAIN
            case 4:put(b,4,2);break;
            case 5:put(b,6,65535);break;
            case 6:put(b,q.length+10,5);break; // truncated A data
            case 7:b=response(q,a(ptr(q.length),1));break; // self pointer
            case 8:b=response(q,a(ptr(511),1));break; // forward/out-of-range pointer
            case 9:b=response(q,a(name("foreign.example.org"),1));break;
            case 10:b=response(q,new byte[0][],new byte[][]{a(ptr(12),1)});break;
            case 11:b=response(q,rr(ptr(12),5,cat(name("edge.example.org"),new byte[]{0})));break;
            case 12:b=response(q,rr(ptr(12),5,name("one.example.org")),rr(ptr(12),5,name("two.example.org")));break;
            case 13:b=response(q,rr(ptr(12),5,name("edge.example.org")),a(ptr(12),1));break;
            case 14:b=response(q,rr(ptr(12),1,new byte[]{1,2,3}));break;
            }
            return new Reply[]{new Reply(b)};
        }});
        fails(new Script(){public Reply[] reply(byte[] q,int n)throws Exception{return new Reply[]{new Reply(response(q,rr(ptr(12),5,name(n==1?"edge.example.org":"bridge.example.org"))))};}});
        fails(new Script(){public Reply[] reply(byte[] q,int n)throws Exception{check(n<=9,"CNAME exchange bound");return new Reply[]{new Reply(response(q,rr(ptr(12),5,name("hop"+n+".example.org"))))};}});
        final UDP flood=install(new Script(){public Reply[] reply(byte[] q,int n)throws Exception{Reply[] r=new Reply[16];for(int i=0;i<r.length;i++)r[i]=new Reply(response(q,a(ptr(12),1)),"datagram://9.9.9.9:53");return r;}});
        DnsResolver r=new DnsResolver();try{r.lookup("bridge.example.org","1.1.1.1");throw new AssertionError("foreign flood accepted");}catch(IOException expected){}closed(r,flood);check(flood.receives==16,"receive flood bounded");
    }
    static final class Lookup extends Thread {
        final DnsResolver resolver; Throwable failure;
        Lookup(DnsResolver r){resolver=r;}
        public void run(){try{resolver.lookup("bridge.example.org","1.1.1.1");failure=new AssertionError("cancelled lookup succeeded");}catch(IOException expected){failure=expected;}catch(Throwable t){failure=t;}}
    }
    static void cancellation()throws Exception {
        Script blocked=new Script(){public Reply[] reply(byte[] q,int n){return new Reply[0];}};
        UDP udp=install(blocked);DnsResolver r=new DnsResolver();Lookup task=new Lookup(r);task.start();check(udp.waiting.await(2,TimeUnit.SECONDS),"receive entered");
        try{r.lookup("bridge.example.org","1.1.1.1");throw new AssertionError("resolver reused");}catch(IOException expected){}
        check(!udp.closed,"second lookup must not close first");r.cancel();task.join(2000);check(!task.isAlive()&&task.failure instanceof IOException,"cancel unblocks UDP");closed(r,udp);
        final UDP late=new UDP(valid());final CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        Connector.factory=new Connector.Factory(){public Connection open(String url,int mode,boolean timeout)throws IOException{entered.countDown();try{release.await();}catch(InterruptedException e){throw new IOException();}return late;}};
        r=new DnsResolver();task=new Lookup(r);task.start();check(entered.await(2,TimeUnit.SECONDS),"native open entered");r.cancel();release.countDown();task.join(2000);check(!task.isAlive()&&task.failure instanceof IOException,"late open cancelled");closed(r,late);check(late.sends==0,"late socket never used");
        r=new DnsResolver();r.cancel();try{r.lookup("bridge.example.org","1.1.1.1");throw new AssertionError("pre-cancel ignored");}catch(IOException expected){}
        udp=install(blocked);r=new DnsResolver();long start=System.currentTimeMillis();try{r.lookup("bridge.example.org","1.1.1.1");throw new AssertionError("deadline ignored");}catch(IOException expected){check(expected.getMessage().indexOf("timed out")>=0,"timeout reported clearly");}
        long elapsed=System.currentTimeMillis()-start;check(elapsed>=11000&&elapsed<16000,"overall 12-second deadline");closed(r,udp);
    }
    public static void main(String[] args)throws Exception {
        literals();packets();rejection();cancellation();
        System.out.println("PASS: bounded CLDC DNS parser/UDP lifecycle ("+checks+" checks)");
    }
}
