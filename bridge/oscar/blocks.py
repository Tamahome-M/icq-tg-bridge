"""Сборка и разбор составных структур OSCAR: инфо о пользователе,
элементы контакт-листа, тело сообщения ICBM."""

from __future__ import annotations

import os
import struct
import time

from . import const as C
from .proto import Reader, TLVList, pstr8, pstr16, tlv, tlv_u16, tlv_u32


def user_info(screenname: str, *, warning: int = 0, user_class: int | None = None,
              status: int = C.STATUS_ONLINE, signon_time: int | None = None,
              online_seconds: int = 0, icon_hash: bytes | None = None) -> bytes:
    """Блок сведений о пользователе — им сервер описывает и себя, и контакты."""
    if user_class is None:
        user_class = C.CLASS_FREE | C.CLASS_ICQ
    if signon_time is None:
        signon_time = int(time.time())
    body = (
        tlv_u16(C.UI_TLV_CLASS, user_class)
        + tlv_u32(C.UI_TLV_SIGNON_TIME, signon_time)
        + tlv_u32(C.UI_TLV_STATUS, status)
        + tlv_u32(C.UI_TLV_ONLINE_TIME, online_seconds)
        + tlv_u32(C.UI_TLV_MEMBER_SINCE, signon_time)
        + tlv(C.UI_TLV_EXTERNAL_IP, b"\x00\x00\x00\x00")
        + tlv(C.UI_TLV_CAPABILITIES, CONTACT_CAPABILITIES)
    )
    tlv_count = 7
    if icon_hash:
        # Примета аватарки: увидев её, клиент сам придёт за картинкой в
        # семейство 0x10. Хеш для него — просто ярлык: каким прислали, таким
        # он его и вернёт в запросе.
        body += tlv(C.UI_TLV_BART,
                    struct.pack(">HBB", C.BART_ICON, C.BART_ICON_FLAGS, len(icon_hash))
                    + icon_hash)
        tlv_count += 1
    return pstr8(screenname.encode("ascii", "replace")) + struct.pack(">HH", warning, tlv_count) + body


def icon_reply(uin: int, icon_hash: bytes, image: bytes) -> bytes:
    """Тело SNAC 10/07: аватарка контакта.

    Приметы идут дважды подряд — так устроен ответ настоящего сервера, и клиент
    отсчитывает начало картинки по этой длине, а не по разбору полей.
    """
    marks = (struct.pack(">HBB", C.BART_ICON, C.BART_ICON_FLAGS, len(icon_hash))
             + icon_hash)
    return (pstr8(str(uin).encode("ascii"))
            + marks + b"\x00" + marks
            + struct.pack(">H", len(image)) + image)


def buddy_departed(uin: int) -> bytes:
    """Короткий блок для SNAC 03/0C — контакт больше не в сети."""
    return pstr8(str(uin).encode("ascii")) + struct.pack(">HH", 0, 0)


def ssi_item(name: bytes, group_id: int, item_id: int, item_type: int, tlvs: bytes = b"") -> bytes:
    """Элемент серверного контакт-листа."""
    return pstr16(name) + struct.pack(">HHH", group_id, item_id, item_type) + pstr16(tlvs)


def ssi_group(name: bytes, group_id: int, member_ids: list[int]) -> bytes:
    members = b"".join(struct.pack(">H", i) for i in member_ids)
    return ssi_item(name, group_id, 0, C.SSI_TYPE_GROUP, tlv(C.SSI_TLV_MEMBERS, members))


def ssi_buddy(uin: int, group_id: int, item_id: int, alias: bytes) -> bytes:
    extra = tlv(C.SSI_TLV_ALIAS, alias) if alias else b""
    return ssi_item(str(uin).encode("ascii"), group_id, item_id, C.SSI_TYPE_BUDDY, extra)


# Возможность «ICQ server relay» — ею помечаются расширенные сообщения,
# на которые клиент присылает подтверждение о получении.
CAP_SERVER_RELAY = bytes.fromhex("094613494C7F11D18222444553540000")
# Возможность «уведомления о наборе»: без неё Jimm не станет сообщать,
# что владелец печатает (JimmUI проверяет её перед отправкой SNAC 04/14).
CAP_TYPING = bytes.fromhex("563FC8090B6F41BD9F79422609DFA2F3")
# Признак ICQ-клиента — им контакт помечается как «свой».
CAP_IS_ICQ = bytes.fromhex("094613444C7F11D18222444553540000")

CONTACT_CAPABILITIES = CAP_TYPING + CAP_IS_ICQ
# Маркер кодировки UTF-8 в конце блока сообщения.
GUID_UTF8 = b"{0946134E-4C7F-11D1-8222-444553540000}"

MSG_TYPE_PLAIN = 0x0001


def channel2_message(cookie: bytes, text: str) -> bytes:
    """Расширенное сообщение ICQ (канал 2) — то, на что Jimm отвечает SNAC 04/0B.

    Раскладка жёсткая: клиент читает поля по фиксированным смещениям и до
    начала текста ждёт ровно 53 байта.
    """
    payload = text.encode("utf-8")
    block = (
        struct.pack("<H", 0x001B)      # длина заголовка
        + struct.pack("<H", 0x0008)    # версия протокола
        + bytes(16)                    # GUID расширения — для обычного текста нули
        + bytes(3)
        + struct.pack("<I", 0)         # флаги возможностей клиента
        + bytes(2)
        + struct.pack("<H", 0xFFFF)    # счётчик
        + struct.pack("<H", 0x000E)
        + bytes(12)
        + struct.pack("<H", MSG_TYPE_PLAIN)
        + struct.pack("<H", 0)         # состояние
        + struct.pack("<H", 0)         # приоритет
        + struct.pack("<H", len(payload))
        + payload
        + struct.pack(">I", 0x00000000)   # цвет текста
        + struct.pack(">I", 0x00FFFFFF)   # цвет фона
        + struct.pack("<I", len(GUID_UTF8)) + GUID_UTF8
    )
    return (
        struct.pack(">H", 0)           # обычное сообщение, не ответ
        + cookie
        + CAP_SERVER_RELAY
        + tlv(0x000A, struct.pack(">H", 1))   # запрашиваем подтверждение
        + tlv(0x000F, b"")
        + tlv(0x2711, block)           # блок данных обязан идти последним
    )


def message_fragments(text: str) -> bytes:
    """Тело сообщения ICBM: фрагмент возможностей + фрагмент текста."""
    try:
        payload = text.encode("ascii")
        charset = C.CHARSET_ASCII
    except UnicodeEncodeError:
        payload = text.encode("utf-16-be", "replace")
        charset = C.CHARSET_UNICODE
    caps = bytes([0x05, 0x01]) + struct.pack(">H", 4) + b"\x01\x01\x01\x02"
    body = struct.pack(">HH", charset, 0) + payload
    text_frag = bytes([0x01, 0x01]) + struct.pack(">H", len(body)) + body
    return caps + text_frag


def parse_message_fragments(data: bytes, fallback_encoding: str = "cp1251") -> str:
    """Достаёт текст из тела сообщения ICBM (TLV 0x0002)."""
    r = Reader(data)
    chunks: list[str] = []
    while r.left >= 4:
        frag_id = r.u8()
        r.u8()  # версия фрагмента
        try:
            frag = r.pstr16()
        except Exception:
            break
        if frag_id != 0x01 or len(frag) < 4:
            continue
        charset, _sub = struct.unpack(">HH", frag[:4])
        chunks.append(decode_text(frag[4:], charset, fallback_encoding))
    return "".join(chunks)


def decode_text(raw: bytes, charset: int, fallback_encoding: str = "cp1251") -> str:
    if charset == C.CHARSET_UNICODE:
        return raw.decode("utf-16-be", "replace")
    if charset == C.CHARSET_LATIN1:
        return raw.decode("latin-1", "replace")
    # charset 0 — «ASCII», но старые клиенты кладут туда однобайтовую кириллицу.
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError:
        return raw.decode(fallback_encoding, "replace")


def parse_old_icq_message(data: bytes, fallback_encoding: str = "cp1251") -> str:
    """Сообщение в старом формате ICQ (ICBM channel 4, TLV 0x0005)."""
    r = Reader(data)
    r.u32le()          # UIN отправителя
    r.u8()             # тип сообщения
    r.u8()             # флаги
    raw = r.read(r.u16le())
    return raw.rstrip(b"\x00").decode(fallback_encoding, "replace")


def asciiz(text: str, encoding: str = "cp1251") -> bytes:
    """Строка в формате сведений ICQ: длина (little-endian) и текст."""
    raw = (text or "").encode(encoding, "replace")
    return struct.pack("<H", len(raw)) + raw


def typing_packet(uin: int, active: bool) -> bytes:
    """Уведомление «печатает» (SNAC 04/14) в том виде, в каком его шлёт Jimm."""
    return (bytes(8) + struct.pack(">H", 1) + pstr8(str(uin).encode("ascii"))
            + struct.pack(">H", 0x0002 if active else 0x0000))


def parse_search_query(data: bytes, encoding: str = "cp1251") -> str:
    """Достаёт из запроса поиска то, по чему искать: ник, имя или ключевое слово."""
    r = Reader(data)
    parts: list[str] = []
    text_fields = (C.SEARCH_FIELD_NICK, C.SEARCH_FIELD_FIRSTNAME,
                   C.SEARCH_FIELD_LASTNAME, C.SEARCH_FIELD_KEYWORD,
                   C.SEARCH_FIELD_EMAIL, C.SEARCH_FIELD_CITY)
    while r.left >= 4:
        field = r.u16()                 # тип поля идёт big-endian
        try:
            value = r.read(r.u16le())
        except Exception:
            break
        if field in text_fields and len(value) > 2:
            # внутри — своя длина, строка и завершающий ноль
            parts.append(value[2:].rstrip(b"\x00").decode(encoding, "replace"))
        elif field == C.SEARCH_FIELD_UIN and len(value) >= 4:
            parts.append(str(struct.unpack("<I", value[:4])[0]))
    return " ".join(p for p in parts if p.strip()).strip()


def search_result(uin: int, nick: str, first: str, last: str, email: str,
                  last_one: bool, found_left: int = 0,
                  encoding: str = "cp1251") -> bytes:
    """Один найденный контакт в формате выдачи поиска ICQ."""
    def string(text: str) -> bytes:
        raw = (text or "").encode(encoding, "replace")
        return struct.pack("<H", len(raw)) + raw

    body = (
        struct.pack("<I", uin)
        + string(nick) + string(first) + string(last) + string(email)
        + bytes([0])                    # авторизация не требуется
        + struct.pack("<H", 0)          # статус: в сети
        + bytes([0])                    # пол не указан
        + struct.pack("<H", 0)          # возраст не указан
    )
    if last_one:
        body += struct.pack("<I", found_left)
    kind = C.ICQ_SEARCH_LAST if last_one else C.ICQ_SEARCH_RESULT
    return (struct.pack("<H", kind) + bytes([C.ICQ_INFO_OK])
            + struct.pack("<H", len(body)) + body)


def new_cookie() -> bytes:
    return os.urandom(8)


def parse_ssi_items(data: bytes) -> list[tuple[bytes, int, int, int, TLVList]]:
    """Разбирает элементы контакт-листа, присланные клиентом (SNAC 13/08, 13/09, 13/0A)."""
    r = Reader(data)
    out = []
    while r.left >= 10:
        name = r.pstr16()
        group_id = r.u16()
        item_id = r.u16()
        item_type = r.u16()
        extra = Reader(r.pstr16()).tlvs()
        out.append((name, group_id, item_id, item_type, extra))
    return out
