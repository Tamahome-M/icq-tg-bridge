#include "settings.h"
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <limits.h>
#include <vector>
#include <stdint.h>
namespace tmm {
static std::string message(const char *what) {
    return std::string(what) + ": " + strerror(errno);
}
bool ensureDirectory(const std::string &path, std::string &error) {
    if (path.empty() || path.size() > 4096) {
        error = "Invalid data directory";
        return false;
    }
    struct stat st;
    if (lstat(path.c_str(), &st) == 0) {
        if (!S_ISDIR(st.st_mode) || S_ISLNK(st.st_mode)) {
            error = "Data path is not a directory";
            return false;
        }
        return true;
    }
    if (errno != ENOENT) {
        error = message("Cannot inspect directory");
        return false;
    }
    size_t slash = path.find_last_of('/');
    if (slash != std::string::npos && slash != 0 && !ensureDirectory(path.substr(0, slash), error))
        return false;
    if (mkdir(path.c_str(), 0700) < 0 && errno != EEXIST) {
        error = message("Cannot create directory");
        return false;
    }
    return lstat(path.c_str(), &st) == 0 && S_ISDIR(st.st_mode) && !S_ISLNK(st.st_mode);
}
bool readBounded(const std::string &path, std::string &data, size_t maximum) {
    data.clear();
    int fd = open(path.c_str(), O_RDONLY | O_NOFOLLOW);
    if (fd < 0)
        return false;
    struct stat st;
    bool ok = fstat(fd, &st) == 0;
    int failure = ok ? 0 : errno;
    if (ok && (!S_ISREG(st.st_mode) || st.st_size < 0)) {
        ok = false;
        failure = EINVAL;
    }
    if (ok && (uint64_t)st.st_size > maximum) {
        ok = false;
        failure = EFBIG;
    }
    char buffer[4096];
    while (ok) {
        ssize_t n = read(fd, buffer, sizeof(buffer));
        if (n < 0 && errno == EINTR)
            continue;
        if (n < 0) {
            failure = errno;
            ok = false;
            break;
        }
        if (!n)
            break;
        if (data.size() + (size_t)n > maximum) {
            failure = EFBIG;
            ok = false;
            break;
        }
        data.append(buffer, n);
    }
    close(fd);
    if (!ok)
        data.clear();
    errno = failure;
    return ok;
}
bool atomicWrite(const std::string &path, const std::string &data, std::string &error) {
    if (path.empty()) {
        error = "No settings path";
        return false;
    }
    size_t slash = path.find_last_of('/');
    std::string dir = slash == std::string::npos ? "." : (slash ? path.substr(0, slash) : "/");
    if (!ensureDirectory(dir, error))
        return false;
    std::string pattern = path + ".new-XXXXXX";
    std::vector<char> temp(pattern.begin(), pattern.end());
    temp.push_back(0);
    int fd = mkstemp(&temp[0]);
    if (fd < 0) {
        error = message("Cannot create temporary file");
        return false;
    }
    bool ok = fchmod(fd, 0600) == 0;
    // My Files may be VFAT: it has no Unix permission bits. mkstemp still
    // creates a unique file; failure to emulate chmod must not lose settings.
    if (!ok && (errno == EPERM || errno == EOPNOTSUPP))
        ok = true;
    size_t offset = 0;
    while (ok && offset < data.size()) {
        ssize_t n = write(fd, data.data() + offset, data.size() - offset);
        if (n < 0 && errno == EINTR)
            continue;
        if (n <= 0) {
            ok = false;
            break;
        }
        offset += n;
    }
    if (ok && fsync(fd) < 0)
        ok = false;
    int saved = errno;
    if (close(fd) < 0 && ok) {
        ok = false;
        saved = errno;
    }
    if (ok && rename(&temp[0], path.c_str()) < 0) {
        ok = false;
        saved = errno;
    }
    if (!ok) {
        unlink(&temp[0]);
        errno = saved;
        error = message("Cannot save file");
        return false;
    }
    int d = open(dir.c_str(), O_RDONLY);
    if (d >= 0) {
        fsync(d);
        close(d);
    }
    return true;
}
static std::string hex(const std::string &s) {
    static const char h[] = "0123456789abcdef";
    std::string r;
    r.reserve(s.size() * 2);
    for (size_t i = 0; i < s.size(); ++i) {
        unsigned char c = s[i];
        r += h[c >> 4];
        r += h[c & 15];
    }
    return r;
}
static int digit(char c) {
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    return -1;
}
static bool unhex(const std::string &s, std::string &r) {
    r.clear();
    if (s.size() % 2)
        return false;
    for (size_t i = 0; i < s.size(); i += 2) {
        int a = digit(s[i]), b = digit(s[i + 1]);
        if (a < 0 || b < 0)
            return false;
        r += (char)((a << 4) | b);
    }
    return true;
}
Settings::Settings() : writable_(false) {}
void Settings::reset() {
    values_.clear();
    writable_ = true;
}
bool Settings::load(const std::string &path, std::string &error) {
    path_ = path;
    writable_ = false;
    std::string data;
    struct stat st;
    if (lstat(path.c_str(), &st) < 0 && errno == ENOENT) {
        values_.clear();
        writable_ = true;
        return true;
    }
    if (!readBounded(path, data, 512 * 1024)) {
        error = "Cannot read settings";
        return false;
    }
    if (data.compare(0, 6, "TMMN1\n") != 0) {
        error = "Unsupported settings file";
        return false;
    }
    std::map<std::string, std::string> staged;
    size_t at = 6;
    while (at < data.size()) {
        size_t end = data.find('\n', at), split = data.find('\t', at);
        if (end == std::string::npos || split == std::string::npos || split >= end) {
            error = "Truncated settings file";
            return false;
        }
        std::string key, value;
        if (!unhex(data.substr(at, split - at), key) ||
            !unhex(data.substr(split + 1, end - split - 1), value) || key.empty() ||
            key.size() > 128 || value.size() > 65536 || staged.size() > 512) {
            error = "Invalid settings entry";
            return false;
        }
        staged[key] = value;
        if (staged.size() > 512) {
            error = "Too many settings";
            return false;
        }
        at = end + 1;
    }
    values_.swap(staged);
    writable_ = true;
    return true;
}
bool Settings::save(std::string &error) const {
    std::string data = "TMMN1\n";
    if (!writable_) {
        error = "Settings were not loaded; damaged file is preserved";
        return false;
    }
    if (values_.size() > 512) {
        error = "Too many settings";
        return false;
    }
    for (std::map<std::string, std::string>::const_iterator i = values_.begin(); i != values_.end();
         ++i) {
        if (i->first.empty() || i->first.size() > 128 || i->second.size() > 65536) {
            error = "Settings value too large";
            return false;
        }
        data += hex(i->first) + "\t" + hex(i->second) + "\n";
        if (data.size() > 512 * 1024) {
            error = "Settings too large";
            return false;
        }
    }
    return atomicWrite(path_, data, error);
}
std::string Settings::get(const std::string &key, const std::string &fallback) const {
    std::map<std::string, std::string>::const_iterator i = values_.find(key);
    return i == values_.end() ? fallback : i->second;
}
int Settings::getInt(const std::string &key, int fallback) const {
    std::string s = get(key);
    if (s.empty())
        return fallback;
    char *end = 0;
    errno = 0;
    long v = strtol(s.c_str(), &end, 10);
    return errno || !end || *end || v < INT_MIN || v > INT_MAX ? fallback : (int)v;
}
bool Settings::getBool(const std::string &key, bool fallback) const {
    std::string s = get(key);
    return s.empty() ? fallback : s == "1" || s == "true";
}
bool Settings::remove(const std::string &key) {
    return values_.erase(key) != 0;
}
bool Settings::removePrefix(const std::string &prefix) {
    bool changed = false;
    std::map<std::string, std::string>::iterator i = values_.lower_bound(prefix);
    while (i != values_.end() && i->first.compare(0, prefix.size(), prefix) == 0) {
        values_.erase(i++);
        changed = true;
    }
    return changed;
}
void Settings::set(const std::string &key, const std::string &value) {
    values_[key] = value;
}
void Settings::setInt(const std::string &key, int value) {
    char b[32];
    snprintf(b, sizeof(b), "%d", value);
    set(key, b);
}
void Settings::setBool(const std::string &key, bool value) {
    set(key, value ? "1" : "0");
}
} // namespace tmm
