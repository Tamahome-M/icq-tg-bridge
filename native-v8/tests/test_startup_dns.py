"""Startup-only DNS uses the real threaded client and loopback DNS/OSCAR servers."""
import asyncio
import os
from pathlib import Path
import struct
import tempfile

from test_network import Phone, compile_driver, Config, Storage, OscarServer, C


async def scenario(executable, folder, behavior):
    cfg = Config()
    cfg.oscar_host = cfg.bos_host = '127.0.0.1'
    cfg.oscar_port = 0
    cfg.oscar_uin = '12345'
    cfg.oscar_password = 'test'
    store = Storage(':memory:')
    store.uin_for_peer(300, kind='user', title='DNS test', group_name='Telegram')

    async def outgoing(*args):
        return 1

    server = OscarServer(cfg, store, outgoing, store.contacts, lambda uin: C.STATUS_ONLINE)
    auth_connections = []
    original_accept = server._accept

    async def accept(reader, writer):
        auth_connections.append(True)
        await original_accept(reader, writer)

    server._accept = accept
    await server.start()
    port = server._server.sockets[0].getsockname()[1]
    cfg.oscar_port = cfg.bos_port = port
    received = asyncio.Event()
    release = asyncio.Event()
    queries, writers, tasks = [], [], set()

    async def dns(reader, writer):
        task = asyncio.current_task()
        tasks.add(task)
        writers.append(writer)
        try:
            n = struct.unpack('!H', await reader.readexactly(2))[0]
            query = await reader.readexactly(n)
            queries.append(query)
            received.set()
            await release.wait()
            if behavior == 'invalid':
                reply = query[:2] + b'\x81\x83' + query[4:]
            else:
                reply = (query[:2] + b'\x81\x80' + b'\0\1\0\1' + b'\0' * 4 + query[12:]
                         + b'\xc0\x0c' + struct.pack('!HHIH', 1, 1, 60, 4) + b'\x7f\0\0\1')
            writer.write(struct.pack('!H', len(reply)) + reply)
            await writer.drain()
            await reader.read()
        except (asyncio.IncompleteReadError, ConnectionError, asyncio.CancelledError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()
            tasks.discard(task)

    listener = await asyncio.start_server(dns, '127.0.0.1', 0)
    env = dict(os.environ, TMM_TEST_PREFETCH='1',
               TMM_TEST_DNS_PORT=str(listener.sockets[0].getsockname()[1]))
    if behavior == 'apn-failure':
        env['TMM_TEST_NETWORK_FAILURE'] = '1'
    process = await asyncio.create_subprocess_exec(
        str(executable), str(port), '0', '1', str(folder), env=env,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)
    phone = Phone(process)

    async def line(text):
        process.stdin.write((text + '\n').encode())
        await process.stdin.drain()

    async def disconnected(generation):
        return await phone.wait(lambda e: e.get('type') == 0 and e.get('state') == 0
                                and e.get('generation') == generation)

    async def online(generation):
        return await phone.wait(lambda e: e.get('type') == 0 and e.get('state') == 2
                                and e.get('generation') == generation)

    try:
        if behavior == 'apn-failure':
            failure = await phone.wait(lambda e: e.get('type') == 12)
            assert failure['error'] == 195 and 'DNS' in failure['text'], failure
            await disconnected(1)
            assert not queries and not auth_connections
            await line('system-network')
            await phone.wait(lambda e: e.get('configured'))
            await line('start')
            failed = await phone.wait(lambda e: e.get('type') == 12 and e.get('generation') == 2)
            assert 'DNS' in failed['text'], failed
            await disconnected(2)
            assert not queries and not auth_connections
            return
        await asyncio.wait_for(received.wait(), 3)
        assert not auth_connections, 'prefetch connected to OSCAR before start()'
        if behavior == 'cancel':
            await line('stop')
            await disconnected(1)
            await line('start')
            failure = await phone.wait(lambda e: e.get('type') == 12)
            assert 'DNS' in failure['text'], failure
            await disconnected(2)
            assert len(queries) == 1 and not auth_connections
        else:
            if behavior == 'concurrent':
                await line('start')
                await asyncio.sleep(.05)
                assert not auth_connections, 'start bypassed incomplete prefetch'
            release.set()
            if behavior == 'invalid':
                failure = await phone.wait(lambda e: e.get('type') == 12)
                assert failure['error'] == 195 and 'DNS' in failure['text'], failure
                await disconnected(1)
                assert not auth_connections
                await line('start')
                await phone.wait(lambda e: e.get('type') == 12 and e.get('generation') == 2)
                await disconnected(2)
                assert len(queries) == 1 and not auth_connections
            else:
                if behavior == 'complete':
                    result = await disconnected(1)
                    assert 'DNS' in result['text'], result
                    assert not auth_connections
                    await line('disable-dns')
                    await phone.wait(lambda e: e.get('configured'))
                    await line('start')
                await online(2)
                assert len(queries) == 1
                await line('stop')
                await disconnected(2)
                await line('start')
                await online(3)
                assert len(queries) == 1, 'reconnect repeated startup DNS'
                await line('stop')
                await disconnected(3)
                previous = len(auth_connections)
                await line('change-host')
                await phone.wait(lambda e: e.get('configured'))
                await line('start')
                failed = await phone.wait(lambda e: e.get('type') == 12
                                          and e.get('generation') == 4)
                assert 'перезапустите' in failed['text'], failed
                assert len(queries) == 1 and len(auth_connections) == previous
    finally:
        if process.returncode is None:
            await line('quit')
            try:
                await asyncio.wait_for(process.wait(), 3)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise
        listener.close()
        release.set()
        for task in list(tasks):
            task.cancel()
        for writer in writers:
            writer.close()
        await asyncio.gather(*tasks, return_exceptions=True)
        await listener.wait_closed()
        await server.stop()
        store.close()


async def main():
    with tempfile.TemporaryDirectory(prefix='tmm-native-prefetch-') as directory:
        folder = Path(directory)
        binary = folder / 'network-test'
        compile_driver(binary)
        for behavior in ('complete', 'concurrent', 'cancel', 'invalid', 'apn-failure'):
            await scenario(binary, folder, behavior)
    print('PASS startup DNS: no login, concurrent start, one lookup across reconnect, '
          'launch settings latch, cancellation and cached errors')


if __name__ == '__main__':
    asyncio.run(main())
