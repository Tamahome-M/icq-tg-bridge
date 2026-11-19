#include "client.h"
#include <iostream>
#include <sstream>
#include <poll.h>
#include <stdlib.h>
#include <time.h>
#include <pthread.h>
#include <errno.h>
#include <sys/socket.h>
#include <arpa/inet.h>
using namespace tmm;
extern "C" int __real_pthread_create(pthread_t *, const pthread_attr_t *, void *(*)(void *),
                                     void *);
extern "C" int __wrap_pthread_create(pthread_t *thread, const pthread_attr_t *attr,
                                     void *(*run)(void *), void *arg) {
    if (getenv("TMM_TEST_THREAD_FAILURE"))
        return EAGAIN;
    return __real_pthread_create(thread, attr, run, arg);
}

extern "C" int __real_connect(int, const struct sockaddr *, socklen_t);
extern "C" int __wrap_connect(int fd, const struct sockaddr *address, socklen_t size) {
    const char *overridePort = getenv("TMM_TEST_DNS_PORT");
    if (overridePort && address->sa_family == AF_INET && size >= sizeof(sockaddr_in)) {
        sockaddr_in a = *reinterpret_cast<const sockaddr_in *>(address);
        if (ntohs(a.sin_port) == 53 && ntohl(a.sin_addr.s_addr) == 0x7f000001) {
            a.sin_port = htons(atoi(overridePort));
            return __real_connect(fd, reinterpret_cast<sockaddr *>(&a), sizeof a);
        }
    }
    return __real_connect(fd, address, size);
}

static pthread_mutex_t sendFaultMutex = PTHREAD_MUTEX_INITIALIZER;
static unsigned sendFaultState = 0, sendsAfterFailure = 0, faultPrefixBytes = 0,
                injectedSendFailures = 0;
extern "C" ssize_t __real_send(int, const void *, size_t, int);
extern "C" ssize_t __wrap_send(int fd, const void *data, size_t size, int flags) {
    pthread_mutex_lock(&sendFaultMutex);
    unsigned state = sendFaultState;
    if (state == 1)
        sendFaultState = 2;
    else if (state == 2) {
        sendFaultState = 3;
        ++injectedSendFailures;
    } else if (state == 3)
        ++sendsAfterFailure;
    pthread_mutex_unlock(&sendFaultMutex);
    if (state >= 2) {
        errno = EIO;
        return -1;
    }
    const ssize_t result = __real_send(fd, data, state == 1 && size > 3 ? 3 : size, flags);
    if (state == 1 && result > 0) {
        pthread_mutex_lock(&sendFaultMutex);
        faultPrefixBytes += result;
        pthread_mutex_unlock(&sendFaultMutex);
    }
    return result;
}

static std::string unhex(const std::string &s) {
    if (s == "-")
        return "";
    std::string out;
    for (size_t i = 0; i + 1 < s.size(); i += 2) {
        unsigned n;
        std::istringstream in(s.substr(i, 2));
        in >> std::hex >> n;
        out += char(n);
    }
    return out;
}
static std::string hex(const std::string &s) {
    const char *d = "0123456789abcdef";
    std::string out;
    for (size_t i = 0; i < s.size(); ++i) {
        unsigned n = (unsigned char)s[i];
        out += d[n >> 4];
        out += d[n & 15];
    }
    return out;
}
static std::string quote(const std::string &s) {
    std::string out = "\"";
    for (size_t i = 0; i < s.size(); ++i) {
        unsigned char c = s[i];
        if (c == '"' || c == '\\') {
            out += '\\';
            out += c;
        } else if (c < 32) {
            const char *d = "0123456789abcdef";
            out += "\\u00";
            out += d[c >> 4];
            out += d[c & 15];
        } else
            out += c;
    }
    return out + '"';
}
static void emit(const Event &e) {
    std::cout << "{\"type\":" << e.type << ",\"id\":" << e.requestId << ",\"uin\":" << e.uin
              << ",\"state\":" << e.state << ",\"generation\":" << e.generation
              << ",\"kind\":" << e.kind << ",\"delivery\":" << e.delivery
              << ",\"cookie\":" << e.cookie << ",\"more\":" << e.more << ",\"offset\":" << e.offset
              << ",\"bytes\":" << e.bytes << ",\"total\":" << e.total << ",\"flag\":" << e.flag
              << ",\"error\":" << e.error << ",\"text\":" << quote(e.text)
              << ",\"path\":" << quote(e.path) << ",\"ref\":" << quote(hex(e.nativeId))
              << ",\"contacts\":[";
    for (size_t i = 0; i < e.contacts.size(); ++i) {
        if (i)
            std::cout << ',';
        const ContactRecord &c = e.contacts[i];
        std::cout << "{\"uin\":" << c.uin << ",\"type\":" << c.type << ",\"name\":" << quote(c.name)
                  << ",\"group\":" << quote(c.group) << ",\"status\":" << c.status << "}";
    }
    std::cout << "],\"messages\":[";
    for (size_t i = 0; i < e.messages.size(); ++i) {
        if (i)
            std::cout << ',';
        const MessageRecord &m = e.messages[i];
        std::cout << "{\"uin\":" << m.uin << ",\"text\":" << quote(m.text) << ",\"time\":" << m.time
                  << ",\"out\":" << m.outgoing << ",\"kind\":" << m.kind
                  << ",\"silent\":" << m.silent << ",\"thread\":" << m.discussionUin
                  << ",\"ref\":" << quote(hex(m.nativeId)) << ",\"token\":" << quote(hex(m.token))
                  << "}";
    }
    std::cout << "],\"fields\":{";
    bool first = true;
    for (std::map<std::string, std::string>::const_iterator i = e.fields.begin();
         i != e.fields.end(); ++i) {
        if (!first)
            std::cout << ',';
        first = false;
        std::cout << quote(i->first) << ':' << quote(i->second);
    }
    std::cout << "}}" << std::endl;
}
int main(int argc, char **argv) {
    std::ios::sync_with_stdio(false);
    if (argc < 5)
        return 2;
    Client client;
    ClientConfig cfg;
    cfg.host = "127.0.0.1";
    cfg.port = atoi(argv[1]);
    cfg.uin = "12345";
    cfg.password = "test";
    cfg.encryption = atoi(argv[2]);
    cfg.md5Login = atoi(argv[3]);
    cfg.psk = "1234";
    if (getenv("TMM_TEST_PASSWORD"))
        cfg.password = getenv("TMM_TEST_PASSWORD");
    if (getenv("TMM_TEST_PSK"))
        cfg.psk = getenv("TMM_TEST_PSK");
    if (getenv("TMM_TEST_MAX_MEDIA"))
        cfg.maxMediaBytes = atoi(getenv("TMM_TEST_MAX_MEDIA"));
    cfg.network = "system";
    cfg.cacheDir = argv[4];
    cfg.autoReconnect = getenv("TMM_TEST_RECONNECT") != 0;
    cfg.reconnectSeconds = 1;
    cfg.pingSeconds = getenv("TMM_TEST_DISABLE_KEEPALIVE") ? 0 : 1;
    cfg.missedPings = 3;
    if (getenv("TMM_TEST_PREFETCH")) {
        cfg.host = "bridge.example.org";
        cfg.dnsServer = "127.0.0.1";
        cfg.startupDns = true;
    }
    if (getenv("TMM_TEST_NETWORK_FAILURE")) {
        cfg.network = "mobile";
        cfg.profile = "missing-test-profile";
    }
    client.configure(cfg);
    if (getenv("TMM_TEST_PREFETCH"))
        client.prefetchDns();
    else
        client.start();
    time_t end = time(0) + 90;
    while (time(0) < end) {
        pollfd p[2];
        p[0].fd = client.eventFd();
        p[0].events = POLLIN;
        p[0].revents = 0;
        p[1].fd = 0;
        p[1].events = POLLIN;
        p[1].revents = 0;
        poll(p, 2, 100);
        if (p[0].revents) {
            std::vector<Event> events;
            client.drainEvents(events);
            for (size_t i = 0; i < events.size(); ++i)
                emit(events[i]);
        }
        if (p[1].revents || std::cin.rdbuf()->in_avail() > 0) {
            std::string line;
            if (!std::getline(std::cin, line))
                break;
            if (line == "quit")
                break;
            if (line == "stop") {
                client.stop();
                continue;
            }
            if (line == "stop-wait") {
                std::cout << "{\"joined\":" << client.stopAndWait() << "}" << std::endl;
                continue;
            }
            if (line == "arm-send-failure" || line == "clear-send-failure" ||
                line == "send-fault-count") {
                pthread_mutex_lock(&sendFaultMutex);
                if (line == "arm-send-failure") {
                    sendFaultState = 1;
                    sendsAfterFailure = 0;
                    faultPrefixBytes = injectedSendFailures = 0;
                } else if (line == "clear-send-failure")
                    sendFaultState = 0;
                unsigned count = sendsAfterFailure, prefix = faultPrefixBytes,
                         failures = injectedSendFailures;
                pthread_mutex_unlock(&sendFaultMutex);
                std::cout << "{\"fault_count\":" << count << ",\"fault_prefix_bytes\":" << prefix
                          << ",\"fault_failures\":" << failures << "}" << std::endl;
                continue;
            }
            if (line == "system-network") {
                cfg.network = "system";
                cfg.profile.clear();
                client.configure(cfg);
                std::cout << "{\"configured\":true}" << std::endl;
                continue;
            }
            if (line == "disable-dns") {
                cfg.startupDns = false;
                cfg.dnsServer = "invalid.example";
                client.configure(cfg);
                std::cout << "{\"configured\":true}" << std::endl;
                continue;
            }
            if (line == "change-host") {
                cfg.host = "different.example.org";
                client.configure(cfg);
                std::cout << "{\"configured\":true}" << std::endl;
                continue;
            }
            if (line == "start") {
                client.start();
                continue;
            }
            std::istringstream in(line);
            int type;
            Command c;
            std::string text, path, token, ref;
            in >> type >> c.requestId >> c.uin >> c.sourceUin >> c.mode >> c.offset >> c.limit >>
                c.duration >> c.flag >> text >> path >> token >> ref;
            c.type = Command::Type(type);
            c.text = unhex(text);
            c.path = unhex(path);
            c.token = unhex(token);
            c.nativeId = unhex(ref);
            c.status = c.mode;
            if (c.type == Command::QuietChats)
                c.uins.push_back(c.uin);
            bool accepted = client.submit(c);
            std::cout << "{\"submitted\":" << c.requestId << ",\"ok\":" << accepted << "}"
                      << std::endl;
        }
    }
    client.stop();
    return 0;
}
