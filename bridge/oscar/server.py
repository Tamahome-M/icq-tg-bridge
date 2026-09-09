"""Сервер протокола OSCAR (ICQ) — то, к чему подключается Jimm на телефоне.

Реализовано ровно столько, сколько нужно старому мобильному клиенту:
авторизация (XOR и MD5), выдача контакт-листа с сервера, обмен текстовыми
сообщениями и уведомления о том, что контакты в сети.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import logging
import os
import struct
import time
from typing import Awaitable, Callable

from ..access import AccessControl
from ..db import Contact, Storage
from . import blocks
from . import const as C
from .proto import (Reader, Snac, flap, pstr8, pstr16, roast_password, snac,
                    tlv, tlv_u16, tlv_u32)

log = logging.getLogger("oscar")

MAX_SNAC_PAYLOAD = 3800          # с запасом под скромные буферы телефона
BUDDY_BURST = 20                 # по столько уведомлений об онлайне за раз
SENDER_IDLE_POLL = 10            # как часто отправитель просыпается сам, секунды
SENT_MEMORY = 200                # столько отправленных помним ради галочек
AWAITING_LIMIT = 500             # потолок неподтверждённых сообщений в памяти
ACK_GRACE = 600                  # столько ждём подтверждения, потом шлём заново
STALE_SECONDS = 60               # с какого возраста сообщению ставится метка времени

# Пары «семейство/подтип» для ответа о лимитах скорости.
RATE_PAIRS = [
    (C.OSERVICE, s) for s in (0x0002, 0x0003, 0x0006, 0x0007, 0x0008, 0x000E,
                              0x000F, 0x0017, 0x0018, 0x001E)
] + [
    (C.LOCATE, 0x0002), (C.LOCATE, 0x0003), (C.LOCATE, 0x0015),
    (C.BUDDY, 0x0002), (C.BUDDY, 0x0003), (C.BUDDY, 0x000B), (C.BUDDY, 0x000C),
    (C.ICBM, 0x0004), (C.ICBM, 0x0005), (C.ICBM, 0x0006), (C.ICBM, 0x0007),
    (C.ICBM, 0x000C), (C.ICBM, 0x0014),
    (C.PD, 0x0002), (C.PD, 0x0003),
    (C.SSI, 0x0002), (C.SSI, 0x0003), (C.SSI, 0x0004), (C.SSI, 0x0006),
    (C.SSI, 0x0007), (C.SSI, 0x0008), (C.SSI, 0x0009), (C.SSI, 0x000A),
    (C.ICQ, 0x0002), (C.ICQ, 0x0003),
    (C.SSBI, C.SSBI_ICQ_REQ), (C.SSBI, C.SSBI_ICQ_REPLY),
]


class Session:
    """Одно TCP-соединение от клиента."""

    def __init__(self, server: "OscarServer", reader: asyncio.StreamReader,
                 writer: asyncio.StreamWriter):
        self.server = server
        self.reader = reader
        self.writer = writer
        self.seq = int.from_bytes(os.urandom(2), "big") & 0x7FFF
        # Соединение, открытое только ради аватарок: сообщений через него нет.
        self.service_only = False
        self.authorized = False
        self.ready = False
        self.closed = False
        self.peer = writer.get_extra_info("peername")
        self.signon_time = int(time.time())
        self.item_to_uin: dict[int, int] = {}
        self.auth_key = b""
        self.last_seen = time.time()
        self.pings_seen = 0
        self._lock = asyncio.Lock()

    # --- отправка -------------------------------------------------------

    async def send_flap(self, channel: int, payload: bytes) -> bool:
        """False означает, что кадр до телефона не ушёл."""
        if self.closed:
            return False
        async with self._lock:
            self.seq = (self.seq + 1) & 0xFFFF
            try:
                self.writer.write(flap(channel, self.seq, payload))
                await self.writer.drain()
            except (ConnectionError, OSError) as exc:
                log.warning("обрыв при отправке телефону: %s", exc)
                self.closed = True
                return False
        return True

    async def send_snac(self, family: int, subtype: int, data: bytes = b"",
                        flags: int = 0, request_id: int = 0) -> bool:
        return await self.send_flap(2, snac(family, subtype, data, flags, request_id))

    async def send_error(self, family: int, code: int, request_id: int) -> None:
        await self.send_snac(family, 0x0001, struct.pack(">H", code), request_id=request_id)

    # --- цикл чтения ----------------------------------------------------

    async def run(self) -> None:
        try:
            await self.send_flap(1, struct.pack(">I", 1))   # приветствие сервера
            while not self.closed:
                header = await self.reader.readexactly(6)
                if header[0] != 0x2A:
                    log.warning("мусор вместо FLAP от %s", self.peer)
                    break
                channel = header[1]
                length = struct.unpack(">H", header[4:6])[0]
                payload = await self.reader.readexactly(length) if length else b""
                await self.handle_flap(channel, payload)
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        except Exception:
            log.exception("сбой в сессии %s", self.peer)
        finally:
            await self.close()

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.server.session_gone(self)
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except Exception:
            pass

    async def handle_flap(self, channel: int, payload: bytes) -> None:
        log.debug("<- FLAP канал %d, %d байт: %s", channel, len(payload), payload[:48].hex())
        self.last_seen = time.time()
        if channel == 5:
            self.pings_seen += 1
        if channel == 1:
            await self.handle_signon(payload)
        elif channel == 2:
            await self.handle_snac(Snac.parse(payload))
        elif channel == 4:
            await self.close()
        # канал 5 — keepalive, отвечать не нужно

    # --- авторизация ----------------------------------------------------

    async def handle_signon(self, payload: bytes) -> None:
        r = Reader(payload)
        if r.left >= 4:
            r.u32()          # версия протокола FLAP
        tlvs = r.tlvs()

        cookie = tlvs.get(C.TLV_AUTH_COOKIE)
        if cookie is not None:
            kind = self.server.consume_cookie(cookie)
            if kind == "bart":
                # Отдельное соединение за аватарками: основное трогать нельзя,
                # иначе телефон останется без сообщений.
                self.service_only = True
                self.authorized = True
                log.debug("подключение за аватарками с %s", self.peer)
                await self.send_snac(C.OSERVICE, C.SRV_READY,
                                     struct.pack(">H", C.SSBI))
            elif kind:
                await self.start_bos()
            else:
                log.warning("неизвестный cookie от %s", self.peer)
                await self.send_flap(4, tlv(C.TLV_ERROR_CODE,
                                            struct.pack(">H", C.AUTH_ERR_BAD_PASSWORD)))
                await self.close()
            return

        name = tlvs.get(C.TLV_SCREENNAME)
        roasted = tlvs.get(C.TLV_ROASTED_PASS)
        if name is not None and roasted is not None:
            password = roast_password(roasted).decode("latin-1")
            client = (tlvs.get(C.TLV_CLIENT_ID_STRING) or b"?").decode("latin-1", "replace")
            log.info("вход по XOR, клиент %r", client)
            await self.finish_auth(name.decode("latin-1"),
                                   self.check_password(password), method="XOR")

    def check_password(self, given: str) -> bool:
        """Сверяет пароль, присланный XOR-способом."""
        expected = self.server.password
        if given == expected:
            return True
        log.warning("пароль не совпал: прислано %d символов, ожидалось %d",
                    len(given), len(expected))
        if given.lower() == expected.lower():
            log.warning("пароли различаются только регистром — проверьте раскладку на телефоне")
        return False

    def md5_variants(self) -> dict[str, bytes]:
        """Схемы подсчёта хэша, встречающиеся у клиентов ICQ тех лет."""
        pw = self.server.password.encode("latin-1")
        inner = hashlib.md5(pw).digest()
        keys = [("", self.auth_key)]
        spare = self.server.last_auth_key
        if spare and spare != self.auth_key:
            keys.append((" [ключ с прошлого соединения]", spare))

        out: dict[str, bytes] = {}
        for tag, key in keys:
            out["key+md5(pw)+соль" + tag] = hashlib.md5(key + inner + C.MD5_SALT).digest()
            out["key+md5(pw)" + tag] = hashlib.md5(key + inner).digest()
            out["md5(pw)+key+соль" + tag] = hashlib.md5(inner + key + C.MD5_SALT).digest()
            out["md5(pw)+key" + tag] = hashlib.md5(inner + key).digest()
            out["key+pw+соль" + tag] = hashlib.md5(key + pw + C.MD5_SALT).digest()
            out["key+pw" + tag] = hashlib.md5(key + pw).digest()
            out["pw+key" + tag] = hashlib.md5(pw + key).digest()
        out["md5(pw)"] = inner
        out["md5(pw+соль)"] = hashlib.md5(pw + C.MD5_SALT).digest()
        return out

    def check_md5(self, given: bytes) -> bool:
        """Сверяет MD5-хэш, принимая любую из известных схем подсчёта."""
        for name, expected in self.md5_variants().items():
            if given == expected:
                log.info("MD5 сошёлся, схема: %s", name)
                return True
        log.warning("MD5-хэш не совпал ни с одной из %d схем", len(self.md5_variants()))
        log.warning("  прислан клиентом : %s", given.hex())
        log.warning("  ключ этой сессии : %s", self.auth_key.decode() or "(ключ не запрашивался!)")
        for name, expected in self.md5_variants().items():
            log.debug("  %-32s %s", name, expected.hex())
        return False

    async def finish_auth(self, screenname: str, password_ok: bool,
                          method: str = "?", reply_to: Snac | None = None) -> None:
        """Ответ на попытку входа: адрес BOS и cookie либо ошибка.

        Клиенту, вошедшему через FLAP-канал 1, ответ уходит тем же каналом 4;
        клиенту, приславшему SNAC 17/02, — как SNAC 17/03. Jimm использует
        второй способ и первого варианта не ждёт.
        """
        host = self.peer[0] if self.peer else ""
        if not password_ok or screenname.strip() != self.server.uin:
            log.warning("отказ в авторизации для %r (%s) с %s — %s", screenname, method, self.peer,
                        "неверный UIN" if screenname.strip() != self.server.uin else "неверный пароль")
            self.server.access.note_failure(host)
            body = (tlv(C.TLV_SCREENNAME, screenname.encode("latin-1", "replace"))
                    + tlv_u16(C.TLV_ERROR_CODE, C.AUTH_ERR_BAD_PASSWORD)
                    + tlv(C.TLV_ERROR_URL, b""))
        else:
            cookie = self.server.new_cookie()
            body = (tlv(C.TLV_SCREENNAME, screenname.encode("latin-1", "replace"))
                    + tlv(C.TLV_BOS_ADDRESS, self.server.bos_address(self.writer).encode())
                    + tlv(C.TLV_AUTH_COOKIE, cookie))
            log.info("авторизация пройдена: %s (%s) с %s", screenname, method, self.peer)
            self.server.access.note_success(host)
        if reply_to is not None:
            log.debug("-> SNAC 17/03: %s", body.hex())
            await self.send_snac(C.AUTH, C.AUTH_LOGIN_REPLY, body,
                                 request_id=reply_to.request_id)
        # Кадр канала 4 нужен обоим способам входа: Jimm считает авторизацию
        # завершённой и идёт на BOS только после него — из SNAC 17/03 он лишь
        # запоминает адрес и cookie, но переподключения не начинает.
        log.debug("-> FLAP канал 4: %s", body.hex())
        await self.send_flap(4, body)
        await asyncio.sleep(1.0)      # медленному GPRS-клиенту нужно время дочитать
        await self.close()

    async def handle_auth_snac(self, s: Snac) -> None:
        if s.subtype == C.AUTH_MD5_KEY_REQ:
            self.auth_key = ("%d" % int.from_bytes(os.urandom(4), "big")).encode()
            self.server.last_auth_key = self.auth_key
            log.info("запрошен ключ для MD5-входа, выдан %s", self.auth_key.decode())
            await self.send_snac(C.AUTH, C.AUTH_MD5_KEY_REPLY,
                                 pstr16(self.auth_key), request_id=s.request_id)
        elif s.subtype == C.AUTH_LOGIN_REQ:
            tlvs = s.reader().tlvs()
            screenname = (tlvs.get(C.TLV_SCREENNAME) or b"").decode("latin-1")
            client = (tlvs.get(C.TLV_CLIENT_ID_STRING) or b"?").decode("latin-1", "replace")

            roasted = tlvs.get(C.TLV_ROASTED_PASS)
            if roasted is not None:
                log.info("вход по XOR внутри SNAC, клиент %r", client)
                password = roast_password(roasted).decode("latin-1")
                await self.finish_auth(screenname, self.check_password(password),
                                       method="XOR", reply_to=s)
                return

            given = tlvs.get(C.TLV_MD5_HASH) or b""
            log.info("вход по MD5, клиент %r", client)
            await self.finish_auth(screenname, self.check_md5(given), method="MD5", reply_to=s)

    # --- сессия BOS -----------------------------------------------------

    async def watch_idle(self) -> None:
        """На GPRS оборванное соединение может «висеть» открытым, и сообщения
        уйдут в никуда. Jimm шлёт keepalive каждые две минуты — если они
        прекратились, считаем телефон отключившимся."""
        timeout = self.server.idle_timeout
        if timeout <= 0:
            return
        while not self.closed:
            await asyncio.sleep(30)
            if self.pings_seen and time.time() - self.last_seen > timeout:
                log.warning("от телефона нет вестей %.0f с — закрываю сессию",
                            time.time() - self.last_seen)
                await self.close()
                return

    async def start_bos(self) -> None:
        self.authorized = True
        self.server.session_arrived(self)
        asyncio.create_task(self.watch_idle())
        families = b"".join(struct.pack(">H", f) for f in C.FAMILY_VERSIONS)
        await self.send_snac(C.OSERVICE, C.SRV_READY, families)

    async def handle_snac(self, s: Snac) -> None:
        log.debug("<- %s", s)
        if s.family == C.AUTH:
            await self.handle_auth_snac(s)
            return
        if not self.authorized:
            return

        handler = {
            (C.OSERVICE, C.CLI_VERSIONS): self.on_versions,
            (C.OSERVICE, C.RATE_REQ): self.on_rate_req,
            (C.OSERVICE, C.SELF_INFO_REQ): self.on_self_info,
            (C.OSERVICE, C.CLI_READY): self.on_client_ready,
            (C.OSERVICE, C.SET_STATUS): self.on_set_status,
            (C.LOCATE, C.LOCATE_RIGHTS_REQ): self.on_locate_rights,
            (C.BUDDY, C.BUDDY_RIGHTS_REQ): self.on_buddy_rights,
            (C.ICBM, C.ICBM_PARAM_REQ): self.on_icbm_params,
            (C.ICBM, C.ICBM_SEND): self.on_icbm_send,
            (C.ICBM, C.ICBM_CLIENT_ACK): self.on_icbm_client_ack,
            (C.ICBM, C.ICBM_CLIENT_EVENT): self.on_icbm_typing,
            (C.OSERVICE, C.SERVICE_REQUEST): self.on_service_request,
            (C.PD, C.PD_RIGHTS_REQ): self.on_pd_rights,
            (C.SSI, C.SSI_RIGHTS_REQ): self.on_ssi_rights,
            (C.SSI, C.SSI_LIST_REQ): self.on_ssi_list,
            (C.SSI, C.SSI_LIST_REQ_IF_CHANGED): self.on_ssi_list,
            (C.SSI, C.SSI_ADD): self.on_ssi_add,
            (C.SSI, C.SSI_UPDATE): self.on_ssi_edit,
            (C.SSI, C.SSI_DELETE): self.on_ssi_delete,
            (C.SSI, C.SSI_REMOVE_ME): self.on_ssi_remove_me,
            (C.ICQ, 0x0002): self.on_icq_meta,
            (C.SSBI, C.SSBI_ICQ_REQ): self.on_icon_request,
        }.get((s.family, s.subtype))

        if handler is None:
            log.debug("без обработчика: %s", s)
            return
        await handler(s)

    async def on_versions(self, s: Snac) -> None:
        body = b"".join(struct.pack(">HH", f, v) for f, v in C.FAMILY_VERSIONS.items())
        await self.send_snac(C.OSERVICE, C.SRV_VERSIONS, body, request_id=s.request_id)

    async def on_rate_req(self, s: Snac) -> None:
        cls = struct.pack(">H", 1) + struct.pack(
            ">IIIIIIIB", 80, 2500, 2000, 1500, 800, 3000, 6000, 0)
        pairs = b"".join(struct.pack(">HH", f, st) for f, st in RATE_PAIRS)
        body = (struct.pack(">H", 1) + cls
                + struct.pack(">HH", 1, len(RATE_PAIRS)) + pairs)
        await self.send_snac(C.OSERVICE, C.RATE_RESP, body, request_id=s.request_id)

    async def on_self_info(self, s: Snac) -> None:
        await self.send_snac(C.OSERVICE, C.SELF_INFO,
                             blocks.user_info(self.server.uin, signon_time=self.signon_time),
                             request_id=s.request_id)

    async def on_set_status(self, s: Snac) -> None:
        """Владелец сменил статус в Jimm — от него зависит, что доставлять."""
        raw = s.reader().tlvs().get(C.UI_TLV_STATUS)
        if raw is None or len(raw) < 4:
            return
        # Старшее слово — служебные флаги, статус лежит в младшем.
        status = struct.unpack(">I", raw[:4])[0] & 0xFFFF
        await self.server.owner_status_changed(status)

    async def on_locate_rights(self, s: Snac) -> None:
        body = tlv_u16(0x0001, 1024) + tlv_u16(0x0002, 16) + tlv_u16(0x0003, 10)
        await self.send_snac(C.LOCATE, C.LOCATE_RIGHTS, body, request_id=s.request_id)

    async def on_buddy_rights(self, s: Snac) -> None:
        body = tlv_u16(0x0001, 1000) + tlv_u16(0x0002, 1000) + tlv_u16(0x0003, 512)
        await self.send_snac(C.BUDDY, C.BUDDY_RIGHTS, body, request_id=s.request_id)

    async def on_icbm_params(self, s: Snac) -> None:
        body = struct.pack(">HIHHHI", 0, 0x0000000B, 8000, 999, 999, 0)
        await self.send_snac(C.ICBM, C.ICBM_PARAM_INFO, body, request_id=s.request_id)

    async def on_pd_rights(self, s: Snac) -> None:
        body = tlv_u16(0x0001, 200) + tlv_u16(0x0002, 200) + tlv_u16(0x0003, 200)
        await self.send_snac(C.PD, C.PD_RIGHTS, body, request_id=s.request_id)

    async def on_ssi_rights(self, s: Snac) -> None:
        limits = [0, 1000, 200, 200, 200, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        body = tlv(0x0004, b"".join(struct.pack(">H", n) for n in limits))
        await self.send_snac(C.SSI, C.SSI_RIGHTS, body, request_id=s.request_id)

    def build_ssi(self) -> list[bytes]:
        """Собирает контакт-лист: группы — папки Telegram, контакты — чаты."""
        contacts = self.server.roster()
        self.item_to_uin.clear()

        groups: dict[str, list[tuple[int, Contact]]] = {}
        next_item_id = 1
        for contact in contacts:
            item_id = next_item_id
            next_item_id += 1
            self.item_to_uin[item_id] = contact.uin
            groups.setdefault(contact.group_name, []).append((item_id, contact))

        enc = self.server.ssi_encoding
        items: list[bytes] = []
        group_ids: list[int] = []
        for group_index, (group_name, members) in enumerate(groups.items(), start=1):
            group_ids.append(group_index)
            items.append(blocks.ssi_group(group_name.encode(enc, "replace"),
                                          group_index, [i for i, _ in members]))
            for item_id, contact in members:
                # Длинные названия обрезаем: на маленьком экране они всё равно
                # не помещаются, а память телефона тратят.
                title = contact.title[:self.server.alias_max_chars]
                items.append(blocks.ssi_buddy(contact.uin, group_index, item_id,
                                              title.encode(enc, "replace")))
        items.insert(0, blocks.ssi_group(b"", 0, group_ids))
        return items

    async def on_ssi_list(self, s: Snac) -> None:
        items = self.build_ssi()
        stamp, count = self.server.ssi_version(items)

        # Ответить коротким «список не менялся» (SNAC 13/0F) нельзя: Jimm
        # ставит по нему только внутренний флаг, а переход к следующему шагу
        # входа у него написан внутри разбора полного списка (ConnectAction,
        # STATE_CLI_CHECKROSTER_SENT). Получив 13/0F, клиент зависает на
        # «checking roster», поэтому всегда отдаём список целиком.
        parts = 0
        for chunk, is_last in _chunked(items, MAX_SNAC_PAYLOAD):
            # Метку времени ставим только в последней части: по ненулевой метке
            # Jimm считает список принятым целиком и перестаёт ждать продолжение
            # (ConnectAction: if (timestamp != 0) srvReplyRosterRcvd = true).
            body = (b"\x00" + struct.pack(">H", len(chunk)) + b"".join(chunk)
                    + struct.pack(">I", stamp if is_last else 0))
            await self.send_snac(C.SSI, C.SSI_LIST, body,
                                 flags=0 if is_last else 0x0001,
                                 request_id=s.request_id)
            parts += 1
        log.info("контакт-лист отдан: %d элементов в %d частях, версия %d",
                 count, parts, stamp)

    async def on_ssi_edit(self, s: Snac) -> None:
        """Правки контакт-листа с телефона не сохраняем — список ведёт Telegram,
        но клиенту отвечаем «принято», иначе он показывает ошибку."""
        count = max(1, len(blocks.parse_ssi_items(s.data)))
        await self.send_snac(C.SSI, C.SSI_EDIT_ACK,
                             b"".join(struct.pack(">H", 0) for _ in range(count)),
                             request_id=s.request_id)

    async def on_ssi_add(self, s: Snac) -> None:
        """Добавление в списки видимости.

        «В невид. список» кладёт контакт в список запрета, «В видим. список» —
        в список разрешённых. Для моста это удобный способ заглушить чат:
        обычные контакты клиент сюда не добавляет.
        """
        for name, _group_id, _item_id, item_type, _extra in blocks.parse_ssi_items(s.data):
            target = name.decode("latin-1", "replace")
            if not target.isdigit():
                continue
            if item_type in (C.SSI_TYPE_DENY, C.SSI_TYPE_IGNORE):
                await self.server.on_privacy(int(target), muted=True)
            elif item_type == C.SSI_TYPE_PERMIT:
                await self.server.on_privacy(int(target), muted=False)
        await self.on_ssi_edit(s)

    async def on_ssi_delete(self, s: Snac) -> None:
        """«Удалить» в клиенте: чат убирается и в Telegram — у себя."""
        items = blocks.parse_ssi_items(s.data)
        for name, _group_id, _item_id, item_type, _extra in items:
            target = name.decode("latin-1", "replace")
            if not target.isdigit():
                continue
            if item_type == C.SSI_TYPE_BUDDY:
                await self.server.on_remove(int(target), revoke=False)
            elif item_type in (C.SSI_TYPE_DENY, C.SSI_TYPE_IGNORE):
                # Убрали из списка запрета — значит чат снова можно слышать.
                await self.server.on_privacy(int(target), muted=False)
        await self.send_snac(C.SSI, C.SSI_EDIT_ACK,
                             b"".join(struct.pack(">H", 0) for _ in range(max(1, len(items)))),
                             request_id=s.request_id)

    async def on_ssi_remove_me(self, s: Snac) -> None:
        """«Удалиться из его КЛ»: чат удаляется у обеих сторон."""
        r = s.reader()
        target = r.pstr8().decode("latin-1", "replace") if r.left else ""
        if target.isdigit():
            await self.server.on_remove(int(target), revoke=True)

    async def on_icq_meta(self, s: Snac) -> None:
        """Запросы семейства 0x15. Обязательно нужен ответ на запрос офлайн-сообщений:
        без него Jimm остаётся на «Reading messages» и отваливается по таймауту."""
        payload = s.reader().tlvs().get(0x0001)
        if not payload or len(payload) < 10:
            return
        r = Reader(payload)
        r.u16le()                     # длина блока
        uin = r.u32le()
        req_type = r.u16le()
        seq = r.u16le()

        if req_type == C.ICQ_META_REQ_TYPE:
            subtype = r.u16le() if r.left >= 2 else 0
            target = r.u32le() if r.left >= 4 else 0
            if subtype == C.ICQ_REQ_USER_INFO:
                await self.send_user_info(uin, seq, target)
            elif subtype == C.ICQ_REQ_SEARCH:
                await self.send_search(uin, seq, payload[r.pos - 4:])
            else:
                log.debug("метазапрос ICQ 0x%04x не поддерживаю", subtype)
                await self.send_snac(C.ICQ, C.ICQ_ERROR,
                                     struct.pack(">H", 0x0004),
                                     request_id=s.request_id)
        elif req_type == C.ICQ_OFFLINE_REQ:
            log.info("запрошены офлайн-сообщения — отвечаю, что их нет")
            await self.send_icq_reply(uin, C.ICQ_OFFLINE_DONE, seq, b"\x00")
        elif req_type == C.ICQ_OFFLINE_DELETE:
            log.debug("клиент попросил очистить офлайн-сообщения")
        else:
            log.debug("запрос ICQ 0x%04x не поддерживаю", req_type)
            await self.send_snac(C.ICQ, C.ICQ_ERROR, struct.pack(">H", 0x0004),
                                 request_id=s.request_id)

    async def send_search(self, uin: int, seq: int, query_data: bytes) -> None:
        """Поиск: клиент ищет анкету, а мы отдаём подходящие чаты Telegram."""
        query = blocks.parse_search_query(query_data, self.server.ssi_encoding)
        if not query:
            await self.send_icq_reply(uin, C.ICQ_META_RESP_TYPE, seq,
                                      struct.pack("<H", C.ICQ_SEARCH_LAST)
                                      + bytes([C.ICQ_NOT_FOUND]))
            return

        found = await self.server.search(query)
        log.info("поиск «%s»: нашлось %d чатов", query, len(found))
        if not found:
            await self.send_icq_reply(uin, C.ICQ_META_RESP_TYPE, seq,
                                      struct.pack("<H", C.ICQ_SEARCH_LAST)
                                      + bytes([C.ICQ_NOT_FOUND]))
            return

        for index, item in enumerate(found):
            await self.send_icq_reply(
                uin, C.ICQ_META_RESP_TYPE, seq,
                blocks.search_result(item["uin"], item.get("title", ""),
                                     item.get("kind", ""), "",
                                     item.get("username", ""),
                                     last_one=index == len(found) - 1,
                                     encoding=self.server.ssi_encoding))

    async def send_user_info(self, uin: int, seq: int, target: int) -> None:
        """Отвечает на «Информация о контакте»: сведения о чате Telegram
        раскладываются по полям профиля ICQ."""
        info = await self.server.chat_info(target)
        enc = self.server.ssi_encoding
        if info is None:
            log.info("сведений о UIN %d нет", target)
            await self.send_icq_reply(uin, C.ICQ_META_RESP_TYPE, seq,
                                      struct.pack("<H", C.ICQ_INFO_END) + b"\x32")
            return

        log.info("отдаю сведения о чате %r", info.get("title", target))
        empty = blocks.asciiz("", enc)

        # Jimm показывает карточку, только собрав не меньше пяти пакетов
        # ответа (RequestInfoAction.isCompleted), поэтому шлём весь набор.
        basic = (
            blocks.asciiz(info.get("title", ""), enc)      # ник
            + blocks.asciiz(info.get("kind", ""), enc)     # имя
            + empty                                        # фамилия
            + blocks.asciiz(info.get("username", ""), enc)  # почта
            + blocks.asciiz(info.get("members", ""), enc)  # город
            + empty                                        # область
            + blocks.asciiz(info.get("phone", ""), enc)    # телефон
            + empty                                        # факс
            + empty                                        # адрес
            + empty                                        # мобильный
        )
        await self.send_info_part(uin, seq, C.ICQ_INFO_BASIC, basic)

        link = info.get("username", "").lstrip("@")
        day, month, year = info.get("bday") or (0, 0, 0)
        age = 0
        if year:
            today = dt.date.today()
            age = today.year - year - ((today.month, today.day) < (month, day))
        more = (
            struct.pack("<H", max(age, 0))        # возраст
            + bytes([0])                          # пол — в Telegram его нет
            + blocks.asciiz(f"t.me/{link}" if link else "", enc)
            + struct.pack("<H", year)             # год рождения
            + bytes([month, day])                 # месяц и день
        )
        await self.send_info_part(uin, seq, C.ICQ_INFO_MORE, more)

        work = (
            empty * 5                             # город, область, телефон, факс, адрес
            + empty                               # индекс
            + struct.pack("<H", 0)                # код страны
            + blocks.asciiz("Telegram", enc)      # организация
            + blocks.asciiz(info.get("kind", ""), enc)   # отдел
            + blocks.asciiz(info.get("marks", ""), enc)  # должность: пометки чата
        )
        await self.send_info_part(uin, seq, C.ICQ_INFO_WORK, work)

        await self.send_info_part(uin, seq, C.ICQ_INFO_ABOUT,
                                  blocks.asciiz(info.get("about", ""), enc))
        await self.send_info_part(uin, seq, C.ICQ_INFO_INTERESTS, bytes([0]))
        await self.send_info_part(uin, seq, C.ICQ_INFO_END, b"")

    async def send_info_part(self, uin: int, seq: int, part: int, data: bytes) -> None:
        await self.send_icq_reply(uin, C.ICQ_META_RESP_TYPE, seq,
                                  struct.pack("<H", part) + bytes([C.ICQ_INFO_OK]) + data)

    async def send_icq_reply(self, uin: int, resp_type: int, seq: int, data: bytes) -> None:
        """Ответ семейства 0x15: всё внутри — little-endian, как принято в ICQ."""
        inner = struct.pack("<IHH", uin, resp_type, seq) + data
        body = struct.pack("<H", len(inner)) + inner
        await self.send_snac(C.ICQ, C.ICQ_FROM_SERVER, tlv(0x0001, body))

    async def on_client_ready(self, s: Snac) -> None:
        if self.ready:
            return
        self.ready = True
        log.info("клиент готов, %s", self.peer)
        asyncio.create_task(self.announce_buddies())
        self.server.wake_sender()

    async def announce_buddies(self) -> None:
        """Сообщает клиенту, кто из контактов в сети и с каким статусом."""
        sent = 0
        for contact in self.server.roster():
            if self.closed:
                return
            await self.notify_status(contact.uin, self.server.status_of(contact.uin))
            sent += 1
            if sent % BUDDY_BURST == 0:
                await asyncio.sleep(0.2)

    async def notify_status(self, uin: int, status: int) -> None:
        if status == C.STATUS_OFFLINE:
            await self.send_snac(C.BUDDY, C.BUDDY_DEPARTED, blocks.buddy_departed(uin))
        else:
            await self.send_snac(C.BUDDY, C.BUDDY_ARRIVED,
                                 blocks.user_info(str(uin), status=status,
                                                  signon_time=self.signon_time,
                                                  icon_hash=self.server.icon_hash(uin)))

    # --- сообщения ------------------------------------------------------

    async def on_icbm_send(self, s: Snac) -> None:
        r = s.reader()
        cookie = r.read(8)            # идентификатор сообщения, по нему клиент ставит галочку
        channel = r.u16()
        target = r.pstr8().decode("latin-1", "replace")
        tlvs = r.tlvs()

        if channel == 1:
            body = tlvs.get(0x0002) or b""
            text = blocks.parse_message_fragments(body, self.server.fallback_encoding)
        elif channel == 4:
            body = tlvs.get(0x0005) or b""
            text = blocks.parse_old_icq_message(body, self.server.fallback_encoding)
        else:
            log.info("сообщение в необслуживаемом канале %d", channel)
            return

        if not text.strip():
            return
        if not target.isdigit():
            log.warning("нечисловой получатель %r", target)
            return

        sent_id = await self.server.on_outgoing(int(target), text)
        if not sent_id or not tlvs.has(0x0003):
            return

        # Cookie в подтверждении обязан быть тем же, что прислал клиент:
        # по нему он и находит своё сообщение.
        if self.server.ack_on_read:
            # Галочку поставим, когда собеседник прочитает сообщение.
            self.server.remember_sent(int(target), sent_id, cookie, channel)
        else:
            await self.send_ack(cookie, channel, int(target))

    async def send_ack(self, cookie: bytes, channel: int, uin: int) -> None:
        await self.send_snac(C.ICBM, C.ICBM_ACK,
                             cookie + struct.pack(">H", channel)
                             + pstr8(str(uin).encode("ascii")))

    async def deliver(self, uin: int, text: str, wait_ack: bool = False,
                      row_id: int | None = None) -> bool:
        """Отправляет текст телефону. True — кадры ушли в сокет.

        В режиме подтверждений сообщение уходит расширенным форматом (канал 2),
        а запись из очереди удалит уже пришедшее позже SNAC 04/0B. Ждать его
        здесь нельзя: очередь встала бы на всё время ожидания.
        """
        parts = _split_text(text, self.server.max_message_chars)
        for index, part in enumerate(parts):
            cookie = blocks.new_cookie()
            sender = blocks.user_info(str(uin), signon_time=self.signon_time)

            if wait_ack:
                body = (cookie + struct.pack(">H", 2) + sender
                        + tlv(0x0005, blocks.channel2_message(cookie, part)))
            else:
                body = (cookie + struct.pack(">H", 1) + sender
                        + tlv(0x0002, blocks.message_fragments(part))
                        + tlv(0x0006, b""))

            # Запись считаем доставленной по подтверждению последней части.
            if wait_ack and row_id is not None and index == len(parts) - 1:
                if len(self.server.awaiting) > AWAITING_LIMIT:
                    self.server.awaiting.clear()   # телефон не отвечает — не копим
                self.server.awaiting[cookie] = row_id

            if not await self.send_snac(C.ICBM, C.ICBM_INCOMING, body):
                self.server.awaiting.pop(cookie, None)
                return False
        return True

    async def on_icbm_typing(self, s: Snac) -> None:
        """Владелец печатает в окне чата — передаём это в Telegram."""
        r = s.reader()
        r.read(8)                     # пустой cookie
        r.u16()                       # канал
        target = r.pstr8().decode("latin-1", "replace")
        flag = r.u16() if r.left >= 2 else 0
        if target.isdigit():
            await self.server.on_typing(int(target), flag == 0x0002)

    async def notify_typing(self, uin: int, active: bool) -> None:
        await self.send_snac(C.ICBM, C.ICBM_CLIENT_EVENT,
                             blocks.typing_packet(uin, active))

    async def on_service_request(self, s: Snac) -> None:
        """Клиент просит адрес дополнительного сервиса.

        Аватарки живут в семействе 0x10, и за ними клиент идёт отдельным
        соединением — присылаем адрес того же сервера и cookie на один вход.
        Остальные сервисы отвечаем отказом, иначе клиент будет ждать впустую.
        """
        family = struct.unpack(">H", s.data[:2])[0] if len(s.data) >= 2 else 0
        if family != C.SSBI or not self.server.avatars_enabled:
            log.debug("запрошен сервис 0x%04x — отвечаю отказом", family)
            await self.send_error(C.OSERVICE, 0x0001, s.request_id)
            return

        cookie = self.server.new_cookie("bart")
        body = (tlv_u16(C.TLV_SERVICE_ID, C.SSBI)
                + tlv(C.TLV_BOS_ADDRESS,
                      self.server.service_address(self.writer).encode())
                + tlv(C.TLV_AUTH_COOKIE, cookie))
        log.debug("отправляю клиента за аватарками на %s",
                  self.server.service_address(self.writer))
        await self.send_snac(C.OSERVICE, C.SERVICE_REDIRECT, body,
                             request_id=s.request_id)

    async def on_icon_request(self, s: Snac) -> None:
        """SNAC 10/06 — клиент просит аватарку контакта."""
        r = Reader(s.data)
        try:
            target = r.pstr8().decode("latin-1")
        except Exception:
            return
        if not target.isdigit():
            return
        got = await self.server.avatar(int(target))
        if got is None:
            log.debug("аватарки для UIN %s нет", target)
            await self.send_error(C.SSBI, 0x0001, s.request_id)
            return
        icon_hash, image = got
        log.info("отдаю аватарку UIN %s, %d байт", target, len(image))
        await self.send_snac(C.SSBI, C.SSBI_ICQ_REPLY,
                             blocks.icon_reply(int(target), icon_hash, image),
                             request_id=s.request_id)

    async def on_icbm_client_ack(self, s: Snac) -> None:
        """Клиент подтвердил получение — теперь запись можно убрать из очереди."""
        cookie = s.data[:8]
        row_id = self.server.awaiting.pop(cookie, None)
        log.debug("подтверждение получения, cookie %s%s", cookie.hex(),
                  "" if row_id else " (лишнее)")
        if self.server.ack_works is None:
            log.info("телефон подтверждает получение — работаем с подтверждениями")
            self.server.ack_works = True
        if row_id is not None:
            self.server.storage.drop_pending(row_id)


def _chunked(items: list[bytes], limit: int):
    """Режет элементы контакт-листа на порции, влезающие в один SNAC."""
    chunk: list[bytes] = []
    size = 0
    for item in items:
        if chunk and size + len(item) > limit:
            yield chunk, False
            chunk, size = [], 0
        chunk.append(item)
        size += len(item)
    yield chunk, True


def _split_text(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts, rest = [], text
    while len(rest) > limit:
        cut = rest.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = rest.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        parts.append(rest)
    return parts


class OscarServer:
    """Слушает порт 5190 и обслуживает единственный телефон владельца."""

    def __init__(self, cfg, storage: Storage,
                 on_outgoing: Callable[[int, str], Awaitable[bool]],
                 roster: Callable[[], list[Contact]],
                 status_of: Callable[[int], int] | None = None,
                 chat_info: Callable[[int], Awaitable[dict | None]] | None = None,
                 search: Callable[[str], Awaitable[list[dict]]] | None = None,
                 verdict_for: Callable[[int], str] | None = None,
                 on_remove: Callable[[int, bool], Awaitable[None]] | None = None,
                 on_privacy: Callable[[int, bool], Awaitable[None]] | None = None,
                 avatar: Callable[[int], Awaitable[tuple[bytes, bytes] | None]] | None = None,
                 icon_hash: Callable[[int], bytes | None] | None = None):
        self.cfg = cfg
        self.storage = storage
        self.on_outgoing = on_outgoing
        self.roster = roster
        self.status_of = status_of or (lambda uin: C.STATUS_ONLINE)
        self.chat_info = chat_info or self._no_info
        self.search = search or self._no_search
        # Решает судьбу записи очереди по текущему статусу: send, hold или drop.
        self.verdict_for = verdict_for or (lambda uin: "send")
        self.on_remove = on_remove or self._ignore_remove
        self.on_privacy = on_privacy or self._ignore_privacy
        # Аватарки: примета для блока сведений и сама картинка по запросу.
        self.avatar = avatar or self._no_avatar
        self.icon_hash = icon_hash or (lambda uin: None)
        self.avatars_enabled = bool(getattr(cfg, "avatars", True))
        self.uin = str(cfg.oscar_uin)
        self.password = cfg.oscar_password
        self.ssi_encoding = cfg.ssi_encoding
        self.fallback_encoding = cfg.ssi_encoding
        self.max_message_chars = cfg.max_message_chars
        self.alias_max_chars = getattr(cfg, "alias_max_chars", 40)
        self.idle_timeout = getattr(cfg, "idle_timeout", 360)
        self.use_ack = getattr(cfg, "delivery_ack", True)
        self.ack_timeout = getattr(cfg, "ack_timeout", 30)
        self.ack_works: bool | None = None    # None — ещё не знаем, умеет ли клиент
        self.awaiting: dict[bytes, int] = {}  # cookie -> запись очереди
        self.owner_status = C.STATUS_ONLINE
        self.on_owner_status = None          # сюда мост подставляет свои обработчики
        self.on_typing = self._ignore_typing
        self.ack_on_read = getattr(cfg, "ack_on", "read") == "read"
        self._sent: list[tuple[int, int, bytes, int]] = []   # uin, номер, cookie, канал
        self._probe_started = 0.0
        self.access = AccessControl(
            allow_from=getattr(cfg, "allow_from", ()),
            max_failures=getattr(cfg, "login_attempts", 5),
            ban_seconds=getattr(cfg, "login_ban_seconds", 300),
            max_connections=getattr(cfg, "max_connections", 8),
        )
        self._wake = asyncio.Event()
        self.session: Session | None = None
        self.last_auth_key = b""
        self._cookies: dict[bytes, float] = {}
        self._server: asyncio.AbstractServer | None = None

    # --- жизненный цикл -------------------------------------------------

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._accept, self.cfg.oscar_host, self.cfg.oscar_port)
        asyncio.create_task(self.sender_loop())
        log.info("OSCAR слушает %s:%d, UIN владельца %s",
                 self.cfg.oscar_host, self.cfg.oscar_port, self.uin)

    async def stop(self) -> None:
        """Перестаёт принимать подключения и закрывает текущую сессию."""
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                pass
            self._server = None
        if self.session is not None:
            await self.session.close()

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        host = peer[0] if peer else ""

        if not self.access.allowed(host):
            log.warning("отказано %s: адрес не в списке разрешённых", host)
            writer.close()
            return
        if self.access.banned(host):
            log.warning("отказано %s: слишком много неудачных попыток входа", host)
            writer.close()
            return
        if not self.access.take_slot():
            log.warning("отказано %s: занято все %d соединений", host,
                        self.access.max_connections)
            writer.close()
            return

        session = Session(self, reader, writer)
        log.info("соединение с %s", session.peer)
        try:
            await session.run()
        finally:
            self.access.free_slot()

    def new_cookie(self, kind: str = "bos") -> bytes:
        cookie = os.urandom(16)
        now = time.time()
        self._cookies = {c: (t, k) for c, (t, k) in self._cookies.items()
                         if now - t < 120}
        self._cookies[cookie] = (now, kind)
        return cookie

    def consume_cookie(self, cookie: bytes) -> str | None:
        """Возвращает род cookie: «bos» — обычный вход, «bart» — за аватарками."""
        got = self._cookies.pop(cookie, None)
        return got[1] if got else None

    def service_address(self, writer: asyncio.StreamWriter) -> str:
        """Куда идти за аватарками.

        Старые клиенты берут из ответа только имя хоста и стучатся на 5190,
        поэтому порт добавляем, лишь когда он другой: клиент, умеющий его
        прочитать, попадёт куда надо, а не умеющий — хотя бы на 5190.
        """
        address = self.bos_address(writer)
        host, _, port = address.rpartition(":")
        return host if port == "5190" else address

    def bos_address(self, writer: asyncio.StreamWriter) -> str:
        host = self.cfg.bos_host
        if not host:
            sock = writer.get_extra_info("sockname")
            host = sock[0] if sock else "127.0.0.1"
        return f"{host}:{self.cfg.bos_port or self.cfg.oscar_port}"

    def session_arrived(self, session: Session) -> None:
        if self.session is not None and self.session is not session:
            asyncio.create_task(self.session.close())
        self.session = session

    def session_gone(self, session: Session) -> None:
        if self.session is session:
            self.session = None
            self.awaiting.clear()
            # Неподтверждённое отправим заново, когда телефон вернётся.
            try:
                returned = self.storage.reset_sent()
            except Exception:
                returned = 0     # мост останавливается, база уже закрыта
            log.info("телефон отключился%s",
                     f", в очередь вернулось {returned} сообщений" if returned else "")

    @property
    def online(self) -> bool:
        return self.session is not None and self.session.ready and not self.session.closed

    # --- доставка -------------------------------------------------------

    async def push(self, uin: int, text: str, row_id: int | None = None) -> bool:
        """Отправляет одну запись очереди телефону."""
        if not self.online:
            return False

        with_ack = self.use_ack and self.ack_works is not False
        if not await self.session.deliver(uin, text, wait_ack=with_ack, row_id=row_id):
            return False

        if row_id is not None:
            if with_ack:
                # Ждём SNAC 04/0B: он и удалит запись.
                self.storage.mark_sent(row_id)
                if self.ack_works is None and not self._probe_started:
                    self._probe_started = time.time()
            else:
                self.storage.drop_pending(row_id)
        return True

    async def deliver(self, uin: int, text: str, forced: bool = False) -> bool:
        """Принимает сообщение к доставке.

        Пишем в очередь и будим отправителя. Ждать подтверждения прямо здесь
        нельзя: это застопорило бы приём сообщений из Telegram.

        forced — ответ на команду с телефона: доставляется при любом статусе,
        ведь его запросили руками.
        """
        self.storage.queue(uin, text, self.cfg.offline_queue_per_chat, forced)
        self.wake_sender()
        return True

    @staticmethod
    async def _no_info(uin: int) -> dict | None:
        return None

    @staticmethod
    async def _ignore_typing(uin: int, active: bool) -> None:
        return None

    @staticmethod
    async def _no_search(query: str) -> list[dict]:
        return []

    @staticmethod
    async def _ignore_remove(uin: int, revoke: bool) -> None:
        return None

    @staticmethod
    async def _ignore_privacy(uin: int, muted: bool) -> None:
        return None

    @staticmethod
    async def _no_avatar(uin: int) -> tuple[bytes, bytes] | None:
        return None

    async def notify_typing(self, uin: int, active: bool) -> None:
        """Показывает на телефоне, что собеседник набирает сообщение."""
        if self.online:
            await self.session.notify_typing(uin, active)

    def remember_sent(self, uin: int, message_id: int, cookie: bytes, channel: int) -> None:
        """Запоминает отправленное, чтобы отметить галочкой после прочтения."""
        self._sent.append((uin, message_id, cookie, channel))
        del self._sent[:-SENT_MEMORY]

    async def confirm_read(self, uin: int, max_id: int) -> int:
        """Собеседник прочитал всё вплоть до max_id — ставим галочки."""
        if not self.online:
            return 0
        confirmed = [row for row in self._sent if row[0] == uin and row[1] <= max_id]
        if not confirmed:
            return 0
        self._sent = [row for row in self._sent if row not in confirmed]
        for _, _, cookie, channel in confirmed:
            await self.session.send_ack(cookie, channel, uin)
        log.debug("отмечено прочитанными %d сообщений", len(confirmed))
        return len(confirmed)

    def ssi_version(self, items: list[bytes]) -> tuple[int, int]:
        """Версия контакт-листа: метка времени последнего изменения и число
        элементов. Метка меняется только когда меняется сам список."""
        digest = hashlib.sha1(b"".join(items)).hexdigest()
        if self.storage.get_meta("ssi_hash") == digest:
            return int(self.storage.get_meta("ssi_stamp", "0") or 0), len(items)
        stamp = int(time.time())
        self.storage.set_meta("ssi_hash", digest)
        self.storage.set_meta("ssi_stamp", str(stamp))
        log.info("контакт-лист изменился, новая версия %d", stamp)
        return stamp, len(items)

    async def owner_status_changed(self, status: int) -> None:
        if status == self.owner_status:
            return
        self.owner_status = status
        if self.on_owner_status is not None:
            await self.on_owner_status(status)

    def wake_sender(self) -> None:
        self._wake.set()

    async def notify_status(self, uin: int, status: int) -> None:
        """Передаёт телефону, что контакт сменил статус."""
        if self.online:
            await self.session.notify_status(uin, status)

    async def sender_loop(self) -> None:
        """Разбирает очередь, пока телефон на связи."""
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._next_tick())
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            try:
                self.check_acks()
                if self.online:
                    await self.drain_queue()
            except Exception:
                log.exception("сбой при разборе очереди")

    def _next_tick(self) -> float:
        """Пока ждём первого подтверждения, просыпаемся к сроку проверки."""
        if self.ack_works is None and self._probe_started:
            left = self.ack_timeout - (time.time() - self._probe_started)
            return max(0.2, min(SENDER_IDLE_POLL, left + 0.1))
        return SENDER_IDLE_POLL

    def check_acks(self) -> None:
        """Следит за подтверждениями: возвращает в очередь потерянное и
        отключает расширенный режим, если клиент его не поддерживает."""
        if self.ack_works is None and self._probe_started:
            if time.time() - self._probe_started > self.ack_timeout:
                log.warning("подтверждений от клиента нет — перехожу на обычные сообщения")
                self.ack_works = False
                self.awaiting.clear()
                self.storage.reset_sent()
                self.wake_sender()
            return
        stale = self.storage.reset_sent(older_than=ACK_GRACE)
        if stale:
            log.warning("%d сообщений не подтверждены за %d с — отправлю заново",
                        stale, ACK_GRACE)
            self.wake_sender()

    async def drain_queue(self) -> None:
        """Отправляет то, что ждёт очереди. Запись удаляется либо сразу
        (обычные сообщения), либо по подтверждению от телефона."""
        rows = self.storage.peek_pending()
        if not rows:
            return
        sent = skipped = 0
        for row_id, uin, text, ts, forced in rows:
            if not self.online:
                break

            # Статус мог смениться, пока сообщения лежали в очереди: то, что
            # сейчас доставлять нельзя, придерживаем или выбрасываем.
            # Ответы на команды идут мимо фильтра — их запросили с телефона.
            verdict = "send" if forced else self.verdict_for(uin)
            if verdict != "send":
                self.storage.drop_pending(row_id)
                if verdict == "hold":
                    self.storage.hold(uin, text, ts, self.cfg.offline_queue_per_chat)
                skipped += 1
                continue

            # Метку времени получает только то, что успело полежать в очереди.
            if time.time() - ts > STALE_SECONDS:
                stamp = time.strftime("%d.%m %H:%M", time.localtime(ts))
                text = f"[{stamp}] {text}"
            if not await self.push(uin, text, row_id):
                break
            sent += 1
        if skipped:
            log.info("по текущему статусу пропущено %d накопленных сообщений", skipped)
        if sent + skipped < len(rows):
            log.warning("отправлено %d из %d, остальное ждёт в очереди", sent, len(rows))
        elif sent > 1:
            log.info("отправлено %d накопленных сообщений", sent)
