"""Production J2ME DNS resolver against a real local DNS-over-TCP fixture.

The MIDP adapter forbids UDP like the affected V8 and only maps the test
resolver's numeric port 53 to a local ephemeral TCP port. Requires localhost
socket permission. Usage: python tests/test_client_dns_wire.py BUILD_WORK
"""
from pathlib import Path
import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
CONNECTOR = '''package javax.microedition.io;
import java.io.*;
public final class Connector {
 public static final int READ_WRITE=3;
 public static int port,udpCalls,sockets,closed,inputsClosed,outputsClosed;
 public static Connection open(String url,int mode,boolean timeouts)throws IOException {
  if(url.startsWith("datagram:")){udpCalls++;throw new SecurityException("Permission denied");}
  if(!url.equals("socket://127.0.0.1:53") || mode!=READ_WRITE)
   throw new AssertionError("Unexpected native DNS lookup or URL: "+url);
  sockets++;return new Socket();
 }
 private static final class Socket implements StreamConnection {
  final java.net.Socket value=new java.net.Socket("127.0.0.1",port);
  Socket()throws IOException{}
  public InputStream openInputStream()throws IOException {
   return new FilterInputStream(value.getInputStream()){
    public void close()throws IOException {inputsClosed++;super.close();}
   };
  }
  public OutputStream openOutputStream()throws IOException {
   return new FilterOutputStream(value.getOutputStream()){
    public void close()throws IOException {outputsClosed++;super.close();}
   };
  }
  public DataInputStream openDataInputStream()throws IOException{return new DataInputStream(openInputStream());}
  public DataOutputStream openDataOutputStream()throws IOException{return new DataOutputStream(openOutputStream());}
  public void close()throws IOException{closed++;value.close();}
 }
}'''


def exact(sock, size):
    result = bytearray()
    while len(result) < size:
        part = sock.recv(size - len(result))
        if not part:
            raise AssertionError('client closed before completing DNS query')
        result.extend(part)
    return bytes(result)


def question(sock, expected):
    size = struct.unpack('!H', exact(sock, 2))[0]
    assert 17 <= size <= 271
    query = exact(sock, size)
    ident, flags, qd, an, ns, ar = struct.unpack('!6H', query[:12])
    assert (flags, qd, an, ns, ar) == (0x0100, 1, 0, 0, 0)
    at, labels = 12, []
    while query[at]:
        length = query[at]
        labels.append(query[at+1:at+1+length].decode('ascii'))
        at += length + 1
    assert '.'.join(labels) == expected
    assert query[at:] == b'\x00\x00\x01\x00\x01'
    return ident, query[12:]


def frame(sock, ident, q, records, fragmented=False):
    payload = struct.pack('!6H', ident, 0x8180, 1, len(records), 0, 0) + q + b''.join(records)
    message = struct.pack('!H', len(payload)) + payload
    # Split the message over writes independent of the resolver's reads.
    # TCP may coalesce some writes; deterministic partial reads have separate tests.
    if fragmented:
        for offset in range(0, len(message), 3):
            sock.sendall(message[offset:offset+3])
    else:
        sock.sendall(message)


def serve(listener, mode, errors):
    try:
        with listener.accept()[0] as peer:
            peer.settimeout(8)
            ident, q = question(peer, 'bridge.example.org')
            if mode == 'cname':
                alias = b'\x04edge\x07example\x03org\x00'
                record = b'\xc0\x0c' + struct.pack('!HHIH', 5, 1, 60, len(alias)) + alias
                frame(peer, ident, q, [record])
                ident, q = question(peer, 'edge.example.org')
            if mode == 'eof':
                peer.sendall(b'\x00\x30\x01')
                return
            if mode == 'oversize':
                peer.sendall(struct.pack('!H', 2049))
            else:
                count = 40 if mode == 'large' else 2
                records = [b'\xc0\x0c' + struct.pack('!HHIH', 1, 1, 60, 4)
                           + bytes([127, 0, 0, i+2]) for i in range(count)]
                frame(peer, ident, q, records, fragmented=True)
            assert peer.recv(1) == b'', 'client kept DNS connection alive after lookup'
    except BaseException as error:
        errors.append(error)


def run(work):
    cp = os.pathsep.join(map(str, [work/'src/build/compile/classes',
                                  *sorted((work/'wtk/lib').glob('*.jar'))]))
    with tempfile.TemporaryDirectory(prefix='tmm-dns-wire-') as folder:
        folder = Path(folder)
        adapter = folder/'javax/microedition/io/Connector.java'
        adapter.parent.mkdir(parents=True)
        adapter.write_text(CONNECTOR)
        subprocess.run([str(work/'jdk/bin/javac'), '-cp', cp, '-d', str(folder),
                        str(adapter), str(ROOT/'tests/java/DnsWireTest.java')], check=True)
        for mode in ('fragmented', 'cname', 'large', 'eof', 'oversize'):
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0)); listener.listen(1); listener.settimeout(8)
                errors = []
                server = threading.Thread(target=serve, args=(listener, mode, errors))
                server.start()
                try:
                    subprocess.run([str(work/'jdk/bin/java'), '-cp', str(folder)+os.pathsep+cp,
                                    'DnsWireTest', mode, str(listener.getsockname()[1])],
                                   check=True, timeout=18)
                finally:
                    server.join(10)
                assert not server.is_alive(), 'DNS fixture hung'
                if errors:
                    raise errors[0]


if __name__ == '__main__':
    run(Path(sys.argv[1]).resolve())
