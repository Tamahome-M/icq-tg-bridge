#include "client.h"
#include <cassert>
#include <cstdio>
#include <vector>

// MontaVista GCC 3.4.3 -Os incorrectly folds the unsigned loop comparison to
// CMN(index, -size). CMN(0, 0) has a different carry flag from CMP(0, 0), so an
// empty vector enters the loop and dereferences unconstructed MessageRecords.
// Keep this loop representative of the client; -fno-expensive-optimizations
// must apply to every translation unit, including this runtime regression.
__attribute__((noinline)) bool contains(const std::vector<tmm::MessageRecord> &messages,
                                        const tmm::MessageRecord &message) {
    for (size_t i = 0; i < messages.size(); ++i)
        if ((message.cookie && messages[i].cookie == message.cookie) ||
            (!message.nativeId.empty() && messages[i].nativeId == message.nativeId))
            return true;
    return false;
}

template <unsigned Words> struct SizedRecord {
    unsigned words[Words];
    std::string tag;
    SizedRecord() {
        for (unsigned i = 0; i < Words; ++i)
            words[i] = 0;
    }
};
template <unsigned Words>
__attribute__((noinline)) bool containsSized(const std::vector<SizedRecord<Words> > &records,
                                             const SizedRecord<Words> &value) {
    for (size_t i = 0; i < records.size(); ++i)
        if ((value.words[0] && records[i].words[0] == value.words[0]) ||
            (!value.tag.empty() && records[i].tag == value.tag))
            return true;
    return false;
}
template <unsigned Words> void checkSize() {
    std::vector<SizedRecord<Words> > records;
    SizedRecord<Words> value;
    value.words[0] = 7;
    value.tag = "test";
    assert(!containsSized(records, value));
    records.reserve(4);
    assert(!containsSized(records, value));
    records.push_back(value);
    assert(containsSized(records, value));
    value.words[0] = 8;
    value.tag = "other";
    assert(!containsSized(records, value));
    records.push_back(value);
    assert(containsSized(records, value));
    records.clear();
    assert(!containsSized(records, value));
}

int main() {
    std::vector<tmm::MessageRecord> messages;
    messages.reserve(4);
    tmm::MessageRecord a;
    a.cookie = 1;
    a.nativeId = "12345678";
    assert(!contains(messages, a));
    messages.push_back(a);
    assert(contains(messages, a));
    tmm::MessageRecord b;
    b.cookie = 2;
    b.nativeId = "87654321";
    assert(!contains(messages, b));
    messages.push_back(b);
    assert(contains(messages, b));
    messages.clear();
    assert(!contains(messages, a));
    checkSize<1>();  // 8 bytes on V8; power of two control case.
    checkSize<2>();  // 12 bytes.
    checkSize<5>();  // 24 bytes.
    checkSize<6>();  // 28 bytes.
    checkSize<8>();  // 36 bytes.
    checkSize<9>();  // 40 bytes.
    checkSize<11>(); // 48 bytes.
    checkSize<13>(); // 56 bytes, like MessageRecord.
    checkSize<14>(); // 60 bytes.
    checkSize<16>(); // 68 bytes.
    std::puts("MontaVista unsigned vector loop: empty/populated/cleared PASS");
    return 0;
}
