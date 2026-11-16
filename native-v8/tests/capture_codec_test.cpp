#include "capture_codec.h"
#include <cstdio>
#include <cstring>
#include <cassert>
int main(int argc, char **argv) {
    assert(argc == 2);
    FILE *empty = std::fopen(argv[1], "wb");
    assert(empty);
    assert(!std::fclose(empty));
    tmm::AmrWriter writer;
    short pcm[160];
    std::memset(pcm, 0, sizeof(pcm));
    if (!writer.open(argv[1], 6700)) {
        std::fprintf(stderr, "open failed %u\n", writer.error());
        return 1;
    }
    for (int i = 0; i < 50; ++i) {
        if (!writer.write(pcm)) {
            std::fprintf(stderr, "frame failed %u\n", writer.error());
            return 2;
        }
    }
    assert(writer.close());
    FILE *f = std::fopen(argv[1], "rb");
    assert(f);
    char magic[6];
    assert(std::fread(magic, 1, 6, f) == 6);
    assert(!std::memcmp(magic, "#!AMR\n", 6));
    for (int i = 0; i < 50; ++i) {
        assert(std::fgetc(f) == 0x1c);
        for (int n = 0; n < 17; ++n)
            assert(std::fgetc(f) != EOF);
    }
    assert(std::fgetc(f) == EOF);
    std::fclose(f);
    assert(!writer.open(argv[1], 123));
    assert(writer.error() == 101);
    std::puts("stock V8 AMR codec: 50 frames, 6700 bit/s, PASS");
    return 0;
}
