#include "storage.h"
#include "settings.h"
#include "crypto.h"
#include <dirent.h>
#include <unistd.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <algorithm>
#include <set>
#include <sys/stat.h>
namespace tmm {
namespace {
const size_t HISTORY_LIMIT = 999, FILE_LIMIT = 2 * 1024 * 1024;
void number(std::string &s, uint32_t v) {
    for (int n = 24; n >= 0; n -= 8)
        s += (char)(v >> n);
}
void field(std::string &s, const std::string &v) {
    number(s, v.size());
    s += v;
}
struct Reader {
    const std::string &s;
    size_t pos;
    bool ok;
    Reader(const std::string &data, size_t start) : s(data), pos(start), ok(true) {}
    uint32_t number() {
        if (!ok || s.size() - pos < 4) {
            ok = false;
            return 0;
        }
        uint32_t v = 0;
        for (unsigned i = 0; i < 4; ++i)
            v = (v << 8) | (unsigned char)s[pos++];
        return v;
    }
    std::string field(size_t limit = 65536) {
        size_t n = number();
        if (!ok || n > limit || n > s.size() - pos) {
            ok = false;
            return "";
        }
        std::string v = s.substr(pos, n);
        pos += n;
        return v;
    }
    bool done() const {
        return ok && pos == s.size();
    }
};
std::string decimal(uint32_t n) {
    char b[32];
    snprintf(b, sizeof b, "%u", (unsigned)n);
    return b;
}
bool removeFile(const std::string &path, std::string &error) {
    if (unlink(path.c_str()) == 0 || errno == ENOENT)
        return true;
    error = std::string("Cannot remove local file: ") + strerror(errno);
    return false;
}
bool validMessage(const MessageRecord &m) {
    return m.text.size() <= 65536 && m.senderName.size() <= 4096 && m.token.size() <= 4096 &&
           m.url.size() <= 8192 && m.nativeId.size() <= 4096;
}
void writeMessage(std::string &s, const MessageRecord &m) {
    number(s, m.uin);
    number(s, m.sourceUin);
    number(s, m.discussionUin);
    number(s, m.time);
    number(s, (uint32_t)(m.cookie >> 32));
    number(s, (uint32_t)m.cookie);
    number(s, m.kind);
    number(s, m.delivery);
    number(s, (m.silent ? 1 : 0) | (m.outgoing ? 2 : 0));
    field(s, m.nativeId);
    field(s, m.text);
    field(s, m.senderName);
    field(s, m.token);
    field(s, m.url);
}
MessageRecord readMessage(Reader &r) {
    MessageRecord m;
    m.uin = r.number();
    m.sourceUin = r.number();
    m.discussionUin = r.number();
    m.time = r.number();
    m.cookie = uint64_t(r.number()) << 32;
    m.cookie |= r.number();
    m.kind = r.number();
    m.delivery = r.number();
    unsigned flags = r.number();
    m.silent = flags & 1;
    m.outgoing = flags & 2;
    m.nativeId = r.field(4096);
    m.text = r.field();
    m.senderName = r.field(4096);
    m.token = r.field(4096);
    m.url = r.field(8192);
    return m;
}
bool sameMessage(const MessageRecord &a, const MessageRecord &b) {
    if (a.uin != b.uin || a.outgoing != b.outgoing)
        return false;
    // Each split fragment has its own delivery cookie, but all fragments
    // retain the original quote locator. Never collapse them by locator alone.
    if (a.cookie && b.cookie)
        return a.cookie == b.cookie;
    return !a.nativeId.empty() && a.nativeId == b.nativeId && a.text == b.text &&
           a.kind == b.kind && a.token == b.token;
}
} // namespace
Storage::Storage(const std::string &base) : base_(base), historyLimit_(200) {}
bool cleanupCachedMedia(const std::string &base, std::string &error) {
    std::string accounts = base + "/accounts";
    struct stat st;
    if (lstat(accounts.c_str(), &st) < 0) {
        if (errno == ENOENT)
            return true;
        error = "Cannot inspect account caches";
        return false;
    }
    if (!S_ISDIR(st.st_mode)) {
        error = "Invalid account directory";
        return false;
    }
    DIR *root = opendir(accounts.c_str());
    if (!root) {
        error = "Cannot enumerate account caches";
        return false;
    }
    bool ok = true;
    struct dirent *entry;
    for (;;) {
        errno = 0;
        entry = readdir(root);
        if (!entry) {
            if (errno)
                ok = false;
            break;
        }
        std::string name = entry->d_name;
        if (name.size() != 64 || name.find_first_not_of("0123456789abcdef") != std::string::npos)
            continue;
        std::string account = accounts + "/" + name;
        if (lstat(account.c_str(), &st) < 0 || !S_ISDIR(st.st_mode))
            continue;
        std::string cache = account + "/cache";
        if (lstat(cache.c_str(), &st) < 0 || !S_ISDIR(st.st_mode))
            continue;
        DIR *dir = opendir(cache.c_str());
        if (!dir) {
            ok = false;
            continue;
        }
        struct dirent *item;
        for (;;) {
            errno = 0;
            item = readdir(dir);
            if (!item) {
                if (errno)
                    ok = false;
                break;
            }
            std::string fileName = item->d_name;
            if (fileName.size() < 12 || fileName.compare(0, 6, "media-") != 0)
                continue;
            std::string random = fileName.substr(6, 6), suffix = fileName.substr(12);
            if (random.find_first_not_of(
                    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") !=
                std::string::npos)
                continue;
            if (!suffix.empty() && suffix != ".jpg" && suffix != ".3gp" && suffix != ".amr" &&
                suffix != ".bin")
                continue;
            std::string path = cache + "/" + fileName;
            if (lstat(path.c_str(), &st) == 0 && S_ISREG(st.st_mode) && unlink(path.c_str()) < 0)
                ok = false;
        }
        closedir(dir);
    }
    closedir(root);
    if (!ok)
        error = "Cannot remove some old media cache files";
    return ok;
}
void Storage::setHistoryLimit(unsigned count) {
    historyLimit_ = std::min(count, (unsigned)HISTORY_LIMIT);
}
bool Storage::setAccount(const std::string &host, unsigned port, uint32_t uin, std::string &error) {
    scope_.clear();
    if (host.empty() || !uin || port == 0 || port > 65535) {
        error = "Invalid account";
        return false;
    }
    std::string identity = host;
    number(identity, port);
    number(identity, uin);
    std::string hash = crypto::sha256(identity), hex;
    const char *digits = "0123456789abcdef";
    for (size_t i = 0; i < hash.size(); ++i) {
        unsigned c = (unsigned char)hash[i];
        hex += digits[c >> 4];
        hex += digits[c & 15];
    }
    std::string dir = base_ + "/accounts/" + hex;
    if (!ensureDirectory(dir, error))
        return false;
    scope_ = dir;
    return true;
}
std::string Storage::file(const char *kind, uint32_t uin) const {
    return scope_.empty() ? "" : scope_ + "/" + kind + "-" + decimal(uin) + ".dat";
}
bool Storage::loadHistory(uint32_t uin, std::vector<MessageRecord> &out, size_t limit) const {
    out.clear();
    if (scope_.empty() || !uin)
        return false;
    std::string s;
    if (!readBounded(file("history", uin), s, FILE_LIMIT))
        return errno == ENOENT;
    if (s.size() < 8 || s.compare(0, 4, "TMH1") != 0)
        return false;
    Reader r(s, 4);
    size_t count = r.number();
    if (count > HISTORY_LIMIT)
        return false;
    limit = std::min(limit, HISTORY_LIMIT);
    std::vector<MessageRecord> parsed;
    parsed.reserve(std::min(count, limit));
    for (size_t i = 0; i < count && r.ok; ++i) {
        MessageRecord m = readMessage(r);
        if (m.uin != uin)
            r.ok = false;
        if (count - i <= limit)
            parsed.push_back(m);
    }
    if (!r.done())
        return false;
    out.swap(parsed);
    return true;
}
bool Storage::saveHistory(uint32_t uin, const std::vector<MessageRecord> &items,
                          std::string &error) {
    if (scope_.empty() || !uin) {
        error = "No account/chat selected";
        return false;
    }
    // Trim both count and encoded bytes. Long messages cannot make the file
    // written here exceed the bounds accepted by the reader on next launch.
    size_t begin = items.size() > historyLimit_ ? items.size() - historyLimit_ : 0, total = 8;
    for (size_t i = items.size(); i > begin; --i) {
        const MessageRecord &m = items[i - 1];
        if (m.uin != uin || !validMessage(m)) {
            error = "Invalid history record";
            return false;
        }
        size_t bytes = 56 + m.nativeId.size() + m.text.size() + m.senderName.size() +
                       m.token.size() + m.url.size();
        if (bytes > FILE_LIMIT - total) {
            begin = i;
            break;
        }
        total += bytes;
    }
    std::string s = "TMH1";
    number(s, items.size() - begin);
    s.reserve(total);
    for (size_t i = begin; i < items.size(); ++i)
        writeMessage(s, items[i]);
    return atomicWrite(file("history", uin), s, error);
}
bool Storage::appendHistory(uint32_t uin, const MessageRecord &message, std::string &error) {
    if (!historyLimit_)
        return true;
    std::vector<MessageRecord> items;
    if (!loadHistory(uin, items, HISTORY_LIMIT)) {
        error = "Local history is damaged; not overwritten";
        return false;
    }
    for (size_t i = 0; i < items.size(); ++i)
        if (sameMessage(items[i], message)) {
            MessageRecord updated = message;
            // A delayed redelivery or a history response may know less than
            // the receipt already stored for this outgoing message.
            updated.delivery = std::max(updated.delivery, items[i].delivery);
            if (!updated.cookie)
                updated.cookie = items[i].cookie;
            if (updated.nativeId.empty())
                updated.nativeId = items[i].nativeId;
            items[i] = updated;
            return saveHistory(uin, items, error);
        }
    items.push_back(message);
    return saveHistory(uin, items, error);
}
bool Storage::updateReceipt(uint32_t uin, uint64_t cookie, unsigned delivery,
                            const std::string &nativeId, std::string &error) {
    if (!cookie || delivery > 2 || nativeId.size() > 4096) {
        error = "Invalid receipt";
        return false;
    }
    std::vector<MessageRecord> items;
    if (!loadHistory(uin, items, HISTORY_LIMIT)) {
        error = "Local history is damaged; not overwritten";
        return false;
    }
    for (size_t i = 0; i < items.size(); ++i) {
        MessageRecord &m = items[i];
        if (!m.outgoing || m.cookie != cookie)
            continue;
        bool changed = false;
        if (delivery > m.delivery) {
            m.delivery = delivery;
            changed = true;
        }
        if (!nativeId.empty() && m.nativeId != nativeId) {
            m.nativeId = nativeId;
            changed = true;
        }
        if (!changed)
            return true;
        // Updating a receipt must not prune old history, including when the
        // user disabled saving new messages after sending this one.
        unsigned previous = historyLimit_;
        historyLimit_ = HISTORY_LIMIT;
        bool ok = saveHistory(uin, items, error);
        historyLimit_ = previous;
        return ok;
    }
    return true;
}
bool Storage::clearHistory(uint32_t uin, std::string &error) {
    return !scope_.empty() && uin && removeFile(file("history", uin), error);
}
bool Storage::clearAllHistory(std::string &error) {
    if (scope_.empty()) {
        error = "No account selected";
        return false;
    }
    DIR *d = opendir(scope_.c_str());
    if (!d) {
        error = "Cannot open account directory";
        return false;
    }
    bool ok = true;
    struct dirent *e;
    for (;;) {
        errno = 0;
        e = readdir(d);
        if (!e) {
            if (errno) {
                error = "Cannot enumerate local history";
                ok = false;
            }
            break;
        }
        std::string n = e->d_name;
        if (n.size() > 12 && n.compare(0, 8, "history-") == 0 &&
            n.compare(n.size() - 4, 4, ".dat") == 0) {
            bool digits = true;
            for (size_t i = 8; i < n.size() - 4; ++i)
                if (n[i] < '0' || n[i] > '9')
                    digits = false;
            if (digits && !removeFile(scope_ + "/" + n, error))
                ok = false;
        }
    }
    closedir(d);
    return ok;
}
std::string Storage::loadDraft(uint32_t uin) const {
    std::string s;
    if (scope_.empty() || !uin || !readBounded(file("draft", uin), s, 65536))
        return "";
    return s;
}
bool Storage::saveDraft(uint32_t uin, const std::string &s, std::string &error) {
    if (scope_.empty() || !uin || s.size() > 65536) {
        error = "Invalid draft";
        return false;
    }
    return atomicWrite(file("draft", uin), s, error);
}
std::vector<std::string> Storage::templates() const {
    std::vector<std::string> items;
    std::string s;
    if (scope_.empty() || !readBounded(scope_ + "/templates.dat", s, 256 * 1024) || s.size() < 8 ||
        s.compare(0, 4, "TMT1") != 0)
        return items;
    Reader r(s, 4);
    unsigned count = r.number();
    if (count > 100)
        return items;
    for (unsigned i = 0; i < count && r.ok; ++i)
        items.push_back(r.field(4096));
    if (!r.done())
        items.clear();
    return items;
}
bool Storage::saveTemplates(const std::vector<std::string> &items, std::string &error) {
    if (scope_.empty() || items.size() > 100) {
        error = "Too many templates or no account";
        return false;
    }
    std::string s = "TMT1";
    number(s, items.size());
    for (size_t i = 0; i < items.size(); ++i) {
        if (items[i].size() > 4096) {
            error = "Template too long";
            return false;
        }
        field(s, items[i]);
    }
    if (s.size() > 256 * 1024) {
        error = "Templates too large";
        return false;
    }
    return atomicWrite(scope_ + "/templates.dat", s, error);
}
bool Storage::loadRoster(std::vector<ContactRecord> &out) const {
    out.clear();
    std::string s;
    if (scope_.empty() || !readBounded(scope_ + "/roster.dat", s, FILE_LIMIT))
        return false;
    if (s.size() < 8 || s.compare(0, 4, "TMR1") != 0)
        return false;
    Reader r(s, 4);
    unsigned count = r.number();
    if (count > 4096)
        return false;
    std::vector<ContactRecord> parsed;
    parsed.reserve(count);
    for (unsigned i = 0; i < count && r.ok; ++i) {
        ContactRecord c;
        c.uin = r.number();
        c.groupId = r.number();
        c.itemId = r.number();
        c.type = r.number();
        c.network = r.number();
        c.days = r.number();
        c.privacy = r.number();
        unsigned flags = r.number();
        c.inRoster = flags & 1;
        c.noAuth = flags & 2;
        c.deleted = flags & 4;
        c.name = r.field(4096);
        c.group = r.field(4096);
        c.avatarHash = r.field(512);
        // Presence is never carried over from a previous session.
        parsed.push_back(c);
    }
    if (!r.done())
        return false;
    out.swap(parsed);
    return true;
}
bool Storage::saveRoster(const std::vector<ContactRecord> &items, std::string &error) {
    if (scope_.empty() || items.size() > 4096) {
        error = "Roster too large or no account";
        return false;
    }
    std::string s = "TMR1";
    number(s, items.size());
    for (size_t i = 0; i < items.size(); ++i) {
        const ContactRecord &c = items[i];
        if (c.name.size() > 4096 || c.group.size() > 4096 || c.avatarHash.size() > 512) {
            error = "Invalid contact";
            return false;
        }
        number(s, c.uin);
        number(s, c.groupId);
        number(s, c.itemId);
        number(s, c.type);
        number(s, c.network);
        number(s, c.days);
        number(s, c.privacy);
        number(s, (c.inRoster ? 1 : 0) | (c.noAuth ? 2 : 0) | (c.deleted ? 4 : 0));
        field(s, c.name);
        field(s, c.group);
        field(s, c.avatarHash);
        if (s.size() > FILE_LIMIT) {
            error = "Roster too large";
            return false;
        }
    }
    return atomicWrite(scope_ + "/roster.dat", s, error);
}
std::vector<uint32_t> Storage::quietChats() const {
    std::vector<uint32_t> out;
    std::string s;
    if (scope_.empty() || !readBounded(scope_ + "/quiet.dat", s, 16392) || s.size() < 8 ||
        s.compare(0, 4, "TMQ1") != 0)
        return out;
    Reader r(s, 4);
    unsigned count = r.number();
    if (count > 4096)
        return out;
    std::set<uint32_t> unique;
    for (unsigned i = 0; i < count && r.ok; ++i) {
        uint32_t n = r.number();
        if (n && unique.insert(n).second)
            out.push_back(n);
    }
    if (!r.done())
        out.clear();
    return out;
}
bool Storage::saveQuietChats(const std::vector<uint32_t> &items, std::string &error) {
    if (scope_.empty() || items.size() > 4096) {
        error = "Quiet list too large or no account";
        return false;
    }
    std::set<uint32_t> unique(items.begin(), items.end());
    unique.erase(0);
    std::string s = "TMQ1";
    number(s, unique.size());
    for (std::set<uint32_t>::const_iterator i = unique.begin(); i != unique.end(); ++i)
        number(s, *i);
    return atomicWrite(scope_ + "/quiet.dat", s, error);
}
} // namespace tmm
