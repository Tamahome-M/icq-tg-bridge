"""Native client against the real OSCAR server; all provider effects are local fakes."""
import asyncio
import json
import os
import shlex
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bridge.config import Config
from bridge.db import Storage
from bridge.oscar.server import OscarServer
from bridge.oscar import const as C, blocks

SOURCES = ['client.cpp', 'keepalive_timer.cpp', 'oscar.cpp', 'transport.cpp', 'dns.cpp', 'crypto.cpp', 'mobile_network.cpp', 'network_profile.cpp']


def compile_driver(path, *, rtc_adapter=False):
    rtc = ([str(ROOT/'native-v8/tests/rtc_sw_shim.cpp'), '-Wl,--wrap=open,--wrap=ioctl,--wrap=gettimeofday']
           if rtc_adapter else [])
    subprocess.run(['g++', '-std=c++98', '-Wall', '-Wextra', '-fno-rtti', '-pthread', '-I', str(ROOT/'native-v8/src'),
                    str(ROOT/'native-v8/tests/network_driver.cpp'), *rtc, *[str(ROOT/'native-v8/src'/s) for s in SOURCES],
                    '-Wl,--wrap=pthread_create,--wrap=connect,--wrap=send,--wrap=clock_gettime', '-ldl', '-lrt','-lresolv', '-o', str(path)], check=True)


class Phone:
    def __init__(self, process):
        self.p = process
        self.events = []

    async def wait(self, predicate, timeout=10):
        async def read():
            while True:
                for index, event in enumerate(self.events):
                    if predicate(event):
                        return self.events.pop(index)
                line = await self.p.stdout.readline()
                if not line:
                    raise AssertionError(('native driver exited', await self.p.stderr.read(), self.events))
                self.events.append(json.loads(line))
        try: return await asyncio.wait_for(read(), timeout)
        except asyncio.TimeoutError: raise AssertionError(('Timed out waiting for native event', self.events[-20:]))

    async def command(self, kind, ident, uin=0, *, source=0, mode=0, offset=0, limit=10, duration=0, flag=False,
                      text='', path='', token=b'', ref=b''):
        fields = [kind, ident, uin, source, mode, offset, limit, duration, int(flag),
                  text.encode().hex() or '-', str(path).encode().hex() or '-', token.hex() or '-', ref.hex() or '-']
        self.p.stdin.write((' '.join(map(str, fields))+'\n').encode())
        await self.p.stdin.drain()
        got = await self.wait(lambda e: e.get('submitted') == ident)
        assert got['ok'], got

    async def response(self, ident, kind):
        event = await self.wait(lambda e: e.get('id') == ident and e.get('type') in (kind, 12))
        assert event['type'] == kind, event
        return event


async def scenario(executable, folder, encryption, md5):
    cfg = Config()
    cfg.oscar_host = '127.0.0.1'; cfg.oscar_port = 0; cfg.oscar_uin = '12345'; cfg.oscar_password = 'test'
    cfg.bos_host = '127.0.0.1'; cfg.oscar_psk = '1234'; cfg.avatars = True
    store = Storage(':memory:')
    who = store.uin_for_peer(100, kind='user', title='Мама', group_name='Telegram/Семья')
    second = store.uin_for_peer(101, kind='user', title='Сергей', group_name='MAX/Друзья')
    sent, quotes, uploads, typing, privacy, removed = [], [], [], [], [], []
    blob = b'\xff\xd8' + bytes(range(256))*600
    photo = b'\xff\xd8native-image'
    avatar_hash = b'a'*16
    async def outgoing(uin, text): sent.append((uin, text)); return type('Sent', (int,), {'message_id': 123456})(123456)
    async def history(uin, count, offset=0):
        if uin == second: raise ConnectionError('Сеть временно недоступна')
        if count == 7: await asyncio.sleep(.15)
        return ([('Мама\nТекст истории', 'photo:1', False, second, 987654)], offset == 0)
    async def attachment(*_): return photo
    async def video(*_): return blob
    async def voice(*_): return blob
    async def file(*_): return 'имя.txt', blob
    async def avatar(uin): return avatar_hash, photo
    async def chat_list(): return [(who, 'Мама', 0, 0, True), (second, 'Сергей', 1, 1, True)]
    async def open_chat(uin): return True
    async def quote(dest, source, message_id): quotes.append((dest, source, message_id)); return ''
    async def send_photo(uin, data): uploads.append(('photo', uin, data)); return True
    async def send_voice(uin, data, duration): uploads.append(('voice', uin, data, duration)); return True
    async def send_video(uin, data, duration): uploads.append(('video', uin, data, duration)); return True
    async def send_file(uin, path, name, kind): uploads.append(('file', uin, pathlib.Path(path).read_bytes(), name, kind)); return True
    async def on_typing(uin, active): typing.append((uin, active))
    async def on_privacy(uin, muted): privacy.append((uin, muted))
    async def on_remove(uin, revoke): removed.append((uin, revoke))
    async def info(uin): return dict(title='Мама', kind='Личный', members='2', network='Telegram', about='Описание чата')
    async def search(text): return [dict(uin=who, title='Мама', kind='Личный', username='mama')]
    server = OscarServer(cfg, store, outgoing, store.contacts, lambda uin: C.STATUS_ONLINE,
                         avatar=avatar, icon_hash=lambda uin: avatar_hash, fetch_attachment=attachment, fetch_history=history,
                         fetch_video=video, fetch_voice=voice, fetch_file=file, chat_list=chat_list, open_chat=open_chat,
                         on_quote=quote, quote_supported=lambda uin: True, on_photo=send_photo, on_voice=send_voice,
                         on_video=send_video, on_file=send_file, chat_info=info, search=search,
                         on_privacy=on_privacy, on_remove=on_remove)
    server.on_typing = on_typing
    offline_ts = int(time.time()) // 60 * 60 - 1800
    store.queue(who, 'Офлайн по UTC', 10, forced=True, ts=offline_ts)
    await server.start()
    port = server._server.sockets[0].getsockname()[1]
    cfg.oscar_port = cfg.bos_port = port
    tokens = {kind: server.register_attachment(who, name) for kind,name in [(6,'photo:1'),(7,'video:1'),(8,'voice:1'),(9,'file:1')]}
    token = tokens[6]
    process = await asyncio.create_subprocess_exec(*executable, str(port), str(int(encryption)), str(int(md5)), str(folder),
                                                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                env=dict(os.environ, TZ='UTC-3'))
    phone = Phone(process)
    try:
        await phone.wait(lambda e: e.get('type') == 0 and e.get('state') == 2)
        progress = [e for e in phone.events if e.get('type') == 10 and e.get('id') == 0]
        assert [e['bytes'] for e in progress] == [0, 10, 20, 35, 50, 65, 75, 90, 100], progress
        assert all(e['total'] == 100 and e['text'] and e['generation'] == 1 for e in progress), progress
        offline = await phone.wait(lambda e: e.get('type') == 3 and e.get('messages')
                                   and e['messages'][0]['text'] == 'Офлайн по UTC')
        assert offline['messages'][0]['time'] == offline_ts, offline
        roster = await phone.wait(lambda e: e.get('type') == 1)
        assert any(c['uin'] == who and c['name'] == 'Мама' and c['group'] == 'Telegram/Семья' for c in roster['contacts']), roster
        await phone.wait(lambda e: e.get('type') == 2 and e.get('uin') == second)
        # The four-byte user-info trailer also belongs to departed records.
        # A stale parser read it as an empty next UIN and reconnected.
        icon_hash_of = server.icon_hash
        server.icon_hash = lambda _: None
        try:
            await server.notify_status(who, C.STATUS_OFFLINE)
        finally:
            server.icon_hash = icon_hash_of
        departed = await phone.wait(lambda e: e.get('type') == 2 and e.get('uin') == who
                                    and any(c['status'] == 0xffffffff for c in e.get('contacts', [])))
        assert departed['generation'] == 1, departed
        await server.session.send_snac(C.BUDDY, C.BUDDY_DEPARTED,
                                       blocks.buddy_departed(second) + blocks.buddy_departed(who))
        for ident in (second, who):
            departed = await phone.wait(lambda e: e.get('type') == 2 and e.get('uin') == ident
                                        and any(c['status'] == 0xffffffff for c in e.get('contacts', [])))
            assert departed['generation'] == 1, departed
        await server.notify_status(who, C.STATUS_ONLINE)
        arrived = await phone.wait(lambda e: e.get('type') == 2 and e.get('uin') == who
                                   and any(c['status'] == C.STATUS_ONLINE for c in e.get('contacts', [])))
        assert arrived['generation'] == 1, arrived
        await server.deliver(who, 'Входящее 😀')
        incoming = await phone.wait(lambda e: e.get('type') == 3 and e.get('messages') and not e['messages'][0]['out'])
        assert incoming['messages'][0]['text'] == 'Входящее 😀', incoming
        await phone.command(0, 10, who, text='Привет 😀')
        receipt = await phone.wait(lambda e: e.get('type') == 4 and e.get('delivery') == 1)
        assert sent == [(who, 'Привет 😀')], sent
        ref = receipt if receipt['ref'] else await phone.wait(lambda e: e.get('type') == 4 and e.get('ref'))
        assert await server.confirm_read(who, 123456) == 1
        read = await phone.wait(lambda e: e.get('type') == 4 and e.get('delivery') == 2)
        assert read['cookie'] == receipt['cookie'] and read['uin'] == who, read
        await phone.command(16, 11, who, source=who, ref=bytes.fromhex(ref['ref']))
        assert (await phone.response(11, 11))['flag']
        assert quotes == [(who, who, 123456)]
        await phone.command(3, 12, who, limit=10)
        page = await phone.response(12, 6)
        assert page['more'] and page['offset'] == 1 and page['messages'][0]['thread'] == second, page
        assert page['messages'][0]['ref'] == (987654).to_bytes(8, 'big').hex()
        # Fresh-chat preload uses the regular history route with one record,
        # not OpenChat (which restores a chat to the roster).
        await phone.command(3, 14, who, limit=1)
        tail = await phone.response(14, 6)
        assert len(tail['messages']) == 1 and tail['messages'][0]['time'] == 0, tail
        assert tail['messages'][0]['text'] == 'Мама\nТекст истории', tail
        await phone.command(3, 13, second)
        failed = await phone.wait(lambda e: e.get('id') == 13 and e.get('type') == 12)
        assert failed['text'] == 'Сеть временно недоступна', failed
        for command, bart_kind in [(5, 1), (6, 0x80), (7, 0x82), (8, 0x83), (9, 0x86)]:
            ident = 20+command
            await phone.command(command, ident, who, token=avatar_hash if command == 5 else tokens[command])
            result = await phone.response(ident, 9)
            assert result['kind'] == bart_kind
            expected = photo if command in (5,6) else blob
            assert pathlib.Path(result['path']).read_bytes() == expected
            chunks = [e for e in phone.events if e.get('id') == ident and e.get('type') == 10]
            assert chunks and chunks[-1]['bytes'] == len(expected), chunks
            assert all(e['total'] == 0 and 'часть' in e['text'] for e in chunks), chunks
        await phone.command(10, 40, who, limit=1)
        page = await phone.response(40, 7)
        assert page['more'] and page['offset'] == 1 and page['contacts'][0]['name'] == 'Мама', page
        await phone.command(10, 41, who, limit=1, offset=page['offset'])
        assert not (await phone.response(41, 7))['more']
        await phone.command(12, 42, text='Ма')
        assert (await phone.response(42, 7))['contacts'][0]['name'] == 'Мама'
        await phone.command(13, 43, who)
        assert (await phone.response(43, 8))['fields']['about'] == 'Описание чата'
        source = folder/'upload.bin'; source.write_bytes(blob)
        for index,command in enumerate((17,18,19,20)):
            await phone.command(command, 50+index, who, path=source, duration=7)
            assert (await phone.response(50+index,13))['flag']
        assert [u[0] for u in uploads] == ['photo','voice','video','file']
        assert all(u[2] == blob for u in uploads)
        # Files chosen from memory use the document route with a media hint;
        # only a newly recorded video uses the timed video-note route above.
        for ident, media_kind in ((54, 1), (55, 2)):
            await phone.command(20, ident, who, path=source, mode=media_kind)
            assert (await phone.response(ident, 13))['flag']
            assert uploads[-1] == ('file', who, blob, 'upload.bin', media_kind), uploads[-1]
        await phone.command(1, 60, who, flag=True)
        await phone.command(22, 61, who)
        assert (await phone.response(61,13))['flag']
        for _ in range(50):
            if server.session.quiet_uins == {who}: break
            await asyncio.sleep(.01)
        assert server.session.quiet_uins == {who}
        await asyncio.sleep(1.3)
        assert typing == [(who, True)]
        assert server.session and not server.session.closed
        await phone.command(3, 70, who, limit=7)
        await phone.command(23, 70, who)
        assert (await phone.response(70,13))['flag']
        await asyncio.sleep(.2)
        await phone.command(13,71,who)
        await phone.response(71,8)
        assert not any(e.get('id')==70 and e.get('type')==6 for e in phone.events), 'cancelled history was surfaced'
        edits = []
        original_edit = server.session.on_ssi_edit
        async def record_edit(snac):
            edits.extend(blocks.parse_ssi_items(snac.data))
            await original_edit(snac)
        server.session.on_ssi_edit = record_edit
        await phone.command(25,72,who,text='Мамочка')
        assert (await phone.response(72,13))['flag']
        renamed = await phone.wait(lambda e:e.get('type')==1 and any(c['uin']==who and c['name']=='Мамочка' for c in e.get('contacts',[])))
        assert any(name==str(who).encode() and kind==0 and extra.get(0x131)=='Мамочка'.encode('cp1251') for name,group,item,kind,extra in edits),edits
        await phone.command(30,73,who,mode=14,flag=True)
        assert (await phone.response(73,13))['flag']
        await phone.command(30,74,who,mode=14,flag=False)
        assert (await phone.response(74,13))['flag']
        assert privacy==[(who,True),(who,False)],privacy
        await phone.command(14,75,second)
        assert (await phone.response(75,13))['flag']
        await phone.command(15,76,second)
        assert (await phone.response(76,13))['flag']
        for _ in range(50):
            if len(removed)==2:break
            await asyncio.sleep(.01)
        assert removed==[(second,False),(second,True)],removed
        process.stdin.write(b'stop-wait\n'); await process.stdin.drain()
        assert (await phone.wait(lambda e: 'joined' in e))['joined']
        process.stdin.write(b'start\n'); await process.stdin.drain()
        await phone.wait(lambda e:e.get('type')==0 and e.get('state')==2 and e.get('generation')==2)
        print('PASS native OSCAR', 'TMME' if encryption else 'plain', 'MD5' if md5 else 'XOR')
    finally:
        if process.returncode is None:
            process.stdin.write(b'quit\n'); await process.stdin.drain()
            try: await asyncio.wait_for(process.wait(), 5)
            except asyncio.TimeoutError: process.kill(); await process.wait(); raise
        await server.stop()
        store.close()


async def negative_cases(executable, folder):
    async def launch(port, variables=None, encrypted=False, cache=None):
        env = os.environ.copy(); env.update(variables or {})
        process = await asyncio.create_subprocess_exec(*executable, str(port), str(int(encrypted)), '1', str(cache or folder),
                    env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        return Phone(process)
    async def close(phone):
        if phone.p.returncode is None:
            phone.p.stdin.write(b'quit\n'); await phone.p.stdin.drain()
            try: await asyncio.wait_for(phone.p.wait(), 3)
            except asyncio.TimeoutError: phone.p.kill(); await phone.p.wait(); raise
    print('CHECK thread failure',flush=True)
    phone = await launch(1, {'TMM_TEST_THREAD_FAILURE':'1'})
    try:
        error = await phone.wait(lambda e:e.get('type')==12)
        assert 'поток' in error['text'],error
        await phone.wait(lambda e:e.get('type')==0 and e.get('state')==0)
    finally: await close(phone)
    print('CHECK stalled greeting cancel',flush=True)
    accepted=asyncio.Event(); writers=[]
    async def stall(reader,writer): writers.append(writer);accepted.set();await reader.read()
    listener=await asyncio.start_server(stall,'127.0.0.1',0)
    phone=await launch(listener.sockets[0].getsockname()[1])
    try:
        await asyncio.wait_for(accepted.wait(),3)
        phone.p.stdin.write(b'stop\n');await phone.p.stdin.drain()
        await phone.wait(lambda e:e.get('type')==0 and e.get('state')==0,timeout=2)
        stages = [e['bytes'] for e in phone.events if e.get('type') == 10 and e.get('id') == 0]
        assert stages == [0, 10, 20], stages
    finally:
        await close(phone);listener.close()
        for writer in writers: writer.close();await writer.wait_closed()
        await listener.wait_closed()
    cfg=Config();cfg.oscar_host=cfg.bos_host='127.0.0.1';cfg.oscar_port=0
    cfg.oscar_uin='12345';cfg.oscar_password='test';cfg.oscar_psk='1234'
    store=Storage(':memory:');who=store.uin_for_peer(200,kind='user',title='Test',group_name='Telegram')
    async def outgoing(*args): return 1
    async def attachment(*args): return b'x'*64
    server=OscarServer(cfg,store,outgoing,store.contacts,lambda uin:C.STATUS_ONLINE,fetch_attachment=attachment)
    await server.start();port=server._server.sockets[0].getsockname()[1];cfg.oscar_port=cfg.bos_port=port
    try:
        print('CHECK wrong password/PSK',flush=True)
        for env,encrypted in [({'TMM_TEST_PASSWORD':'wrong'},False),({'TMM_TEST_PSK':'wrong'},True)]:
            phone=await launch(port,dict(env,TMM_TEST_RECONNECT='1'),encrypted)
            try:
                await phone.wait(lambda e:e.get('type')==12)
                await phone.wait(lambda e:e.get('type')==0 and e.get('state')==0)
                assert not any(e.get('type')==0 and e.get('state')==3 for e in phone.events),phone.events
            finally: await close(phone)
        print('CHECK media size/disk errors',flush=True)
        token=server.register_attachment(who,'photo:negative')
        blocked=folder/'cache-not-directory';blocked.write_bytes(b'occupied')
        for env,cache in [({'TMM_TEST_MAX_MEDIA':'10'},folder),({},blocked)]:
            phone=await launch(port,env,cache=cache)
            try:
                await phone.wait(lambda e:e.get('type')==0 and e.get('state')==2)
                await phone.command(6,81,who,token=token)
                failure=await phone.wait(lambda e:e.get('type')==12 and e.get('id')==81)
                assert failure['text'],failure
                await phone.command(2,82,mode=C.STATUS_AWAY)
                assert (await phone.response(82,13))['flag']
                assert server.session and not server.session.closed
            finally: await close(phone)
        print('PASS native errors: thread failure, stop during greeting, fatal password/PSK, media size/disk error keeps chat online')
    finally: await server.stop();store.close()


async def password_cases(executable, folder):
    cases = [
        ('12345678901234567890', '12345678901234567890', True),
        (' aB2!z ', ' aB2!z ', True),
        ('caféÆÿ', 'caféÆÿ', True),
        ('abc2', 'Abc2', False),
        ('dummy', 'пароль', False),
    ]
    for md5 in (True, False):
        for expected, given, accepted in cases:
            cfg = Config()
            cfg.oscar_host = cfg.bos_host = '127.0.0.1'
            cfg.oscar_port = 0
            cfg.oscar_uin = '12345'
            cfg.oscar_password = expected
            store = Storage(':memory:')
            async def outgoing(*_): return 1
            server = OscarServer(cfg, store, outgoing, store.contacts, lambda _: C.STATUS_ONLINE)
            await server.start()
            port = server._server.sockets[0].getsockname()[1]
            cfg.oscar_port = cfg.bos_port = port
            process = await asyncio.create_subprocess_exec(
                *executable, str(port), '0', str(int(md5)), str(folder),
                env=dict(os.environ, TMM_TEST_PASSWORD=given), stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            phone = Phone(process)
            try:
                result = await phone.wait(lambda e: e.get('type') == 12 or
                                          (e.get('type') == 0 and e.get('state') == 2))
                assert (result['type'] == 0) == accepted, result
            finally:
                process.stdin.write(b'quit\n')
                await process.stdin.drain()
                await asyncio.wait_for(process.wait(), 5)
                await server.stop()
                store.close()
    print('PASS native passwords: digits, mixed case, spaces, Latin-1, wrong case and unsupported characters')


async def main():
    with tempfile.TemporaryDirectory(prefix='tmm-native-network-') as directory:
        folder = pathlib.Path(directory); binary = folder/'network-test'
        if os.environ.get('TMM_NETWORK_DRIVER'): command = shlex.split(os.environ['TMM_NETWORK_DRIVER'])
        else: compile_driver(binary); command = [str(binary)]
        for encrypted,md5 in ((False,True),(True,True),(False,False)):
            cache=folder/f'cache-{encrypted}-{md5}';cache.mkdir()
            await scenario(command,cache,encrypted,md5)
        await password_cases(command, folder)
        if not os.environ.get("TMM_NETWORK_DRIVER"): await negative_cases(command,folder)

if __name__ == '__main__': asyncio.run(main())
