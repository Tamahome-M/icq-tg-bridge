#include "capture_media.h"
#include <cstdio>
#include <cstring>
#include <stdint.h>
#include <sys/stat.h>
namespace tmm {
namespace {
uint32_t u32(const unsigned char *p) {
    return (uint32_t(p[0]) << 24) | (uint32_t(p[1]) << 16) | (uint32_t(p[2]) << 8) | p[3];
}
uint64_t u64(const unsigned char *p) {
    return (uint64_t(u32(p)) << 32) | u32(p + 4);
}
bool read(FILE *f, unsigned long at, void *out, unsigned count) {
    return !std::fseek(f, at, SEEK_SET) && std::fread(out, 1, count, f) == count;
}
unsigned seconds(uint64_t duration, uint32_t timescale) {
    if (!timescale || duration > uint64_t(timescale) * 3600)
        return 0;
    return static_cast<unsigned>((duration + timescale - 1) / timescale);
}
unsigned movie(FILE *f, unsigned long begin, unsigned long end, int depth, unsigned &budget) {
    unsigned char header[40];
    for (unsigned long at = begin; at + 8 <= end && budget;) {
        --budget;
        if (!read(f, at, header, 8))
            return 0;
        uint64_t size = u32(header);
        unsigned head = 8;
        bool moov = std::memcmp(header + 4, "moov", 4) == 0,
             mvhd = std::memcmp(header + 4, "mvhd", 4) == 0;
        if (size == 1) {
            if (at + 16 > end || !read(f, at + 8, header, 8))
                return 0;
            size = u64(header);
            head = 16;
        } else if (!size)
            size = end - at;
        if (size < head || size > end - at)
            return 0;
        if (moov && !depth) {
            unsigned value = movie(f, at + head, at + static_cast<unsigned long>(size), 1, budget);
            if (value)
                return value;
        }
        if (mvhd && depth) {
            if (size < head + 20 || !read(f, at + head, header, 20))
                return 0;
            if (header[0] == 0)
                return seconds(u32(header + 16), u32(header + 12));
            if (header[0] == 1) {
                if (size < head + 32 || !read(f, at + head, header, 32))
                    return 0;
                return seconds(u64(header + 24), u32(header + 20));
            }
            return 0;
        }
        at += static_cast<unsigned long>(size);
    }
    return 0;
}
} // namespace
unsigned captureDuration(const char *path) {
    if (!path)
        return 0;
    FILE *f = std::fopen(path, "rb");
    if (!f)
        return 0;
    struct stat st;
    if (fstat(fileno(f), &st) || !S_ISREG(st.st_mode) || st.st_size < 6 ||
        st.st_size > 16 * 1024 * 1024) {
        std::fclose(f);
        return 0;
    }
    unsigned char magic[6];
    unsigned result = 0;
    if (read(f, 0, magic, 6) && !std::memcmp(magic, "#!AMR\n", 6)) {
        const unsigned sizes[] = {12, 13, 15, 17, 19, 20, 26, 31, 5, 0, 0, 0, 0, 0, 0, 0};
        unsigned frames = 0;
        unsigned long at = 6;
        bool valid = true;
        while (at < static_cast<unsigned long>(st.st_size) && frames < 180000) {
            int toc = std::fgetc(f);
            if (toc < 0 || (toc & 0x83)) {
                valid = false;
                break;
            }
            unsigned mode = (toc >> 3) & 15;
            if (mode > 8 && mode != 15) {
                valid = false;
                break;
            }
            unsigned count = sizes[mode];
            if (at + 1 + count > static_cast<unsigned long>(st.st_size) ||
                std::fseek(f, count, SEEK_CUR)) {
                valid = false;
                break;
            }
            at += 1 + count;
            ++frames;
        }
        if (valid && at == static_cast<unsigned long>(st.st_size))
            result = (frames + 49) / 50;
    } else {
        unsigned budget = 10000;
        result = movie(f, 0, static_cast<unsigned long>(st.st_size), 0, budget);
    }
    std::fclose(f);
    return result;
}
} // namespace tmm
