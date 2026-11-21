#include "oscar.h"
#include <stdio.h>
#include <time.h>
namespace tmm {
namespace wire {
unsigned Reader::u8() {
    if (!left())
        throw Error("Оборванный пакет");
    return (unsigned char)data_[pos_++];
}
unsigned Reader::u16() {
    unsigned a = u8();
    return (a << 8) | u8();
}
uint32_t Reader::u32() {
    uint32_t a = u16();
    return (a << 16) | u16();
}
uint64_t Reader::u64() {
    uint64_t a = u32();
    return (a << 32) | u32();
}
unsigned Reader::le16() {
    unsigned a = u8();
    return a | (u8() << 8);
}
uint32_t Reader::le32() {
    uint32_t a = le16();
    return a | (uint32_t(le16()) << 16);
}
std::string Reader::bytes(size_t n) {
    if (n > left())
        throw Error("Оборванный пакет");
    std::string s = data_.substr(pos_, n);
    pos_ += n;
    return s;
}
void Reader::skip(size_t n) {
    if (n > left())
        throw Error("Оборванный пакет");
    pos_ += n;
}
std::string Reader::p8() {
    unsigned n = u8();
    return bytes(n);
}
std::string Reader::p16() {
    unsigned n = u16();
    return bytes(n);
}
std::string Reader::zle() {
    unsigned n = le16();
    std::string s = bytes(n);
    if (!s.empty() && s[s.size() - 1] == 0)
        s.erase(s.size() - 1);
    return s;
}
std::string be16(unsigned n) {
    char b[2] = {char(n >> 8), char(n)};
    return std::string(b, 2);
}
std::string be32(uint32_t n) {
    return be16(n >> 16) + be16(n);
}
std::string be64(uint64_t n) {
    return be32(uint32_t(n >> 32)) + be32(uint32_t(n));
}
std::string le16(unsigned n) {
    char b[2] = {char(n), char(n >> 8)};
    return std::string(b, 2);
}
std::string le32(uint32_t n) {
    return le16(n) + le16(n >> 16);
}
std::string p8(const std::string &s) {
    if (s.size() > 255)
        throw Error("Поле длиннее 255 байт");
    return std::string(1, char(s.size())) + s;
}
std::string p16(const std::string &s) {
    if (s.size() > 65535)
        throw Error("Поле длиннее 65535 байт");
    return be16(s.size()) + s;
}
std::string tlv(unsigned t, const std::string &s) {
    return be16(t) + p16(s);
}
std::string decimal(uint32_t n) {
    char b[16];
    snprintf(b, sizeof b, "%u", n);
    return b;
}
uint32_t uin(const std::string &s) {
    if (s.empty() || s.size() > 10)
        throw Error("Неверный UIN");
    uint64_t n = 0;
    for (size_t i = 0; i < s.size(); ++i) {
        if (s[i] < '0' || s[i] > '9')
            throw Error("Неверный UIN");
        n = n * 10 + s[i] - '0';
        if (n > uint64_t(0xffffffffU))
            throw Error("Неверный UIN");
    }
    return uint32_t(n);
}
Tlvs tlvs(Reader &r, int count) {
    Tlvs out;
    while (r.left() && (count < 0 || count-- > 0)) {
        unsigned t = r.u16();
        out[t] = r.p16();
    }
    if (count > 0)
        throw Error("Недостаточно TLV");
    return out;
}
Snac snac(const std::string &s) {
    Reader r(s);
    Snac a;
    a.family = r.u16();
    a.subtype = r.u16();
    a.flags = r.u16();
    a.request = r.u32();
    if (a.flags & 0x8000)
        r.p16();
    a.data = r.bytes(r.left());
    return a;
}
std::string snac(unsigned f, unsigned t, const std::string &d, uint32_t q, unsigned flags) {
    return be16(f) + be16(t) + be16(flags) + be32(q) + d;
}
std::string flap(unsigned c, unsigned q, const std::string &d) {
    if (d.size() > 65535)
        throw Error("Пакет слишком большой");
    return std::string("*", 1) + std::string(1, char(c)) + be16(q) + p16(d);
}
static const unsigned cp[128] = {
    0x402,  0x403,  0x201a, 0x453,  0x201e, 0x2026, 0x2020, 0x2021, 0x20ac, 0x2030, 0x409,  0x2039,
    0x40a,  0x40c,  0x40b,  0x40f,  0x452,  0x2018, 0x2019, 0x201c, 0x201d, 0x2022, 0x2013, 0x2014,
    0xfffd, 0x2122, 0x459,  0x203a, 0x45a,  0x45c,  0x45b,  0x45f,  0xa0,   0x40e,  0x45e,  0x408,
    0xa4,   0x490,  0xa6,   0xa7,   0x401,  0xa9,   0x404,  0xab,   0xac,   0xad,   0xae,   0x407,
    0xb0,   0xb1,   0x406,  0x456,  0x491,  0xb5,   0xb6,   0xb7,   0x451,  0x2116, 0x454,  0xbb,
    0x458,  0x405,  0x455,  0x457,  0x410,  0x411,  0x412,  0x413,  0x414,  0x415,  0x416,  0x417,
    0x418,  0x419,  0x41a,  0x41b,  0x41c,  0x41d,  0x41e,  0x41f,  0x420,  0x421,  0x422,  0x423,
    0x424,  0x425,  0x426,  0x427,  0x428,  0x429,  0x42a,  0x42b,  0x42c,  0x42d,  0x42e,  0x42f,
    0x430,  0x431,  0x432,  0x433,  0x434,  0x435,  0x436,  0x437,  0x438,  0x439,  0x43a,  0x43b,
    0x43c,  0x43d,  0x43e,  0x43f,  0x440,  0x441,  0x442,  0x443,  0x444,  0x445,  0x446,  0x447,
    0x448,  0x449,  0x44a,  0x44b,  0x44c,  0x44d,  0x44e,  0x44f};
std::string utf8(unsigned c) {
    std::string s;
    if (c < 128)
        s += char(c);
    else if (c < 2048) {
        s += char(0xc0 | (c >> 6));
        s += char(0x80 | (c & 63));
    } else if (c < 65536) {
        s += char(0xe0 | (c >> 12));
        s += char(0x80 | ((c >> 6) & 63));
        s += char(0x80 | (c & 63));
    } else if (c <= 0x10ffff) {
        s += char(0xf0 | (c >> 18));
        s += char(0x80 | ((c >> 12) & 63));
        s += char(0x80 | ((c >> 6) & 63));
        s += char(0x80 | (c & 63));
    } else
        return utf8(0xfffd);
    return s;
}
static unsigned nextUtf8(const std::string &s, size_t &i) {
    unsigned c = (unsigned char)s[i++];
    if (c < 128)
        return c;
    unsigned n = c >= 0xf0 ? 3 : c >= 0xe0 ? 2 : c >= 0xc2 ? 1 : 0;
    if (!n || i + n > s.size())
        throw Error("Неверный UTF-8");
    unsigned min = n == 1 ? 128 : n == 2 ? 2048 : 65536;
    c &= (1 << (6 - n)) - 1;
    while (n--) {
        unsigned a = (unsigned char)s[i++];
        if ((a & 0xc0) != 0x80)
            throw Error("Неверный UTF-8");
        c = (c << 6) | (a & 63);
    }
    if (c < min || c > 0x10ffff || (c >= 0xd800 && c <= 0xdfff))
        throw Error("Неверный UTF-8");
    return c;
}
std::string passwordBytes(const std::string &s) {
    // Settings/editor text is UTF-8; classic ICQ and this bridge authenticate
    // Latin-1 bytes. Do not fold case, trim whitespace or silently replace a
    // character with '?': any such change authenticates a different password.
    std::string out;
    for (size_t at = 0; at < s.size();) {
        unsigned c = nextUtf8(s, at);
        if (c > 255)
            throw Error(
                "Пароль учётной записи содержит символы, которые мост не поддерживает (Latin-1)");
        out += char(c);
    }
    return out;
}
std::string utf16(const std::string &s) {
    std::string out;
    for (size_t i = 0; i < s.size();) {
        unsigned c = nextUtf8(s, i);
        if (c > 65535) {
            c -= 65536;
            out += be16(0xd800 | (c >> 10));
            out += be16(0xdc00 | (c & 1023));
        } else
            out += be16(c);
    }
    return out;
}
std::string decode(const std::string &s, const std::string &e) {
    if (e == "UTF-8" || e == "utf-8")
        return s;
    std::string out;
    if (e == "UTF-16BE") {
        Reader r(s);
        while (r.left() >= 2) {
            unsigned c = r.u16();
            if (c >= 0xd800 && c <= 0xdbff && r.left() >= 2) {
                unsigned d = r.u16();
                c = d >= 0xdc00 && d <= 0xdfff ? 0x10000 + ((c - 0xd800) << 10) + d - 0xdc00
                                               : 0xfffd;
            }
            out += utf8(c);
        }
        return out;
    }
    for (size_t i = 0; i < s.size(); ++i) {
        unsigned c = (unsigned char)s[i];
        out += utf8(c < 128 ? c : e == "LATIN1" ? c : cp[c - 128]);
    }
    return out;
}
std::string encode1251(const std::string &s) {
    std::string out;
    for (size_t i = 0; i < s.size();) {
        unsigned c = nextUtf8(s, i);
        if (c < 128) {
            out += char(c);
            continue;
        }
        unsigned j = 0;
        while (j < 128 && cp[j] != c)
            ++j;
        out += j < 128 ? char(j + 128) : '?';
    }
    return out;
}
std::string messageBody(const std::string &s) {
    return std::string("\5\1\0\4\1\1\1\2", 8) + std::string("\1\1", 2) +
           p16(be16(2) + be16(0) + utf16(s));
}
std::string ssiItem(const ContactRecord &c, const std::string &e) {
    std::string n = c.type == 1 ? c.name : decimal(c.uin);
    if (c.type == 1 && e != "UTF-8" && e != "utf-8")
        n = encode1251(n);
    std::string extra;
    if (c.type == 0 && !c.name.empty())
        extra = tlv(0x131, e == "UTF-8" || e == "utf-8" ? c.name : encode1251(c.name));
    return p16(n) + be16(c.groupId) + be16(c.itemId) + be16(c.type) + p16(extra);
}
void ssi(const Snac &s, std::vector<ContactRecord> &out, uint32_t &stamp, const std::string &e) {
    Reader r(s.data);
    bool full = s.subtype == 6;
    if (full)
        r.u8();
    unsigned count = full ? r.u16() : 65535;
    while (count-- && r.left() > (full ? 4U : 0U)) {
        ContactRecord c;
        std::string n = r.p16();
        c.groupId = r.u16();
        c.itemId = r.u16();
        c.type = r.u16();
        std::string ex = r.p16();
        Reader er(ex);
        Tlvs t = tlvs(er);
        c.deleted = s.subtype == 10;
        c.inRoster = !c.deleted;
        if (c.type == 1)
            c.name = decode(n, e);
        else if (c.type == 0 || c.type == 2 || c.type == 3 || c.type == 14) {
            c.uin = uin(n);
            c.name = decode(t[0x131], e);
            c.noAuth = t.count(0x66);
            c.privacy = c.type;
        } else
            continue;
        out.push_back(c);
        if (out.size() > 4096)
            throw Error("Контакт-лист слишком большой");
    }
    if (full)
        stamp = r.u32();
    if (r.left())
        throw Error("Лишние данные контакт-листа");
}
ContactRecord presence(const Snac &s) {
    Reader r(s.data);
    ContactRecord c;
    c.uin = uin(r.p8());
    r.u16();
    Tlvs t = tlvs(r, r.u16());
    if (r.left())
        throw Error("Лишние данные статуса контакта");
    if (s.subtype == 12)
        return c;
    if (t[6].size() == 4) {
        Reader v(t[6]);
        c.status = v.u32();
    } else
        c.status = 0;
    if (t.count(0x1d)) {
        Reader b(t[0x1d]);
        while (b.left()) {
            unsigned k = b.u16();
            b.u8();
            std::string h = b.p8();
            if (k == 1 && h.size() == 16)
                c.avatarHash = h;
        }
    }
    return c;
}
MessageRecord incoming(const Snac &s, std::string &ack, const std::string &e) {
    Reader r(s.data);
    MessageRecord m;
    m.cookie = r.u64();
    unsigned channel = r.u16();
    std::string sender = r.p8();
    m.uin = m.sourceUin = uin(sender);
    m.time = time(0);
    r.u16();
    tlvs(r, r.u16());
    Tlvs t = tlvs(r);
    if (channel == 1) {
        Reader f(t[2]);
        while (f.left()) {
            unsigned id = f.u8();
            f.u8();
            std::string raw = f.p16();
            if (id == 1) {
                Reader b(raw);
                unsigned enc = b.u16();
                b.u16();
                m.text += decode(b.bytes(b.left()), enc == 2   ? "UTF-16BE"
                                                    : enc == 3 ? "LATIN1"
                                                               : e);
            }
        }
    } else if (channel == 2) {
        Reader b(t[5]);
        if (b.u16() != 0)
            throw Error("Неверное расширенное сообщение");
        b.skip(24);
        Tlvs bt = tlvs(b);
        std::string block = bt[0x2711];
        Reader body(block);
        body.skip(45);
        unsigned type = body.le16();
        body.skip(4);
        unsigned length = body.le16();
        std::string raw = body.bytes(length);
        if (!raw.empty() && raw[raw.size() - 1] == 0)
            raw.erase(raw.size() - 1);
        body.skip(8);
        std::string enc = e;
        if (body.left() >= 4) {
            unsigned n = body.le32();
            if (n == 38 && body.bytes(n) == "{0946134E-4C7F-11D1-8222-444553540000}")
                enc = "UTF-8";
        }
        if (type == 4) {
            size_t at = raw.find(char(0xfe));
            if (at != std::string::npos) {
                m.url = decode(raw.substr(at + 1), enc);
                raw.erase(at);
            }
        } else if (type != 1)
            throw Error("Неподдерживаемый тип сообщения");
        m.text = decode(raw, enc);
        ack = be64(m.cookie) + be16(channel) + p8(sender) + be16(3) + block.substr(0, 51) +
              le16(1) + std::string(1, 0);
    } else
        throw Error("Неподдерживаемый канал сообщения");
    if (t[0x9001].size() == 17) {
        m.kind = (unsigned char)t[0x9001][0];
        m.token = t[0x9001].substr(1);
    }
    if (t[0x9002].size() == 8)
        m.nativeId = t[0x9002];
    m.senderName = t[0x9004];
    m.silent = t[0x9005] == std::string(1, 1);
    return m;
}
void history(const std::string &data, uint32_t who, std::vector<MessageRecord> &rows, bool &more) {
    Reader r(data);
    more = false;
    if (r.left() && (unsigned char)data[0] == 255) {
        r.u8();
        more = r.u8() != 0;
    }
    while (r.left()) {
        MessageRecord m;
        m.uin = m.sourceUin = who;
        m.text = r.p16();
        unsigned flag = r.u8();
        if ((flag & 0xc0) || ((flag & 6) && !(flag & 1)))
            throw Error("Неизвестный формат истории");
        m.outgoing = (flag & 8) != 0;
        if (flag & 1) {
            m.token = r.bytes(16);
            m.kind = (flag & 6) == 6 ? 4 : flag & 4 ? 3 : flag & 2 ? 2 : 1;
        }
        if (flag & 16)
            m.discussionUin = r.u32();
        if (flag & 32)
            m.nativeId = r.bytes(8);
        rows.push_back(m);
        if (rows.size() > 200)
            throw Error("Слишком много сообщений истории");
    }
}
void chats(const std::string &data, std::vector<ContactRecord> &rows, bool &more) {
    Reader r(data);
    more = false;
    if (data.substr(0, 3) == "CP1") {
        r.skip(3);
        more = r.u8() != 0;
    }
    while (r.left()) {
        ContactRecord c;
        c.uin = r.u32();
        unsigned flags = r.u8();
        c.network = flags & 4 ? 2 : flags & 1 ? 1 : 0;
        c.inRoster = (flags & 2) != 0;
        c.days = r.u16();
        c.name = r.p16();
        rows.push_back(c);
        if (rows.size() > 1024)
            throw Error("Слишком много чатов");
    }
}
Bart bart(const std::string &data) {
    Reader r(data);
    Bart b;
    b.uin = uin(r.p8());
    b.kind = r.u16();
    b.part = r.u8();
    b.token = r.p8();
    if (r.u8() != 0 || r.u16() != b.kind)
        throw Error("Неверный ответ BART");
    b.total = r.u8();
    if (r.p8() != b.token)
        throw Error("Токены BART не совпадают");
    if (!b.part && !b.total) {
        b.part = r.u16();
        b.total = r.u16();
    }
    b.data = r.p16();
    if (r.left() || !b.part || !b.total || b.part > b.total)
        throw Error("Неверные части BART");
    return b;
}
} // namespace wire
} // namespace tmm
