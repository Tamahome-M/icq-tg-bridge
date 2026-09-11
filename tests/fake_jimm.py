"""Тестовый клиент: повторяет диалог, который ведёт Jimm 0.7 с ICQ-сервером."""

from __future__ import annotations

import asyncio
import hashlib
import struct
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.oscar import const as C
from bridge.oscar.blocks import message_fragments, parse_message_fragments
from bridge.oscar.proto import (Reader, Snac, flap, pstr8, pstr16,
                                roast_password, snac, tlv, tlv_u16)


class FakeJimm:
    def __init__(self, host: str, port: int, uin: str, password: str):
        self.host, self.port = host, port
        self.uin, self.password = uin, password
        self.seq = 1
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.contacts: list[tuple[int, int, int, int, bytes]] = []
        self.groups: dict[int, str] = {}
        self.ssi_stamp = 0
        self.ssi_count = 0
        self.aliases: dict[int, str] = {}
        self.online_uins: list[int] = []
        self.offline_uins: list[int] = []
        self.statuses: dict[int, int] = {}
        self.capabilities: dict[int, bytes] = {}
        self.icon_hashes: dict[int, bytes] = {}
        self.privacy: list[tuple[int, int]] = []
        self.urls: list[tuple[int, str]] = []      # ссылки из URL-сообщений
        self.offline: list[tuple[int, tuple, str]] = []   # офлайн-сообщения с датой
        self.received: list[tuple[int, str]] = []
        self.acks: list[bytes] = []
        self.next_msg_id = 1000
        self.send_acks = True            # отвечать ли на расширенные сообщения
        self.channels: list[int] = []    # каналы, которыми приходили сообщения
        self.to_ack: list[bytes] = []
        self.typing: list[tuple[int, bool]] = []
        self.errors: list[tuple[int, int]] = []

    async def connect(self) -> None:
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        await self.recv_flap()          # приветствие сервера

    async def send_flap(self, channel: int, payload: bytes) -> None:
        self.seq += 1
        self.writer.write(flap(channel, self.seq, payload))
        await self.writer.drain()

    async def send_snac(self, family: int, subtype: int, data: bytes = b"", req: int = 0) -> None:
        await self.send_flap(2, snac(family, subtype, data, 0, req))

    async def recv_flap(self, timeout: float = 5.0) -> tuple[int, bytes]:
        header = await asyncio.wait_for(self.reader.readexactly(6), timeout)
        assert header[0] == 0x2A, f"не FLAP: {header!r}"
        length = struct.unpack(">H", header[4:6])[0]
        payload = await asyncio.wait_for(self.reader.readexactly(length), timeout) if length else b""
        return header[1], payload

    async def recv_snac(self, timeout: float = 5.0) -> Snac:
        while True:
            channel, payload = await self.recv_flap(timeout)
            if channel == 2:
                return Snac.parse(payload)

    async def expect(self, family: int, subtype: int, timeout: float = 5.0) -> Snac:
        while True:
            s = await self.recv_snac(timeout)
            if (s.family, s.subtype) == (family, subtype):
                return s
            self._absorb(s)

    def _absorb(self, s: Snac) -> None:
        if (s.family, s.subtype) == (C.BUDDY, C.BUDDY_ARRIVED):
            r = s.reader()
            uin = int(r.pstr8())
            r.u16()                      # уровень предупреждений
            tlvs = r.tlvs(r.u16())
            raw = tlvs.get(C.UI_TLV_STATUS) or b"\x00\x00\x00\x00"
            self.online_uins.append(uin)
            self.statuses[uin] = struct.unpack(">I", raw)[0]
            self.capabilities[uin] = tlvs.get(C.UI_TLV_CAPABILITIES) or b""
            bart = tlvs.get(C.UI_TLV_BART)
            if bart and len(bart) >= 4:
                # тип приметы, флаги, длина, дальше сам хеш
                kind, flags, size = struct.unpack(">HBB", bart[:4])
                if kind == C.BART_ICON:
                    self.icon_hashes[uin] = bart[4:4 + size]
        elif (s.family, s.subtype) == (C.BUDDY, C.BUDDY_DEPARTED):
            self.offline_uins.append(int(s.reader().pstr8()))
        elif (s.family, s.subtype) == (C.ICBM, C.ICBM_ACK):
            self.acks.append(s.data[:8])
        elif (s.family, s.subtype) == (C.ICBM, C.ICBM_CLIENT_EVENT):
            r = s.reader()
            r.read(8)
            r.u16()
            uin = int(r.pstr8())
            self.typing.append((uin, r.u16() == 0x0002))
        elif s.subtype == 0x0001 and s.family in (C.OSERVICE, C.ICQ):
            self.errors.append((s.family, struct.unpack(">H", s.data[:2])[0]))
        elif (s.family, s.subtype) == (C.ICBM, C.ICBM_INCOMING):
            sender, text, ack = self._parse_incoming(s)
            self.received.append((sender, text))
            if ack is not None and self.send_acks:
                self.to_ack.append(ack)

    def _parse_incoming(self, s: Snac) -> tuple[int, str, bytes | None]:
        """Разбирает входящее сообщение так же, как это делает Jimm."""
        r = s.reader()
        cookie = r.read(8)
        channel = r.u16()
        sender_raw = r.pstr8()
        sender = int(sender_raw)
        r.u16()                       # уровень предупреждений
        r.tlvs(r.u16())               # TLV блока отправителя
        tlvs = r.tlvs()
        self.channels.append(channel)

        if channel == 1:
            return sender, parse_message_fragments(tlvs.get(0x0002) or b""), None

        # Канал 2: те же проверки и смещения, что в ActionListener.java
        msg = tlvs.get(0x0005)
        assert msg is not None and len(msg) >= 10, "нет блока расширенного сообщения"
        mr = Reader(msg)
        assert mr.u16() == 0x0000, "ждём обычное сообщение, а не ответ"
        mr.read(8)                    # тот же cookie
        mr.read(16)                   # признак возможности
        block = None
        while mr.left >= 4:
            tlv_type = mr.u16()
            value = mr.pstr16()
            if tlv_type == 0x2711:
                block = value
                break
        assert block is not None, "нет TLV 0x2711 с данными сообщения"
        assert len(block) >= 53, f"блок {len(block)} байт, Jimm ждёт минимум 53"

        msg_type = struct.unpack_from("<H", block, 45)[0]
        assert msg_type in (0x0001, 0x0004), \
            f"тип сообщения {msg_type:#06x} Jimm не покажет"
        text_len = struct.unpack_from("<H", block, 51)[0]
        assert len(block) >= 53 + text_len + 8, "блок обрывается на тексте"
        raw = block[53:53 + text_len]

        tail = 53 + text_len + 8
        encoding = "cp1251"
        if len(block) >= tail + 4:
            guid_len = struct.unpack_from("<I", block, tail)[0]
            if guid_len == 38 and block[tail + 4:tail + 4 + guid_len] == \
                    b"{0946134E-4C7F-11D1-8222-444553540000}":
                encoding = "utf-8"

        ack = (cookie + struct.pack(">H", channel) + pstr8(sender_raw)
               + struct.pack(">H", 0x0003) + block[:51]
               + struct.pack("<H", 1) + b"\x00")

        if msg_type == 0x0004:
            # URL-сообщение: подпись и ссылка разделены байтом 0xFE — так их
            # делит и настоящий клиент, показывая ссылку отдельной строкой.
            head, sep, tail_url = raw.partition(b"\xfe")
            self.urls.append((sender, tail_url.decode(encoding, "replace") if sep else ""))
            return sender, head.decode(encoding, "replace"), ack

        return sender, raw.decode(encoding, "replace"), ack

    async def flush_acks(self) -> None:
        """Отправляет накопленные подтверждения — как Jimm после разбора."""
        while self.to_ack:
            await self.send_snac(C.ICBM, C.ICBM_CLIENT_ACK, self.to_ack.pop(0))

    # --- сценарии входа -------------------------------------------------

    async def login_xor(self) -> bytes:
        await self.send_flap(1, struct.pack(">I", 1)
                             + tlv(C.TLV_SCREENNAME, self.uin.encode())
                             + tlv(C.TLV_ROASTED_PASS, roast_password(self.password.encode()))
                             + tlv(C.TLV_CLIENT_ID_STRING, b"Jimm 0.7.0"))
        channel, payload = await self.recv_flap()
        assert channel == 4, f"ожидали канал 4, пришёл {channel}"
        tlvs = Reader(payload).tlvs()
        assert tlvs.get(C.TLV_ERROR_CODE) is None, "сервер отказал в авторизации"
        return tlvs.get(C.TLV_AUTH_COOKIE)

    async def login_md5(self) -> bytes:
        await self.send_flap(1, struct.pack(">I", 1))
        await self.send_snac(C.AUTH, C.AUTH_MD5_KEY_REQ,
                             tlv(C.TLV_SCREENNAME, self.uin.encode()))
        key = Reader((await self.expect(C.AUTH, C.AUTH_MD5_KEY_REPLY)).data).pstr16()
        digest = hashlib.md5(key + hashlib.md5(self.password.encode()).digest()
                             + C.MD5_SALT).digest()
        await self.send_snac(C.AUTH, C.AUTH_LOGIN_REQ,
                             tlv(C.TLV_SCREENNAME, self.uin.encode())
                             + tlv(C.TLV_MD5_HASH, digest)
                             + tlv(C.TLV_CLIENT_ID_STRING, b"Jimm 0.7.0"))
        reply = await self.expect(C.AUTH, C.AUTH_LOGIN_REPLY)
        tlvs = Reader(reply.data).tlvs()
        assert tlvs.get(C.TLV_ERROR_CODE) is None, "сервер отказал в авторизации"
        # Jimm ждёт вдогонку кадр канала 4 и только тогда идёт на BOS
        channel, _ = await self.recv_flap()
        assert channel == 4, f"после SNAC 17/03 ожидали канал 4, пришёл {channel}"
        return tlvs.get(C.TLV_AUTH_COOKIE)

    async def login_md5_jimm(self) -> bytes:
        """Схема Jimm 0.7: md5(ключ + пароль + соль AIM), без хэширования пароля."""
        await self.send_flap(1, struct.pack(">I", 1))
        await self.send_snac(C.AUTH, C.AUTH_MD5_KEY_REQ,
                             tlv(C.TLV_SCREENNAME, self.uin.encode()))
        key = Reader((await self.expect(C.AUTH, C.AUTH_MD5_KEY_REPLY)).data).pstr16()
        digest = hashlib.md5(key + self.password.encode() + C.MD5_SALT).digest()
        await self.send_snac(C.AUTH, C.AUTH_LOGIN_REQ,
                             tlv(C.TLV_SCREENNAME, self.uin.encode())
                             + tlv(C.TLV_MD5_HASH, digest))
        reply = await self.expect(C.AUTH, C.AUTH_LOGIN_REPLY)
        tlvs = Reader(reply.data).tlvs()
        assert tlvs.get(C.TLV_ERROR_CODE) is None, "сервер отказал в авторизации"
        # Jimm ждёт вдогонку кадр канала 4 и только тогда идёт на BOS
        channel, _ = await self.recv_flap()
        assert channel == 4, f"после SNAC 17/03 ожидали канал 4, пришёл {channel}"
        return tlvs.get(C.TLV_AUTH_COOKIE)

    async def bos(self, cookie: bytes, encoding: str = "cp1251",
                  request_offline: bool = True) -> None:
        """Вход на BOS по cookie и вся цепочка запросов, как у Jimm.

        В конце, как и настоящий клиент, спрашивает офлайн-сообщения —
        request_offline=False оставляет этот шаг вызывающему.
        """
        self.writer.close()
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        await self.recv_flap()
        await self.send_flap(1, struct.pack(">I", 1) + tlv(C.TLV_AUTH_COOKIE, cookie))
        await self.expect(C.OSERVICE, C.SRV_READY)

        await self.send_snac(C.OSERVICE, C.CLI_VERSIONS,
                             b"".join(struct.pack(">HH", f, v) for f, v in C.FAMILY_VERSIONS.items()))
        await self.expect(C.OSERVICE, C.SRV_VERSIONS)

        await self.send_snac(C.OSERVICE, C.RATE_REQ)
        await self.expect(C.OSERVICE, C.RATE_RESP)
        await self.send_snac(C.OSERVICE, C.RATE_ACK, struct.pack(">H", 1))

        await self.send_snac(C.OSERVICE, C.SELF_INFO_REQ)
        await self.expect(C.OSERVICE, C.SELF_INFO)

        await self.send_snac(C.LOCATE, C.LOCATE_RIGHTS_REQ)
        await self.expect(C.LOCATE, C.LOCATE_RIGHTS)
        await self.send_snac(C.BUDDY, C.BUDDY_RIGHTS_REQ)
        await self.expect(C.BUDDY, C.BUDDY_RIGHTS)
        await self.send_snac(C.ICBM, C.ICBM_PARAM_REQ)
        await self.expect(C.ICBM, C.ICBM_PARAM_INFO)
        await self.send_snac(C.PD, C.PD_RIGHTS_REQ)
        await self.expect(C.PD, C.PD_RIGHTS)

        await self.send_snac(C.SSI, C.SSI_RIGHTS_REQ)
        await self.expect(C.SSI, C.SSI_RIGHTS)
        await self.send_snac(C.SSI, C.SSI_LIST_REQ)
        await self.read_ssi(encoding)
        await self.send_snac(C.SSI, C.SSI_ACTIVATE)

        await self.send_snac(C.OSERVICE, C.SET_STATUS, tlv(0x0006, b"\x00\x00\x00\x00"))
        await self.send_snac(C.OSERVICE, C.CLI_READY,
                             b"".join(struct.pack(">HHHH", f, v, 0x0110, 0x0629)
                                      for f, v in C.FAMILY_VERSIONS.items()))
        if request_offline:
            await self.offline_messages()

    async def read_ssi(self, encoding: str) -> None:
        """Читает контакт-лист так же, как Jimm.

        Клиент считает список принятым по ненулевой метке времени, поэтому
        приём прекращается ровно на той части, где она пришла.
        """
        self.ssi_count = 0
        while True:
            s = await self.expect(C.SSI, C.SSI_LIST)
            r = s.reader()
            r.u8()                       # версия списка
            count = r.u16()
            self.ssi_count += count
            for _ in range(count):
                name = r.pstr16()
                group_id, item_id, item_type = r.u16(), r.u16(), r.u16()
                extra = Reader(r.pstr16()).tlvs()
                if item_type == C.SSI_TYPE_GROUP and group_id:
                    self.groups[group_id] = name.decode(encoding, "replace")
                elif item_type in (C.SSI_TYPE_DENY, C.SSI_TYPE_PERMIT,
                                   C.SSI_TYPE_IGNORE):
                    # По этим элементам клиент рисует пометки списков видимости.
                    self.privacy.append((int(name), item_type))
                elif item_type == C.SSI_TYPE_BUDDY:
                    uin = int(name)
                    alias = (extra.get(C.SSI_TLV_ALIAS) or b"").decode(encoding, "replace")
                    self.contacts.append((uin, group_id, item_id, item_type, name))
                    self.aliases[uin] = alias
            stamp = r.u32()              # версия списка
            if stamp:
                # Ненулевая метка = список окончен, дальше клиент не слушает.
                self.ssi_stamp = stamp
                break
            assert s.flags & 0x0001, "часть без метки должна быть помечена как неполная"

    async def offline_messages(self) -> int:
        """Запрашивает офлайн-сообщения так же, как это делает Jimm.

        Записи 0x0041 разбираются по тем же смещениям, что в ActionListener:
        uin, дата, тип, длина, текст с завершающим нулём — и попадают в
        received. На 0x0042 уходит подтверждение 0x003E, как у клиента.
        """
        body = struct.pack("<HIHH", 8, int(self.uin), C.ICQ_OFFLINE_REQ, 2)
        await self.send_snac(C.ICQ, C.ICQ_TO_SERVER, tlv(0x0001, body))
        while True:
            channel, payload = await self.recv_flap()
            if channel != 2:
                continue
            s = Snac.parse(payload)
            if (s.family, s.subtype) != (C.ICQ, C.ICQ_FROM_SERVER):
                self._absorb(s)
                continue
            # Jimm отвергает кадры короче 24 байт
            assert len(payload) >= 24, f"кадр {len(payload)} байт, Jimm ждёт минимум 24"
            value = Reader(s.data).tlvs().get(0x0001)
            r = Reader(value)
            r.u16le()
            r.u32le()
            resp = r.u16le()
            if resp == C.ICQ_OFFLINE_MSG:
                r.u16le()                                   # номер запроса
                buf = r.read(r.left)
                assert len(buf) > 13, "запись офлайн-сообщения слишком коротка"
                sender = struct.unpack_from("<I", buf, 0)[0]
                year = struct.unpack_from("<H", buf, 4)[0]
                month, day, hour, minute = buf[6], buf[7], buf[8], buf[9]
                msg_type = struct.unpack_from("<H", buf, 10)[0]
                text_len = struct.unpack_from("<H", buf, 12)[0]
                assert len(buf) == 14 + text_len, \
                    f"запись {len(buf)} байт при длине текста {text_len} — Jimm бросит исключение"
                assert msg_type in (0x0001, 0x0004), f"тип {msg_type:#06x} Jimm не покажет"
                raw = buf[14:14 + text_len].rstrip(b"\x00")
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = raw.decode("cp1251", "replace")
                self.offline.append((sender, (year, month, day, hour, minute), text))
                self.received.append((sender, text))
                continue
            if resp == C.ICQ_OFFLINE_DONE:
                ack = struct.pack("<HIHH", 8, int(self.uin), C.ICQ_OFFLINE_DELETE, 2)
                await self.send_snac(C.ICQ, C.ICQ_TO_SERVER, tlv(0x0001, ack))
            return resp

    async def ping(self) -> None:
        """Keepalive — пустой кадр канала 5, как шлёт Jimm раз в две минуты."""
        await self.send_flap(5, b"")

    async def send_typing(self, uin: int, active: bool) -> None:
        """Сообщает серверу, что владелец набирает сообщение."""
        await self.send_snac(C.ICBM, C.ICBM_CLIENT_EVENT,
                             bytes(8) + struct.pack(">H", 1)
                             + pstr8(str(uin).encode()) 
                             + struct.pack(">H", 0x0002 if active else 0x0000))

    async def search(self, nick: str, encoding: str = "cp1251") -> list[dict]:
        """Ищет контакты так же, как SearchAction, и разбирает выдачу."""
        raw = nick.encode(encoding)
        query = (struct.pack("<H", C.ICQ_REQ_SEARCH)
                 + struct.pack(">H", C.SEARCH_FIELD_NICK)
                 + struct.pack("<H", len(raw) + 3) + struct.pack("<H", len(raw) + 1)
                 + raw + b"\x00")
        body = (struct.pack("<H", 2 + len(query)) + struct.pack("<I", int(self.uin))
                + struct.pack("<H", C.ICQ_META_REQ_TYPE) + struct.pack("<H", 7) + query)
        await self.send_snac(C.ICQ, C.ICQ_TO_SERVER, tlv(0x0001, body))

        results: list[dict] = []
        while True:
            s = await self.recv_snac()
            if (s.family, s.subtype) != (C.ICQ, C.ICQ_FROM_SERVER):
                self._absorb(s)
                continue
            r = Reader(Reader(s.data).tlvs().get(0x0001))
            r.u16le(); r.u32le(); r.u16le(); r.u16le()      # длина, UIN, тип, номер
            kind = r.u16le()
            ok = r.u8()
            if ok != C.ICQ_INFO_OK:
                return results                              # ничего не нашлось
            r.u16le()                                       # длина блока
            item = {"uin": r.u32le()}
            for field in ("nick", "first", "last", "email"):
                item[field] = r.read(r.u16le()).decode(encoding, "replace")
            r.u8(); r.u16le(); r.u8(); r.u16le()            # авторизация, статус, пол, возраст
            results.append(item)
            if kind == C.ICQ_SEARCH_LAST:
                return results

    async def request_service(self, family: int) -> None:
        """Просит адрес дополнительного сервиса — так Jimm ищет аватары."""
        await self.send_snac(C.OSERVICE, C.SERVICE_REQUEST, struct.pack(">H", family))

    async def request_avatar(self, uin: int, timeout: float = 5.0) -> dict:
        """Забирает аватарку так же, как настоящий Jimm.

        Сначала спрашивает адрес службы, потом открывает к ней отдельное
        соединение по выданному cookie и уже там просит картинку.
        """
        await self.request_service(C.SSBI)
        redirect = await self.expect(C.OSERVICE, C.SERVICE_REDIRECT, timeout)
        tlvs = redirect.reader().tlvs(3)
        host = (tlvs.get(C.TLV_BOS_ADDRESS) or b"").decode()
        cookie = tlvs.get(C.TLV_AUTH_COOKIE) or b""
        port = int(host.partition(":")[2] or 5190)

        main_reader, main_writer = self.reader, self.writer
        self.reader, self.writer = await asyncio.open_connection(self.host, port)
        try:
            await self.recv_flap()
            await self.send_flap(1, struct.pack(">I", 1) + tlv(C.TLV_AUTH_COOKIE, cookie))
            await self.expect(C.OSERVICE, C.SRV_READY, timeout)
            await self.send_snac(C.OSERVICE, C.CLI_READY, b"")

            digest = self.icon_hashes.get(uin, b"\x00" * 16)
            body = (pstr8(str(uin).encode()) + b"\x01" + struct.pack(">H", 1)
                    + b"\x01" + bytes([len(digest)]) + digest)
            await self.send_snac(C.SSBI, C.SSBI_ICQ_REQ, body)
            reply = await self.expect(C.SSBI, C.SSBI_ICQ_REPLY, timeout)
        finally:
            self.writer.close()
            self.reader, self.writer = main_reader, main_writer

        r = reply.reader()
        got_uin = int(r.pstr8())
        # Клиент отсчитывает начало картинки по длине блока примет: две
        # штуки подряд и разделительный байт между ними.
        r.read(2 + 1 + 1 + 16 + 1 + 2 + 1 + 1 + 16)
        length = r.u16()
        return {"uin": got_uin, "image": r.read(length), "hash": digest}

    async def set_status(self, status: int) -> None:
        """Ставит статус так же, как это делает Jimm."""
        await self.send_snac(C.OSERVICE, C.SET_STATUS,
                             tlv(C.UI_TLV_STATUS, struct.pack(">I", status)))

    async def check_roster(self) -> str:
        """Спрашивает список с версией, как Jimm при входе.

        Клиент ждёт здесь именно полный список: короткий ответ «не менялся»
        (13/0F) он засчитывает флагом, но дальше по входу не идёт и остаётся
        на «checking roster».
        """
        await self.send_snac(C.SSI, C.SSI_LIST_REQ_IF_CHANGED,
                             struct.pack(">IH", self.ssi_stamp, self.ssi_count))
        while True:
            s = await self.recv_snac()
            if (s.family, s.subtype) == (C.SSI, C.SSI_LIST_UNCHANGED):
                return "unchanged"
            if (s.family, s.subtype) == (C.SSI, C.SSI_LIST):
                while s.flags & 0x0001:            # дочитываем продолжение
                    s = await self.expect(C.SSI, C.SSI_LIST)
                return "full"
            self._absorb(s)

    async def request_info(self, target: int, encoding: str = "cp1251") -> dict:
        """Запрашивает карточку контакта и разбирает ответ, как RequestInfoAction.

        Клиент показывает карточку, лишь собрав не меньше пяти пакетов, поэтому
        считаем их и проверяем, что каждый блок разбирается без остатка.
        """
        body = (struct.pack("<H", 12) + struct.pack("<I", int(self.uin))
                + struct.pack("<H", C.ICQ_META_REQ_TYPE) + struct.pack("<H", 3)
                + struct.pack("<H", C.ICQ_REQ_USER_INFO) + struct.pack("<I", target))
        await self.send_snac(C.ICQ, C.ICQ_TO_SERVER, tlv(0x0001, body))

        info: dict = {"packets": 0}
        while True:
            s = await self.recv_snac()
            if (s.family, s.subtype) != (C.ICQ, C.ICQ_FROM_SERVER):
                self._absorb(s)
                continue
            value = Reader(s.data).tlvs().get(0x0001)
            r = Reader(value)
            r.u16le()                      # длина
            r.u32le()                      # UIN
            r.u16le()                      # тип ответа
            r.u16le()                      # номер запроса
            part = r.u16le()
            ok = r.u8()

            def asciiz() -> str:
                return r.read(r.u16le()).decode(encoding, "replace")

            if part == C.ICQ_INFO_BASIC:
                for field in ("nick", "first", "last", "email", "city",
                              "state", "phone", "fax", "address", "cell"):
                    info[field] = asciiz()
            elif part == C.ICQ_INFO_MORE:
                info["age"] = r.u16le()
                r.u8()                     # пол
                info["homepage"] = asciiz()
                year = r.u16le()
                month, day = r.u8(), r.u8()
                # Клиент показывает дату, только если пришёл год
                info["bday"] = f"{day}.{month}.{year}" if year else ""
            elif part == C.ICQ_INFO_WORK:
                for _ in range(5):         # город, область, телефон, факс, адрес
                    asciiz()
                asciiz()                   # индекс
                r.u16le()                  # код страны
                info["company"] = asciiz()
                info["department"] = asciiz()
                info["position"] = asciiz()
            elif part == C.ICQ_INFO_ABOUT:
                info["about"] = asciiz()
            elif part == C.ICQ_INFO_INTERESTS:
                for _ in range(r.u8()):
                    r.u16le()
                    asciiz()
            elif part == C.ICQ_INFO_END:
                info["found"] = ok == C.ICQ_INFO_OK
                info["packets"] += 1
                return info

            assert r.left == 0, f"в блоке 0x{part:04X} осталось {r.left} лишних байт"
            info["packets"] += 1

    async def say(self, uin: int, text: str) -> bytes:
        """Отправляет сообщение так же, как Jimm: cookie = номер сообщения и 1."""
        self.next_msg_id += 1
        cookie = struct.pack(">II", self.next_msg_id, 1)
        await self.send_snac(C.ICBM, C.ICBM_SEND,
                             cookie + struct.pack(">H", 1)
                             + pstr8(str(uin).encode())
                             + tlv(0x0002, message_fragments(text)) + tlv(0x0003, b""))
        return cookie

    async def drain_for(self, seconds: float) -> None:
        try:
            while True:
                self._absorb(await self.recv_snac(seconds))
                await self.flush_acks()
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            pass

    async def close(self) -> None:
        if self.writer:
            self.writer.close()
