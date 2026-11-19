#include "theme_patch.h"
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <dirent.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <map>
#include <vector>
namespace tmm {
namespace {
const uint32_t packMagic = 0xabcddcbaU, blockMagic = 0xdcbaabcdU;
uint32_t word(const unsigned char *p) {
    return p[0] | uint32_t(p[1]) << 8 | uint32_t(p[2]) << 16 | uint32_t(p[3]) << 24;
}
bool put(FILE *f, uint32_t n) {
    unsigned char b[4];
    for (unsigned i = 0; i < 4; ++i)
        b[i] = n >> (8 * i);
    return fwrite(b, 1, 4, f) == 4;
}
uint32_t hash(const std::string &name) {
    uint32_t n = 0;
    for (size_t i = 0; i < name.size(); ++i) {
        // Explicit arithmetic shift: independent of host compiler semantics.
        uint32_t shift = (n >> 20) | ((n & 0x80000000U) ? 0xfffff000U : 0);
        n = shift ^ (n << 1) ^ static_cast<unsigned char>(name[i]);
    }
    return n;
}
struct Entry {
    unsigned source;
    uint32_t offset, length;
};
typedef std::map<std::string, Entry> Entries;
struct Pack {
    FILE *file;
    Pack() : file(0) {}
    ~Pack() {
        if (file)
            fclose(file);
    }
    bool load(const std::string &path, Entries &entries, unsigned source) {
        file = fopen(path.c_str(), "rb");
        struct stat st;
        if (!file || fstat(fileno(file), &st) || !S_ISREG(st.st_mode) || st.st_size < 44 ||
            st.st_size > 64 * 1024 * 1024)
            return false;
        unsigned char prefix[25], header[20];
        if (fread(prefix, 1, 25, file) != 25 || memcmp(prefix, "motoskin\n\nv1.00\n", 16))
            return false;
        char hex[9];
        memcpy(hex, prefix + 16, 8);
        hex[8] = 0;
        for (unsigned i = 0; i < 8; ++i)
            if (!((hex[i] >= '0' && hex[i] <= '9') || (hex[i] >= 'A' && hex[i] <= 'F') ||
                  (hex[i] >= 'a' && hex[i] <= 'f')))
                return false;
        uint32_t h = strtoul(hex, 0, 16);
        if (h < 25 || h % 4 || h > uint64_t(st.st_size) - 20 || fseek(file, h, SEEK_SET) ||
            fread(header, 1, 20, file) != 20)
            return false;
        uint32_t names = word(header + 4), count = word(header + 8), index = word(header + 12),
                 data = word(header + 16);
        if (word(header) != packMagic || names < 25 || names > h || h - names > 1024 * 1024 ||
            count > 20000 || index != h + 20 || data != index + count * 12 ||
            data > uint64_t(st.st_size))
            return false;
        std::vector<unsigned char> text(h - names), table(count * 12);
        if (fseek(file, names, SEEK_SET) ||
            (!text.empty() && fread(&text[0], 1, text.size(), file) != text.size()) ||
            fseek(file, index, SEEK_SET) ||
            (!table.empty() && fread(&table[0], 1, table.size(), file) != table.size()))
            return false;
        Entries seen;
        for (unsigned i = 0; i < count; ++i) {
            const unsigned char *record = &table[i * 12];
            uint32_t name = word(record + 4), offset = word(record + 8);
            if (name >= text.size() || offset > uint64_t(st.st_size) - data ||
                uint64_t(data) + offset + 8 > uint64_t(st.st_size))
                return false;
            std::string key;
            for (size_t k = name; k < text.size() && text[k] != '\n'; ++k) {
                if (text[k] < 32 || text[k] > 126 || text[k] == '/' || text[k] == '\\' ||
                    key.size() >= 200)
                    return false;
                key += text[k];
            }
            if (key.size() < 3 ||
                (key.substr(key.size() - 2) != ".k" && key.substr(key.size() - 2) != ".g") ||
                hash(key) != word(record) || seen.count(key))
                return false;
            unsigned char block[8];
            if (fseek(file, data + offset, SEEK_SET) || fread(block, 1, 8, file) != 8 ||
                word(block) != blockMagic ||
                uint64_t(data) + offset + 8 + word(block + 4) > uint64_t(st.st_size))
                return false;
            if (source && (key.compare(0, 4, "tmm_") || key.size() > 60 ||
                           key.substr(key.size() - 2) != ".g"))
                return false;
            Entry entry;
            entry.source = source;
            entry.offset = data + offset + 8;
            entry.length = word(block + 4);
            seen[key] = entry;
            entries[key] = entry;
        }
        return !seen.empty();
    }
};
bool temporary(const std::string &target, std::string &path, FILE *&file, mode_t mode) {
    std::vector<char> pattern(target.begin(), target.end());
    const char *suffix = ".tmp-XXXXXX";
    pattern.insert(pattern.end(), suffix, suffix + strlen(suffix) + 1);
    int fd = mkstemp(&pattern[0]);
    if (fd < 0)
        return false;
    path = &pattern[0];
    fchmod(fd, mode & 0777);
    file = fdopen(fd, "wb");
    if (!file) {
        close(fd);
        unlink(path.c_str());
    }
    return file != 0;
}
bool finish(FILE *f, const std::string &temp, const std::string &target, bool ok) {
    if (fflush(f) || fsync(fileno(f)))
        ok = false;
    if (fclose(f))
        ok = false;
    if (ok && rename(temp.c_str(), target.c_str()) == 0)
        return true;
    unlink(temp.c_str());
    return false;
}
bool readText(const std::string &path, std::string &text, mode_t *mode = 0) {
    FILE *f = fopen(path.c_str(), "rb");
    if (!f)
        return false;
    struct stat st;
    bool ok =
        fstat(fileno(f), &st) == 0 && S_ISREG(st.st_mode) && st.st_size >= 0 && st.st_size <= 65536;
    if (ok) {
        text.resize(st.st_size);
        ok = text.empty() || fread(&text[0], 1, text.size(), f) == text.size();
        if (mode)
            *mode = st.st_mode;
    }
    fclose(f);
    return ok;
}
bool writeText(const std::string &path, const std::string &text, mode_t mode = 0600) {
    FILE *f = 0;
    std::string temp;
    if (!temporary(path, temp, f, mode))
        return false;
    return finish(f, temp, path, fwrite(text.data(), 1, text.size(), f) == text.size());
}
std::string trim(const std::string &s) {
    size_t a = s.find_first_not_of(" \t\r"), b = s.find_last_not_of(" \t\r");
    return a == std::string::npos ? "" : s.substr(a, b - a + 1);
}
bool skinSetting(const std::string &text, std::string &skin, size_t &a, size_t &b) {
    bool group = false;
    unsigned found = 0;
    for (size_t start = 0; start < text.size();) {
        size_t end = text.find('\n', start);
        if (end == std::string::npos)
            end = text.size();
        std::string line = trim(text.substr(start, end - start));
        if (!line.empty() && line[0] == '[')
            group = line == "[THEME_GROUP_LOG]";
        size_t equal = line.find('=');
        if (group && equal != std::string::npos && trim(line.substr(0, equal)) == "CurrentSkin") {
            skin = trim(line.substr(equal + 1));
            a = start;
            b = end > start && text[end - 1] == '\r' ? end - 1 : end;
            ++found;
        }
        start = end + 1;
    }
    return found == 1 && !skin.empty() && skin[0] == '/' && skin.find('\0') == std::string::npos;
}
bool directory(const std::string &path) {
    if (mkdir(path.c_str(), 0700) == 0)
        return true;
    struct stat st;
    return lstat(path.c_str(), &st) == 0 && S_ISDIR(st.st_mode) && st.st_uid == getuid();
}
} // namespace
bool mergeStatusIcons(const std::string &base, const std::string &bundle, const std::string &output,
                      std::string &error) {
    error = "Invalid Motorola icon resource pack";
    Pack files[2];
    Entries entries;
    if ((!base.empty() && !files[0].load(base, entries, 0)) || !files[1].load(bundle, entries, 1))
        return false;
    // A truncated/incomplete add-on must never replace a working skin.
    const char *states[] = {"offline", "online", "away", "busy", "invisible"};
    const char *displays[] = {"cli", "main"};
    for (unsigned d = 0; d < 2; ++d) {
        if (!entries.count(std::string("tmm_offline_") + displays[d] + ".g"))
            return false;
        for (unsigned s = 0; s < 5; ++s)
            if (!entries.count(std::string("tmm_msg_") + states[s] + "_" + displays[d] + ".g"))
                return false;
    }
    if (!entries.count("tmm_status_v1.g"))
        return false;
    std::string names;
    for (Entries::const_iterator i = entries.begin(); i != entries.end(); ++i)
        names += i->first + '\n';
    uint32_t header = (25 + names.size() + 3) & ~3U, index = header + 20,
             data = index + entries.size() * 12;
    const std::string alignedNames = names + std::string(header - 25 - names.size(), '\0');
    FILE *f = 0;
    std::string temp;
    error = "Cannot write the patched icon resource pack";
    if (!temporary(output, temp, f, 0644))
        return false;
    bool ok = fprintf(f, "motoskin\n\nv1.00\n%08X\n", unsigned(header)) == 25 &&
              fwrite(alignedNames.data(), 1, alignedNames.size(), f) == alignedNames.size() &&
              put(f, packMagic) && put(f, 25) && put(f, entries.size()) && put(f, index) &&
              put(f, data);
    uint32_t nameOffset = 0, dataOffset = 0;
    for (Entries::const_iterator i = entries.begin(); ok && i != entries.end(); ++i) {
        ok = put(f, hash(i->first)) && put(f, nameOffset) && put(f, dataOffset);
        nameOffset += i->first.size() + 1;
        dataOffset += 8 + ((i->second.length + 3) & ~3U);
    }
    unsigned char buffer[8192];
    for (Entries::const_iterator i = entries.begin(); ok && i != entries.end(); ++i) {
        const Entry &entry = i->second;
        FILE *input = files[entry.source].file;
        ok =
            put(f, blockMagic) && put(f, entry.length) && fseek(input, entry.offset, SEEK_SET) == 0;
        for (uint32_t left = entry.length; ok && left;) {
            size_t n = left < sizeof buffer ? left : sizeof buffer;
            ok = fread(buffer, 1, n, input) == n && fwrite(buffer, 1, n, f) == n;
            left -= n;
        }
        const char padding[3] = {0, 0, 0};
        unsigned n = (4 - entry.length % 4) % 4;
        ok = ok && fwrite(padding, 1, n, f) == n;
    }
    return finish(f, temp, output, ok);
}
bool patchStatusTheme(const std::string &config, const std::string &dir, const std::string &bundle,
                      bool restore, std::string &error) {
    error = "Cannot read the active Motorola theme";
    std::string text, skin;
    size_t a = 0, b = 0;
    mode_t mode = 0600;
    if (!readText(config, text, &mode) || !skinSetting(text, skin, a, b))
        return false;
    char resolved[4096];
    if (!realpath(dir.c_str(), resolved))
        return false;
    const std::string root(resolved), clone = root + "/skin", state = root + "/source-skin";
    if (restore) {
        if (skin != clone) {
            error = "The active theme is already unchanged; no restoration is needed";
            return false;
        }
        std::string original;
        struct stat st;
        if (!readText(state, original) || original.empty() || original[0] != '/' ||
            original.find_first_of("\r\n\0", 0, 3) != std::string::npos ||
            stat(original.c_str(), &st) || !S_ISDIR(st.st_mode)) {
            error = "The original theme is unavailable; its backup has been kept";
            return false;
        }
        text.replace(a, b - a, "CurrentSkin = " + original);
        error = "Cannot restore the previous theme configuration";
        return writeText(config, text, mode);
    }
    std::string original = skin;
    if (skin == clone && !readText(state, original)) {
        error = "The original theme path is missing; refusing to replace this theme";
        return false;
    }
    if (!realpath(original.c_str(), resolved) || std::string(resolved) == clone) {
        error = "The original theme directory is unavailable";
        return false;
    }
    original = resolved;
    error = "Cannot prepare the writable theme copy";
    if (!directory(clone) || chmod(root.c_str(), 0755) || chmod(clone.c_str(), 0755))
        return false;
    // Build the new pack first. Any error here leaves CurrentSkin untouched.
    struct stat st;
    std::string base = original + "/iconres.ezx";
    if (stat(base.c_str(), &st)) {
        if (errno != ENOENT)
            return false;
        base.clear(); // No skin pack: the firmware still uses its common pack.
    }
    if (!mergeStatusIcons(base, bundle, clone + "/iconres.ezx", error))
        return false;
    // When the user selects a different theme, discard links unique to the
    // previous one. On upgrades the active clone's style links stay intact.
    if (skin != clone) {
        DIR *previous = opendir(clone.c_str());
        if (!previous)
            return false;
        bool clean = true;
        struct dirent *old;
        while (clean && (old = readdir(previous))) {
            std::string name(old->d_name);
            if (name == "." || name == ".." || name == "iconres.ezx")
                continue;
            std::string path = clone + "/" + name;
            clean =
                lstat(path.c_str(), &st) == 0 && S_ISLNK(st.st_mode) && unlink(path.c_str()) == 0;
        }
        closedir(previous);
        if (!clean) {
            error = "The generated skin contains user files; refusing to remove them";
            return false;
        }
    }
    DIR *list = opendir(original.c_str());
    if (!list)
        return false;
    bool ok = true;
    struct dirent *item;
    while (ok && (item = readdir(list))) {
        std::string name(item->d_name);
        if (name == "." || name == ".." || name == "iconres.ezx")
            continue;
        std::string target = clone + "/" + name, source = original + "/" + name;
        if (lstat(target.c_str(), &st) == 0) {
            // Only replace links we generated; never remove user files.
            if (!S_ISLNK(st.st_mode) || unlink(target.c_str())) {
                ok = false;
                break;
            }
        } else if (errno != ENOENT) {
            ok = false;
            break;
        }
        ok = symlink(source.c_str(), target.c_str()) == 0;
    }
    closedir(list);
    if (!ok)
        return false;
    // Save a full config copy for inspection and a separate rollback path.
    // On upgrades retain the original backup, never back up our own skin.
    if (skin != clone &&
        (!writeText(root + "/theme-backup.cfg", text, mode) || !writeText(state, original)))
        return false;
    text.replace(a, b - a, "CurrentSkin = " + clone);
    error = "Cannot switch to the prepared theme; the original remains active";
    return writeText(config, text, mode);
}
} // namespace tmm
