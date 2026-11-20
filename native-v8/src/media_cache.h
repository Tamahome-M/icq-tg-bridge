#ifndef TMM_MEDIA_CACHE_H
#define TMM_MEDIA_CACHE_H
#include "client.h"
#include <stdint.h>
#include <string>
#include <vector>
namespace tmm {
// Session cache: retain completed downloads on disk, never decoded media in RAM.
class MediaCache {
  public:
    explicit MediaCache(unsigned entries = 8, uint64_t bytes = 16 * 1024 * 1024);
    ~MediaCache();
    void setDirectory(const std::string &directory);
    bool find(const std::string &key, std::string &path, std::string &filename);
    bool store(const std::string &key, const std::string &path, const std::string &filename);
    bool owns(const std::string &path) const;
    void clear();
    void reserve(uint64_t bytes);
    static std::string requestKey(const Command &command);

  private:
    struct Entry {
        std::string key, path, filename;
        uint64_t bytes, used;
    };
    std::string directory_;
    std::vector<Entry> entries_;
    unsigned maximumEntries_;
    uint64_t maximumBytes_, bytes_, clock_;
    bool validPath(const std::string &path) const;
    void remove(unsigned index);
    MediaCache(const MediaCache &);
    MediaCache &operator=(const MediaCache &);
};
} // namespace tmm
#endif
