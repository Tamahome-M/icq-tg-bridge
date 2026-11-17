#include "ui_smileys.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
namespace tmm {
namespace {
bool number(const std::string &text, unsigned maximum, unsigned &result) {
    if (text.empty() || text.find_first_not_of("0123456789") != std::string::npos)
        return false;
    char *end = 0;
    unsigned long value = strtoul(text.c_str(), &end, 10);
    if (*end || value > maximum)
        return false;
    result = value;
    return true;
}
std::vector<std::string> words(const char *line) {
    std::vector<std::string> result;
    const std::string text(line);
    size_t at = 0;
    while ((at = text.find_first_not_of(" \t\r\n", at)) != std::string::npos) {
        const size_t end = text.find_first_of(" \t\r\n", at);
        result.push_back(text.substr(at, end == std::string::npos ? end : end - at));
        if (end == std::string::npos)
            break;
        at = end;
    }
    return result;
}
} // namespace
bool loadJavaSmileys(const std::string &path, std::vector<SmileyDefinition> &definitions,
                     unsigned &cellSize, std::string &error) {
    FILE *file = fopen(path.c_str(), "rb");
    if (!file) {
        error = "Не удалось открыть список смайлов";
        return false;
    }
    struct stat st;
    bool ok =
        !fstat(fileno(file), &st) && S_ISREG(st.st_mode) && st.st_size > 0 && st.st_size <= 65536;
    char line[1024];
    unsigned size = 0;
    std::vector<SmileyDefinition> parsed;
    if (ok && fgets(line, sizeof(line), file)) {
        const std::vector<std::string> header = words(line);
        ok = header.size() == 1 && number(header[0], 64, size) && size > 0;
    } else
        ok = false;
    while (ok && fgets(line, sizeof(line), file)) {
        const long consumed = ftell(file);
        if (consumed < 0 || consumed > 65536) {
            ok = false;
            break;
        }
        if (!strchr(line, '\n') && !feof(file) && strlen(line) == sizeof(line) - 1) {
            ok = false;
            break;
        }
        const std::vector<std::string> fields = words(line);
        if (fields.empty() || fields[0][0] == '#')
            continue;
        // Java ignores short lines and uses the first alias for selection.
        if (fields.size() < 3)
            continue;
        unsigned index;
        if (!number(fields[0], 1023, index) || fields[1].size() > 128 || fields[2].size() > 128 ||
            parsed.size() >= 256) {
            ok = false;
            break;
        }
        std::string label = fields[1];
        for (size_t i = 0; i < label.size(); ++i)
            if (label[i] == '_')
                label[i] = ' ';
        parsed.push_back(SmileyDefinition(index, label, fields[2]));
    }
    if (ferror(file))
        ok = false;
    fclose(file);
    if (!ok || parsed.empty()) {
        error = "Неверный список смайлов";
        return false;
    }
    definitions.swap(parsed);
    cellSize = size;
    error.clear();
    return true;
}
} // namespace tmm
