#include "oscar.h"
#include <assert.h>
#include <stdlib.h>
#include <iostream>
using namespace tmm;
using namespace tmm::wire;
int main() {
    const std::string text = "Привет 😀";
    assert(decode(utf16(text), "UTF-16BE") == text);
    assert(decode(encode1251("Семья")) == "Семья");
    for (unsigned n = 0; n < 256; ++n) {
        std::string raw(1, char(n));
        assert(decode(raw).size() >= 1);
    }
    Snac s;
    s.family = 4;
    s.subtype = 7;
    s.data = be64(42) + be16(1) + p8("1000001") + be16(0) + be16(0) + tlv(2, messageBody(text)) +
             tlv(0x9001, std::string(1, 2) + std::string(16, 'T')) + tlv(0x9002, be64(123456)) +
             tlv(0x9004, "Имя") + tlv(0x9005, std::string(1, 1));
    std::string ack;
    Snac departed;
    departed.family = 3;
    departed.subtype = 12;
    departed.data = p8("1000001") + be16(0) + be16(0);
    assert(presence(departed).uin == 1000001 && presence(departed).status == 0xffffffffU);
    departed.data = p8("1000001");
    bool invalidPresence = false;
    try {
        presence(departed);
    } catch (const Error &) {
        invalidPresence = true;
    }
    assert(invalidPresence);
    MessageRecord m = incoming(s, ack);
    assert(m.text == text && m.silent && m.kind == 2 && m.nativeId == be64(123456) &&
           m.senderName == "Имя" && ack.empty());
    std::string block(53, 0);
    block.replace(45, 2, le16(1));
    block.replace(51, 2, le16(text.size() + 1));
    block += text + std::string(1, 0) + std::string(8, 0) + le32(38) +
             "{0946134E-4C7F-11D1-8222-444553540000}";
    s.data = be64(43) + be16(2) + p8("1000001") + be16(0) + be16(0) +
             tlv(5, be16(0) + be64(43) + std::string(16, 0) + tlv(0x2711, block));
    m = incoming(s, ack);
    assert(m.text == text && m.cookie == 43 && !ack.empty());
    Reader ar(ack);
    assert(ar.u64() == 43 && ar.u16() == 2 && ar.p8() == "1000001");
    std::vector<MessageRecord> rows;
    bool more = false;
    history(std::string("\xff\1", 2) + p16(text) + std::string(1, 0x3f) + std::string(16, 'T') +
                be32(1000002) + be64(987),
            1000001, rows, more);
    assert(more && rows.size() == 1 && rows[0].kind == 4 && rows[0].outgoing &&
           rows[0].discussionUin == 1000002 && rows[0].nativeId == be64(987));
    std::vector<ContactRecord> contacts;
    chats("CP1" + std::string(1, 1) + be32(1000001) + std::string(1, 6) + be16(2) + p16(text),
          contacts, more);
    assert(more && contacts.size() == 1 && contacts[0].network == 2 && contacts[0].inRoster);
    ContactRecord c;
    c.uin = 1000001;
    c.name = "Сергей";
    c.groupId = 1;
    c.itemId = 3;
    Snac list;
    list.subtype = 6;
    list.data = std::string(1, 0) + be16(1) + ssiItem(c) + be32(123);
    uint32_t stamp = 0;
    contacts.clear();
    ssi(list, contacts, stamp);
    assert(stamp == 123 && contacts.size() == 1 && contacts[0].name == c.name);
    Bart b = bart(p8("1000001") + be16(0x82) + std::string("\1\20", 2) + std::string(16, 't') +
                  std::string(1, 0) + be16(0x82) + std::string("\2\20", 2) + std::string(16, 't') +
                  p16("part"));
    assert(b.part == 1 && b.total == 2 && b.data == "part");
    // Corrupted/truncated lengths and compression-independent OSCAR layouts may
    // throw a bounded protocol error, but must not read outside their frame.
    srand(42);
    for (unsigned n = 0; n < 40000; ++n) {
        std::string raw(rand() % 600, 0);
        for (size_t i = 0; i < raw.size(); ++i)
            raw[i] = char(rand());
        try {
            switch (n % 7) {
            case 0: {
                Reader r(raw);
                tlvs(r);
                break;
            }
            case 1:
                snac(raw);
                break;
            case 2: {
                std::vector<MessageRecord> r;
                history(raw, 1, r, more);
                break;
            }
            case 3: {
                std::vector<ContactRecord> r;
                chats(raw, r, more);
                break;
            }
            case 4:
                bart(raw);
                break;
            case 5:
                s.data = raw;
                incoming(s, ack);
                break;
            case 6: {
                list.data = raw;
                std::vector<ContactRecord> r;
                ssi(list, r, stamp);
                break;
            }
            }
        } catch (const std::exception &) {
        }
    }
    std::cout << "PASS OSCAR codecs + 40000 malformed frames" << std::endl;
}
