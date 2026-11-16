#include "ui_files.h"
#include <assert.h>
#include <stdio.h>
#include <string>
#include <unistd.h>
#include <stdlib.h>
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
    unlink(path.c_str());
    unlink(copy.c_str());
    rmdir(dir);
    puts("ui image/copy tests passed");
}
