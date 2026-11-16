// TMME/1 primitives, ported from TeleMotoMax SecureCrypto.java.
// SHA-256 (FIPS 180-4), MD5 (RFC 1321, OSCAR compatibility only),
// HKDF (RFC 5869), ChaCha20 (RFC 8439). No dependency on firmware TLS.
#include "crypto.h"
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <string.h>
namespace tmm {
namespace crypto {
static uint32_t rol(uint32_t v, unsigned n) {
    return (v << n) | (v >> (32 - n));
}
static uint32_t ror(uint32_t v, unsigned n) {
    return (v >> n) | (v << (32 - n));
}
static uint32_t be(const unsigned char *p) {
    return (uint32_t(p[0]) << 24) | (uint32_t(p[1]) << 16) | (uint32_t(p[2]) << 8) | p[3];
}
static uint32_t le(const unsigned char *p) {
    return (uint32_t(p[3]) << 24) | (uint32_t(p[2]) << 16) | (uint32_t(p[1]) << 8) | p[0];
}
static std::string u64(uint64_t v) {
    std::string s(8, '\0');
    for (int i = 7; i >= 0; --i) {
        s[i] = (char)v;
        v >>= 8;
    }
    return s;
}
static std::string pad(const std::string &data, bool big) {
    std::string s = data;
    s += '\x80';
    while (s.size() % 64 != 56)
        s += '\0';
    uint64_t bits = uint64_t(data.size()) * 8;
    if (big)
        s += u64(bits);
    else
        for (int i = 0; i < 8; ++i) {
            s += (char)bits;
            bits >>= 8;
        }
    return s;
}
std::string sha256(const std::string &data) {
    static const uint32_t k[64] = {
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2};
    uint32_t h[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                     0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
    std::string s = pad(data, true);
    for (size_t p = 0; p < s.size(); p += 64) {
        uint32_t w[64];
        for (unsigned i = 0; i < 16; ++i)
            w[i] = be((const unsigned char *)s.data() + p + 4 * i);
        for (unsigned i = 16; i < 64; ++i) {
            uint32_t a = w[i - 15], b = w[i - 2];
            w[i] = w[i - 16] + (ror(a, 7) ^ ror(a, 18) ^ (a >> 3)) + w[i - 7] +
                   (ror(b, 17) ^ ror(b, 19) ^ (b >> 10));
        }
        uint32_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], z = h[7];
        for (unsigned i = 0; i < 64; ++i) {
            uint32_t t =
                z + (ror(e, 6) ^ ror(e, 11) ^ ror(e, 25)) + ((e & f) ^ (~e & g)) + k[i] + w[i];
            uint32_t q = (ror(a, 2) ^ ror(a, 13) ^ ror(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
            z = g;
            g = f;
            f = e;
            e = d + t;
            d = c;
            c = b;
            b = a;
            a = t + q;
        }
        h[0] += a;
        h[1] += b;
        h[2] += c;
        h[3] += d;
        h[4] += e;
        h[5] += f;
        h[6] += g;
        h[7] += z;
    }
    std::string out(32, '\0');
    for (unsigned i = 0; i < 32; ++i)
        out[i] = (char)(h[i / 4] >> (24 - 8 * (i % 4)));
    return out;
}
std::string md5(const std::string &data) {
    static const uint32_t k[64] = {
        0xd76aa478, 0xe8c7b756, 0x242070db, 0xc1bdceee, 0xf57c0faf, 0x4787c62a, 0xa8304613,
        0xfd469501, 0x698098d8, 0x8b44f7af, 0xffff5bb1, 0x895cd7be, 0x6b901122, 0xfd987193,
        0xa679438e, 0x49b40821, 0xf61e2562, 0xc040b340, 0x265e5a51, 0xe9b6c7aa, 0xd62f105d,
        0x02441453, 0xd8a1e681, 0xe7d3fbc8, 0x21e1cde6, 0xc33707d6, 0xf4d50d87, 0x455a14ed,
        0xa9e3e905, 0xfcefa3f8, 0x676f02d9, 0x8d2a4c8a, 0xfffa3942, 0x8771f681, 0x6d9d6122,
        0xfde5380c, 0xa4beea44, 0x4bdecfa9, 0xf6bb4b60, 0xbebfbc70, 0x289b7ec6, 0xeaa127fa,
        0xd4ef3085, 0x04881d05, 0xd9d4d039, 0xe6db99e5, 0x1fa27cf8, 0xc4ac5665, 0xf4292244,
        0x432aff97, 0xab9423a7, 0xfc93a039, 0x655b59c3, 0x8f0ccc92, 0xffeff47d, 0x85845dd1,
        0x6fa87e4f, 0xfe2ce6e0, 0xa3014314, 0x4e0811a1, 0xf7537e82, 0xbd3af235, 0x2ad7d2bb,
        0xeb86d391};
    static const unsigned r[16] = {7, 12, 17, 22, 5, 9, 14, 20, 4, 11, 16, 23, 6, 10, 15, 21};
    uint32_t h[4] = {0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476};
    std::string s = pad(data, false);
    for (size_t p = 0; p < s.size(); p += 64) {
        uint32_t w[16];
        for (unsigned i = 0; i < 16; ++i)
            w[i] = le((const unsigned char *)s.data() + p + 4 * i);
        uint32_t a = h[0], b = h[1], c = h[2], d = h[3];
        for (unsigned i = 0; i < 64; ++i) {
            uint32_t f;
            unsigned g;
            if (i < 16) {
                f = (b & c) | (~b & d);
                g = i;
            } else if (i < 32) {
                f = (d & b) | (~d & c);
                g = (5 * i + 1) % 16;
            } else if (i < 48) {
                f = b ^ c ^ d;
                g = (3 * i + 5) % 16;
            } else {
                f = c ^ (b | ~d);
                g = (7 * i) % 16;
            }
            uint32_t prev = d;
            d = c;
            c = b;
            b += rol(a + f + k[i] + w[g], r[(i / 16) * 4 + i % 4]);
            a = prev;
        }
        h[0] += a;
        h[1] += b;
        h[2] += c;
        h[3] += d;
    }
    std::string out(16, '\0');
    for (unsigned i = 0; i < 16; ++i)
        out[i] = (char)(h[i / 4] >> (8 * (i % 4)));
    return out;
}
std::string hmac(const std::string &key, const std::string &data) {
    std::string k = key.size() > 64 ? sha256(key) : key;
    k.resize(64, '\0');
    std::string a = k, b = k;
    for (unsigned i = 0; i < 64; ++i) {
        a[i] ^= 0x36;
        b[i] ^= 0x5c;
    }
    return sha256(b + sha256(a + data));
}
static bool equal(const std::string &a, const std::string &b) {
    if (a.size() != b.size())
        return false;
    unsigned d = 0;
    for (size_t i = 0; i < a.size(); ++i)
        d |= (unsigned char)(a[i] ^ b[i]);
    return !d;
}
static int digit(char c) {
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    if (c >= 'A' && c <= 'F')
        return c - 'A' + 10;
    return -1;
}
bool derivePsk(const std::string &phrase, std::string &key, std::string &error) {
    key.clear();
    size_t a = 0, b = phrase.size();
    while (a < b && (unsigned char)phrase[a] <= 32)
        ++a;
    while (b > a && (unsigned char)phrase[b - 1] <= 32)
        --b;
    std::string s = phrase.substr(a, b - a);
    unsigned units = 0;
    for (size_t i = 0; i < s.size();) {
        unsigned char first = s[i++];
        uint32_t c = first;
        unsigned follow = 0;
        if (first >= 0xc2 && first <= 0xdf) {
            c = first & 31;
            follow = 1;
        } else if (first >= 0xe0 && first <= 0xef) {
            c = first & 15;
            follow = 2;
        } else if (first >= 0xf0 && first <= 0xf4) {
            c = first & 7;
            follow = 3;
        } else if (first >= 0x80) {
            error = "Invalid UTF-8 key";
            return false;
        }
        if (i + follow > s.size()) {
            error = "Truncated UTF-8 key";
            return false;
        }
        for (unsigned n = 0; n < follow; ++n) {
            unsigned char v = s[i++];
            if ((v & 0xc0) != 0x80) {
                error = "Invalid UTF-8 key";
                return false;
            }
            c = (c << 6) | (v & 63);
        }
        if ((follow == 1 && c < 0x80) || (follow == 2 && c < 0x800) ||
            (follow == 3 && c < 0x10000) || c > 0x10ffff || (c >= 0xd800 && c <= 0xdfff)) {
            error = "Invalid Unicode key";
            return false;
        }
        units += c > 0xffff ? 2 : 1;
    }
    if (!units || units > 64) {
        error = "Key must contain 1-64 UTF-16 units";
        return false;
    }
    if (s.size() == 64) {
        bool hex = true;
        for (size_t i = 0; i < 64; ++i)
            if (digit(s[i]) < 0)
                hex = false;
        if (hex) {
            for (size_t i = 0; i < 64; i += 2)
                key += (char)((digit(s[i]) << 4) | digit(s[i + 1]));
            return true;
        }
    }
    static const char prefix[] = "TeleMotoMax PSK v1\0";
    key = sha256(std::string(prefix, sizeof(prefix) - 1) + s);
    return true;
}
bool randomBytes(size_t length, std::string &data, std::string &error) {
    data.clear();
    if (length > 4096) {
        error = "Random request too large";
        return false;
    }
    int fd = ::open("/dev/urandom", O_RDONLY);
    if (fd < 0) {
        error = "Cannot open system random source";
        return false;
    }
    data.resize(length);
    size_t at = 0;
    while (at < length) {
        ssize_t n = read(fd, &data[at], length - at);
        if (n < 0 && errno == EINTR)
            continue;
        if (n <= 0) {
            close(fd);
            data.clear();
            error = "System random source failed";
            return false;
        }
        at += n;
    }
    close(fd);
    return true;
}
static std::string prefix(unsigned op) {
    std::string p = "TMME";
    p += '\1';
    p += (char)op;
    return p;
}
std::string clientHello(const std::string &key, const std::string &nonce) {
    if (key.size() != 32 || nonce.size() != 16)
        return "";
    std::string body = prefix(1) + nonce;
    return body + hmac(key, "client hello" + body).substr(0, 16);
}
bool finishHandshake(const std::string &key, const std::string &request,
                     const std::string &response, std::string &finish, std::string &keys,
                     std::string &error) {
    finish.clear();
    keys.clear();
    if (response.size() >= 7 && response.substr(0, 6) == prefix(255)) {
        error = "Server refused encryption";
        return false;
    }
    if (key.size() != 32 || request.size() != 38 || request.substr(0, 6) != prefix(1) ||
        response.size() != 54 || response.substr(0, 6) != prefix(2)) {
        error = "Invalid secure handshake";
        return false;
    }
    if (!equal(response.substr(38),
               hmac(key, "server hello" + request + response.substr(0, 38)).substr(0, 16))) {
        error = "Incorrect key or damaged handshake";
        return false;
    }
    finish = prefix(3) + hmac(key, "client finish" + request + response).substr(0, 16);
    std::string prk = hmac(request.substr(6, 16) + response.substr(6, 32), key), previous;
    for (unsigned i = 1; i <= 4; ++i) {
        previous = hmac(prk, previous + "TeleMotoMax secure v1" + std::string(1, (char)i));
        keys += previous;
    }
    return true;
}
static void quarter(uint32_t *x, unsigned a, unsigned b, unsigned c, unsigned d) {
    x[a] += x[b];
    x[d] = rol(x[d] ^ x[a], 16);
    x[c] += x[d];
    x[b] = rol(x[b] ^ x[c], 12);
    x[a] += x[b];
    x[d] = rol(x[d] ^ x[a], 8);
    x[c] += x[d];
    x[b] = rol(x[b] ^ x[c], 7);
}
static std::string chacha(const std::string &key, uint64_t counter, const std::string &data) {
    std::string out = data, nonce(4, '\0');
    nonce += u64(counter);
    uint32_t state[16] = {0x61707865, 0x3320646e, 0x79622d32, 0x6b206574};
    for (unsigned i = 0; i < 8; ++i)
        state[4 + i] = le((const unsigned char *)key.data() + 4 * i);
    state[12] = 0;
    for (unsigned i = 0; i < 3; ++i)
        state[13 + i] = le((const unsigned char *)nonce.data() + 4 * i);
    for (size_t p = 0; p < data.size(); p += 64) {
        uint32_t x[16];
        memcpy(x, state, sizeof x);
        for (unsigned i = 0; i < 10; ++i) {
            quarter(x, 0, 4, 8, 12);
            quarter(x, 1, 5, 9, 13);
            quarter(x, 2, 6, 10, 14);
            quarter(x, 3, 7, 11, 15);
            quarter(x, 0, 5, 10, 15);
            quarter(x, 1, 6, 11, 12);
            quarter(x, 2, 7, 8, 13);
            quarter(x, 3, 4, 9, 14);
        }
        for (unsigned i = 0; i < 16; ++i)
            x[i] += state[i];
        for (unsigned i = 0; i < 64 && p + i < data.size(); ++i)
            out[p + i] ^= (char)(x[i / 4] >> (8 * (i % 4)));
        ++state[12];
    }
    return out;
}
RecordCipher::RecordCipher() : counter_(0), ready_(false), exhausted_(false) {}
bool RecordCipher::reset(const std::string &e, const std::string &m) {
    enc_ = e;
    mac_ = m;
    counter_ = 0;
    exhausted_ = false;
    ready_ = e.size() == 32 && m.size() == 32;
    return ready_;
}
bool RecordCipher::seal(const std::string &plain, std::string &record, std::string &error) {
    record.clear();
    if (!ready_ || exhausted_ || plain.empty() || plain.size() > 1024) {
        error = "Invalid secure record";
        return false;
    }
    std::string payload = chacha(enc_, counter_, plain);
    record += (char)(plain.size() >> 8);
    record += (char)plain.size();
    record += payload;
    record += hmac(mac_, u64(counter_) + record).substr(0, 16);
    if (counter_ == ((uint64_t(1) << 63) - 2))
        exhausted_ = true;
    else
        ++counter_;
    return true;
}
bool RecordCipher::open(const std::string &record, std::string &plain, std::string &error) {
    plain.clear();
    if (!ready_ || exhausted_ || record.size() < 19) {
        error = "Invalid secure record";
        return false;
    }
    size_t n = ((unsigned char)record[0] << 8) | (unsigned char)record[1];
    if (!n || n > 1024 || record.size() != n + 18) {
        error = "Invalid secure record length";
        return false;
    }
    if (!equal(record.substr(n + 2),
               hmac(mac_, u64(counter_) + record.substr(0, n + 2)).substr(0, 16))) {
        error = "Secure record authentication failed";
        return false;
    }
    plain = chacha(enc_, counter_, record.substr(2, n));
    if (counter_ == ((uint64_t(1) << 63) - 2))
        exhausted_ = true;
    else
        ++counter_;
    return true;
}
} // namespace crypto
} // namespace tmm
