"""Real native UDP/TCP DNS and cancellation, with loopback wire fixtures."""
import asyncio
import os
import shlex
from pathlib import Path
import struct
import subprocess
import tempfile
import time
ROOT=Path(__file__).resolve().parents[2]


def name(value): return b''.join(bytes([len(x)])+x.encode() for x in value.split('.'))+b'\0'
def rr(owner,kind,data): return owner+struct.pack('!HHIH',kind,1,60,len(data))+data
def answer(q,*records): return q[:2]+b'\x81\x80'+b'\0\1'+struct.pack('!H',len(records))+b'\0'*4+q[12:]+b''.join(records)
def a(n): return rr(b'\xc0\x0c',1,bytes([10,20,30,n]))


class UDP(asyncio.DatagramProtocol):
    def __init__(self,case): self.case=case;self.count=0
    def connection_made(self,transport): self.transport=transport
    def datagram_received(self,q,peer):
        self.count+=1
        for reply in self.case(q,self.count,False): self.transport.sendto(reply,peer)


async def run_case(binary, case, tcp=True, expected=None, error=False, cancel=0):
    tcp_count=0
    tasks=set()
    async def connected(reader,writer):
        nonlocal tcp_count
        task=asyncio.current_task();tasks.add(task)
        try:
            while True:
                size=struct.unpack('!H',await reader.readexactly(2))[0]
                q=await reader.readexactly(size);tcp_count+=1
                for reply in case(q,tcp_count,True):
                    frame=reply if isinstance(reply,bytearray) else struct.pack('!H',len(reply))+reply
                    # Deliberately split the two length bytes and the payload.
                    for part in (frame[:1],frame[1:2],frame[2:9],frame[9:]):
                        writer.write(part);await writer.drain();await asyncio.sleep(.001)
        except (asyncio.IncompleteReadError,ConnectionError,asyncio.CancelledError): pass
        finally: writer.close();await writer.wait_closed();tasks.discard(task)
    server=await asyncio.start_server(connected,'127.0.0.1',0)
    port=server.sockets[0].getsockname()[1]
    loop=asyncio.get_running_loop();transport,udp=await loop.create_datagram_endpoint(lambda:UDP(case),local_addr=('127.0.0.1',port))
    start=time.monotonic()
    process=await asyncio.create_subprocess_exec(*binary,str(port),str(int(tcp)),'bridge.example.org',str(cancel),stdout=asyncio.subprocess.PIPE)
    try:
        raw,_=await asyncio.wait_for(process.communicate(),15)
        lines=raw.decode().splitlines()
        if error: assert process.returncode==3 and lines[0].startswith('ERR '),lines
        else: assert process.returncode==0 and lines==expected,(process.returncode,lines)
        if cancel: assert time.monotonic()-start<2, 'cancellation was not prompt'
        return tcp_count,udp.count
    finally:
        if process.returncode is None:process.kill();await process.wait()
        server.close();await server.wait_closed();transport.close()
        for task in list(tasks):task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)


async def main():
    with tempfile.TemporaryDirectory(prefix='tmm-native-dns-') as folder:
        binary=Path(folder)/'dns-test'
        if os.environ.get('TMM_DNS_DRIVER'): command=shlex.split(os.environ['TMM_DNS_DRIVER'])
        else:
            subprocess.run(['g++','-std=c++98','-Wall','-Wextra','-fno-rtti','-pthread','-I',str(ROOT/'native-v8/src'),str(ROOT/'native-v8/tests/dns_driver.cpp'),*[str(ROOT/'native-v8/src'/s) for s in ['dns.cpp','transport.cpp','oscar.cpp','crypto.cpp']],'-Wl,--wrap=connect','-lrt','-lresolv','-o',str(binary)],check=True)
            command=[str(binary)]
        valid=lambda q,n,t:[answer(q,a(1),a(1),a(2),a(3),a(4),a(5))]
        assert await run_case(command,valid,True,['10.20.30.1','10.20.30.2','10.20.30.3','10.20.30.4'])==(1,0)
        assert await run_case(command,valid,False,['10.20.30.1','10.20.30.2','10.20.30.3','10.20.30.4'])==(0,1)
        assert await run_case(command,valid,2,['10.20.30.1','10.20.30.2','10.20.30.3','10.20.30.4'])==(0,1)
        def truncated(q,n,t):
            if t:return [answer(q,a(9))]
            b=answer(q);return [b[:2]+b'\x83\x80'+b[4:]]
        assert await run_case(command,truncated,False,['10.20.30.9'])==(1,1)
        def aliases(q,n,t):
            if n==1:return [answer(q,rr(b'\xc0\x0c',5,name('edge.example.org')))]
            assert q[12:]==name('edge.example.org')+b'\0\1\0\1'
            return [answer(q,a(8))]
        assert await run_case(command,aliases,True,['10.20.30.8'])==(2,0)
        def wrongid(q,n,t):
            b=answer(q,a(7));return [bytes([b[0]^1])+b[1:],b]
        await run_case(command,wrongid,True,['10.20.30.7'])
        for case in [lambda q,n,t:[answer(q,rr(name('other.example.org'),1,b'\1\2\3\4'))],
                     lambda q,n,t:[answer(q,rr(b'\xc0\x0c',5,name('bridge.example.org')))],
                     lambda q,n,t:[bytearray(b'\xff\xff')],
                     lambda q,n,t:[bytearray(b'\0\0')],
                     lambda q,n,t:[answer(q,rr(b'\xc0\x0c',1,b'\1\2\3'))]]:
            await run_case(command,case,error=True)
        if not os.environ.get('TMM_DNS_NO_THREADS'):
            for tcp in (True,False): await run_case(command,lambda q,n,t:[],tcp,error=True,cancel=100)
        else: print('SKIP threaded cancellation: target LinuxThreads unsupported by emulator')
        print('PASS native DNS: UDP system, TCP custom, TC fallback, framing, owners, CNAME, malformed')

if __name__=='__main__':asyncio.run(main())
