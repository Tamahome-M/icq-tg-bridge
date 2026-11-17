#include "ui_files.h"
#include <assert.h>
#include <stdio.h>
#include <string>
#include <unistd.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <sstream>
static void put(const std::string &p, const std::string &s) {
    FILE *f = fopen(p.c_str(), "wb");
    assert(f);
    assert(fwrite(s.data(), 1, s.size(), f) == s.size());
    fclose(f);
}
int main() {
    char dir[] = "/tmp/tmm-ui-files-XXXXXX";
    assert(mkdtemp(dir));
    std::string path = std::string(dir) + "/image", error;
    unsigned w, h;
    std::string png("\x89PNG\r\n\x1a\n\0\0\0\x0dIHDR\0\0\0\xf0\0\0\1\x40", 24);
    put(path, png);
    assert(tmm::imageDimensions(path, w, h, error) && w == 240 && h == 320);
    png[16] = 0x7f;
    put(path, png);
    assert(!tmm::imageDimensions(path, w, h, error));
    put(path, "not an image");
    assert(!tmm::imageDimensions(path, w, h, error));
    std::string jpg("\xff\xd8\xff\xe0\0\x10", 6);
    jpg += std::string(14, 'x');
    jpg += std::string("\xff\xc0\0\x11\x08\0\x90\0\xb0", 9);
    jpg += std::string(10, 'x');
    put(path, jpg);
    assert(tmm::imageDimensions(path, w, h, error) && w == 176 && h == 144);
    jpg[23] = 0;
    put(path, jpg);
    assert(!tmm::imageDimensions(path, w, h, error));
    put(path, std::string(100000, 'a'));
    std::string copy = std::string(dir) + "/copy";
    assert(tmm::copyMediaFile(path, copy, error));
    assert(!tmm::copyMediaFile(path, copy, error));
    FILE *f = fopen(copy.c_str(), "rb");
    assert(f);
    fseek(f, 0, SEEK_END);
    assert(ftell(f) == 100000);
    fclose(f);
    // A dangling/looping symlink must not masquerade as a readdir() failure.
    std::string child = std::string(dir) + "/folder";
    assert(mkdir(child.c_str(), 0700) == 0);
    std::string broken = std::string(dir) + "/broken", loop = std::string(dir) + "/loop";
    assert(symlink("missing", broken.c_str()) == 0);
    assert(symlink("loop", loop.c_str()) == 0);
    std::string alias = std::string(dir) + "/alias";
    assert(symlink("folder", alias.c_str()) == 0);
    std::string parent = child + "/up";
    assert(symlink("..", parent.c_str()) == 0);
    std::string unicode = std::string(dir) + "/снимок.jpg";
    put(unicode, "payload");
    std::vector<tmm::MediaFileEntry> entries;
    std::string canonical;
    bool truncated = true;
    assert(tmm::listMediaDirectory(dir, canonical, entries, truncated, error));
    assert(canonical == dir && !truncated && error.empty() && entries.size() == 5);
    assert(entries[0].directory && entries[0].name == "alias");
    assert(entries[1].directory && entries[1].name == "folder");
    assert(entries[4].name == "снимок.jpg" && entries[4].path == unicode && entries[4].bytes == 7);
    // Canonical navigation prevents repeated symlink traversal from growing
    // paths until the browser cannot return to a parent folder.
    assert(tmm::listMediaDirectory(alias + "/up/folder/up", canonical, entries, truncated, error));
    assert(canonical == dir && entries.size() == 5);
    std::string resolved;
    assert(tmm::readableMediaDirectory(alias, resolved) && resolved == child);
    assert(!tmm::readableMediaDirectory(path, resolved));
    assert(resolved == child);
    // An inaccessible target never publishes partial rows or a different
    // canonical directory. The UI can show its navigation/error safely.
    assert(!tmm::listMediaDirectory(std::string(dir) + "/missing", canonical, entries, truncated,
                                    error));
    assert(canonical == dir && entries.size() == 5 && !error.empty());
    std::string crowded = std::string(dir) + "/crowded";
    assert(mkdir(crowded.c_str(), 0700) == 0);
    for (unsigned i = 0; i < 1005; ++i) {
        std::ostringstream number;
        number << i;
        put(crowded + "/" + number.str(), "x");
    }
    assert(tmm::listMediaDirectory(crowded, canonical, entries, truncated, error));
    assert(canonical == crowded && truncated && entries.size() == 1000);
    for (unsigned i = 0; i < 1005; ++i) {
        std::ostringstream number;
        number << i;
        unlink((crowded + "/" + number.str()).c_str());
    }
    rmdir(crowded.c_str());
    unlink(unicode.c_str());
    unlink(parent.c_str());
    unlink(alias.c_str());
    unlink(loop.c_str());
    unlink(broken.c_str());
    rmdir(child.c_str());
    unlink(path.c_str());
    unlink(copy.c_str());
    rmdir(dir);
    puts("ui image/copy/directory tests passed");
}
