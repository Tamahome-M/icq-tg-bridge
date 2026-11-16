#ifndef TMM_OSCAR_H
#define TMM_OSCAR_H
#include "client.h"
#include <stdexcept>
namespace tmm {
namespace wire {
struct Error : std::runtime_error {
    explicit Error(const std::string &s) : std::runtime_error(s) {}
};
class Reader {
    const std::string &data_;
    size_t pos_;

  public:
    explicit Reader(const std::string &data) : data_(data), pos_(0) {}
    size_t left() const {
        return data_.size() - pos_;
    }
    size_t pos() const {
        return pos_;
    }
    unsigned u8();
    unsigned u16();
    uint32_t u32();
    uint64_t u64();
    unsigned le16();
    uint32_t le32();
    std::string bytes(size_t n);
    void skip(size_t n);
    std::string p8();
    std::string p16();
    std::string zle();
};
std::string be16(unsigned n);
std::string be32(uint32_t n);
std::string be64(uint64_t n);
std::string le16(unsigned n);
std::string le32(uint32_t n);
std::string p8(const std::string &s);
std::string p16(const std::string &s);
std::string tlv(unsigned type, const std::string &s);
std::string decimal(uint32_t n);
uint32_t uin(const std::string &s);
typedef std::map<unsigned, std::string> Tlvs;
Tlvs tlvs(Reader &r, int count = -1);
struct Snac {
    unsigned family, subtype, flags;
    uint32_t request;
    std::string data;
    Snac() : family(0), subtype(0), flags(0), request(0) {}
};
Snac snac(const std::string &s);
std::string snac(unsigned family, unsigned subtype, const std::string &data, uint32_t request = 0,
                 unsigned flags = 0);
std::string flap(unsigned channel, unsigned sequence, const std::string &data);
std::string utf8(unsigned code);
std::string decode(const std::string &text, const std::string &encoding = "CP1251");
std::string encode1251(const std::string &utf8);
std::string utf16(const std::string &utf8);
std::string passwordBytes(const std::string &utf8);
std::string messageBody(const std::string &text);
std::string ssiItem(const ContactRecord &c, const std::string &encoding = "CP1251");
void ssi(const Snac &s, std::vector<ContactRecord> &out, uint32_t &stamp,
         const std::string &encoding = "CP1251");
ContactRecord presence(const Snac &s);
MessageRecord incoming(const Snac &s, std::string &ack, const std::string &encoding = "CP1251");
void history(const std::string &data, uint32_t uin, std::vector<MessageRecord> &rows, bool &more);
void chats(const std::string &data, std::vector<ContactRecord> &rows, bool &more);
struct Bart {
    uint32_t uin;
    unsigned kind, part, total;
    std::string token, data;
};
Bart bart(const std::string &data);
} // namespace wire
} // namespace tmm
#endif
