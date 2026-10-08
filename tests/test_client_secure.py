"""Independent crypto vectors and real compiled J2ME socket against Python OSCAR.
Usage: python tests/test_client_secure.py BUILD_WORK [COMPILED_CLASSES]
"""
from pathlib import Path
import asyncio
import hashlib
import hmac
import os
import struct
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
from bridge.oscar import secure
from tests.test_client_ui import STUBS
from tests.test_telemotomax import make_server

CONNECTOR = """
package javax.microedition.io;
import java.io.*;
public class Connector {
 public static final int READ_WRITE=3;
 public static volatile int written;
 public static Connection open(String url,int mode) throws IOException {return new Socket(url.substring(9));}
 public static final class Socket implements SocketConnection {
  final java.net.Socket value;
  Socket(String address) throws IOException {int i=address.lastIndexOf(':');value=new java.net.Socket(address.substring(0,i),Integer.parseInt(address.substring(i+1)));}
  public InputStream openInputStream() throws IOException{return value.getInputStream();}
  public OutputStream openOutputStream() throws IOException{final OutputStream raw=value.getOutputStream();return new OutputStream(){
   public void write(int n) throws IOException{raw.write(n);written++;}
   public void write(byte[] b,int o,int n) throws IOException{raw.write(b,o,n);written+=n;}
   public void flush() throws IOException{raw.flush();}public void close() throws IOException{raw.close();}};}
  public DataInputStream openDataInputStream() throws IOException{return new DataInputStream(openInputStream());}
  public DataOutputStream openDataOutputStream() throws IOException{return new DataOutputStream(openOutputStream());}
  public void close() throws IOException{value.close();}
  public void setSocketOption(byte option,int number){} public int getSocketOption(byte option){return 0;}
  public String getLocalAddress(){return value.getLocalAddress().getHostAddress();}public int getLocalPort(){return value.getLocalPort();}
  public String getAddress(){return value.getInetAddress().getHostAddress();}public int getPort(){return value.getPort();}
 }
}
"""


def fixture(path):
    key = bytes(range(32))
    def blob(out, data): out.write(struct.pack(">I", len(data))+data)
    sizes = [0, 1, 17, 55, 56, 63, 64, 65, 511, 1024]
    with path.open("wb") as out:
        blob(out, key);out.write(struct.pack(">I", len(sizes)))
        for size in sizes:
            data = bytes(i % 256 for i in range(size));auth = bytes(range(80))
            nonce = bytes(range(12));counter = 1
            encryptor = Cipher(algorithms.ChaCha20(key, struct.pack("<I", counter)+nonce), None).encryptor()
            for part in [data, hashlib.sha256(data).digest(), auth, hmac.digest(auth, data, "sha256"), nonce]: blob(out, part)
            out.write(struct.pack(">I", counter));blob(out, encryptor.update(data)+encryptor.finalize())
        request = secure.client_hello(key, bytes(range(16)));response = secure.server_hello(key, request, bytes(range(32)))
        keys = secure.session_keys(key, request, response);plain = bytes(range(256))*12+b"tail"
        records = []
        for start in (0, 64):
            cipher = secure.RecordCipher(keys[start:start+32], keys[start+32:start+64])
            records.append(b"".join(cipher.seal(plain[i:i+1024]) for i in range(0, len(plain), 1024)))
        for part in [request, response, keys, plain, *records]: blob(out, part)


async def run(work, classes):
    root = Path(__file__).resolve().parents[1]
    classpath = os.pathsep.join(str(p) for p in [classes, *sorted((work/"wtk/lib").glob("*.jar"))])
    with tempfile.TemporaryDirectory(prefix="tmm-secure-java-") as temp:
        directory = Path(temp); sources = []
        stubs = dict(STUBS);stubs["javax/microedition/io/Connector.java"] = CONNECTOR
        for name, source in stubs.items():
            path = directory/name;path.parent.mkdir(parents=True, exist_ok=True);path.write_text(source);sources.append(str(path))
        process = await asyncio.create_subprocess_exec(str(work/"jdk/bin/javac"), "-encoding", "UTF-8", "-cp", classpath, "-d", str(directory), *sources,
                                                     str(root/"tests/java/SecureTransportTest.java"))
        assert await process.wait() == 0
        fixture(directory/"vectors.bin")
        server, storage = make_server(0);server.cfg.oscar_psk = bytes(range(32)).hex()
        await server.start();port = server._server.sockets[0].getsockname()[1]
        async def stalled(reader, writer):
            try:
                from bridge.oscar.proto import flap
                writer.write(flap(1, 1, b"\0\0\0\1"));await writer.drain();await reader.read()
            finally:
                writer.close();await writer.wait_closed()
        stalled_server = await asyncio.start_server(stalled, "127.0.0.1", 0)
        stalled_port = stalled_server.sockets[0].getsockname()[1]
        try:
            process = await asyncio.create_subprocess_exec(str(work/"jdk/bin/java"), "-cp", str(directory)+os.pathsep+classpath,
                "SecureTransportTest", str(directory/"vectors.bin"), f"127.0.0.1:{port}", f"127.0.0.1:{stalled_port}")
            assert await asyncio.wait_for(process.wait(), 30) == 0
        finally:
            if process.returncode is None: process.kill();await process.wait()
            stalled_server.close();await stalled_server.wait_closed()
            await server.stop();await asyncio.sleep(.03);storage.close()


if __name__ == "__main__":
    work = Path(sys.argv[1]).resolve()
    asyncio.run(run(work, Path(sys.argv[2]).resolve() if len(sys.argv)>2 else work/"src/build/compile/classes"))
