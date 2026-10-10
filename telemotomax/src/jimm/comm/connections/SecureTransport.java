package jimm.comm.connections;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import javax.microedition.rms.RecordStore;

/** TMME/1: explicitly requested by the client, before OSCAR login.
 * Cleartext clients receive exactly the old server hello. Secure clients
 * consume it, negotiate keys, then receive a new hello inside this stream.
 */
public final class SecureTransport {
    public static final int CHANNEL=0x7e, MAX_RECORD=1024;
    private static final byte[] MAGIC={'T','M','M','E',1};
    public final InputStream input;
    public final OutputStream output;
    public static final class Failure extends IOException {
        public final int code;
        public Failure(int value){super("TMME transport error");code=value;}
    }
    private SecureTransport(InputStream in,OutputStream out,byte[] keys) {
        input=new RecordInput(in,SecureCrypto.slice(keys,64,32),SecureCrypto.slice(keys,96,32));
        output=new RecordOutput(out,SecureCrypto.slice(keys,0,32),SecureCrypto.slice(keys,32,32));
    }
    public static byte[] parseKey(String text) throws Failure {
        if(text==null)throw new Failure(180);
        text=text.trim();
        if(text.length()<1 || text.length()>64)throw new Failure(180);
        if(text.length()==64){
            byte[] key=new byte[32];boolean legacy=true;
            for(int i=0;i<32;i++){
                int hi=hex(text.charAt(i*2)),lo=hex(text.charAt(i*2+1));
                if(hi<0 || lo<0){legacy=false;break;}key[i]=(byte)((hi<<4)|lo);
            }
            if(legacy)return key;
        }
        // Reject malformed UTF-16 rather than silently replacing characters.
        for(int i=0;i<text.length();i++){
            char ch=text.charAt(i);
            if(ch>=0xd800 && ch<=0xdbff){
                if(++i>=text.length() || text.charAt(i)<0xdc00 || text.charAt(i)>0xdfff)throw new Failure(180);
            }else if(ch>=0xdc00 && ch<=0xdfff)throw new Failure(180);
        }
        // Fast phrase mapping for the phone; it does not add password entropy.
        try{return SecureCrypto.sha256(("TeleMotoMax PSK v1\u0000"+text).getBytes("UTF-8"));}
        catch(java.io.UnsupportedEncodingException e){throw new Failure(180);}
    }
    private static int hex(char ch) {
        if(ch>='0' && ch<='9')return ch-'0';
        if(ch>='a' && ch<='f')return ch-'a'+10;
        if(ch>='A' && ch<='F')return ch-'A'+10;return -1;
    }
    /** Uniqueness, not entropy: secret keys depend on PSK and OS randomness
     * from the authenticated server. Persist before any network write.
     */
    public static synchronized byte[] nextNonce() throws Failure {
        RecordStore store=null;
        try {
            store=RecordStore.openRecordStore("tmm_secure_counter",true);
            long counter=0;
            if(store.getNumRecords()>0){
                byte[] old=store.getRecord(1);if(old.length!=8)throw new Failure(180);
                for(int i=0;i<8;i++)counter=(counter<<8)|(old[i]&255);
            }
            if(counter<0 || counter==Long.MAX_VALUE)throw new Failure(180);
            byte[] saved=new byte[8];SecureCrypto.putLong(saved,0,++counter);
            if(store.getNumRecords()==0)store.addRecord(saved,0,8);else store.setRecord(1,saved,0,8);
            byte[] nonce=new byte[16];System.arraycopy(saved,0,nonce,0,8);
            SecureCrypto.putLong(nonce,8,System.currentTimeMillis());return nonce;
        }catch(Failure e){throw e;}catch(Exception e){throw new Failure(180);}
        finally{if(store!=null)try{store.closeRecordStore();}catch(Exception ignored){}}
    }
    public static SecureTransport open(InputStream in,OutputStream out,String keyText) throws IOException {
        byte[] key=parseKey(keyText);
        byte[] hello=readFlap(in,1);
        if(hello.length!=4 || hello[0]!=0 || hello[1]!=0 || hello[2]!=0 || hello[3]!=1)throw new Failure(183);
        byte[] request=new byte[38];System.arraycopy(MAGIC,0,request,0,5);request[5]=1;
        System.arraycopy(nextNonce(),0,request,6,16);
        byte[] proof=SecureCrypto.hmac(key,SecureCrypto.ascii("client hello"),SecureCrypto.slice(request,0,22),null);
        System.arraycopy(proof,0,request,22,16);sendFlap(out,request,1);
        byte[] response=readFlap(in,CHANNEL);
        if(response.length==7 && SecureCrypto.equal(response,0,MAGIC,5) && response[5]==(byte)255)
            throw new Failure(response[6]==1?181:182);
        if(response.length!=54 || !SecureCrypto.equal(response,0,MAGIC,5) || response[5]!=2)throw new Failure(183);
        proof=SecureCrypto.hmac(key,SecureCrypto.ascii("server hello"),request,SecureCrypto.slice(response,0,38));
        if(!SecureCrypto.equal(response,38,proof,16))throw new Failure(182);
        byte[] finish=new byte[22];System.arraycopy(MAGIC,0,finish,0,5);finish[5]=3;
        proof=SecureCrypto.hmac(key,SecureCrypto.ascii("client finish"),request,response);
        System.arraycopy(proof,0,finish,6,16);sendFlap(out,finish,2);
        return new SecureTransport(in,out,SecureCrypto.keys(key,request,response));
    }
    private static byte[] readFlap(InputStream in,int channel) throws IOException {
        byte[] header=new byte[6];fully(in,header,0,6);
        int size=((header[4]&255)<<8)|(header[5]&255);
        if(header[0]!=42 || (header[1]&255)!=channel || size>64)throw new Failure(183);
        byte[] data=new byte[size];fully(in,data,0,size);return data;
    }
    private static void sendFlap(OutputStream out,byte[] data,int sequence) throws IOException {
        byte[] header={42,(byte)CHANNEL,0,(byte)sequence,0,(byte)data.length};
        out.write(header);out.write(data);out.flush();
    }
    private static void fully(InputStream in,byte[] data,int off,int length) throws IOException {
        while(length>0){int n=in.read(data,off,length);if(n<0)throw new IOException("TMME truncated stream");
            if(n==0){int b=in.read();if(b<0)throw new IOException("TMME truncated stream");data[off++]=(byte)b;length--;}
            else{off+=n;length-=n;}}
    }
    private static final class State {
        private final byte[] key,header=new byte[10],nonce=new byte[12],macTag=new byte[16];
        private final SecureCrypto.RecordMac mac;
        private final SecureCrypto.ChaCha cipher=new SecureCrypto.ChaCha();
        private long sequence;
        State(byte[] k,byte[] a){key=k;mac=new SecureCrypto.RecordMac(a);}
        void prepare(int size) throws Failure {
            if(size<1 || size>MAX_RECORD || sequence==Long.MAX_VALUE)throw new Failure(184);
            SecureCrypto.putLong(header,0,sequence);header[8]=(byte)(size>>>8);header[9]=(byte)size;
            SecureCrypto.putLong(nonce,4,sequence);
        }
        byte[] tag(byte[] data,int length){mac.calculate(header,data,length,macTag);return macTag;}
        void crypt(byte[] data,int length){cipher.crypt(key,nonce,0,data,length);sequence++;}
    }
    private static final class RecordInput extends InputStream {
        private final InputStream raw;
        private final State state;
        private final byte[] buffer=new byte[MAX_RECORD],tag=new byte[16];
        private int pos,limit;
        RecordInput(InputStream in,byte[] key,byte[] auth){raw=in;state=new State(key,auth);}
        private boolean refill() throws IOException {
            int hi=raw.read();if(hi<0)return false;int lo=raw.read();if(lo<0)throw new Failure(184);
            int size=(hi<<8)|lo;state.prepare(size);
            fully(raw,buffer,0,size);fully(raw,tag,0,16);
            if(!SecureCrypto.equal(tag,0,state.tag(buffer,size),16))throw new Failure(184);
            state.crypt(buffer,size);pos=0;limit=size;return true;
        }
        public int read() throws IOException {if(pos==limit && !refill())return -1;return buffer[pos++]&255;}
        public int read(byte[] data,int off,int length) throws IOException {
            if(length==0)return 0;if(pos==limit && !refill())return -1;
            int n=Math.min(length,limit-pos);System.arraycopy(buffer,pos,data,off,n);pos+=n;return n;
        }
        public int available() throws IOException {return pos<limit?limit-pos:(raw.available()>0?1:0);}
        public void close() throws IOException {raw.close();}
    }
    private static final class RecordOutput extends OutputStream {
        private final OutputStream raw;
        private final State state;
        private final byte[] buffer=new byte[MAX_RECORD],single=new byte[1];
        RecordOutput(OutputStream out,byte[] key,byte[] auth){raw=out;state=new State(key,auth);}
        public void write(int value) throws IOException {single[0]=(byte)value;write(single,0,1);}
        public void write(byte[] data,int off,int length) throws IOException {
            while(length>0){
                int n=Math.min(length,MAX_RECORD);System.arraycopy(data,off,buffer,0,n);state.prepare(n);
                state.crypt(buffer,n);byte[] tag=state.tag(buffer,n);
                raw.write(state.header,8,2);raw.write(buffer,0,n);raw.write(tag,0,16);off+=n;length-=n;
            }
        }
        public void flush() throws IOException {raw.flush();}
        public void close() throws IOException {raw.close();}
    }
}
