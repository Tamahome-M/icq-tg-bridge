#ifndef TMM_UI_FILES_H
#define TMM_UI_FILES_H
#include <string>
#include <vector>
#include <stdint.h>
namespace tmm {
struct MediaFileEntry {
    std::string name, path;
    uint64_t bytes;
    bool directory;
    MediaFileEntry(const std::string &n, const std::string &p, uint64_t s, bool d)
        : name(n), path(p), bytes(s), directory(d) {}
};
bool readableMediaDirectory(const std::string &, std::string &);
bool listMediaDirectory(const std::string &, std::string &, std::vector<MediaFileEntry> &, bool &,
                        std::string &);
bool imageDimensions(const std::string &, unsigned &, unsigned &, std::string &);
bool copyMediaFile(const std::string &, const std::string &, std::string &);
} // namespace tmm
#endif
