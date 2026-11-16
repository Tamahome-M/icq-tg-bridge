#include "client.h"
#include "oscar.h"
#include "transport.h"
#include "dns.h"
#include "mobile_network.h"
#include "crypto.h"
#include <pthread.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <poll.h>
#include <errno.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <time.h>
#include <deque>
#include <set>
#include <algorithm>
namespace tmm {
using namespace wire;
namespace {
struct Guard {
    pthread_mutex_t &m;
    Guard(pthread_mutex_t &v) : m(v) {
        pthread_mutex_lock(&m);
    }
    ~Guard() {
        pthread_mutex_unlock(&m);
    }
};
void signalPipe(int fd) {
    char c = 1;
    ssize_t ignored = ::write(fd, &c, 1);
    (void)ignored;
}
void pipeDrain(int fd) {
    char b[64];
    while (::read(fd, b, sizeof b) > 0) {
    }
}
void makePipe(int p[2]) {
    if (pipe(p))
        throw Error(strerror(errno));
    for (int i = 0; i < 2; ++i) {
        fcntl(p[i], F_SETFL, O_NONBLOCK);
        fcntl(p[i], F_SETFD, FD_CLOEXEC);
    }
}
std::string basename(const std::string &s) {
    size_t n = s.find_last_of("/\\");
    return s.substr(n == std::string::npos ? 0 : n + 1);
}
void mkdirs(const std::string &s) {
    if (s.empty() || s.size() > 1024)
        throw Error("Неверный каталог медиа");
    for (size_t i = 1; i <= s.size(); ++i)
        if (i == s.size() || s[i] == '/') {
            std::string p = s.substr(0, i);
            if (mkdir(p.c_str(), 0700) && errno != EEXIST)
                throw Error("Не удалось создать каталог медиа");
            struct stat st;
            if (stat(p.c_str(), &st) || !S_ISDIR(st.st_mode))
                throw Error("Каталог медиа недоступен");
        }
}
unsigned mediaType(Command::Type type) {
    switch (type) {
    case Command::Avatar:
        return 1;
    case Command::Photo:
        return 0x80;
    case Command::History:
    case Command::Discussion:
        return 0x81;
    case Command::Video:
        return 0x82;
    case Command::Voice:
        return 0x83;
    case Command::AllChats:
        return 0x84;
    case Command::OpenChat:
        return 0x85;
    case Command::File:
        return 0x86;
    default:
        return 0;
    }
}
struct Pending {
    Command command;
    unsigned kind, next, total;
    int fd;
    uint64_t bytes, deadline;
    std::string path, name, data;
    ContactRecord desired;
    bool hasSsi;
    Event info;
    Pending()
        : kind(0), next(1), total(0), fd(-1), bytes(0), deadline(0), hasSsi(false),
          info(Event::ContactInfo) {}
};
struct Upload {
    Command command;
    int fd;
    unsigned part, total;
    uint64_t bytes, size;
    Upload() : fd(-1), part(1), total(0), bytes(0), size(0) {}
};
} // namespace
class Client::Impl : public Cancellation {
  public:
    mutable pthread_mutex_t mutex;
    pthread_cond_t drained;
    pthread_t thread;
    bool running, joinable, stopping, restart, online, permanentFailure, finishing, prefetchOnly;
    int wake[2], notify[2];
    uint32_t nextId, generation, activeGeneration;
    ClientConfig configured, cfg;
    std::deque<Command> commands;
    std::deque<Event> events;
    size_t eventBytes;
    MobileNetwork mobile;
    Transport socket;
    unsigned sequence, metaSeq;
    uint64_t lastRx, lastPing;
    std::vector<ContactRecord> roster;
    std::map<uint32_t, Pending> pending;
    std::map<unsigned, uint32_t> metas;
    Upload upload;
    std::vector<std::string> startupAddresses;
    std::string pinned, dnsHost, dnsServer;
    bool dnsTried, dnsPolicySet, startupDnsEnabled;
    std::string launchDnsHost, launchDnsServer;
    uint32_t stamp;
    Impl()
        : running(false), joinable(false), stopping(false), restart(false), online(false),
          permanentFailure(false), finishing(false), prefetchOnly(false), nextId(1), generation(0),
          activeGeneration(0), eventBytes(0), socket(*this), sequence(1), metaSeq(1), lastRx(0),
          lastPing(0), dnsTried(false), dnsPolicySet(false), startupDnsEnabled(false), stamp(0) {
        wake[0] = wake[1] = notify[0] = notify[1] = -1;
        pthread_mutex_init(&mutex, 0);
        pthread_cond_init(&drained, 0);
        try {
            makePipe(wake);
            makePipe(notify);
        } catch (...) {
            if (wake[0] >= 0) {
                ::close(wake[0]);
                ::close(wake[1]);
            }
            pthread_cond_destroy(&drained);
            pthread_mutex_destroy(&mutex);
            throw;
        }
    }
    ~Impl() {
        stop();
        if (joinable)
            pthread_join(thread, 0);
        cleanup();
        for (int i = 0; i < 2; ++i) {
            ::close(wake[i]);
            ::close(notify[i]);
        }
        pthread_cond_destroy(&drained);
        pthread_mutex_destroy(&mutex);
    }
    virtual bool cancelled() const {
        Guard g(mutex);
        return stopping;
    }
    virtual int wakeFd() const {
        return wake[0];
    }
    virtual void bindSocket(int fd) {
        std::string error;
        if (!mobile.bind_socket(fd, error))
            throw Error(error);
    }
    void stop() {
        Guard g(mutex);
        stopping = true;
        restart = false;
        commands.clear();
        pthread_cond_broadcast(&drained);
        signalPipe(wake[1]);
    }
    static size_t eventSize(const Event &e) {
        size_t n = sizeof(Event) + e.text.size() + e.path.size() + e.filename.size() +
                   e.token.size() + e.nativeId.size();
        for (size_t i = 0; i < e.contacts.size(); ++i)
            n += sizeof(ContactRecord) + e.contacts[i].name.size() + e.contacts[i].group.size() +
                 e.contacts[i].avatarHash.size();
        for (size_t i = 0; i < e.messages.size(); ++i)
            n += sizeof(MessageRecord) + e.messages[i].text.size() +
                 e.messages[i].senderName.size() + e.messages[i].token.size() +
                 e.messages[i].nativeId.size() + e.messages[i].url.size();
        for (std::map<std::string, std::string>::const_iterator i = e.fields.begin();
             i != e.fields.end(); ++i)
            n += 64 + i->first.size() + i->second.size();
        return n;
    }
    bool post(Event e, bool wait = true) {
        e.generation = activeGeneration;
        size_t size = eventSize(e);
        if (size > 2 * 1024 * 1024)
            throw Error("Слишком большое событие интерфейса");
        Guard g(mutex);
        while (events.size() >= 128 || eventBytes + size > 2 * 1024 * 1024) {
            if (stopping || !wait)
                return false;
            if (e.type == Event::Progress)
                return true;
            pthread_cond_wait(&drained, &mutex);
        }
        events.push_back(e);
        eventBytes += size;
        signalPipe(notify[1]);
        return true;
    }
    void state(unsigned n, const std::string &text) {
        Event e(Event::State);
        e.state = n;
        e.text = text;
        post(e);
    }
    void error(uint32_t id, uint32_t who, const std::string &text, int code = 1) {
        Event e(Event::Error);
        e.requestId = id;
        e.uin = who;
        e.text = text;
        e.error = code;
        post(e);
    }
    void sendFlap(unsigned channel, const std::string &body) {
        socket.write(flap(channel, ++sequence, body), monotonicMs() + 120000);
    }
    void send(unsigned family, unsigned subtype, const std::string &data = std::string(),
              uint32_t id = 0) {
        sendFlap(2, snac(family, subtype, data, id));
    }
    std::string readFlap(unsigned &channel, uint64_t deadline) {
        std::string header = socket.read(6, deadline);
        Reader h(header);
        if (h.u8() != 42)
            throw Error("Неверный заголовок OSCAR");
        channel = h.u8();
        h.u16();
        unsigned size = h.u16();
        std::string body = socket.read(size, deadline);
        lastRx = monotonicMs();
        return body;
    }
    Snac receive(uint64_t deadline) {
        for (;;) {
            unsigned ch;
            std::string body = readFlap(ch, deadline);
            if (ch == 2)
                return snac(body);
            if (ch == 4) {
                Reader r(body);
                Tlvs t = tlvs(r);
                throw Error(t.count(8) ? "Сервер отказал в подключении" : "Сервер закрыл сеанс");
            }
            if (ch == 5)
                return Snac();
            throw Error("Неожиданный пакет OSCAR");
        }
    }
    Snac expect(unsigned f, unsigned s, uint64_t deadline) {
        for (;;) {
            Snac a = receive(deadline);
            if (a.family == f && a.subtype == s)
                return a;
            dispatch(a);
        }
    }
    std::vector<std::string> resolve(const std::string &host, bool startup) {
        if (startup && host != launchDnsHost)
            throw Error("Адрес сервера изменён: перезапустите приложение для DNS");
        if (isIPv4(host))
            return std::vector<std::string>(1, host);
        if (startup) {
            if (dnsTried && (dnsHost != host || dnsServer != cfg.dnsServer))
                throw Error("Настройки DNS изменены: перезапустите приложение");
            if (!pinned.empty())
                return std::vector<std::string>(1, pinned);
            if (!dnsTried) {
                dnsTried = true;
                dnsHost = host;
                dnsServer = cfg.dnsServer;
                startupAddresses = resolveDns(host, cfg.dnsServer, *this);
            }
            if (startupAddresses.empty())
                throw Error("DNS: нужен перезапуск приложения");
            return startupAddresses;
        }
        std::vector<DnsServer> servers = systemDnsServers();
        if (servers.empty())
            throw Error("Системный DNS APN недоступен");
        std::string failure;
        for (size_t i = 0; i < servers.size(); ++i) {
            try {
                return resolveDns(host, servers[i].address, *this, false, servers[i].port);
            } catch (const std::exception &e) {
                failure = e.what();
                if (cancelled())
                    throw;
            }
        }
        throw Error(failure);
    }
    void open(const std::string &host, unsigned port, const std::string &forced = std::string()) {
        std::vector<std::string> ips = forced.empty()
                                           ? resolve(host, cfg.startupDns && host == cfg.host)
                                           : std::vector<std::string>(1, forced);
        std::string failure;
        bool connected = false;
        for (size_t i = 0; i < ips.size(); ++i) {
            try {
                socket.connect(ips[i], port, monotonicMs() + 20000);
                connected = true;
                break;
            } catch (const std::exception &e) {
                failure = e.what();
                socket.close();
                if (cancelled())
                    throw;
            }
        }
        if (!connected)
            throw Error(failure);
        uint64_t deadline = monotonicMs() + 45000;
        unsigned ch;
        std::string body = readFlap(ch, deadline);
        if (ch != 1 || body != be32(1))
            throw Error("Неверное приветствие сервера");
        if (cfg.encryption) {
            std::string key, nonce, error;
            if (!crypto::derivePsk(cfg.psk, key, error) || !crypto::randomBytes(16, nonce, error)) {
                permanentFailure = true;
                throw Error(error);
            }
            std::string request = crypto::clientHello(key, nonce);
            sendFlap(0x7e, request);
            std::string response = readFlap(ch, deadline), finish, keys;
            if (ch != 0x7e ||
                !crypto::finishHandshake(key, request, response, finish, keys, error)) {
                permanentFailure = true;
                throw Error(error.empty() ? "Сервер не поддерживает TMME" : error);
            }
            sendFlap(0x7e, finish);
            socket.secure(keys);
            body = readFlap(ch, deadline);
            if (ch != 1 || body != be32(1))
                throw Error("Неверное защищённое приветствие");
        }
    }
    void profile() {
        std::string body = p8("Motorola V8 native Linux") + be16(240) + be16(320) + be32(32768) +
                           be16(19) + be16(131);
        for (std::map<unsigned, unsigned>::const_iterator i = cfg.media.begin();
             i != cfg.media.end(); ++i)
            if (i->first != 19)
                body += be16(i->first) + be16(i->second);
        if (!cfg.media.count(14))
            body += be16(14) + be16(cfg.networkMask & 4 ? 1 : 2);
        if (!cfg.media.count(15))
            body += be16(15) + be16(cfg.networkMask & 2 ? 1 : 2);
        if (!cfg.media.count(16))
            body += be16(16) + be16(cfg.networkMask & 1 ? 1 : 2);
        send(1, 0xf2, body);
    }
    void quiet() {
        if (cfg.quietChats.size() > 256)
            throw Error("Слишком много тихих чатов");
        std::string body = be16(cfg.quietChats.size());
        for (size_t i = 0; i < cfg.quietChats.size(); ++i) {
            if (!cfg.quietChats[i])
                throw Error("Неверный UIN тихого чата");
            body += be32(cfg.quietChats[i]);
        }
        send(1, 0xf3, body);
    }
    void meta(unsigned type, unsigned seq, const std::string &data = std::string()) {
        std::string body = le32(uin(cfg.uin)) + le16(type) + le16(seq) + data;
        send(0x15, 2, tlv(1, le16(body.size()) + body));
    }
    void login(const std::string &ip) {
        open(cfg.host, cfg.port, ip);
        uint64_t deadline = monotonicMs() + 60000;
        Tlvs reply;
        if (cfg.md5Login) {
            sendFlap(1, be32(1));
            send(0x17, 6, tlv(1, cfg.uin));
            Snac keyReply = expect(0x17, 7, deadline);
            Reader kr(keyReply.data);
            std::string key = kr.p16();
            std::string digest = crypto::md5(key + cfg.password + "AOL Instant Messenger (SM)");
            send(0x17, 2, tlv(1, cfg.uin) + tlv(0x25, digest) + tlv(3, "TeleMotoMax Native V8"));
            Snac loginReply = expect(0x17, 3, deadline);
            Reader lr(loginReply.data);
            reply = tlvs(lr);
        } else {
            static const unsigned char roast[16] = {0xf3, 0x26, 0x81, 0xc4, 0x39, 0x86, 0xdb, 0x92,
                                                    0x71, 0xa3, 0xb9, 0xe6, 0x53, 0x7a, 0x95, 0x7c};
            std::string password = cfg.password;
            for (size_t i = 0; i < password.size(); ++i)
                password[i] ^= roast[i % 16];
            sendFlap(1, be32(1) + tlv(1, cfg.uin) + tlv(2, password) +
                            tlv(3, "TeleMotoMax Native V8"));
            unsigned ch;
            std::string body = readFlap(ch, deadline);
            if (ch != 4)
                throw Error("Неверный ответ авторизации");
            Reader lr(body);
            reply = tlvs(lr);
        }
        if (reply.count(8)) {
            permanentFailure = true;
            throw Error("Неверный UIN или пароль");
        }
        if (reply[6].empty())
            throw Error("Сервер не выдал cookie");
        std::string host = cfg.host;
        unsigned port = cfg.port;
        if (!reply[5].empty()) {
            host = reply[5];
            size_t colon = host.rfind(':');
            if (colon != std::string::npos) {
                port = uin(host.substr(colon + 1));
                host.erase(colon);
            }
        }
        socket.close();
        open(host, port, host == cfg.host ? ip : std::string());
        sendFlap(1, be32(1) + tlv(6, reply[6]));
        expect(1, 3, deadline);
        unsigned fam[] = {1, 2, 3, 4, 9, 0x10, 0x13, 0x15};
        std::string versions, ready;
        for (unsigned i = 0; i < sizeof fam / sizeof fam[0]; ++i) {
            unsigned version = fam[i] == 1 || fam[i] == 0x13 ? 3 : 1;
            versions += be16(fam[i]) + be16(version);
            ready += be16(fam[i]) + be16(version) + be16(0x110) + be16(0x629);
        }
        send(1, 0x17, versions);
        profile();
        std::string caps("\x09\x46\x13\x49\x4c\x7f\x11\xd1\x82\x22\x44\x45\x53\x54\0\0", 16);
        caps += std::string("\x56\x3f\xc8\x09\x0b\x6f\x41\xbd\x9f\x79\x42\x26\x09\xdf\xa2\xf3", 16);
        caps += "TMM:";
        caps += char(1);
        caps += char(31);
        caps += char(1);
        caps += std::string(9, 0);
        send(2, 4, tlv(5, caps));
        send(1, 6);
        send(1, 0xe);
        send(2, 2);
        send(3, 2);
        send(4, 4);
        send(9, 2);
        send(0x13, 2);
        send(0x13, 4);
        stamp = 0;
        roster.clear();
        while (!stamp) {
            Snac a = receive(deadline);
            if (a.family == 0x13 && a.subtype == 6)
                wire::ssi(a, roster, stamp, cfg.ssiEncoding);
            else if (a.family == 1 && a.subtype == 7)
                send(1, 8, be16(1));
            else
                dispatch(a);
        }
        std::map<unsigned, std::string> groups;
        for (size_t i = 0; i < roster.size(); ++i)
            if (roster[i].type == 1)
                groups[roster[i].groupId] = roster[i].name;
        for (size_t i = 0; i < roster.size(); ++i) {
            roster[i].group = groups[roster[i].groupId];
            roster[i].network = roster[i].group.find("MAX") == 0       ? 1
                                : roster[i].group.find("eXpress") == 0 ? 2
                                                                       : 0;
        }
        Event e(Event::Roster);
        e.flag = true;
        e.contacts = roster;
        post(e);
        send(0x13, 7);
        send(1, 0x1e, tlv(6, be32(cfg.status)));
        quiet();
        send(1, 2, ready);
        meta(0x3c, 2);
        if (cfg.startupDns && pinned.empty())
            pinned = ip;
        lastRx = lastPing = monotonicMs();
        {
            Guard g(mutex);
            online = true;
        }
        state(Event::Online, "Подключено");
    }
    void cleanupPending(uint32_t id) {
        std::map<uint32_t, Pending>::iterator i = pending.find(id);
        if (i != pending.end()) {
            if (i->second.fd >= 0)
                ::close(i->second.fd);
            if (!i->second.path.empty())
                unlink(i->second.path.c_str());
            pending.erase(i);
        }
        for (std::map<unsigned, uint32_t>::iterator m = metas.begin(); m != metas.end();) {
            if (m->second == id)
                metas.erase(m++);
            else
                ++m;
        }
        if (upload.fd >= 0 && upload.command.requestId == id) {
            ::close(upload.fd);
            upload = Upload();
        }
    }
    void cleanup() {
        socket.close();
        while (!pending.empty())
            cleanupPending(pending.begin()->first);
        metas.clear();
        if (upload.fd >= 0) {
            ::close(upload.fd);
            upload = Upload();
        }
    }
    void result(const Command &c, bool ok, const std::string &text = std::string()) {
        Event e(Event::CommandResult);
        e.requestId = c.requestId;
        e.uin = c.uin;
        e.flag = ok;
        e.text = text;
        post(e);
    }
    void handleMeta(const Snac &s) {
        Reader outer(s.data);
        Tlvs t = tlvs(outer);
        Reader r(t[1]);
        r.le16();
        r.le32();
        unsigned kind = r.le16(), seq = r.le16();
        if (kind == 0x41) {
            MessageRecord m;
            m.uin = m.sourceUin = r.le32();
            unsigned year = r.le16(), month = r.u8(), day = r.u8(), hour = r.u8(), minute = r.u8();
            struct tm tmv;
            memset(&tmv, 0, sizeof tmv);
            tmv.tm_year = year - 1900;
            tmv.tm_mon = month - 1;
            tmv.tm_mday = day;
            tmv.tm_hour = hour;
            tmv.tm_min = minute;
            tmv.tm_isdst = -1;
            // OSCAR offline dates are UTC, independent of the phone timezone.
            m.time = timegm(&tmv);
            unsigned type = r.le16(), len = r.le16();
            std::string raw = r.bytes(len);
            if (!raw.empty() && raw[raw.size() - 1] == 0)
                raw.erase(raw.size() - 1);
            if (type == 4) {
                size_t n = raw.find(char(0xfe));
                if (n != std::string::npos) {
                    m.url = raw.substr(n + 1);
                    raw.erase(n);
                }
            }
            m.text = raw;
            try {
                utf16(raw);
            } catch (...) {
                m.text = decode(raw, cfg.ssiEncoding);
            }
            if (r.left()) {
                Tlvs x = tlvs(r);
                m.senderName = x[0x9004];
            }
            Event e(Event::Message);
            e.uin = m.uin;
            e.messages.push_back(m);
            if (!post(e))
                throw Error("Отменено");
            return;
        }
        if (kind == 0x42) {
            meta(0x3e, seq);
            return;
        }
        if (kind != 0x7da || !metas.count(seq))
            return;
        uint32_t id = metas[seq];
        if (!pending.count(id)) {
            metas.erase(seq);
            return;
        }
        Pending &p = pending[id];
        unsigned part = r.le16(), ok = r.u8();
        if (ok != 0x0a) {
            if (p.command.type == Command::Search) {
                Event e(Event::Chats);
                e.requestId = id;
                post(e);
            } else
                error(id, p.command.uin, "Сведения недоступны", ok);
            cleanupPending(id);
            return;
        }
        if (part == 0x1a4 || part == 0x1ae) {
            r.le16();
            ContactRecord c;
            c.uin = r.le32();
            c.name = decode(r.bytes(r.le16()), cfg.ssiEncoding);
            std::string first = decode(r.bytes(r.le16()), cfg.ssiEncoding);
            r.bytes(r.le16());
            std::string email = decode(r.bytes(r.le16()), cfg.ssiEncoding);
            r.u8();
            c.status = r.le16();
            c.group = first;
            p.info.contacts.push_back(c);
            if (p.info.contacts.size() > 1024)
                throw Error("Слишком много результатов поиска");
            if (part == 0x1ae) {
                p.info.type = Event::Chats;
                p.info.requestId = id;
                post(p.info);
                cleanupPending(id);
            }
            return;
        }
        Event &e = p.info;
        e.requestId = id;
        e.uin = p.command.uin;
        if (part == 0xc8) {
            const char *fields[] = {"name",   "kind",  "last", "username", "members",
                                    "region", "phone", "fax",  "address",  "mobile"};
            for (unsigned n = 0; n < 10; ++n)
                e.fields[fields[n]] = decode(r.zle(), cfg.ssiEncoding);
        } else if (part == 0xdc) {
            e.fields["age"] = decimal(r.le16());
            r.u8();
            e.fields["url"] = decode(r.zle(), cfg.ssiEncoding);
            e.fields["year"] = decimal(r.le16());
            e.fields["month"] = decimal(r.u8());
            e.fields["day"] = decimal(r.u8());
        } else if (part == 0xd2) {
            for (unsigned n = 0; n < 6; ++n)
                r.zle();
            r.le16();
            e.fields["network"] = decode(r.zle(), cfg.ssiEncoding);
            e.fields["kind"] = decode(r.zle(), cfg.ssiEncoding);
            e.fields["marks"] = decode(r.zle(), cfg.ssiEncoding);
        } else if (part == 0xe6)
            e.fields["about"] = decode(r.zle(), cfg.ssiEncoding);
        else if (part == 0xfa) {
            e.text = e.fields["name"];
            post(e);
            cleanupPending(id);
        }
    }
    void handleBart(const Snac &s) {
        std::map<uint32_t, Pending>::iterator it = pending.find(s.request);
        if (it == pending.end())
            return;
        Pending &p = it->second;
        Bart b = bart(s.data);
        if (b.uin != p.command.uin || b.kind != p.kind || b.token != p.command.token ||
            b.part != p.next || (p.total && p.total != b.total)) {
            error(s.request, p.command.uin, "Нарушен порядок частей вложения");
            cleanupPending(s.request);
            return;
        }
        p.total = b.total;
        ++p.next;
        p.deadline = monotonicMs() + 180000;
        std::string data = b.data;
        if (p.kind == 0x81 || p.kind == 0x84 || p.kind == 0x85) {
            if (p.data.size() + data.size() > 32768)
                throw Error("Слишком большой ответ истории");
            p.data += data;
        } else {
            if (p.next == 2) {
                if (p.kind == 0x86) {
                    Reader f(data);
                    p.name = f.p8();
                    data = f.bytes(f.left());
                }
                mkdirs(cfg.cacheDir);
                std::string pattern = cfg.cacheDir + "/media-XXXXXX";
                std::vector<char> path(pattern.begin(), pattern.end());
                path.push_back(0);
                p.fd = mkstemp(&path[0]);
                if (p.fd < 0)
                    throw Error("Не удалось создать файл медиа");
                fcntl(p.fd, F_SETFD, FD_CLOEXEC);
                p.path = &path[0];
            }
            if (p.bytes + data.size() > cfg.maxMediaBytes) {
                error(s.request, p.command.uin, "Вложение больше установленного лимита");
                cleanupPending(s.request);
                return;
            }
            size_t off = 0;
            while (off < data.size()) {
                ssize_t n = ::write(p.fd, data.data() + off, data.size() - off);
                if (n < 0 && errno == EINTR)
                    continue;
                if (n <= 0)
                    throw Error("Ошибка записи вложения");
                off += n;
            }
            p.bytes += data.size();
            Event progress(Event::Progress);
            progress.requestId = s.request;
            progress.uin = b.uin;
            progress.bytes = p.bytes;
            progress.kind = p.kind;
            post(progress);
        }
        if (b.part != b.total)
            return;
        Event e;
        e.requestId = s.request;
        e.uin = b.uin;
        e.kind = p.kind;
        e.token = p.command.token;
        if (p.kind == 0x81) {
            e.type = Event::History;
            history(p.data, b.uin, e.messages, e.more);
            e.offset = p.command.offset + e.messages.size();
        } else if (p.kind == 0x84) {
            e.type = Event::Chats;
            chats(p.data, e.contacts, e.more);
            e.offset = p.command.offset + e.contacts.size();
        } else if (p.kind == 0x85) {
            e.type = Event::CommandResult;
            e.flag = p.data == std::string(1, 0);
            if (!e.flag)
                e.text = "Не удалось открыть чат";
        } else {
            if (p.fd >= 0) {
                if (::close(p.fd))
                    throw Error("Не удалось сохранить вложение");
                p.fd = -1;
            }
            std::string extension = p.kind == 1 || p.kind == 0x80      ? ".jpg"
                                    : p.kind == 0x82 || p.kind == 0x83 ? ".3gp"
                                                                       : "";
            if (p.kind == 0x86) {
                size_t dot = p.name.rfind('.');
                if (dot != std::string::npos && p.name.size() - dot <= 13) {
                    extension = p.name.substr(dot);
                    for (size_t x = 1; x < extension.size(); ++x)
                        if (!((extension[x] >= 'a' && extension[x] <= 'z') ||
                              (extension[x] >= 'A' && extension[x] <= 'Z') ||
                              (extension[x] >= '0' && extension[x] <= '9'))) {
                            extension.clear();
                            break;
                        }
                }
            }
            if (!extension.empty()) {
                std::string complete = p.path + extension;
                if (rename(p.path.c_str(), complete.c_str()))
                    throw Error("Не удалось завершить сохранение медиа");
                p.path = complete;
            }
            e.type = Event::Media;
            e.path = p.path;
            e.filename = p.name;
            e.bytes = p.bytes;
            e.mime = p.kind == 1 || p.kind == 0x80 ? "image/jpeg"
                     : p.kind == 0x83              ? "audio/3gpp"
                     : p.kind == 0x82              ? "video/3gpp"
                                                   : "application/octet-stream";
            p.path.clear();
        }
        post(e);
        cleanupPending(s.request);
    }
    void dispatch(const Snac &s) {
        if (s.subtype == 1) {
            Reader r(s.data);
            unsigned code = r.u16();
            std::string text = "Ошибка сервера " + decimal(code);
            if (r.left()) {
                Tlvs t = tlvs(r);
                if (t.count(0x9003))
                    text = t[0x9003];
            }
            uint32_t who = pending.count(s.request) ? pending[s.request].command.uin : 0;
            error(s.request, who, text, code);
            cleanupPending(s.request);
            return;
        }
        if (s.family == 3 && (s.subtype == 11 || s.subtype == 12)) {
            Reader r(s.data);
            while (r.left()) {
                ContactRecord c;
                c.uin = uin(r.p8());
                if (s.subtype == 11) {
                    r.u16();
                    Tlvs t = tlvs(r, r.u16());
                    if (t[6].size() == 4) {
                        Reader status(t[6]);
                        c.status = status.u32();
                    } else
                        c.status = 0;
                    if (t.count(0x1d)) {
                        Reader br(t[0x1d]);
                        while (br.left()) {
                            unsigned kind = br.u16();
                            br.u8();
                            std::string h = br.p8();
                            if (kind == 1)
                                c.avatarHash = h;
                        }
                    }
                }
                for (size_t i = 0; i < roster.size(); ++i)
                    if (roster[i].uin == c.uin && roster[i].type == 0) {
                        roster[i].status = c.status;
                        if (!c.avatarHash.empty())
                            roster[i].avatarHash = c.avatarHash;
                    }
                Event e(Event::Presence);
                e.uin = c.uin;
                e.status = c.status;
                e.contacts.push_back(c);
                post(e);
            }
            return;
        }
        if (s.family == 4 && s.subtype == 7) {
            std::string ack;
            MessageRecord m = incoming(s, ack, cfg.ssiEncoding);
            Event e(Event::Message);
            e.uin = m.uin;
            e.silent = m.silent;
            e.messages.push_back(m);
            if (!post(e))
                throw Error("Отменено");
            if (!ack.empty())
                send(4, 11, ack);
            return;
        }
        if (s.family == 4 && (s.subtype == 12 || s.subtype == 0x15 || s.subtype == 0x16)) {
            Reader r(s.data);
            Event e(Event::Receipt);
            e.cookie = r.u64();
            if (s.subtype == 12)
                r.u16();
            e.uin = uin(r.p8());
            e.delivery = s.subtype == 0x16 ? 2 : 1;
            if (s.subtype == 0x15)
                e.nativeId = r.bytes(8);
            post(e);
            return;
        }
        if (s.family == 4 && s.subtype == 0x14) {
            Reader r(s.data);
            r.skip(10);
            Event e(Event::Typing);
            e.uin = uin(r.p8());
            e.flag = r.u16() == 2;
            post(e);
            return;
        }
        if (s.family == 0x13 && (s.subtype == 8 || s.subtype == 9 || s.subtype == 10)) {
            Event e(Event::Roster);
            uint32_t unused = 0;
            ssi(s, e.contacts, unused, cfg.ssiEncoding);
            for (size_t i = 0; i < e.contacts.size(); ++i)
                applyRecord(e.contacts[i]);
            post(e);
            return;
        }
        if (s.family == 0x13 && s.subtype == 14) {
            if (!pending.count(s.request))
                return;
            Reader r(s.data);
            bool ok = true;
            while (r.left())
                if (r.u16())
                    ok = false;
            if (ok && pending[s.request].hasSsi) {
                applyRecord(pending[s.request].desired);
                emitRoster();
            }
            result(pending[s.request].command, ok, ok ? "" : "Изменение контакта отклонено");
            cleanupPending(s.request);
            return;
        }
        if (s.family == 0x15 && s.subtype == 3) {
            handleMeta(s);
            return;
        }
        if (s.family == 0x10 && s.subtype == 7) {
            try {
                handleBart(s);
            } catch (const std::exception &e) {
                uint32_t who = pending.count(s.request) ? pending[s.request].command.uin : 0;
                error(s.request, who, e.what());
                cleanupPending(s.request);
            }
            return;
        }
        if (s.family == 0x10 && s.subtype == 10) {
            Reader r(s.data);
            Event e(Event::QuoteResult);
            e.requestId = s.request;
            e.flag = r.u8() == 0;
            e.text = r.bytes(r.left());
            if (pending.count(s.request))
                e.uin = pending[s.request].command.uin;
            post(e);
            cleanupPending(s.request);
            return;
        }
        if (s.family == 0x10 && s.subtype == 3) {
            Reader r(s.data);
            Event e(Event::CommandResult);
            e.requestId = s.request;
            e.uin = uin(r.p8());
            e.flag = r.u8() == 0;
            e.text = e.flag ? "Отправлено" : "Не удалось отправить вложение";
            post(e);
            cleanupPending(s.request);
            return;
        }
    }
    void applyRecord(ContactRecord c) {
        for (std::vector<ContactRecord>::iterator i = roster.begin(); i != roster.end(); ++i) {
            bool same = c.type == 1 ? i->type == 1 && i->groupId == c.groupId
                                    : i->type == c.type && i->uin == c.uin;
            if (same) {
                if (c.deleted)
                    roster.erase(i);
                else {
                    if (c.type == 0) {
                        c.status = i->status;
                        if (c.avatarHash.empty())
                            c.avatarHash = i->avatarHash;
                    }
                    *i = c;
                }
                return;
            }
        }
        if (!c.deleted) {
            if (roster.size() >= 4096)
                throw Error("Контакт-лист слишком большой");
            roster.push_back(c);
        }
    }
    void emitRoster() {
        std::map<unsigned, std::string> groups;
        for (size_t i = 0; i < roster.size(); ++i)
            if (roster[i].type == 1)
                groups[roster[i].groupId] = roster[i].name;
        for (size_t i = 0; i < roster.size(); ++i)
            roster[i].group = groups[roster[i].groupId];
        Event e(Event::Roster);
        e.flag = true;
        e.contacts = roster;
        post(e);
    }
    ContactRecord contact(uint32_t who) {
        for (size_t i = 0; i < roster.size(); ++i)
            if (roster[i].uin == who && roster[i].type == 0)
                return roster[i];
        ContactRecord c;
        c.uin = who;
        return c;
    }
    unsigned newItemId() {
        unsigned n = 1;
        for (size_t i = 0; i < roster.size(); ++i)
            n = std::max(n, std::max(roster[i].itemId, roster[i].groupId) + 1);
        for (std::map<uint32_t, Pending>::const_iterator i = pending.begin(); i != pending.end();
             ++i)
            if (i->second.hasSsi)
                n = std::max(n, std::max(i->second.desired.itemId, i->second.desired.groupId) + 1);
        if (n > 65535)
            throw Error("Нет свободных ID контакт-листа");
        return n;
    }
    void execute(Command c) {
        if (c.type == Command::CancelRequest) {
            cleanupPending(c.requestId);
            result(c, true, "Загрузка отменена");
            return;
        }
        if (c.type == Command::SendMessage) {
            if (c.text.empty() || c.text.size() > 16000)
                throw Error("Сообщение пустое или слишком длинное");
            if (!c.cookie) {
                std::string random, error;
                if (!crypto::randomBytes(8, random, error))
                    throw Error(error);
                Reader r(random);
                c.cookie = r.u64();
            }
            send(4, 6,
                 be64(c.cookie) + be16(1) + p8(decimal(c.uin)) + tlv(2, messageBody(c.text)) +
                     tlv(3, std::string()),
                 c.requestId);
            MessageRecord m;
            m.uin = m.sourceUin = c.uin;
            m.cookie = c.cookie;
            m.outgoing = true;
            m.text = c.text;
            m.time = time(0);
            Event e(Event::Message);
            e.requestId = c.requestId;
            e.uin = c.uin;
            e.messages.push_back(m);
            post(e);
            return;
        }
        if (c.type == Command::Typing) {
            send(4, 0x14, std::string(8, 0) + be16(1) + p8(decimal(c.uin)) + be16(c.flag ? 2 : 0));
            return;
        }
        if (c.type == Command::Status) {
            cfg.status = c.status;
            send(1, 0x1e, tlv(6, be32(c.status)));
            result(c, true);
            return;
        }
        if (c.type == Command::Settings) {
            cfg.media = c.media;
            profile();
            result(c, true);
            return;
        }
        if (c.type == Command::QuietChats) {
            cfg.quietChats = c.uins;
            quiet();
            result(c, true);
            return;
        }
        if (pending.size() >= 16)
            throw Error("Дождитесь завершения текущих запросов");
        Pending p;
        p.command = c;
        p.deadline = monotonicMs() + 180000;
        p.kind = mediaType(c.type);
        if (p.kind) {
            if (c.type == Command::History || c.type == Command::Discussion) {
                if (c.offset > 65535 || !c.limit || c.limit > 200)
                    throw Error("Неверная страница истории");
                c.token = be16(c.limit) + be16(c.offset) + std::string(1, 1) + std::string(11, 0);
            } else if (c.type == Command::AllChats) {
                c.token =
                    "P1" + be16(c.offset) +
                    std::string(1, char(std::min<uint32_t>(30, std::max<uint32_t>(1, c.limit)))) +
                    std::string(11, 0);
                if (!c.uin)
                    c.uin = uin(cfg.uin);
            } else if (c.type == Command::OpenChat) {
                c.token = be32(c.uin) + std::string(12, 0);
            } else if (c.type == Command::Avatar && c.token.empty())
                c.token = contact(c.uin).avatarHash;
            if (c.token.empty() && c.type == Command::Avatar)
                c.token = std::string(16, 0);
            if (c.token.size() != 16)
                throw Error("Нет токена вложения");
            p.command = c;
            pending[c.requestId] = p;
            std::string token = c.token;
            if (c.type == Command::Video && c.offset) {
                if (c.offset > 255)
                    throw Error("Неверный фрагмент видео");
                token += char(c.offset);
            }
            send(0x10, 6,
                 p8(decimal(c.uin)) + std::string(1, 1) + be16(p.kind) +
                     std::string(1, char(1 | (c.mode & 0x30))) + p8(token),
                 c.requestId);
            return;
        }
        if (c.type == Command::Quote) {
            if (c.nativeId.size() != 8 || !c.sourceUin)
                throw Error("Нет исходного сообщения для цитирования");
            pending[c.requestId] = p;
            send(0x10, 9, p8(decimal(c.uin)) + p8(decimal(c.sourceUin)) + c.nativeId, c.requestId);
            return;
        }
        if (c.type == Command::Search || c.type == Command::ContactInfo) {
            do {
                metaSeq = (metaSeq + 1) & 65535;
            } while (!metaSeq || metas.count(metaSeq));
            pending[c.requestId] = p;
            metas[metaSeq] = c.requestId;
            std::string query;
            if (c.type == Command::Search) {
                std::string text = cfg.ssiEncoding == "UTF-8" || cfg.ssiEncoding == "utf-8"
                                       ? c.text
                                       : encode1251(c.text);
                if (text.size() > 250)
                    throw Error("Запрос поиска слишком длинный");
                query = le16(0x55f) + be16(0x5401) + le16(text.size() + 3) + le16(text.size() + 1) +
                        text + std::string(1, 0);
            } else
                query = le16(0x4b2) + le32(c.uin);
            meta(0x7d0, metaSeq, query);
            return;
        }
        if (c.type == Command::UploadPhoto || c.type == Command::UploadVoice ||
            c.type == Command::UploadVideo || c.type == Command::UploadFile) {
            if (upload.fd >= 0)
                throw Error("Другая отправка ещё не закончена");
            int fd = ::open(c.path.c_str(), O_RDONLY);
            if (fd < 0)
                throw Error("Не удалось открыть файл");
            struct stat st;
            if (fstat(fd, &st) || !S_ISREG(st.st_mode) || st.st_size <= 0 ||
                uint64_t(st.st_size) > cfg.maxMediaBytes ||
                (c.type != Command::UploadFile && st.st_size > 4 * 1024 * 1024)) {
                ::close(fd);
                throw Error("Файл пустой, недоступен или превышает лимит");
            }
            fcntl(fd, F_SETFD, FD_CLOEXEC);
            upload = Upload();
            upload.fd = fd;
            upload.command = c;
            upload.size = st.st_size;
            upload.total = (st.st_size + 29999) / 30000;
            pending[c.requestId] = p;
            return;
        }
        if (c.type == Command::RemoveMe) {
            send(0x13, 0x16, p8(decimal(c.uin)), c.requestId);
            result(c, true, "Запрос удаления отправлен");
            return;
        }
        if (c.type == Command::RequestAuthorization || c.type == Command::GrantAuthorization ||
            c.type == Command::DenyAuthorization) {
            std::string reason = encode1251(c.text);
            unsigned subtype = c.type == Command::RequestAuthorization ? 0x18 : 0x1a;
            std::string body = p8(decimal(c.uin));
            if (subtype == 0x1a)
                body += char(c.type == Command::GrantAuthorization ? 1 : 0);
            body += p16(reason);
            if (subtype == 0x18)
                body += be16(0);
            send(0x13, subtype, body, c.requestId);
            result(c, true, "Запрос авторизации отправлен");
            return;
        }
        ContactRecord rec = contact(c.uin);
        unsigned action = 9;
        if (c.type == Command::AddContact) {
            rec.uin = c.uin;
            rec.groupId = c.groupId;
            rec.itemId = c.itemId ? c.itemId : newItemId();
            rec.name = c.text;
            action = 8;
        } else if (c.type == Command::RenameContact)
            rec.name = c.text;
        else if (c.type == Command::MoveContact)
            rec.groupId = c.groupId;
        else if (c.type == Command::DeleteChat)
            action = 10;
        else if (c.type == Command::AddGroup || c.type == Command::RenameGroup ||
                 c.type == Command::DeleteGroup) {
            rec = ContactRecord();
            rec.type = 1;
            rec.groupId = c.groupId ? c.groupId : newItemId();
            rec.name = c.text;
            action = c.type == Command::AddGroup ? 8 : c.type == Command::DeleteGroup ? 10 : 9;
        } else if (c.type == Command::Privacy) {
            if (c.mode != 2 && c.mode != 3 && c.mode != 14)
                throw Error("Неверный список приватности");
            rec.type = c.mode;
            rec.groupId = 0;
            rec.itemId = c.itemId ? c.itemId : newItemId();
            action = c.flag ? 8 : 10;
        } else
            throw Error("Неизвестная команда");
        rec.deleted = action == 10;
        p.hasSsi = true;
        p.desired = rec;
        pending[c.requestId] = p;
        send(0x13, 0x11);
        send(0x13, action, ssiItem(rec, cfg.ssiEncoding), c.requestId);
        send(0x13, 0x12);
    }
    void uploadPart() {
        if (upload.fd < 0)
            return;
        std::string chunk(30000, 0);
        ssize_t n;
        do {
            n = ::read(upload.fd, &chunk[0], chunk.size());
        } while (n < 0 && errno == EINTR);
        if (n <= 0)
            throw Error("Файл изменился во время отправки");
        chunk.resize(n);
        Command &c = upload.command;
        std::string body = p8(decimal(c.uin)) + be16(upload.part) + be16(upload.total);
        unsigned subtype = 2;
        if (c.type == Command::UploadFile) {
            subtype = 8;
            body += be32(upload.size);
        } else if (c.type == Command::UploadVoice || c.type == Command::UploadVideo) {
            subtype = c.type == Command::UploadVoice ? 4 : 5;
            body += be16(std::min<uint32_t>(c.duration, 65535));
        }
        body += p16(chunk);
        if (upload.part == 1) {
            if (subtype == 8) {
                std::string name = basename(c.path);
                if (name.size() > 200)
                    name.erase(200);
                body += p8(name) + std::string(1, char(c.mode));
            } else if (subtype == 4 || subtype == 5)
                body += p8(c.text.empty() ? (subtype == 4 ? "audio/amr" : "video/3gpp") : c.text);
        }
        send(0x10, subtype, body, c.requestId);
        upload.bytes += n;
        ++upload.part;
        Event e(Event::Progress);
        e.requestId = c.requestId;
        e.uin = c.uin;
        e.bytes = upload.bytes;
        e.total = upload.size;
        post(e);
        pending[c.requestId].deadline = monotonicMs() + 180000;
        if (upload.part > upload.total) {
            ::close(upload.fd);
            upload.fd = -1;
        }
    }
    void session() {
        unsigned failures = 0;
        for (;;) {
            if (cancelled())
                return;
            try {
                state(failures ? Event::Reconnecting : Event::Connecting,
                      failures ? "Переподключение" : "Подключение");
                std::string mobileError;
                if (!mobile.open(cfg, *this, mobileError))
                    throw Error(mobileError);
                std::vector<std::string> ips = resolve(cfg.host, cfg.startupDns);
                std::string reason;
                bool ok = false;
                for (size_t i = 0; i < ips.size(); ++i) {
                    try {
                        login(ips[i]);
                        ok = true;
                        break;
                    } catch (const std::exception &e) {
                        reason = e.what();
                        socket.close();
                        if (cancelled())
                            throw;
                        if (permanentFailure)
                            throw;
                    }
                }
                if (!ok)
                    throw Error(reason);
                failures = 0;
                for (;;) {
                    if (cancelled())
                        return;
                    Command c;
                    bool have = false;
                    {
                        Guard g(mutex);
                        if (!commands.empty()) {
                            c = commands.front();
                            commands.pop_front();
                            have = true;
                        }
                    }
                    if (have) {
                        try {
                            execute(c);
                        } catch (const std::exception &e) {
                            if (socket.failed())
                                throw;
                            cleanupPending(c.requestId);
                            error(c.requestId, c.uin, e.what());
                        }
                    }
                    uint64_t now = monotonicMs();
                    if (cfg.pingSeconds && now - lastPing >= uint64_t(cfg.pingSeconds) * 1000) {
                        if (cfg.missedPings &&
                            now - lastRx >= uint64_t(cfg.pingSeconds) * cfg.missedPings * 1000)
                            throw Error("Соединение не отвечает на пинги");
                        sendFlap(5, std::string());
                        send(1, 0xe);
                        lastPing = now;
                    }
                    if (upload.fd >= 0) {
                        try {
                            uploadPart();
                        } catch (const std::exception &e) {
                            if (socket.failed())
                                throw;
                            uint32_t id = upload.command.requestId, who = upload.command.uin;
                            cleanupPending(id);
                            error(id, who, e.what());
                        }
                    }
                    for (std::map<uint32_t, Pending>::iterator i = pending.begin();
                         i != pending.end();) {
                        uint32_t id = i->first;
                        bool expired = now >= i->second.deadline;
                        uint32_t who = i->second.command.uin;
                        ++i;
                        if (expired) {
                            error(id, who, "Время запроса истекло");
                            cleanupPending(id);
                        }
                    }
                    struct pollfd p[2];
                    p[0].fd = socket.fd();
                    p[0].events = POLLIN;
                    p[0].revents = 0;
                    p[1].fd = wake[0];
                    p[1].events = POLLIN;
                    p[1].revents = 0;
                    int n = poll(p, 2, socket.buffered() || have || upload.fd >= 0 ? 0 : 500);
                    if (n < 0 && errno != EINTR)
                        throw Error(strerror(errno));
                    if (p[1].revents)
                        pipeDrain(wake[0]);
                    if (socket.buffered() || p[0].revents) {
                        Snac s = receive(monotonicMs() + 180000);
                        dispatch(s);
                    }
                }
            } catch (const std::exception &e) {
                {
                    Guard g(mutex);
                    online = false;
                }
                if (!cancelled())
                    error(0, 0, e.what());
                for (std::map<uint32_t, Pending>::iterator i = pending.begin(); i != pending.end();
                     ++i)
                    if (!cancelled())
                        error(i->first, i->second.command.uin,
                              "Соединение прервано; запрос не повторён");
                cleanup();
                mobile.close();
                if (cancelled())
                    return;
                if (permanentFailure || (cfg.startupDns && dnsTried && startupAddresses.empty()) ||
                    !cfg.autoReconnect ||
                    (cfg.reconnectAttempts && ++failures > cfg.reconnectAttempts))
                    return;
                if (!cfg.reconnectAttempts)
                    ++failures;
                state(Event::Reconnecting, "Ожидание перед повторным подключением");
                uint64_t end = monotonicMs() + uint64_t(std::max(1U, cfg.reconnectSeconds)) * 1000;
                while (!cancelled() && monotonicMs() < end) {
                    struct pollfd p;
                    p.fd = wake[0];
                    p.events = POLLIN;
                    p.revents = 0;
                    poll(&p, 1, 250);
                    if (p.revents)
                        pipeDrain(wake[0]);
                }
            }
        }
    }
    static void *entry(void *p) {
        Impl *self = static_cast<Impl *>(p);
        for (;;) {
            bool begin, prefetch;
            {
                Guard g(self->mutex);
                begin = !self->stopping || self->restart;
                if (self->restart)
                    self->stopping = false;
                self->restart = false;
                prefetch = self->prefetchOnly;
                self->cfg = self->configured;
                self->activeGeneration = self->generation;
                self->online = false;
                self->permanentFailure = false;
                self->finishing = false;
                self->commands.clear();
            }
            std::string completed = "Отключено";
            try {
                if (begin && prefetch) {
                    std::string mobileError;
                    if (!self->mobile.open(self->cfg, *self, mobileError))
                        throw Error(mobileError);
                    self->resolve(self->cfg.host, true);
                    completed = "DNS при запуске выполнен";
                } else if (begin) {
                    self->session();
                }
            } catch (const std::exception &e) {
                if (!self->cancelled())
                    self->error(0, 0,
                                prefetch ? std::string("DNS при запуске: ") + e.what() : e.what(),
                                prefetch ? 195 : 1);
                if (prefetch)
                    completed = "DNS недоступен";
            } catch (...) {
                if (!self->cancelled())
                    self->error(0, 0, "Внутренняя ошибка сетевого потока");
            }
            // Cancellation/APN failure can precede the first DNS packet. Keep that
            // startup outcome sticky too: a later manual connect must not retry it.
            if (prefetch && !self->dnsTried) {
                self->dnsTried = true;
                self->dnsHost = self->cfg.host;
                self->dnsServer = self->cfg.dnsServer;
            }
            self->cleanup();
            self->mobile.close();
            {
                Guard g(self->mutex);
                self->finishing = true;
            }
            self->state(Event::Disconnected, completed);
            {
                Guard g(self->mutex);
                self->online = false;
                if (self->restart)
                    continue;
                self->running = false;
                break;
            }
        }
        return 0;
    }
};
Client::Client() : impl_(new Impl) {}
Client::~Client() {
    delete impl_;
}
void Client::configure(const ClientConfig &c) {
    Guard g(impl_->mutex);
    Impl &i = *impl_;
    if (!i.dnsPolicySet) {
        i.dnsPolicySet = true;
        i.startupDnsEnabled = c.startupDns;
        i.launchDnsHost = c.host;
        i.launchDnsServer = c.dnsServer;
    }
    i.configured = c;
    i.configured.startupDns = i.startupDnsEnabled;
    i.configured.dnsServer = i.launchDnsServer;
}
void Client::start() {
    launch(false);
}
void Client::prefetchDns() {
    launch(true);
}
void Client::launch(bool prefetch) {
    Impl &i = *impl_;
    pthread_mutex_lock(&i.mutex);
    if (!i.dnsPolicySet) {
        i.dnsPolicySet = true;
        i.startupDnsEnabled = i.configured.startupDns;
        i.launchDnsHost = i.configured.host;
        i.launchDnsServer = i.configured.dnsServer;
    }
    if (prefetch && (!i.configured.startupDns || isIPv4(i.configured.host))) {
        pthread_mutex_unlock(&i.mutex);
        return;
    }
    if (i.running) {
        if (!prefetch && (i.stopping || i.finishing || i.prefetchOnly)) {
            i.restart = true;
            i.prefetchOnly = false;
            ++i.generation;
        }
        pthread_mutex_unlock(&i.mutex);
        return;
    }
    bool join = i.joinable;
    pthread_t old = i.thread;
    i.joinable = false;
    pthread_mutex_unlock(&i.mutex);
    if (join)
        pthread_join(old, 0);
    pthread_mutex_lock(&i.mutex);
    i.running = true;
    i.prefetchOnly = prefetch;
    i.stopping = false;
    i.restart = false;
    ++i.generation;
    int failure = pthread_create(&i.thread, 0, Impl::entry, &i);
    if (failure) {
        i.running = false;
        i.activeGeneration = i.generation;
        if (prefetch && !i.dnsTried) {
            i.dnsTried = true;
            i.dnsHost = i.configured.host;
            i.dnsServer = i.configured.dnsServer;
        }
    } else
        i.joinable = true;
    pthread_mutex_unlock(&i.mutex);
    if (failure) {
        Event error(Event::Error);
        error.error = failure;
        error.text = "Не удалось запустить поток связи";
        i.post(error, false);
        Event state(Event::State);
        state.state = Event::Disconnected;
        state.text = error.text;
        i.post(state, false);
    }
}
void Client::stop() {
    impl_->stop();
}
int Client::eventFd() const {
    return impl_->notify[0];
}
uint32_t Client::nextRequestId() {
    Guard g(impl_->mutex);
    if (++impl_->nextId == 0)
        ++impl_->nextId;
    return impl_->nextId;
}
uint32_t Client::sessionGeneration() const {
    Guard g(impl_->mutex);
    return impl_->generation;
}
bool Client::submit(const Command &command) {
    Guard g(impl_->mutex);
    if (!impl_->online || impl_->stopping || impl_->commands.size() >= 32 ||
        command.text.size() > 16384 || command.path.size() > 1024 || command.token.size() > 17 ||
        command.nativeId.size() > 8 || command.uins.size() > 256 || command.media.size() > 32)
        return false;
    Command c = command;
    if (!c.requestId)
        c.requestId = ++impl_->nextId;
    impl_->commands.push_back(c);
    signalPipe(impl_->wake[1]);
    return true;
}
void Client::drainEvents(std::vector<Event> &out) {
    Guard g(impl_->mutex);
    pipeDrain(impl_->notify[0]);
    while (!impl_->events.empty()) {
        out.push_back(impl_->events.front());
        impl_->eventBytes -= Impl::eventSize(impl_->events.front());
        impl_->events.pop_front();
    }
    pthread_cond_broadcast(&impl_->drained);
}
} // namespace tmm
