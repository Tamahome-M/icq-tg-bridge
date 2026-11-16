import java.io.*;
import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.*;
import javax.microedition.io.*;
import jimm.comm.connections.DnsResolver;

/** Real parser and lookup lifecycle; only the MIDP TCP socket is replaced. */
public final class DnsResolverTest {
    interface Script { Reply[] reply(byte[] query, int number) throws Exception; }
    static final class Reply {
        byte[] data; boolean raw;
        Reply(byte[] data) { this(data, false); }
        Reply(byte[] data, boolean raw) { this.data=data; this.raw=raw; }
    }
    static final class TCP implements StreamConnection {
        Script script; Vector received=new Vector(); int sends,frames,writes,flushes;
        int inputOpens,outputOpens,connectionCloses,inputCloses,outputCloses,bytesRead,maxRead;
        int fragment=512,position; byte[] current;
        boolean closed,inputClosed,outputClosed,eofWhenEmpty,zeroRead,failInput,failOutput;
        CountDownLatch inputEntered,inputRelease,outputEntered,outputRelease;
        final CountDownLatch waiting=new CountDownLatch(1);
        TCP(Script script){this.script=script;}
        public synchronized void close(){closed=true;connectionCloses++;notifyAll();}
        final InputStream input=new InputStream(){
            public int read()throws IOException{throw new AssertionError("Use bounded bulk reads");}
            public int read(byte[] b,int off,int len)throws IOException{
                synchronized(TCP.this){
                    maxRead=Math.max(maxRead,len);
                    waiting.countDown();
                    if(zeroRead)return 0;
                    while((current==null||position==current.length)&&received.isEmpty()&&!inputClosed){
                        if(eofWhenEmpty)return -1;
                        try{TCP.this.wait();}catch(InterruptedException e){throw new IOException("interrupted");}
                    }
                    if(inputClosed)throw new IOException("input closed");
                    if(current==null||position==current.length){current=(byte[])received.elementAt(0);received.removeElementAt(0);position=0;frames++;}
                    int count=Math.min(Math.min(len,fragment),current.length-position);
                    System.arraycopy(current,position,b,off,count);position+=count;bytesRead+=count;return count;
                }
            }
            public void close(){synchronized(TCP.this){inputClosed=true;inputCloses++;TCP.this.notifyAll();}}
        };
        final OutputStream output=new OutputStream(){
            public void write(int value)throws IOException{throw new AssertionError("Prefix and query must use one write");}
            public void write(byte[] b,int off,int len)throws IOException{
                synchronized(TCP.this){
                    if(outputClosed)throw new IOException("output closed");
                    writes++;
                    check(word(b,off)==len-2,"complete length-prefixed query in one write");
                    byte[] query=Arrays.copyOfRange(b,off+2,off+len);
                    check(query.length<=271&&word(query,2)==0x100&&word(query,4)==1,"bounded recursive A query");
                    check(word(query,6)==0&&word(query,8)==0&&word(query,10)==0,"query has no EDNS or extra records");
                    check(word(query,query.length-4)==1&&word(query,query.length-2)==1,"A/IN query");
                    try{
                        Reply[] replies=script.reply(query,++sends);
                        for(int i=0;i<replies.length;i++){
                            Reply r=replies[i];
                            if(r.raw)received.addElement(r.data);
                            else{byte[] frame=new byte[r.data.length+2];put(frame,0,r.data.length);System.arraycopy(r.data,0,frame,2,r.data.length);received.addElement(frame);}
                        }
                    }catch(IOException e){throw e;}catch(Exception e){throw new AssertionError(e);}
                    TCP.this.notifyAll();
                }
            }
            public void flush(){flushes++;}
            public void close(){synchronized(TCP.this){outputClosed=true;outputCloses++;TCP.this.notifyAll();}}
        };
        void gate(CountDownLatch entered,CountDownLatch release)throws IOException{
            if(entered==null)return;entered.countDown();
            try{release.await();}catch(InterruptedException e){throw new IOException("interrupted");}
        }
        public InputStream openInputStream()throws IOException{inputOpens++;gate(inputEntered,inputRelease);if(failInput)throw new IOException("input open failed");return input;}
        public OutputStream openOutputStream()throws IOException{outputOpens++;gate(outputEntered,outputRelease);if(failOutput)throw new IOException("output open failed");return output;}
        public DataInputStream openDataInputStream(){throw new AssertionError("No extra input wrapper");}
        public DataOutputStream openDataOutputStream(){throw new AssertionError("No extra output wrapper");}
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
    static int udpCalls;
    static TCP install(Script script){final TCP tcp=new TCP(script);install(tcp);return tcp;}
    static void install(final TCP tcp){Connector.factory=new Connector.Factory(){public Connection open(String url,int mode,boolean timeouts){if(url.startsWith("datagram:")){udpCalls++;throw new SecurityException("UDP denied on V8");}check(url.equals("socket://1.1.1.1:53")&&mode==Connector.READ_WRITE&&timeouts,"numeric TCP DNS URL and timeout hint");return tcp;}};}
    static void closed(DnsResolver resolver,TCP tcp)throws Exception{
        check(tcp.closed&&tcp.connectionCloses==1,"TCP connection closed exactly once");
        check(tcp.inputCloses==(tcp.failInput?0:tcp.inputOpens),"every returned input closed");
        check(tcp.outputCloses==(tcp.failOutput?0:tcp.outputOpens),"every returned output closed");
        for(String name:new String[]{"timer","connection","input","output"}){Field f=DnsResolver.class.getDeclaredField(name);f.setAccessible(true);check(f.get(resolver)==null,name+" released");}
    }
    static int[] resolve(String host,Script script)throws Exception{TCP udp=install(script);DnsResolver resolver=new DnsResolver();try{return resolver.lookup(host,"1.1.1.1");}finally{closed(resolver,udp);}}
    static void fails(Script script)throws Exception {
        TCP udp=install(script);DnsResolver r=new DnsResolver();try{r.lookup("bridge.example.org","1.1.1.1");throw new AssertionError("bad reply accepted");}catch(IOException expected){check(expected.getMessage()!=null,"visible DNS failure");}finally{closed(r,udp);}
    }
    static Script valid(){return new Script(){public Reply[] reply(byte[] q,int n)throws Exception{return new Reply[]{new Reply(response(q,a(ptr(12),1))) };}};}

    static void fails(TCP tcp)throws Exception {
        install(tcp);DnsResolver r=new DnsResolver();
        try{r.lookup("bridge.example.org","1.1.1.1");throw new AssertionError("broken TCP exchange accepted");}
        catch(IOException expected){check(expected.getMessage()!=null,"visible transport failure");}
        finally{closed(r,tcp);}
    }

    static void framing()throws Exception {
        for(int fragment:new int[]{1,2,7,512}){
            TCP tcp=install(valid());tcp.fragment=fragment;DnsResolver r=new DnsResolver();
            check(r.lookup("bridge.example.org","1.1.1.1")[0]==0x0a141e01,"partial length prefix and body");
            closed(r,tcp);check(tcp.writes==1&&tcp.flushes==1,"single query write and flush");
        }
        for(final int size:new int[]{513,1024,2048}){
            TCP tcp=install(new Script(){public Reply[] reply(byte[] q,int n)throws Exception{
                byte[] address=a(ptr(12),9);
                byte[] padding=rr(ptr(12),16,new byte[size-q.length-address.length-12]);
                byte[] b=response(q,new byte[][]{address},new byte[][]{padding});
                check(b.length==size,"large valid DNS fixture");return new Reply[]{new Reply(b)};
            }});tcp.fragment=11;DnsResolver r=new DnsResolver();
            check(r.lookup("bridge.example.org","1.1.1.1")[0]==0x0a141e09,"bounded reply larger than UDP limit");
            closed(r,tcp);check(tcp.maxRead==size,"reply buffer grows only when required");
        }
        for(final int length:new int[]{0,1,11,2049,65535}){
            TCP tcp=new TCP(new Script(){public Reply[] reply(byte[] q,int n){byte[] b=new byte[2];put(b,0,length);return new Reply[]{new Reply(b,true)};}});
            fails(tcp);check(tcp.bytesRead==2,"invalid length rejected before reading or allocating body");
        }
        for(final int cut:new int[]{0,1,3,15}){
            TCP tcp=new TCP(new Script(){public Reply[] reply(byte[] q,int n)throws Exception{
                if(cut==0)return new Reply[0];
                byte[] b=response(q,a(ptr(12),1)),frame=new byte[b.length+2];put(frame,0,b.length);System.arraycopy(b,0,frame,2,b.length);
                return new Reply[]{new Reply(Arrays.copyOf(frame,cut),true)};
            }});tcp.eofWhenEmpty=true;fails(tcp);
        }
        TCP tcp=new TCP(valid());tcp.zeroRead=true;fails(tcp);
        tcp=new TCP(valid());tcp.failInput=true;fails(tcp);
        tcp=new TCP(valid());tcp.failOutput=true;fails(tcp);
        final TCP cname=install(new Script(){public Reply[] reply(byte[] q,int n)throws Exception{
            check(n<=2,"one additional CNAME query");
            if(n==2)return new Reply[0];
            return new Reply[]{new Reply(response(q,rr(ptr(12),5,name("edge.example.org"))))};
        }});cname.eofWhenEmpty=true;fails(cname);check(cname.sends==2,"EOF on reused CNAME socket is bounded");
        Connector.factory=new Connector.Factory(){public Connection open(String a,int b,boolean c){throw new SecurityException("socket permission denied");}};
        DnsResolver denied=new DnsResolver();
        try{denied.lookup("bridge.example.org","1.1.1.1");throw new AssertionError("permission ignored");}
        catch(IOException expected){check(expected.getMessage().indexOf("TCP permission denied")>=0,"permission diagnosis identifies TCP");}
        Field timer=DnsResolver.class.getDeclaredField("timer");timer.setAccessible(true);check(timer.get(denied)==null,"permission denial releases timer");
    }

    static void literals()throws Exception {
        for(String good:new String[]{"1.1.1.1","0.0.0.0","255.255.255.255","192.168.1.10"})check(DnsResolver.isIPv4(good),good);
        for(String bad:new String[]{"","1.1.1","1.1.1.1.","01.1.1.1","256.1.1.1","1.-1.1.1","example.org","1.1.1.1:53","::1"})check(!DnsResolver.isIPv4(bad),bad);
        check(!DnsResolver.isIPv4(null),"null literal");
        check(DnsResolver.ipv4(0xc0a80101).equals("192.168.1.1"),"unsigned IPv4 conversion");
        Connector.factory=new Connector.Factory(){public Connection open(String a,int b,boolean c){throw new AssertionError("literal or invalid input used network");}};
        check(new DnsResolver().lookup("192.168.1.1","1.1.1.1")[0]==0xc0a80101,"literal uses no socket");
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
        got=resolve("bridge.example.org",new Script(){public Reply[] reply(byte[] q,int n)throws Exception{
            byte[] valid=response(q,a(ptr(12),3)),wrongId=(byte[])valid.clone(),wrongQuestion=(byte[])valid.clone();wrongId[0]^=1;wrongQuestion[13]='x';
            return new Reply[]{new Reply(wrongId),new Reply(wrongQuestion),new Reply(valid)};
        }});
        check(got[0]==0x0a141e03,"foreign id/question ignored");
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
        final TCP flood=install(new Script(){public Reply[] reply(byte[] q,int n)throws Exception{Reply[] r=new Reply[16];for(int i=0;i<r.length;i++){byte[] b=response(q,a(ptr(12),1));b[0]^=1;r[i]=new Reply(b);}return r;}});
        DnsResolver r=new DnsResolver();try{r.lookup("bridge.example.org","1.1.1.1");throw new AssertionError("foreign flood accepted");}catch(IOException expected){}closed(r,flood);check(flood.frames==16,"receive flood bounded");
    }
    static final class Lookup extends Thread {
        final DnsResolver resolver; Throwable failure;
        Lookup(DnsResolver r){resolver=r;}
        public void run(){try{resolver.lookup("bridge.example.org","1.1.1.1");failure=new AssertionError("cancelled lookup succeeded");}catch(IOException expected){failure=expected;}catch(Throwable t){failure=t;}}
    }
    static void cancellation()throws Exception {
        Script blocked=new Script(){public Reply[] reply(byte[] q,int n){return new Reply[0];}};
        TCP udp=install(blocked);DnsResolver r=new DnsResolver();Lookup task=new Lookup(r);task.start();check(udp.waiting.await(2,TimeUnit.SECONDS),"receive entered");
        try{r.lookup("bridge.example.org","1.1.1.1");throw new AssertionError("resolver reused");}catch(IOException expected){}
        check(!udp.closed,"second lookup must not close first");r.cancel();task.join(2000);check(!task.isAlive()&&task.failure instanceof IOException,"cancel unblocks TCP input");closed(r,udp);
        final TCP late=new TCP(valid());final CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        Connector.factory=new Connector.Factory(){public Connection open(String url,int mode,boolean timeout)throws IOException{entered.countDown();try{release.await();}catch(InterruptedException e){throw new IOException();}return late;}};
        r=new DnsResolver();task=new Lookup(r);task.start();check(entered.await(2,TimeUnit.SECONDS),"native open entered");r.cancel();release.countDown();task.join(2000);check(!task.isAlive()&&task.failure instanceof IOException,"late open cancelled");closed(r,late);check(late.sends==0,"late socket never used");
        for(int stage=0;stage<2;stage++)for(int expiry=0;expiry<2;expiry++){
            TCP stream=new TCP(valid());CountDownLatch streamEntered=new CountDownLatch(1),streamRelease=new CountDownLatch(1);
            if(stage==0){stream.inputEntered=streamEntered;stream.inputRelease=streamRelease;}
            else{stream.outputEntered=streamEntered;stream.outputRelease=streamRelease;}
            install(stream);r=new DnsResolver();task=new Lookup(r);task.start();check(streamEntered.await(2,TimeUnit.SECONDS),"native stream open entered");
            if(expiry==0)r.cancel();else{Method expire=DnsResolver.class.getDeclaredMethod("expire");expire.setAccessible(true);expire.invoke(r);}
            streamRelease.countDown();task.join(2000);
            check(!task.isAlive()&&task.failure instanceof IOException,"late stream closed after cancel or expiry");
            check(task.failure.getMessage().indexOf(expiry==0?"cancelled":"timed out")>=0,"late stream failure preserves deadline reason");
            closed(r,stream);check(stream.sends==0,"late stream never used");
        }
        r=new DnsResolver();r.cancel();try{r.lookup("bridge.example.org","1.1.1.1");throw new AssertionError("pre-cancel ignored");}catch(IOException expected){}
        udp=install(blocked);r=new DnsResolver();long start=System.currentTimeMillis();try{r.lookup("bridge.example.org","1.1.1.1");throw new AssertionError("deadline ignored");}catch(IOException expected){check(expected.getMessage().indexOf("timed out")>=0,"timeout reported clearly");}
        long elapsed=System.currentTimeMillis()-start;check(elapsed>=11000&&elapsed<16000,"overall 12-second deadline");closed(r,udp);
    }
    public static void main(String[] args)throws Exception {
        literals();packets();rejection();framing();cancellation();
        check(udpCalls==0,"UDP blocked by V8 permissions is never attempted");
        System.out.println("PASS: bounded CLDC DNS parser/TCP lifecycle ("+checks+" checks)");
    }
}
