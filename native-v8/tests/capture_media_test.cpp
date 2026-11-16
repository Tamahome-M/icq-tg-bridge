#include "capture_media.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <unistd.h>
#include <cstdlib>
static void put32(FILE *f, unsigned n) {
    for (int i = 3; i >= 0; --i)
        std::fputc((n >> (i * 8)) & 255, f);
}
static void movie(const char *p, unsigned version, unsigned timescale, unsigned long long duration,
                  bool extended) {
    FILE *f = std::fopen(p, "wb");
    assert(f);
    unsigned body = version ? 32 : 20;
    put32(f, extended ? 1 : 16 + body);
    std::fwrite("moov", 1, 4, f);
    if (extended) {
        put32(f, 0);
        put32(f, 24 + body);
    }
    put32(f, 8 + body);
    std::fwrite("mvhd", 1, 4, f);
    std::fputc(version, f);
    for (int i = 0; i < 3 + (version ? 16 : 8); ++i)
        std::fputc(0, f);
    put32(f, timescale);
    if (version)
        put32(f, duration >> 32);
    put32(f, duration);
    assert(!std::fclose(f));
}
int main(int argc, char **argv) {
    char path[] = "/tmp/tmm-media-meta-XXXXXX";
    int fd = mkstemp(path);
    assert(fd >= 0);
    close(fd);
    movie(path, 0, 1000, 12345, false);
    assert(tmm::captureDuration(path) == 13);
    movie(path, 1, 1000, 30000, true);
    assert(tmm::captureDuration(path) == 30);
    movie(path, 0, 0, 30000, false);
    assert(!tmm::captureDuration(path));
    movie(path, 1, 1000, 0xffffffffffffffffULL, false);
    assert(!tmm::captureDuration(path));
    FILE *f = std::fopen(path, "wb");
    put32(f, 4);
    std::fwrite("moov", 1, 4, f);
    std::fclose(f);
    assert(!tmm::captureDuration(path));
    f = std::fopen(path, "wb");
    std::fwrite("#!AMR\n", 1, 6, f);
    std::fputc(0x1c, f);
    std::fputc(0, f);
    std::fclose(f);
    assert(!tmm::captureDuration(path));
    if (argc == 2)
        assert(tmm::captureDuration(argv[1]) == 1);
    unlink(path);
    std::puts("capture duration: mvhd v0/v1/extended, rounding, truncation, invalid AMR PASS");
    return 0;
}
