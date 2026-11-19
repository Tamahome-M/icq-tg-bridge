// Pure host checks against the shared Java V8 resource; no Qt/hardware substitutes.
#include "ui_links.h"
#include "ui_smileys.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>
#include <string>
#include <vector>
static void one(const std::string &source, const char *url) {
    std::vector<std::string> links = tmm::javaMessageUrls(source);
    assert(links.size() == 1 && links[0] == url);
}
int main(int argc, char **argv) {
    assert(argc == 2);
    std::vector<tmm::SmileyDefinition> smileys;
    unsigned cell = 99;
    std::string error;
    assert(tmm::loadJavaSmileys(argv[1], smileys, cell, error));
    assert(cell == 16 && smileys.size() == 32 && error.empty());
    assert(smileys[0].index == 0 && smileys[0].code == ":-)" && smileys[0].label == "Smile");
    assert(smileys[7].index == 7 && smileys[7].code == ":-D" && smileys[7].label == "Very happy");
    assert(smileys[31].index == 31 && smileys[31].code == "=)" &&
           smileys[31].label == "On the side");
    const char *codes[] = {":-)",      ":-(",  ";-)",     ":-P",         "*JOKINGLY*", ":'(",
                           "*KISSED*", ":-D",  "*STOP*",  "*IN_LOVE*",   ">:o",        ":-!",
                           "*DRINK*",  ":-\\", "*TIRED*", "*THUMBS_UP*", ":-X",        "[:-}",
                           "@=",       "O:-)", "8-)",     "@}->--",      ":-[",        "=-O",
                           "]:->",     ":-*",  ":-$",     "*KISSING*",   ";-D",        "%-)",
                           "X-)",      "=)"};
    for (unsigned i = 0; i < smileys.size(); ++i)
        assert(smileys[i].index == i && smileys[i].code == codes[i]);
    char bad[] = "/tmp/tmm-smiles-XXXXXX";
    int fd = mkstemp(bad);
    assert(fd >= 0);
    const char *broken = "16\n0 Smile :-)\n999999 Broken :(\n";
    assert(write(fd, broken, strlen(broken)) == (ssize_t)strlen(broken));
    close(fd);
    assert(!tmm::loadJavaSmileys(bad, smileys, cell, error));
    assert(smileys.size() == 32 && cell == 16 && !error.empty());
    unlink(bad);
    assert(tmm::javaMessageUrls("HTTP://abc http://ab www.ab mailto:a@").empty());
    one("www.example.test", "http://www.example.test");
    one("http://www.example.test www.example.test", "http://www.example.test");
    one("http://abcДальше", "http://abc");
    one("http://ééé", "http://ééé");
    assert(tmm::javaMessageUrls("http://éé").empty());
    one("mailto:a@b", "mailto:a@b");
    one("ftp://ftp.example.test", "ftp://ftp.example.test");
    one("ftp.example.test", "http://ftp.example.test");
    std::vector<std::string> links =
        tmm::javaMessageUrls("http://abc,https://def\"www.ghi http://abc");
    assert(links.size() == 3 && links[0] == "http://abc" && links[1] == "https://def" &&
           links[2] == "http://www.ghi");
    const std::string video = "[видео](http://bridge.test/v/1234567890abcdef?key=secret) 0:08\n"
                              "Caption with https://example.test";
    assert(tmm::videoMessageText(video, "") == "[видео] 0:08\nCaption with https://example.test");
    assert(tmm::javaMessageUrls(video).size() == 2); // Browser actions keep original URLs.
    assert(
        tmm::videoMessageText("\nhttp://bridge.test/v/123\n", "http://bridge.test/v/123").empty());
    assert(tmm::videoMessageText("Caption https://example.test", "") ==
           "Caption https://example.test");
    assert(tmm::videoMessageText("[видео](broken", "") == "[видео](broken");
    puts("Java URLs, hidden video links and full32 smiley manifest: host checks passed");
}
