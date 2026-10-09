"""Native bool quotations and eXpress history errors through the real bridge.

Runs offline: browser/network results are supplied by FakeExpress.
"""
from __future__ import annotations
import asyncio
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bridge.bridge import Bridge
from bridge.config import Config
from bridge.express.client import ExpressSide, chat_peer
from bridge.oscar import const as C
from bridge.oscar.proto import Reader, Snac, pstr8
from bridge.oscar.server import Session
from tests.test_express import FakeExpress, raw_event, GROUP, BOSS, ME

CHECK=unittest.TestCase()


class Browser(FakeExpress):
    fail=False
    async def history(self, chat_id, count=50):
        if self.fail:raise RuntimeError('browser unavailable')
        return await super().history(chat_id,count)


async def main():
    with tempfile.TemporaryDirectory() as work:
        cfg=Config(tg_api_id=1,tg_api_hash='x',db=str(Path(work)/'bridge.db'),photos_enabled=False)
        bridge=Bridge(cfg)
        try:
            fake=Browser()
            fake.rows[GROUP]=[
                raw_event(10,GROUP,BOSS,'до ответа'),
                raw_event(11,GROUP,BOSS,'ответ',reply=dict(quote=True,senderHuid=ME,
                    payload=dict(body='исходный\n текст'))),
                raw_event(12,GROUP,BOSS,'после ответа',kind='image',payload=dict(
                    file='/uploads/x.jpg',fileName='x.jpg',fileSize=5,fileMimeType='image/jpeg')),
            ]
            bridge.express=ExpressSide(cfg,bridge.on_telegram_message,client=fake)
            bridge.active['express']=True
            await bridge.express.dialogs()
            uin=bridge.storage.uin_for_peer(chat_peer(GROUP),title='Common',kind='chat',group_name='eXpress')
            session=Session(bridge.oscar,None,NS(get_extra_info=lambda _:('127.0.0.1',1)))
            session.tmm_version=(1,3)
            packets=[]
            async def capture(family,subtype,data=b'',**kwargs):
                packets.append((family,subtype,data,kwargs));return True
            session.send_snac=capture
            async def request(count=20,paged=False):
                token=struct.pack('>HHB',count,0,int(paged))+bytes(11)
                body=pstr8(str(uin).encode())+b'\x01'+struct.pack('>H',C.BART_HISTORY)+b'\x01\x10'+token
                await session.on_icon_request(Snac(C.SSBI,C.SSBI_ICQ_REQ,0,77,body))
                return packets[-1]
            rows,more=await bridge.fetch_history(uin,20)
            assert len(rows)==3 and not more
            assert rows[1][0].endswith('[в ответ мне: исходный текст] ответ')
            assert rows[2][1].startswith('photo:') and all(row[4] for row in rows)
            packet=await request()
            assert packet[:2]==(C.SSBI,C.SSBI_ICQ_REPLY) and 'исходный текст'.encode('utf-8') in packet[2]
            assert 'после ответа'.encode('utf-8') in packet[2]

            fake.fail=True;before=len(packets)
            with CHECK.assertLogs(level='WARNING'):
                packet=await request()
            assert len(packets)==before+1 and packet[:2]==(C.SSBI,1)
            assert packet[3]['request_id']==77 and packet[2][:2]==b'\0\1'
            reason=Reader(packet[2][2:]).tlvs().get(C.TLV_TMM_ERROR_TEXT).decode('utf-8')
            assert reason=='Не получилось загрузить историю'
            for method,args in [(bridge.express.render_items,(chat_peer(GROUP),20,None,20)),
                                (bridge.express.last_photos,(chat_peer(GROUP),1))]:
                with CHECK.assertLogs(level='WARNING'):
                    try:await method(*args)
                    except RuntimeError:pass
                    else:raise AssertionError('manual history failure became an empty result')
            replies=[]
            async def reply(contact,text,**kwargs):replies.append(text)
            bridge.reply=reply
            with CHECK.assertLogs(level='WARNING'):
                assert await bridge.on_phone_message(uin,'!last 20')==-1
            assert replies[-1]=='Не получилось загрузить историю'
            with CHECK.assertLogs(level='WARNING'):
                assert await bridge.express.missed(chat_peer(GROUP),0,20)==[]

            fake.fail=False
            packet=await request(paged=True)
            assert packet[:2]==(C.SSBI,C.SSBI_ICQ_REPLY) and 'исходный текст'.encode() in packet[2]
            # A genuinely empty chat is still an empty successful response.
            fake.rows[GROUP]=[]
            assert await bridge.fetch_history(uin,20)==([],False)
            packet=await request()
            assert packet[:2]==(C.SSBI,C.SSBI_ICQ_REPLY)
            print('PASS: native eXpress quote=true in a mixed history page; all rows/media/UUID refs survive; manual errors reach phone as error TLV and !last response, background behavior retained; retry succeeds and empty chat is distinct')
        finally:bridge.storage.close()


if __name__=='__main__':asyncio.run(main())
