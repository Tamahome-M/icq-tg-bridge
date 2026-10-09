package jimm.comm.connections;

/** Small CLDC-only SHA-256/HMAC/HKDF and ChaCha20 implementation.
 * SHA-256: FIPS 180-4; HKDF: RFC 5869; ChaCha20: RFC 8439.
 * No JCE, BigInteger, native SSL or per-message packet-sized copies.
 */
public final class SecureCrypto {
    private SecureCrypto() {}
    public static byte[] ascii(String text) {
        byte[] out=new byte[text.length()];
        for(int i=0;i<out.length;i++)out[i]=(byte)text.charAt(i);
        return out;
    }
    public static byte[] slice(byte[] data,int start,int length) {
        byte[] out=new byte[length];System.arraycopy(data,start,out,0,length);return out;
    }
    public static boolean equal(byte[] a,int off,byte[] b,int length) {
        if(off<0 || off+length>a.length || length>b.length)return false;
        int diff=0;for(int i=0;i<length;i++)diff|=a[off+i]^b[i];return diff==0;
    }
    public static void putLong(byte[] out,int off,long value) {
        for(int i=7;i>=0;i--){out[off+i]=(byte)value;value>>>=8;}
    }
    public static byte[] hmac(byte[] key,byte[] a,byte[] b,byte[] c) {
        return hmac(key,a,b,b==null?0:b.length,c);
    }
    public static byte[] recordMac(byte[] key,byte[] header,byte[] data,int length) {
        return hmac(key,header,data,length,null);
    }
    private static byte[] hmac(byte[] key,byte[] a,byte[] b,int length,byte[] c) {
        byte[] pad=new byte[64];
        byte[] actual=key.length>64?sha256(key):key;
        for(int i=0;i<64;i++)pad[i]=(byte)((i<actual.length?actual[i]:0)^0x36);
        Sha256 inner=new Sha256();inner.update(pad,0,64);
        if(a!=null)inner.update(a,0,a.length);
        if(b!=null)inner.update(b,0,length);
        if(c!=null)inner.update(c,0,c.length);
        byte[] hashed=inner.finish();
        for(int i=0;i<64;i++)pad[i]^=0x36^0x5c;
        Sha256 outer=new Sha256();outer.update(pad,0,64);outer.update(hashed,0,32);
        return outer.finish();
    }
    public static byte[] sha256(byte[] data) {
        Sha256 digest=new Sha256();digest.update(data,0,data.length);return digest.finish();
    }
    public static byte[] keys(byte[] psk,byte[] request,byte[] response) {
        byte[] salt=new byte[48];
        System.arraycopy(request,6,salt,0,16);System.arraycopy(response,6,salt,16,32);
        byte[] prk=hmac(salt,psk,null,null), previous=null, out=new byte[128];
        byte[] info=ascii("TeleMotoMax secure v1");
        for(int i=1;i<=4;i++){
            previous=hmac(prk,previous,info,new byte[]{(byte)i});
            System.arraycopy(previous,0,out,(i-1)*32,32);
        }
        return out;
    }
    private static int rotate(int x,int n){return (x<<n)|(x>>>(32-n));}
    private static int little(byte[] b,int i){return (b[i]&255)|((b[i+1]&255)<<8)|((b[i+2]&255)<<16)|((b[i+3]&255)<<24);}
    private static void quarter(int[] x,int a,int b,int c,int d) {
        x[a]+=x[b];x[d]=rotate(x[d]^x[a],16);x[c]+=x[d];x[b]=rotate(x[b]^x[c],12);
        x[a]+=x[b];x[d]=rotate(x[d]^x[a],8);x[c]+=x[d];x[b]=rotate(x[b]^x[c],7);
    }
    public static final class ChaCha {
        private final int[] state=new int[16], work=new int[16];
        private final byte[] block=new byte[64];
        public void crypt(byte[] key,byte[] nonce,int counter,byte[] data,int length) {
            state[0]=0x61707865;state[1]=0x3320646e;state[2]=0x79622d32;state[3]=0x6b206574;
            for(int i=0;i<8;i++)state[4+i]=little(key,i*4);
            state[12]=counter;state[13]=little(nonce,0);state[14]=little(nonce,4);state[15]=little(nonce,8);
            for(int pos=0;pos<length;pos+=64){
                System.arraycopy(state,0,work,0,16);
                for(int i=0;i<10;i++){
                    quarter(work,0,4,8,12);quarter(work,1,5,9,13);quarter(work,2,6,10,14);quarter(work,3,7,11,15);
                    quarter(work,0,5,10,15);quarter(work,1,6,11,12);quarter(work,2,7,8,13);quarter(work,3,4,9,14);
                }
                for(int i=0;i<16;i++){
                    int value=work[i]+state[i];
                    for(int j=0;j<4;j++){block[i*4+j]=(byte)value;value>>>=8;}
                }
                int n=Math.min(64,length-pos);
                for(int i=0;i<n;i++)data[pos+i]^=block[i];
                state[12]++;
            }
        }
    }
    private static final class Sha256 {
        private static final int[] K={
            0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
            0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
            0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
            0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
            0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
            0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
            0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
            0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
        private final int[] h={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
        private final int[] w=new int[16];
        private final byte[] buffer=new byte[64];
        private long count;private int used;
        private static int right(int v,int n){return (v>>>n)|(v<<(32-n));}
        void update(byte[] data,int off,int length) {
            count+=length;
            while(length>0){
                int n=Math.min(length,64-used);System.arraycopy(data,off,buffer,used,n);
                used+=n;off+=n;length-=n;if(used==64){compress();used=0;}
            }
        }
        private void compress() {
            for(int i=0;i<16;i++){int p=i*4;w[i]=((buffer[p]&255)<<24)|((buffer[p+1]&255)<<16)|((buffer[p+2]&255)<<8)|(buffer[p+3]&255);}
            int a=h[0],b=h[1],c=h[2],d=h[3],e=h[4],f=h[5],g=h[6],v=h[7];
            for(int i=0;i<64;i++){
                // Only the previous 16 schedule words are needed. Reuse their
                // slots instead of allocating another 192 bytes per digest.
                if(i>=16){
                    int x=w[(i-15)&15],y=w[(i-2)&15];
                    w[i&15]+=(right(x,7)^right(x,18)^(x>>>3))+w[(i-7)&15]+(right(y,17)^right(y,19)^(y>>>10));
                }
                int t1=v+(right(e,6)^right(e,11)^right(e,25))+((e&f)^(~e&g))+K[i]+w[i&15];
                int t2=(right(a,2)^right(a,13)^right(a,22))+((a&b)^(a&c)^(b&c));
                v=g;g=f;f=e;e=d+t1;d=c;c=b;b=a;a=t1+t2;
            }
            h[0]+=a;h[1]+=b;h[2]+=c;h[3]+=d;h[4]+=e;h[5]+=f;h[6]+=g;h[7]+=v;
        }
        byte[] finish() {
            long bits=count*8;buffer[used++]=(byte)0x80;
            if(used>56){while(used<64)buffer[used++]=0;compress();used=0;}
            while(used<56)buffer[used++]=0;putLong(buffer,56,bits);compress();
            byte[] out=new byte[32];
            for(int i=0;i<8;i++)for(int j=0;j<4;j++)out[i*4+j]=(byte)(h[i]>>>(24-j*8));
            return out;
        }
    }
}
