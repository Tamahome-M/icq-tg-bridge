#include "oscar.h"
#include "crypto.h"
#include <assert.h>
#include <stdio.h>

static void rejects(const std::string &value) {
    try {
        tmm::wire::passwordBytes(value);
    } catch (const tmm::wire::Error &) {
        return;
    }
    assert(!"unsupported or malformed password accepted");
}

int main() {
    using tmm::wire::passwordBytes;
    const std::string ascii = " AbC019zZ ";
    assert(passwordBytes(ascii) == ascii);
    const std::string latin = "caf\xc3\xa9\xc3\x86\xc3\xbf";
    const std::string bytes = "caf\xe9\xc6\xff";
    assert(passwordBytes(latin) == bytes);
    // Independently calculated with Python hashlib over the bridge's Latin-1 bytes.
    assert(tmm::crypto::md5("2468013579" + passwordBytes(ascii) + "AOL Instant Messenger (SM)") ==
           std::string("\x68\xdc\x35\xb9\xc7\x8e\x83\x88\x72\xc1\xd0\xe4\x41\xc7\x81\xbf", 16));
    assert(tmm::crypto::md5("2468013579" + passwordBytes(latin) + "AOL Instant Messenger (SM)") ==
           std::string("\x48\xa1\x9f\xd1\xde\x07\xa7\xdc\x7b\x2a\x3e\xea\x80\x96\xce\xd2", 16));
    assert(passwordBytes("").empty());
    for (unsigned c = 1; c < 256; ++c) {
        std::string utf8;
        if (c < 128)
            utf8 += char(c);
        else {
            utf8 += char(0xc0 | (c >> 6));
            utf8 += char(0x80 | (c & 63));
        }
        assert(passwordBytes(utf8) == std::string(1, char(c)));
    }
    rejects("пароль");
    rejects("😀");
    rejects("\xff");
    rejects("\xc3");
    rejects("\xc0\x80");
    rejects("\xed\xa0\x80");
    rejects("\xf4\x90\x80\x80");
    puts("password encoding: case, spaces, all Latin-1 bytes and rejected invalid characters");
}
