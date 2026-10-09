"""Real adapters, original attachment bytes and reversible eXpress references.

No requests are made to any live messaging account.
"""
from __future__ import annotations
import asyncio
from pathlib import Path
import sys
import tempfile
import struct
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from telethon import types
from pymax.api.uploads.payloads import AttachFilePayload
from bridge.bridge import Bridge
from bridge.config import Config
from bridge.db import Storage, PROCESSED_PER_CHAT
from bridge.express.client import ExpressSide, chat_peer, message_number
from bridge.max.client import MaxSide, to_peer
from bridge.oscar import blocks, const as C
from bridge.oscar.proto import Reader, Snac, pstr8, tlv
from bridge.oscar.server import Session
from bridge.quotes import QuoteError, filename
from tests.test_cross_quote import Telegram, Maximum, BIG_ID, NOW
from tests.test_express import FakeExpress, raw_event, PERSONAL, GROUP, THREAD, BOSS, ME

DATA = b'original media bytes\x00\xff'
CAPTION = '**Original** _caption_ 😀\nsecond line'


class MediaMessage(types.Message):
    def __init__(self, kind):
        super().__init__(id=123, peer_id=types.PeerChannel(1234), date=NOW, message=CAPTION)
        self.kind = kind
    @property
    def photo(self): return self.kind == 'photo'
    @property
    def voice(self): return self.kind == 'voice'
    @property
    def video(self): return self.kind == 'video'
    @property
    def document(self): return self.kind == 'file'
    @property
    def file(self): return NS(size=len(DATA), name=names[self.kind], ext='.bin')
    async def download_media(self, file, progress_callback):
        progress_callback(len(DATA), len(DATA)); Path(file).write_bytes(DATA); return file


names = dict(photo='original.jpg', video='original.mp4', voice='original.ogg', file='original.bin')


class Express(FakeExpress):
    def __init__(self): super().__init__(); self.allowed = True; self.forwards = []
    async def can_forward(self, message): return self.allowed and not message.deleted
    async def download(self, message, *, max_bytes=0): return DATA
    async def forward(self, message, target):
        if not self.allowed: return None
        self.forwards.append((message.id, message.chat_id, target))
        return self.message(raw_event(800+len(self.forwards), target, ME, message.text,
                                     forward=dict(senderHuid=BOSS)))


async def main():
    with tempfile.TemporaryDirectory() as work:
        cfg = Config(tg_api_id=1, tg_api_hash='x', db=str(Path(work)/'bridge.db'), photos_enabled=False)
        bridge = Bridge(cfg)
        try:
            tg, maximum, ex = Telegram(), Maximum(), Express()
            tg.media = []; maximum.media = []
            async def send_file(peer, **kwargs):
                tg.media.append((peer, Path(kwargs['file']).read_bytes(), kwargs))
                return NS(id=3000+len(tg.media))
            tg.send_file = send_file
            async def upload(attachments):
                for a in attachments:
                    maximum.media.append((type(a).__name__, Path(a.path).read_bytes(), a.name))
                return [AttachFilePayload(file_id=888)]
            maximum._app.api.messages._upload_attachments = upload
            async def get_url(*args): return NS(url='https://media/')
            maximum.get_video_by_id = maximum.get_file_by_id = get_url
            bridge.telegram.client = tg
            bridge.max = MaxSide(cfg, bridge.on_telegram_message, client=maximum)
            bridge.express = ExpressSide(cfg, bridge.on_telegram_message, client=ex)
            ex.on_message=bridge.express._on_new_message
            bridge.active.update(max=True, express=True)
            await bridge.express.dialogs()
            async def download(url, max_bytes=0): return DATA
            bridge.max._download = download
            def contact(peer, title, topic=0):
                return bridge.storage.uin_for_peer(peer, kind='chat', title=title, group_name='Chats', topic_id=topic)
            sources = dict(telegram=contact(-1000000001234,'TG'), max=contact(to_peer(-5678),'MAX'),
                           express=contact(chat_peer(PERSONAL),'EX'))
            targets = dict(telegram=contact(-1000000002345,'TG dest',77),
                           max=contact(to_peer(-6789),'MAX dest'), express=contact(chat_peer(GROUP),'EX dest'))

            for kind in names:
                tg.message = MediaMessage(kind)
                attach = NS(type=dict(photo='PHOTO',video='VIDEO',voice='AUDIO',file='FILE')[kind],
                            name=names[kind], size=len(DATA), url='https://media/', base_url='https://media/',
                            video_id=55, file_id=66)
                maximum.message = NS(id=BIG_ID,chat_id=-5678,text=CAPTION,attaches=[attach])
                event = raw_event(300,PERSONAL,BOSS,CAPTION,kind=dict(photo='image',voice='voice',video='video',file='file')[kind],
                                  payload=dict(file='/media',fileName=names[kind],fileSize=len(DATA),
                                               fileMimeType='video/mp4' if kind=='video' else 'application/octet-stream'))
                ex.rows[PERSONAL] = [event]
                bridge.express._messages.clear()
                source_id = event['syncId']
                reference = bridge.storage.quote_reference(sources['express'],source_id)
                ids = dict(telegram=123,max=BIG_ID,express=reference)
                for source in sources:
                    for target in targets:
                        if source==target: continue
                        assert not await bridge.on_phone_quote(targets[target],sources[source],ids[source]), (source,target,kind)
                        if target=='telegram':
                            peer,data,kw=tg.media[-1]
                            assert peer==-1000000002345 and data==DATA and kw['reply_to']==77
                            assert kw['parse_mode'] is None and kw['voice_note']==(kind=='voice')
                            caption=kw['caption']
                            assert (-1000000002345,3000+len(tg.media)) in bridge.telegram._own_ids
                        elif target=='max':
                            cls,data,name=maximum.media[-1]
                            assert data==DATA and name==names[kind]
                            assert cls==dict(photo='Photo',video='Video',voice='Voice',file='File')[kind]
                            caption=maximum.sent[-1]['message']['text']
                            assert maximum.sent[-1]['message']['elements']==[]
                        else:
                            chat,name,data,caption,document=ex.sent[-1]
                            assert chat==GROUP and data==DATA and name==names[kind]
                            assert document==(kind in ('file','voice'))
                        assert caption.startswith('Цитировано из ') and caption.endswith(CAPTION)
            print('PASS: 24 media transfers through real TG/MAX/eXpress adapters; original bytes, captions, literal text, native upload types, forum routing and own echoes')

            # eXpress same-network forwarding uses full UUID and exact discussion.
            # The thread has been discovered by dialogs; its topic is looked up from that mapping.
            thread_source = contact(chat_peer(GROUP),'Thread',next(topic for peer,topic in bridge.express._threads if peer==chat_peer(GROUP)))
            thread_id=ex.rows[THREAD][0]['syncId']
            thread_ref=bridge.storage.quote_reference(thread_source,thread_id)
            assert not await bridge.on_phone_quote(targets['express'],thread_source,thread_ref)
            assert ex.forwards[-1]==(thread_id,THREAD,GROUP)
            wrong=bridge.storage.quote_reference(sources['express'],thread_id)
            assert await bridge.on_phone_quote(targets['express'],sources['express'],wrong)
            ex.allowed=False
            before=len(tg.media)
            assert await bridge.on_phone_quote(targets['telegram'],sources['express'],reference)
            assert len(tg.media)==before
            ex.allowed=True

            # Multiple attachments all download before the first upload.
            maximum.message.attaches=[attach,NS(type='FILE',name='second.bin',size=len(DATA),url='https://second/')]
            before=len(tg.media)
            assert not await bridge.on_phone_quote(targets['telegram'],sources['max'],BIG_ID)
            assert len(tg.media)==before+2
            async def broken(url,max_bytes=0): return None if 'second' in url else DATA
            bridge.max._download=broken
            before=len(tg.media)
            assert 'скачать' in await bridge.on_phone_quote(targets['telegram'],sources['max'],BIG_ID)
            assert len(tg.media)==before
            bridge.max._download=download
            maximum.message.attaches[1].size=cfg.render_source_max_mb*1024*1024+1
            assert 'source_max_mb' in await bridge.on_phone_quote(targets['telegram'],sources['max'],BIG_ID)
            assert len(tg.media)==before

            # A long caption is complete in text messages; attached file remains intact.
            tg.message=MediaMessage('video');tg.message.message='😀'*2500
            before=len(maximum.sent)
            assert not await bridge.on_phone_quote(targets['max'],sources['telegram'],123)
            sent=maximum.sent[before:]
            assert len(sent)==3 and sent[0]['message']['attaches']
            assert ''.join(p['message']['text'].split('\n',1)[1] for p in sent[1:])==tg.message.message
            tg.message.message=''
            assert not await bridge.on_phone_quote(targets['max'],sources['telegram'],123)
            assert maximum.sent[-1]['message']['attaches'] and maximum.sent[-1]['message']['text'].endswith('\n')
            print('PASS: native eXpress forwarding, exact source discussion, prohibited forwarding, multiple files, preflight download/size failures and complete long captions')

            items=await bridge.express.history(chat_peer(PERSONAL),20,None,20)
            assert items[0].source_id==source_id and items[0].msg_id==message_number(source_id)
            session=Session(bridge.oscar,None,NS(get_extra_info=lambda _ : ('127.0.0.1',1)))
            session.tmm_version=(0,85);packets=[]
            async def capture(family,subtype,data=b'',**kw):packets.append(data);return True
            session.send_snac=capture
            await session.deliver(sources['express'],'live',message_id=source_id)
            r=Reader(packets[-1]);r.read(8);r.u16();r.pstr8();r.u16();r.tlvs(r.u16())
            assert r.tlvs().get(C.TLV_TMM_MESSAGE_REF)==blocks.message_ref(reference)
            assert bridge.oscar.message_ref(sources['express'],source_id)==blocks.message_ref(reference)
            # Phone-originated IDs are distinct from millisecond read markers.
            receipt=await bridge.express.send(chat_peer(GROUP),'own')
            own_ref=bridge.storage.quote_reference(targets['express'],receipt.message_id)
            async def outgoing(*args): return receipt
            bridge.oscar.on_outgoing=outgoing;packets.clear();cookie=bytes(range(8))
            await session.on_icbm_send(Snac(4,6,0,1,cookie+struct.pack('>H',1)+pstr8(str(targets['express']).encode())+
                                           tlv(2,blocks.message_fragments('own'))))
            assert packets[0]==cookie+pstr8(str(targets['express']).encode())+blocks.message_ref(own_ref)
        finally: bridge.storage.close()
        storage=Storage(cfg.db)
        try:
            assert storage.quote_source(sources['express'],reference)==source_id
            assert storage.quote_reference(sources['express'],source_id)==reference
            a='aaaaaaaa-0000-0000-0000-000000000001';b='aaaaaaaa-0000-0000-0000-000000000002'
            ra,rb=storage.quote_reference(1,a),storage.quote_reference(1,b)
            assert ra!=rb and storage.quote_source(1,ra)==a and storage.quote_source(2,ra) is None
            for n in range(PROCESSED_PER_CHAT+1): storage.quote_reference(1,f'bbbbbbbb-0000-0000-0000-{n:012x}')
            assert storage.quote_source(1,ra) is None
            assert storage.quote_reference(1,a)>rb  # Expired references are never reused.
            assert storage.quote_reference(1,BIG_ID)==BIG_ID and storage.quote_reference(1,'bad')==0
            assert filename('../x.bin')=='x.bin' and filename('..')=='file.bin'
        finally:storage.close()
        print('PASS: eXpress live/history UUID references, persistent mapping, same-prefix collisions, source chat scope, bounded map, expired IDs never reused and full unsigned MAX IDs')

    # Exercise the actual HTTP reader, including a server omitting Content-Length.
    class Response:
        status=200;content_length=0
        def __init__(self):self.content=self
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def iter_chunked(self,size):yield b'abc';yield b'def'
        async def read(self):return b'abcdef'
    response=Response();side=MaxSide.__new__(MaxSide);side._http=NS(get=lambda *args,**kw:response)
    assert await side._download('https://offline/',6)==b'abcdef'
    assert await side._download('https://offline/')==b'abcdef'
    for length in (0,20):
        response.content_length=length
        try:await side._download('https://offline/',5)
        except QuoteError:pass
        else:raise AssertionError('HTTP size limit swallowed or ignored')
    print('PASS: actual MAX HTTP downloader enforces declared and streamed sizes and propagates actionable quota errors')


if __name__=='__main__': asyncio.run(main())
