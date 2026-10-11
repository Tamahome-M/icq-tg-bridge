"""Independent messenger startup/retry, cached presence and resource cleanup.

Network adapters are simulated; OSCAR and HTTP use real local sockets.
"""
from __future__ import annotations

import asyncio
import builtins
from itertools import combinations
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace as NS
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from telethon import errors, types
from playwright.async_api import TimeoutError as PageTimeout
from bridge import policy
from bridge.bridge import Bridge
from bridge.config import Config, describe
from bridge.express.client import EXPRESS_BASE, ExpressSide
from bridge.express.web import ExpressClient
from bridge.max.client import MaxSide, to_peer
from bridge.oscar import const as C
from bridge.oscar.proto import Snac
from bridge.oscar.secure import parse_psk
from bridge.tg.client import Dialog, TelegramSide
from tests.fake_jimm import FakeJimm
from tests.test_max import FakeMax
from tests.test_secure import SecureDialer

NAMES = ("telegram", "max", "express")


async def until(check, timeout=3):
    async with asyncio.timeout(timeout):
        while not check():
            await asyncio.sleep(.005)


def configuration():
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.toml"
        base = '[oscar]\nuin="100500"\n[telegram]\napi_id=1\napi_hash="test"\n[bridge]\n'
        path.write_text(base)
        assert Config.load(path).network_retry_minutes == 30
        path.write_text(base + 'network_retry_minutes=7.5\n')
        cfg = Config.load(path)
        assert cfg.network_retry_minutes == 7.5
        assert any('7.5 мин' in row for row in describe(cfg))
        for invalid in ('0', '-1', 'nan', 'inf'):
            path.write_text(base + 'network_retry_minutes=' + invalid + '\n')
            try:
                Config.load(path)
            except ValueError as exc:
                assert 'network_retry_minutes' in str(exc)
            else:
                raise AssertionError(invalid)
    print('PASS: retry defaults to 30 minutes, TOML override/description and positive finite validation')


class Side:
    def __init__(self, name):
        self.name = name
        self.allowed = True
        self.gate = None
        self.attempts = []
        self.resources = False
        self.stops = 0
        self.drop = asyncio.Event()
        self.sent = []
        self.missed_calls = []
        base = {'telegram': 555, 'max': to_peer(100), 'express': EXPRESS_BASE + 100}[name]
        self.rows = [Dialog(base+i, 'user', name+str(i), name, i, status=status)
                     for i, status in enumerate(('online', 'offline', 'away'))]
        self.rows.append(Dialog(base+3, 'chat', name+' topic', name, 3,
                                topic_id=42, muted=True, unread=1))

    async def start(self):
        self.attempts.append(time.monotonic())
        self.resources = True
        if self.gate is not None:
            await self.gate.wait()
        if not self.allowed:
            raise PageTimeout('Page.goto: Timeout 90000ms exceeded.')
        self.drop = asyncio.Event()

    async def stop(self):
        self.resources = False
        self.stops += 1

    async def wait_disconnected(self):
        await self.drop.wait()
        raise ConnectionError('connection lost')

    async def dialogs(self):
        return self.rows  # reuse deliberately: refresh must not mutate positions

    async def send(self, peer, text, topic=0):
        self.sent.append((peer, text, topic))
        return 101

    async def missed(self, peer, *args):
        self.missed_calls.append(peer)
        return []


class Client(FakeJimm):
    def _absorb(self, packet):
        if (packet.family, packet.subtype) == (C.BUDDY, C.BUDDY_ARRIVED):
            r = packet.reader()
            while r.left:
                start = r.pos
                r.pstr8(); r.u16(); r.tlvs(r.u16())
                super()._absorb(Snac(packet.family, packet.subtype, packet.flags,
                                     packet.request_id, packet.data[start:r.pos]))
            return
        super()._absorb(packet)
        if (packet.family, packet.subtype) == (C.BUDDY, C.BUDDY_DEPARTED):
            self.statuses[int(packet.reader().pstr8())] = C.STATUS_WIRE_OFFLINE


def make_bridge(temp, interval=.2):
    cfg = Config(tg_api_id=1, tg_api_hash='test', tg_session=str(Path(temp)/'tg.session'),
                 db=str(Path(temp)/'bridge.db'), oscar_host='127.0.0.1', oscar_port=0, oscar_uin='100500',
                 oscar_password='test', oscar_psk='1234', typing_prime=False,
                 photos_host='127.0.0.1', photos_port=0, photos_dir=str(Path(temp)/'photos'),
                 render_enabled=False, max_enabled=True, max_phone='+70000000000',
                 express_enabled=True, network_retry_minutes=interval/60)
    bridge = Bridge(cfg)
    bridge.telegram.client.session.close()  # replaced below; no open test session retained
    sides = {name: Side(name) for name in NAMES}
    for name, side in sides.items():
        setattr(bridge, name, side)
        for row in side.rows:
            bridge.storage.uin_for_peer(row.peer_id, kind=row.kind, title=row.title,
                                        group_name=row.group_name, topic_id=row.topic_id,
                                        muted=int(row.muted))
            bridge.storage.note_delivered(row.peer_id, 1, row.topic_id)
    return bridge, sides


async def http_ready(bridge):
    port = bridge.photo_server._server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection('127.0.0.1', port)
    try:
        writer.write(b'GET / HTTP/1.0\r\nHost: localhost\r\n\r\n')
        await writer.drain()
        assert (await asyncio.wait_for(reader.read(), 2)).startswith(b'HTTP/1.1 200')
    finally:
        writer.close()
        await writer.wait_closed()


async def login(bridge, secure=False):
    port = bridge.oscar._server.sockets[0].getsockname()[1]
    phone = Client('127.0.0.1', port, bridge.cfg.oscar_uin, bridge.cfg.oscar_password)
    phone.tmm_version = (1, 11)
    if secure:
        phone.open_transport = SecureDialer(parse_psk('1234'))
    await phone.connect()
    await phone.bos(await phone.login_md5_jimm())
    await phone.drain_for(.025)
    return phone


async def matrix():
    for size in range(4):
        for failed_tuple in combinations(NAMES, size):
            failed = set(failed_tuple)
            with tempfile.TemporaryDirectory() as temp:
                bridge, sides = make_bridge(temp)
                for name in failed:
                    sides[name].allowed = False
                task = asyncio.create_task(bridge.run())
                phone = None
                try:
                    await until(lambda: bridge.photo_server._server is not None
                                and set(bridge._network_ready) == set(NAMES)-failed
                                and all(side.attempts for side in sides.values()))
                    await http_ready(bridge)
                    phone = await login(bridge, secure=size == 3)
                    assert len(phone.aliases) == 12
                    for name, side in sides.items():
                        for row in side.rows:
                            contact = bridge.storage.contact_by_peer(row.peer_id, row.topic_id)
                            expected = (policy.STATUS_INVISIBLE if name in failed else
                                        {'online': C.STATUS_ONLINE, 'offline': C.STATUS_WIRE_OFFLINE,
                                         'away': C.STATUS_AWAY}[row.status])
                            if row.muted and name not in failed:
                                expected = C.STATUS_DND
                            assert phone.statuses[contact.uin] == expected, (name, phone.statuses)
                            assert contact.gone == 0
                        contact = bridge.storage.contact_by_peer(side.rows[0].peer_id)
                        cookie = await phone.say(contact.uin, 'outgoing')
                        await phone.drain_for(.025)
                        assert (cookie in phone.acks) == (name not in failed)
                        assert bool(side.sent) == (name not in failed)
                        if name not in failed:
                            await bridge.on_telegram_message(contact.peer_id, '', 'incoming '+name,
                                                             message_id=501)
                            await phone.drain_for(.025)
                            assert (contact.uin, 'incoming '+name) in phone.received
                    assert not task.done()
                    for name in failed:
                        assert bridge.status_of(bridge.storage.contact_by_peer(sides[name].rows[1].peer_id).uin) == policy.STATUS_INVISIBLE
                        outside = bridge.storage.contact_by_peer(sides[name].rows[0].peer_id)
                        cached = bridge._by_uin.pop(outside.uin)
                        assert bridge.status_of(outside.uin) == policy.STATUS_INVISIBLE
                        bridge._by_uin[outside.uin] = cached
                        try:
                            await bridge.fetch_history(bridge.storage.contact_by_peer(sides[name].rows[0].peer_id).uin, 10)
                        except ConnectionError as exc:
                            assert 'Нет подключения' in str(exc)
                        else:
                            raise AssertionError('unavailable history reported empty rather than an error')
                        sides[name].allowed = True
                    await until(lambda: bridge._network_ready == set(NAMES))
                    await until(lambda: all(side.missed_calls for side in sides.values()))
                    await phone.drain_for(.03)
                    for name, side in sides.items():
                        assert len(side.attempts) >= (2 if name in failed else 1)
                        if name in failed:
                            assert all(b-a >= .195 for a, b in zip(side.attempts, side.attempts[1:]))
                        else:
                            assert len(side.attempts) == 1, 'healthy network restarted'
                        for row in side.rows:
                            contact = bridge.storage.contact_by_peer(row.peer_id, row.topic_id)
                            expected = (C.STATUS_DND if row.muted else
                                        {'online': C.STATUS_ONLINE, 'offline': C.STATUS_WIRE_OFFLINE,
                                         'away': C.STATUS_AWAY}[row.status])
                            assert phone.statuses[contact.uin] == expected
                            assert contact.gone == 0
                    assert bridge.mode == policy.UNMUTED
                    assert all(row.position == i for side in sides.values()
                               for i, row in enumerate(side.rows))
                finally:
                    if phone is not None:
                        await phone.close()
                    await bridge.close()
                    await asyncio.wait_for(task, 2)
                    assert not any(side.resources for side in sides.values())
    print('PASS: all eight available/unavailable combinations; real OSCAR/HTTP (all-down encrypted), cached users/topics retained, invisible versus real offline, healthy messages/ACKs, timed retry and restored real/policy statuses')


async def lifecycle():
    with tempfile.TemporaryDirectory() as temp:
        bridge, sides = make_bridge(temp, interval=.12)
        sides['express'].gate = asyncio.Event()
        task = asyncio.create_task(bridge.run())
        phone = None
        try:
            with patch('bridge.bridge.NETWORK_START_TIMEOUT', .15):
                await until(lambda: bridge.photo_server._server is not None
                            and bridge._network_ready == {'telegram', 'max'})
                phone = await login(bridge)
                assert len(sides['express'].attempts) == 1
                assert sides['express'].resources  # phone works while eXpress start still hangs
                await until(lambda: sides['express'].stops > 0)
                await bridge.set_network_active('express', False)
                attempts = len(sides['express'].attempts)
                await asyncio.sleep(.16)
                assert len(sides['express'].attempts) == attempts
                assert not sides['express'].resources
                assert bridge.storage.get_meta('network_on:express') == '0'
                sides['express'].gate.set()
                await bridge.set_network_active('express', True)
                await until(lambda: 'express' in bridge._network_ready)
                assert bridge.storage.get_meta('network_on:express') == '1'
                first = len(sides['max'].attempts)
                sides['max'].drop.set()
                await until(lambda: 'max' not in bridge._network_ready)
                assert all(bridge.status_of(c.uin) == policy.STATUS_INVISIBLE
                           for c in bridge.roster() if bridge._network_key(c.peer_id) == 'max')
                await until(lambda: len(sides['max'].attempts) == first+1 and 'max' in bridge._network_ready)
                assert len(sides['telegram'].attempts) == 1
                async def broken(): raise OSError('dialog list unavailable')
                sides['telegram'].dialogs = broken
                await bridge.refresh_roster()
                assert all(c.gone == 0 for c in bridge.storage.contacts())
                # A stalled Telegram roster must not delay new MAX data.
                gate = asyncio.Event()
                async def slow(): await gate.wait(); raise OSError('still unavailable')
                sides['telegram'].dialogs = slow
                sides['max'].rows[0].title = 'changed while Telegram stalls'
                refresh = asyncio.create_task(bridge.refresh_roster())
                try:
                    await until(lambda: bridge.storage.contact_by_peer(sides['max'].rows[0].peer_id).title
                                == 'changed while Telegram stalls')
                    assert not refresh.done()
                finally:
                    gate.set()
                    await refresh
                # An internally cancelled adapter still gets a retry.
                attempts = len(sides['express'].attempts)
                cancelled_seen = asyncio.Event()
                async def cancelled():
                    cancelled_seen.set()
                    raise asyncio.CancelledError()
                original_wait = sides['express'].wait_disconnected
                sides['express'].wait_disconnected = cancelled
                sides['express'].drop.set()
                await asyncio.wait_for(cancelled_seen.wait(), 2)
                assert not bridge._network_tasks['express'].done()
                sides['express'].wait_disconnected = original_wait
                await until(lambda: len(sides['express'].attempts) >= attempts+2
                            and 'express' in bridge._network_ready)
                assert all(row.position == i for side in sides.values()
                           for i, row in enumerate(side.rows))
                # Stop while a retry sleeps: it must not connect after DB close.
                sides['express'].allowed = False
                sides['express'].drop.set()
                await until(lambda: 'express' not in bridge._network_ready)
        finally:
            if phone is not None: await phone.close()
            await bridge.close()
            await bridge.close()  # shutdown is idempotent
            await asyncio.wait_for(task, 2)
        counts = [len(side.attempts) for side in sides.values()]
        await asyncio.sleep(.16)
        assert counts == [len(side.attempts) for side in sides.values()]
        assert not bridge._network_tasks
    print('PASS: slow/timed-out startup does not block phone, disabled network stops retries, explicit enable starts immediately, runtime loss retries only that network, failed Telegram roster preserves chats, shutdown cancels waits')


async def adapter_cleanup():
    async def nothing(*args, **kwargs): pass
    with tempfile.TemporaryDirectory() as temp:
        cfg = Config(tg_api_id=1, tg_api_hash='test', tg_session=str(Path(temp)/'tg.session'),
                     mirror_outgoing=True)
        tg = TelegramSide(cfg, nothing, nothing, nothing, nothing)
        tg.client.session.close()
        class Telethon:
            def __init__(self): self.handlers = []; self.calls = 0
            async def connect(self): self.calls += 1
            async def is_user_authorized(self): return True
            async def get_me(self): return types.User(42, first_name='test')
            def add_event_handler(self, *args): self.handlers.append(args)
            async def disconnect(self): pass
        tg.client = Telethon()
        for _ in range(3):
            await tg.start(); await tg.stop()
        assert tg.client.calls == 3 and len(tg.client.handlers) == 4

        class Hanging(FakeMax):
            def __init__(self): super().__init__(); self.closed = 0
            async def start(self): await asyncio.Event().wait()
            async def close(self): self.closed += 1
        for cancel in (False, True):
            raw = Hanging()
            maximum = MaxSide(cfg, nothing, client=raw)
            with patch('bridge.max.client.START_TIMEOUT', .02):
                pending = asyncio.create_task(maximum.start())
                await asyncio.sleep(.005)
                if cancel: pending.cancel()
                result = (await asyncio.gather(pending, return_exceptions=True))[0]
                assert isinstance(result, asyncio.CancelledError if cancel else RuntimeError)
            assert raw.closed == 1 and maximum.client is None and maximum._task is None
            assert not maximum._started.is_set()
            await maximum.stop()
            assert raw.closed == 1
        class Closing:
            def __init__(self): self.closed = 0
            async def close(self): self.closed += 1
            async def stop(self): self.closed += 1
        for cancel in (False, True):
            web = ExpressClient(str(Path(temp)/'express'))
            ctx, pw = Closing(), Closing()
            async def launch():
                web._ctx, web._pw = ctx, pw
                web._tasks.add(asyncio.create_task(asyncio.Event().wait()))
                if cancel: await asyncio.Event().wait()
                raise PageTimeout('Page.goto: Timeout 90000ms exceeded.')
            web._launch = launch
            express = ExpressSide(cfg, nothing, client=web)
            pending = asyncio.create_task(express.start())
            await asyncio.sleep(.005)
            if cancel: pending.cancel()
            result = (await asyncio.gather(pending, return_exceptions=True))[0]
            assert isinstance(result, asyncio.CancelledError if cancel else RuntimeError)
            assert express.client is None and ctx.closed == pw.closed == 1
            assert web._ctx is web._pw is web._page is web._watchdog is None
            assert not web._tasks
            web.on_message = nothing
            web._on_emit(None, '{}')
            web._drop_download(NS(cancel=nothing))
            assert not web._tasks, 'closed browser started a late callback'
        # A loaded page without a backend connection must fail startup too.
        web = ExpressClient(str(Path(temp)/'express'))
        ctx, pw = Closing(), Closing()
        async def wait_function(script, **kwargs):
            if 'isConnectionAlive' in script:
                raise PageTimeout('backend timeout')
        async def evaluate(*args): pass
        async def open_page(*args): return NS(wait_for_function=wait_function, evaluate=evaluate)
        async def logged_in(*args): return True
        async def launch():
            web._ctx, web._pw = ctx, pw
            await web._load()
        web._launch = launch
        with patch('bridge.express.web.open_app', open_page), patch('bridge.express.web.is_logged_in', logged_in):
            try:
                await web.start()
            except ConnectionError as exc:
                assert 'нет связи' in str(exc)
            else:
                raise AssertionError('eXpress without backend became ready')
        assert ctx.closed == pw.closed == 1
        # The actual watchdog reports an unavailable backend to the bridge.
        web = ExpressClient(str(Path(temp)/'express'))
        async def evaluate(script): return {'alive': False} if script != '() => !!window.__exWatching' else True
        web._page = NS(evaluate=evaluate)
        with patch('bridge.express.web.WATCHDOG_SECONDS', .005):
            web._watchdog = asyncio.create_task(web._watch())
            try:
                await asyncio.wait_for(web.wait_disconnected(), 1)
            except ConnectionError:
                pass
            else:
                raise AssertionError('disconnected eXpress stayed ready')
        await web.stop()
    assert not [t for t in asyncio.all_tasks() if not t.done() and t.get_name() in
                {'max-client', 'express-watchdog', 'bridge-telegram', 'bridge-max', 'bridge-express'}]
    print('PASS: Telegram reconnect registers handlers once; MAX timeout/cancel releases client/start waiter; eXpress timeout/cancel closes partial browser, tasks and profile; actual watchdog reports backend loss')


async def authorization_failure():
    """A revoked Telegram session or missing optional library is local to it."""
    original_import = builtins.__import__
    attempts = []
    def unavailable(name, *args, **kwargs):
        if name == 'pymax':
            attempts.append(time.monotonic())
            raise ImportError('simulated missing MAX library')
        return original_import(name, *args, **kwargs)
    with tempfile.TemporaryDirectory() as temp, patch('builtins.__import__', unavailable):
        bridge, sides = make_bridge(temp, interval=.05)
        bridge.max = MaxSide(bridge.cfg, bridge.on_telegram_message)
        original_start = sides['telegram'].start
        async def revoked(): raise errors.AuthKeyUnregisteredError(None)
        sides['telegram'].start = revoked
        task = asyncio.create_task(bridge.run())
        try:
            await until(lambda: len(attempts) >= 2 and bridge._network_ready == {'express'})
            assert not task.done() and len(sides['express'].attempts) == 1
            assert all(bridge.status_of(c.uin) == policy.STATUS_INVISIBLE
                       for c in bridge.roster() if bridge._network_key(c.peer_id) != 'express')
            assert attempts[1]-attempts[0] >= .045
            sides['telegram'].start = original_start
            bridge.max._make_client = lambda interactive: FakeMax()
            await until(lambda: bridge._network_ready == set(NAMES))
            await until(lambda: bridge.max._started.is_set())
        finally:
            await bridge.close()
            await asyncio.wait_for(task, 2)
    print('PASS: revoked Telegram session and missing MAX dependency do not stop eXpress/bridge; both retry on interval and recover independently')


async def saved_switches():
    with tempfile.TemporaryDirectory() as temp:
        first, _ = make_bridge(temp, interval=.05)
        cfg = first.cfg
        uin = first.storage.contact_by_peer(to_peer(100)).uin
        for name in NAMES:
            first.storage.set_meta('network_on:'+name, '0')
        await first.close()
        bridge = Bridge(cfg)
        bridge.telegram.client.session.close()
        sides = {name: Side(name) for name in NAMES}
        for name, side in sides.items(): setattr(bridge, name, side)
        assert not any(bridge.active.values())
        task = asyncio.create_task(bridge.run())
        phone = None
        try:
            await until(lambda: bridge.photo_server._server is not None)
            await http_ready(bridge)
            phone = await login(bridge)
            assert not phone.aliases and not bridge._network_tasks
            await asyncio.sleep(.06)
            assert not any(side.attempts for side in sides.values())
            await bridge.set_network_active('max', True)
            await until(lambda: bridge._network_ready == {'max'})
            assert bridge.storage.contact_by_peer(to_peer(100)).uin == uin
            assert not sides['telegram'].attempts and not sides['express'].attempts
        finally:
            if phone is not None: await phone.close()
            await bridge.close()
            await asyncio.wait_for(task, 2)
    print('PASS: persisted disabled networks do not start or retry after restart; all-off bridge still serves phone/HTTP; explicit enable preserves UIN and starts only that network')


async def main():
    configuration()
    await adapter_cleanup()
    await authorization_failure()
    await saved_switches()
    await matrix()
    await lifecycle()


if __name__ == '__main__':
    asyncio.run(main())
