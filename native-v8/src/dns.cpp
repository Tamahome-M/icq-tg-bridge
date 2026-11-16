#include "dns.h"
#include "oscar.h"
#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>
#include <fcntl.h>
#include <poll.h>
#include <errno.h>
#include <string.h>
#include <resolv.h>
#include <set>
#include <algorithm>
namespace tmm {
bool isIPv4(const std::string &s) {
    struct in_addr a;
    return inet_pton(AF_INET, s.c_str(), &a) == 1;
}
std::vector<DnsServer> systemDnsServers() {
    // Motorola NAPI_DnsResolverConfig changes this worker's libc resolver
    // state directly, including the port of its optional local DNS proxy.
    res_state state = __res_state();
    if (!(state->options & RES_INIT) && res_init() < 0)
        throw wire::Error("Не удалось настроить системный DNS");
    std::vector<DnsServer> out;
    for (int i = 0; i < state->nscount && i < MAXNS; ++i) {
        const sockaddr_in &address = state->nsaddr_list[i];
        char host[INET_ADDRSTRLEN];
        unsigned port = ntohs(address.sin_port);
        if (address.sin_family == AF_INET && port &&
            inet_ntop(AF_INET, &address.sin_addr, host, sizeof host))
            out.push_back(DnsServer(host, port));
    }
    return out;
}
static std::string canonical(std::string s) {
    if (!s.empty() && s[s.size() - 1] == '.')
        s.erase(s.size() - 1);
    if (s.empty() || s.size() > 253)
        throw wire::Error("Неверное DNS-имя");
    unsigned label = 0;
    for (size_t i = 0; i < s.size(); ++i) {
        unsigned char c = s[i];
        if (c == '.') {
            if (!label)
                throw wire::Error("Неверное DNS-имя");
            label = 0;
        } else {
            if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') ||
                  c == '-' || c == '_') ||
                ++label > 63)
                throw wire::Error("Неверное DNS-имя");
            if (c >= 'A' && c <= 'Z')
                s[i] = c + 32;
        }
    }
    if (!label)
        throw wire::Error("Неверное DNS-имя");
    return s;
}
static unsigned word(const std::string &s, size_t p) {
    if (p + 2 > s.size())
        throw wire::Error("Оборванный DNS-ответ");
    return (unsigned char)s[p] * 256 + (unsigned char)s[p + 1];
}
static std::string name(const std::string &s, size_t &p) {
    size_t at = p, end = 0;
    unsigned jumps = 0;
    std::string out;
    for (;;) {
        if (at >= s.size())
            throw wire::Error("Неверное DNS-имя");
        unsigned n = (unsigned char)s[at++];
        if (!n) {
            p = end ? end : at;
            return out;
        }
        if ((n & 192) == 192) {
            if (at >= s.size() || ++jumps > 128)
                throw wire::Error("Неверный DNS-указатель");
            size_t target = ((n & 63) << 8) | (unsigned char)s[at];
            if (target < 12 || target >= at - 1)
                throw wire::Error("Неверный DNS-указатель");
            if (!end)
                end = at + 1;
            at = target;
            continue;
        }
        if (n > 63 || at + n > s.size() || out.size() + n + 1 > 254)
            throw wire::Error("Неверное DNS-имя");
        if (!out.empty())
            out += '.';
        out += s.substr(at, n);
        at += n;
        out = canonical(out);
    }
}
class DnsChannel {
    Transport tcp_;
    Cancellation &cancel_;
    std::string server_;
    unsigned port_;
    int udp_;
    bool tcpMode_;
    uint64_t deadline_;

  public:
    DnsChannel(const std::string &server, Cancellation &cancel, bool tcpOnly, unsigned port,
               uint64_t deadline)
        : tcp_(cancel), cancel_(cancel), server_(server), port_(port), udp_(-1), tcpMode_(tcpOnly),
          deadline_(deadline) {
        if (tcpMode_)
            tcp_.connect(server, port_, deadline);
        else {
            udp_ = socket(AF_INET, SOCK_DGRAM, 0);
            if (udp_ < 0)
                throw wire::Error(strerror(errno));
            try {
                if (server.substr(0, 4) != "127.")
                    cancel_.bindSocket(udp_);
                if (fcntl(udp_, F_SETFL, O_NONBLOCK) < 0 || fcntl(udp_, F_SETFD, FD_CLOEXEC) < 0)
                    throw wire::Error(strerror(errno));
                sockaddr_in a;
                memset(&a, 0, sizeof a);
                a.sin_family = AF_INET;
                a.sin_port = htons(port_);
                inet_pton(AF_INET, server.c_str(), &a.sin_addr);
                if (::connect(udp_, reinterpret_cast<sockaddr *>(&a), sizeof a))
                    throw wire::Error(strerror(errno));
            } catch (...) {
                ::close(udp_);
                udp_ = -1;
                throw;
            }
        }
    }
    ~DnsChannel() {
        if (udp_ >= 0)
            ::close(udp_);
    }
    void send(const std::string &query) {
        if (tcpMode_)
            tcp_.write(wire::p16(query), deadline_);
        else if (::send(udp_, query.data(), query.size(), 0) != ssize_t(query.size()))
            throw wire::Error("Не удалось отправить системный DNS-запрос");
    }
    std::string receive() {
        if (tcpMode_) {
            std::string h = tcp_.read(2, deadline_);
            unsigned n = word(h, 0);
            if (n < 12 || n > 2048)
                throw wire::Error("Неверная длина DNS-ответа");
            return tcp_.read(n, deadline_);
        }
        for (;;) {
            if (cancel_.cancelled())
                throw wire::Error("DNS отменён");
            uint64_t now = monotonicMs();
            if (now >= deadline_)
                throw wire::Error("Время системного DNS истекло");
            pollfd p[2];
            p[0].fd = udp_;
            p[0].events = POLLIN;
            p[0].revents = 0;
            p[1].fd = cancel_.wakeFd();
            p[1].events = POLLIN;
            p[1].revents = 0;
            int count = poll(p, 2, int(std::min<uint64_t>(deadline_ - now, 500)));
            if (count < 0) {
                if (errno == EINTR)
                    continue;
                throw wire::Error(strerror(errno));
            }
            if (p[1].revents) {
                char x[64];
                while (::read(p[1].fd, x, sizeof x) > 0) {
                }
                continue;
            }
            if (p[0].revents) {
                char data[2048];
                ssize_t n = recv(udp_, data, sizeof data, MSG_TRUNC);
                if (n < 0 && (errno == EAGAIN || errno == EINTR))
                    continue;
                if (n < 12 || n > 2048)
                    throw wire::Error("Системный DNS вернул повреждённый пакет");
                return std::string(data, n);
            }
        }
    }
    void truncated(const std::string &query) {
        if (tcpMode_)
            throw wire::Error("Оборванный DNS TCP-ответ");
        ::close(udp_);
        udp_ = -1;
        tcpMode_ = true;
        tcp_.connect(server_, port_, deadline_);
        send(query);
    }
};
struct Record {
    std::string owner, alias;
    unsigned type, cls;
    uint32_t address;
};
std::vector<std::string> resolveDns(const std::string &host, const std::string &server,
                                    Cancellation &cancel, bool tcpOnly, unsigned port) {
    if (isIPv4(host))
        return std::vector<std::string>(1, host);
    if (!isIPv4(server) || !port || port > 65535)
        throw wire::Error("Неверный IP DNS-сервера");
    std::string current = canonical(host);
    std::set<std::string> seen;
    seen.insert(current);
    uint64_t deadline = monotonicMs() + 12000;
    DnsChannel channel(server, cancel, tcpOnly, port, deadline);
    std::vector<std::string> result;
    for (unsigned hop = 0; hop <= 8; ++hop) {
        std::string random, error;
        if (!crypto::randomBytes(2, random, error))
            throw wire::Error(error);
        unsigned id = word(random, 0);
        std::string query = random + wire::be16(0x100) + wire::be16(1) + std::string(6, 0);
        size_t begin = 0;
        for (size_t i = 0; i <= current.size(); ++i)
            if (i == current.size() || current[i] == '.') {
                query += wire::p8(current.substr(begin, i - begin));
                begin = i + 1;
            }
        query += std::string(1, 0) + wire::be16(1) + wire::be16(1);
        channel.send(query);
        std::vector<Record> records;
        bool matched = false;
        for (unsigned packets = 0; packets < 16; ++packets) {
            std::string s = channel.receive();
            if (word(s, 0) != id)
                continue;
            unsigned flags = word(s, 2);
            if (flags & 0x200) {
                channel.truncated(query);
                continue;
            }
            if (!(flags & 0x8000) || (flags & 0x7840) || word(s, 4) != 1)
                throw wire::Error("Неверный DNS-ответ");
            size_t p = 12;
            std::string asked = name(s, p);
            unsigned type = word(s, p), cls = word(s, p + 2);
            p += 4;
            if (asked != current || type != 1 || cls != 1)
                continue;
            if (flags & 15)
                throw wire::Error("DNS-сервер не нашёл адрес");
            unsigned answers = word(s, 6), count = answers + word(s, 8) + word(s, 10);
            if (count > (s.size() - p) / 11)
                throw wire::Error("Неверное число DNS-записей");
            for (unsigned n = 0; n < count; ++n) {
                Record r;
                r.owner = name(s, p);
                r.type = word(s, p);
                r.cls = word(s, p + 2);
                unsigned bytes = word(s, p + 8);
                p += 10;
                if (bytes > s.size() - p)
                    throw wire::Error("Оборванная DNS-запись");
                if (n < answers && r.cls == 1) {
                    if (r.type == 1) {
                        if (bytes != 4)
                            throw wire::Error("Неверная DNS A-запись");
                        r.address = (uint32_t(word(s, p)) << 16) | word(s, p + 2);
                    } else if (r.type == 5) {
                        size_t a = p;
                        r.alias = name(s, a);
                        if (a != p + bytes)
                            throw wire::Error("Неверная DNS CNAME-запись");
                    }
                    records.push_back(r);
                }
                p += bytes;
            }
            if (p != s.size())
                throw wire::Error("Лишние DNS-данные");
            matched = true;
            break;
        }
        if (!matched)
            throw wire::Error("Нет подходящего DNS-ответа");
        bool advanced = false;
        for (;;) {
            std::string alias;
            bool hasA = false;
            for (size_t i = 0; i < records.size(); ++i)
                if (records[i].owner == current) {
                    if (records[i].type == 5) {
                        if (records[i].alias.empty() ||
                            (!alias.empty() && alias != records[i].alias))
                            throw wire::Error("Противоречивый DNS CNAME");
                        alias = records[i].alias;
                    }
                    if (records[i].type == 1) {
                        hasA = true;
                        uint32_t a = records[i].address;
                        if (!a || a == 0xffffffffU || (a >> 24) >= 224)
                            continue;
                        std::string ip =
                            wire::decimal(a >> 24) + "." + wire::decimal((a >> 16) & 255) + "." +
                            wire::decimal((a >> 8) & 255) + "." + wire::decimal(a & 255);
                        if (result.size() < 4 &&
                            std::find(result.begin(), result.end(), ip) == result.end())
                            result.push_back(ip);
                    }
                }
            if (!alias.empty()) {
                if (hasA || seen.size() >= 9 || !seen.insert(alias).second)
                    throw wire::Error("Цикл DNS CNAME");
                current = alias;
                advanced = true;
                continue;
            }
            if (!result.empty())
                return result;
            if (!advanced)
                throw wire::Error("Нет IPv4-адресов DNS");
            break;
        }
    }
    throw wire::Error("Слишком длинная цепочка DNS");
}
} // namespace tmm
