#include "crypto.h"
#include <iostream>
#include <sstream>
#include <string>
using namespace tmm::crypto;
static int digit(char c) {
    return c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : -1;
}
static std::string unhex(std::string s) {
    if (s == "-")
        return "";
    std::string r;
    for (size_t i = 0; i + 1 < s.size(); i += 2) {
        if (digit(s[i]) < 0 || digit(s[i + 1]) < 0)
            return "";
        r += (char)((digit(s[i]) << 4) | digit(s[i + 1]));
    }
    return r;
}
static std::string hex(const std::string &s) {
    const char *d = "0123456789abcdef";
    std::string r;
    for (size_t i = 0; i < s.size(); ++i) {
        unsigned c = (unsigned char)s[i];
        r += d[c >> 4];
        r += d[c & 15];
    }
    return r.empty() ? "-" : r;
}
int main() {
    std::string line;
    RecordCipher tx, rx;
    while (std::getline(std::cin, line)) {
        std::istringstream in(line);
        std::string op, a, b, c, out, error;
        in >> op >> a >> b >> c;
        a = unhex(a);
        b = unhex(b);
        c = unhex(c);
        bool ok = true;
        if (op == "sha")
            out = sha256(a);
        else if (op == "md5")
            out = md5(a);
        else if (op == "hmac")
            out = hmac(a, b);
        else if (op == "psk")
            ok = derivePsk(a, out, error);
        else if (op == "hello")
            out = clientHello(a, b);
        else if (op == "finish") {
            std::string keys;
            ok = finishHandshake(a, b, c, out, keys, error);
            out += keys;
        } else if (op == "reset")
            ok = tx.reset(a, b) && rx.reset(a, b);
        else if (op == "seal")
            ok = tx.seal(a, out, error);
        else if (op == "open")
            ok = rx.open(a, out, error);
        else if (op == "random")
            ok = randomBytes(32, out, error);
        else
            return 2;
        std::cout << (ok ? "OK " : "ERROR ") << hex(out) << std::endl;
    }
    return 0;
}
