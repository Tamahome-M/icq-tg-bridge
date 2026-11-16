#include "ui_files.h"
#include <stdio.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <errno.h>
#include <string.h>
#include <dirent.h>
#include <stdlib.h>
#include <limits.h>
#include <algorithm>
namespace tmm {
static DIR *openMediaDirectory(const std::string &path, std::string &canonical) {
    char resolved[PATH_MAX];
    if (path.empty() || !realpath(path.c_str(), resolved)) {
        if (path.empty())
            errno = ENOENT;
        return 0;
    }
    DIR *directory = opendir(resolved);
    if (directory)
        canonical = resolved;
    return directory;
}
bool readableMediaDirectory(const std::string &path, std::string &canonical) {
    DIR *directory = openMediaDirectory(path, canonical);
    if (!directory)
        return false;
    closedir(directory);
    return true;
}
static bool fileEntryLess(const MediaFileEntry &a, const MediaFileEntry &b) {
    return a.directory != b.directory ? a.directory : a.name < b.name;
}
bool listMediaDirectory(const std::string &path, std::string &canonical,
                        std::vector<MediaFileEntry> &entries, bool &truncated, std::string &error) {
    std::string resolved;
    DIR *directory = openMediaDirectory(path, resolved);
    if (!directory) {
        error = std::string("Не открыть папку: ") + strerror(errno);
        return false;
    }
    std::vector<MediaFileEntry> result;
    unsigned scanned = 0;
    bool limited = false;
    int failure = 0;
    for (;;) {
        // stat() below can fail for a broken or looping symlink. Only errno
        // from readdir() determines whether the directory read failed.
        errno = 0;
        struct dirent *entry = readdir(directory);
        if (!entry) {
            failure = errno;
            break;
        }
        std::string name = entry->d_name;
        if (name == "." || name == "..")
            continue;
        if (++scanned > 4096 || result.size() >= 1000) {
            limited = true;
            break;
        }
        std::string child = resolved + (resolved == "/" ? "" : "/") + name;
        struct stat st;
        if (stat(child.c_str(), &st) < 0)
            continue;
        if (S_ISDIR(st.st_mode) || S_ISREG(st.st_mode))
            result.push_back(MediaFileEntry(name, child, st.st_size, S_ISDIR(st.st_mode)));
    }
    closedir(directory);
    if (failure) {
        error = std::string("Ошибка чтения папки: ") + strerror(failure);
        return false;
    }
    std::sort(result.begin(), result.end(), fileEntryLess);
    canonical = resolved;
    entries.swap(result);
    truncated = limited;
    error.clear();
    return true;
}
static unsigned be16(const unsigned char *p) {
    return ((unsigned)p[0] << 8) | p[1];
}
static unsigned be32(const unsigned char *p) {
    return (be16(p) << 16) | be16(p + 2);
}
bool imageDimensions(const std::string &path, unsigned &w, unsigned &h, std::string &error) {
    w = h = 0;
    FILE *f = fopen(path.c_str(), "rb");
    if (!f) {
        error = "Не удалось открыть изображение";
        return false;
    }
    struct stat st;
    unsigned char b[32];
    bool ok = false;
    if (fstat(fileno(f), &st) == 0 && S_ISREG(st.st_mode) && st.st_size > 0 &&
        st.st_size <= 8 * 1024 * 1024 && fread(b, 1, 24, f) == 24) {
        if (!memcmp(b, "\x89PNG\r\n\x1a\n", 8) && be32(b + 8) == 13 && !memcmp(b + 12, "IHDR", 4)) {
            w = be32(b + 16);
            h = be32(b + 20);
            ok = true;
        } else if (!memcmp(b, "GIF87a", 6) || !memcmp(b, "GIF89a", 6)) {
            w = b[6] | ((unsigned)b[7] << 8);
            h = b[8] | ((unsigned)b[9] << 8);
            ok = true;
        } else if (b[0] == 0xff && b[1] == 0xd8) {
            fseek(f, 2, SEEK_SET);
            unsigned scanned = 0;
            while (scanned++ < 1024 && ftell(f) < 1024 * 1024) {
                int c = fgetc(f);
                if (c != 0xff)
                    break;
                do {
                    c = fgetc(f);
                } while (c == 0xff);
                if (c < 0 || c == 0xda || c == 0xd9)
                    break;
                if (c == 1 || (c >= 0xd0 && c <= 0xd7))
                    continue;
                if (fread(b, 1, 2, f) != 2)
                    break;
                unsigned length = be16(b);
                if (length < 2)
                    break;
                bool sof = (c >= 0xc0 && c <= 0xcf && c != 0xc4 && c != 0xc8 && c != 0xcc);
                if (sof) {
                    if (length < 8 || fread(b, 1, 5, f) != 5)
                        break;
                    h = be16(b + 1);
                    w = be16(b + 3);
                    ok = true;
                    break;
                }
                if (fseek(f, length - 2, SEEK_CUR) != 0)
                    break;
            }
        }
    }
    fclose(f);
    if (!ok || !w || !h || w > 4096 || h > 4096 || w > 2000000UL / h) {
        error = "Изображение слишком большое или формат не поддерживается";
        w = h = 0;
        return false;
    }
    return true;
}
bool copyMediaFile(const std::string &source, const std::string &target, std::string &error) {
    int in = open(source.c_str(), O_RDONLY);
    if (in < 0) {
        error = strerror(errno);
        return false;
    }
    struct stat a, b;
    if (fstat(in, &a) < 0 || !S_ISREG(a.st_mode)) {
        close(in);
        error = "Файл недоступен";
        return false;
    }
    if (stat(target.c_str(), &b) == 0) {
        close(in);
        error = "Файл с таким именем уже существует";
        return false;
    }
    // O_EXCL prevents a file created during copying from being overwritten.
    // This also works on the phone SD card (VFAT has no hard-link commit).
    int out = open(target.c_str(), O_WRONLY | O_CREAT | O_EXCL, 0600);
    if (out < 0) {
        close(in);
        error = strerror(errno);
        return false;
    }
    bool ok = true;
    char buffer[8192];
    for (;;) {
        ssize_t n = read(in, buffer, sizeof(buffer));
        if (n == 0)
            break;
        if (n < 0) {
            if (errno == EINTR)
                continue;
            ok = false;
            break;
        }
        ssize_t at = 0;
        while (at < n) {
            ssize_t written = write(out, buffer + at, n - at);
            if (written < 0 && errno == EINTR)
                continue;
            if (written <= 0) {
                ok = false;
                break;
            }
            at += written;
        }
        if (!ok)
            break;
    }
    if (ok && fsync(out) < 0)
        ok = false;
    if (close(out) < 0)
        ok = false;
    close(in);
    if (!ok) {
        error = strerror(errno);
        unlink(target.c_str());
    }
    return ok;
}
} // namespace tmm
