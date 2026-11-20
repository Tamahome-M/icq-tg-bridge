#include "media_cache.h"
#include <sys/stat.h>
#include <unistd.h>
namespace tmm {
namespace {
void number(std::string &out, uint32_t value) {
    for (unsigned shift = 0; shift < 32; shift += 8)
        out += char(value >> shift);
}
} // namespace
MediaCache::MediaCache(unsigned entries, uint64_t bytes)
    : maximumEntries_(entries), maximumBytes_(bytes), bytes_(0), clock_(0) {}
MediaCache::~MediaCache() {
    clear();
}
void MediaCache::reserve(uint64_t bytes) {
    // Capacity is a disk budget, not an allocation. Grow only for an explicit
    // larger video setting; never evict a currently playing file on Save.
    if (bytes > maximumBytes_ && bytes <= 512ULL * 1024 * 1024)
        maximumBytes_ = bytes;
}
void MediaCache::setDirectory(const std::string &directory) {
    clear();
    directory_ = directory;
    if (!directory_.empty() && directory_[directory_.size() - 1] != '/')
        directory_ += '/';
}
bool MediaCache::validPath(const std::string &path) const {
    return !directory_.empty() && path.compare(0, directory_.size(), directory_) == 0 &&
           path.compare(directory_.size(), 6, "media-") == 0 &&
           path.find('/', directory_.size()) == std::string::npos;
}
bool MediaCache::owns(const std::string &path) const {
    for (size_t i = 0; i < entries_.size(); ++i)
        if (entries_[i].path == path)
            return true;
    return false;
}
void MediaCache::remove(unsigned index) {
    if (validPath(entries_[index].path))
        unlink(entries_[index].path.c_str());
    bytes_ -= entries_[index].bytes;
    entries_.erase(entries_.begin() + index);
}
void MediaCache::clear() {
    while (!entries_.empty())
        remove(entries_.size() - 1);
    clock_ = 0;
}
bool MediaCache::find(const std::string &key, std::string &path, std::string &filename) {
    for (size_t i = 0; i < entries_.size(); ++i) {
        Entry &entry = entries_[i];
        if (entry.key != key)
            continue;
        struct stat st;
        if (lstat(entry.path.c_str(), &st) || !S_ISREG(st.st_mode) || st.st_size <= 0 ||
            uint64_t(st.st_size) != entry.bytes) {
            remove(i);
            return false;
        }
        entry.used = ++clock_;
        path = entry.path;
        filename = entry.filename;
        return true;
    }
    return false;
}
bool MediaCache::store(const std::string &key, const std::string &path,
                       const std::string &filename) {
    struct stat st;
    if (key.empty() || !maximumEntries_ || !validPath(path) || lstat(path.c_str(), &st) ||
        !S_ISREG(st.st_mode) || st.st_size <= 0 || uint64_t(st.st_size) > maximumBytes_)
        return false;
    for (size_t i = 0; i < entries_.size();) {
        if (entries_[i].path == path) {
            // A file can have only one owner, even if the caller changes its key.
            bytes_ -= entries_[i].bytes;
            entries_.erase(entries_.begin() + i);
        } else if (entries_[i].key == key)
            remove(i);
        else
            ++i;
    }
    while (entries_.size() >= maximumEntries_ || bytes_ > maximumBytes_ - st.st_size) {
        unsigned oldest = 0;
        for (size_t i = 1; i < entries_.size(); ++i)
            if (entries_[i].used < entries_[oldest].used)
                oldest = i;
        remove(oldest);
    }
    Entry entry;
    entry.key = key;
    entry.path = path;
    entry.filename = filename;
    entry.bytes = st.st_size;
    entry.used = ++clock_;
    entries_.push_back(entry);
    bytes_ += entry.bytes;
    return true;
}
std::string MediaCache::requestKey(const Command &c) {
    std::string key;
    number(key, c.type);
    number(key, c.uin);
    number(key, c.offset);
    number(key, c.mode);
    const std::string &identity = c.token.empty() ? c.nativeId : c.token;
    number(key, identity.size());
    key += identity;
    for (std::map<unsigned, unsigned>::const_iterator i = c.media.begin(); i != c.media.end();
         ++i) {
        number(key, i->first);
        number(key, i->second);
    }
    return key;
}
} // namespace tmm
