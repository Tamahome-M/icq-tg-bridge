"""A partial FLAP/TMME write poisons only that connection, never the next packet."""
import asyncio
from pathlib import Path
import tempfile

from test_network import Phone, compile_driver, Config, Storage, OscarServer, C


async def scenario(binary, folder, encrypted, upload):
    cfg = Config()
    cfg.oscar_host = cfg.bos_host = '127.0.0.1'
    cfg.oscar_port = 0
    cfg.oscar_uin, cfg.oscar_password, cfg.oscar_psk = '12345', 'test', '1234'
    store = Storage(':memory:')
    who = store.uin_for_peer(400, kind='user', title='IO test', group_name='Telegram')
    sent = []

    async def outgoing(*args):
        sent.append(args)
        return 1

    async def receive_file(*args):
        sent.append(args)
        return True

    server = OscarServer(cfg, store, outgoing, store.contacts, lambda uin: C.STATUS_ONLINE,
                         on_file=receive_file)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]
    cfg.oscar_port = cfg.bos_port = port
    process = await asyncio.create_subprocess_exec(
        str(binary), str(port), str(int(encrypted)), '1', str(folder),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)
    phone = Phone(process)

    async def line(value):
        process.stdin.write((value + '\n').encode())
        await process.stdin.drain()

    try:
        await phone.wait(lambda e: e.get('type') == 0 and e.get('state') == 2)
        await line('arm-send-failure')
        await phone.wait(lambda e: 'fault_count' in e)
        if upload:
            source = folder / 'upload.bin'
            source.write_bytes(b'payload' * 100)
            await phone.command(20, 80, who, path=source)
        else:
            await phone.command(0, 80, who, text='Must not be delivered')
        await phone.wait(lambda e: e.get('type') == 12)
        await phone.wait(lambda e: e.get('type') == 0 and e.get('state') == 0)
        await line('send-fault-count')
        state = await phone.wait(lambda e: 'fault_count' in e)
        assert state['fault_count'] == 0, 'client appended another packet after a partial write'
        assert not sent, sent
        await line('clear-send-failure')
        await phone.wait(lambda e: 'fault_count' in e)
        await line('start')
        await phone.wait(lambda e: e.get('type') == 0 and e.get('state') == 2
                         and e.get('generation') == 2)
        await phone.command(2, 81, mode=C.STATUS_AWAY)
        assert (await phone.response(81, 13))['flag']
        assert not sent, 'failed send/upload was replayed after reconnect'
    finally:
        if process.returncode is None:
            await line('quit')
            try:
                await asyncio.wait_for(process.wait(), 3)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise
        await server.stop()
        store.close()


async def main():
    with tempfile.TemporaryDirectory(prefix='tmm-native-write-failure-') as directory:
        folder = Path(directory)
        binary = folder / 'network-test'
        compile_driver(binary)
        for encrypted in (False, True):
            for upload in (False, True):
                await scenario(binary, folder, encrypted, upload)
    print('PASS partial write: plain/TMME message and upload close damaged connection; '
          'new session works without replay')


if __name__ == '__main__':
    asyncio.run(main())
