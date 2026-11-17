#include "ui_links.h"
#include <algorithm>
#include <string.h>
namespace tmm {
namespace {
const char *prefixes[] = {"http://", "https://", "ftp://", "www.", "ftp.", "mailto:"};
// Java permits codepoints <= U+00FF except whitespace, double quote and comma.
// Consume valid UTF-8 here so non-Latin-1 message text ends a URL identically.
size_t urlCharacter(const std::string &text, size_t at) {
    const unsigned char first = text[at];
    if (first < 0x80)
        return first > ' ' && first != '"' && first != ',' ? 1 : 0;
    if ((first == 0xc2 || first == 0xc3) && at + 1 < text.size()) {
        const unsigned char second = text[at + 1];
        if (second >= 0x80 && second <= 0xbf)
            return 2;
    }
    return 0;
}
} // namespace
std::vector<std::string> javaMessageUrls(const std::string &text) {
    std::vector<std::string> result;
    size_t start = 0;
    while (start < text.size()) {
        size_t next = std::string::npos;
        unsigned family = 0;
        for (unsigned i = 0; i < sizeof(prefixes) / sizeof(prefixes[0]); ++i) {
            const size_t candidate = text.find(prefixes[i], start);
            if (candidate < next) {
                next = candidate;
                family = i;
            }
        }
        if (next == std::string::npos)
            break;
        const size_t body = next + strlen(prefixes[family]);
        size_t end = body, characters = 0;
        for (size_t length; end < text.size() && (length = urlCharacter(text, end)) != 0;) {
            end += length;
            ++characters;
        }
        if (characters < 3) {
            start = body;
            continue;
        }
        start = end;
        std::string url = text.substr(next, end - next);
        if (family == 3 || family == 4)
            url = "http://" + url;
        if (std::find(result.begin(), result.end(), url) == result.end())
            result.push_back(url);
    }
    return result;
}
} // namespace tmm
