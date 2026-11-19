#include "chat_history.h"
#include <cassert>
#include <cstdio>
using namespace tmm;
static MessageRecord message(const char *id, const char *text = "body", unsigned time = 1) {
    MessageRecord m;
    m.nativeId = id;
    m.text = text;
    m.time = time;
    m.uin = 1000001;
    return m;
}
static void ids(const std::vector<MessageRecord> &v, const char *expected) {
    std::string joined;
    for (size_t i = 0; i < v.size(); ++i)
        joined += v[i].nativeId;
    assert(joined == expected);
}
int main() {
    std::vector<MessageRecord> current, page;
    current.push_back(message("3"));
    current.push_back(message("4"));
    current.push_back(message("5"));
    current[1].cookie = 123;
    current[1].delivery = 2;
    current[1].outgoing = true;
    page.push_back(message("1"));
    page.push_back(message("2"));
    page.push_back(message("3"));
    page.push_back(message("4"));
    page.push_back(message("5"));
    HistoryMerge merged = mergeChatHistory(current, page, 3);
    ids(current, "12345");
    assert(merged.firstPage == 0 && merged.oldPositions[0] == 2 && merged.oldPositions[2] == 4);
    assert(current[3].cookie == 123 && current[3].delivery == 2 && current[3].outgoing);
    merged = mergeChatHistory(current, page, 0);
    ids(current, "12345");
    assert(merged.oldPositions[4] == 4);
    page.clear();
    page.push_back(message("0"));
    merged = mergeChatHistory(current, page, 0);
    ids(current, "012345");
    assert(merged.firstPage == 0 && merged.oldPositions[0] == 1);
    page.clear();
    merged = mergeChatHistory(current, page, 6);
    ids(current, "012345");
    assert(merged.oldPositions[5] == 5 && merged.firstPage == 6);
    // No common IDs: old local context, snapshot, then live arrival. Opaque
    // references must not be sorted lexically or interpreted as timestamps.
    current.clear();
    page.clear();
    current.push_back(message("z"));
    current.push_back(message("a"));
    page.push_back(message("y"));
    page.push_back(message("b"));
    merged = mergeChatHistory(current, page, 1);
    ids(current, "zyba");
    assert(merged.oldPositions[1] == 3 && merged.firstPage == 1);
    // A split live ICBM retains its individual pieces, cookies and receipts.
    current.clear();
    page.clear();
    current.push_back(message("B", "part1", 10));
    current.push_back(message("B", "part2", 10));
    current.push_back(message("C", "last", 11));
    current[1].cookie = 9;
    current[0].kind = 1;
    current[0].token = "expired";
    page.push_back(message("A"));
    page.push_back(message("B", "complete server text", 0));
    page.back().kind = 1;
    page.back().token = "fresh";
    page.back().url = "fresh-url";
    page.push_back(message("C", "last", 0));
    merged = mergeChatHistory(current, page, 3);
    ids(current, "ABBC");
    assert(current[1].text == "part1" && current[2].text == "part2" && current[2].cookie == 9);
    assert(current[1].time == 10 && current[1].token == "fresh" && current[1].url == "fresh-url" &&
           merged.oldPositions[1] == 2);
    // Legacy formatted history is deduplicated by the entire header/body,
    // never by body alone or against messages with a known live timestamp.
    current.clear();
    page.clear();
    current.push_back(message("", "[17.11 12:05] Nick: body", 0));
    page.push_back(current[0]);
    mergeChatHistory(current, page, 1);
    assert(current.size() == 1);
    current[0].time = 42;
    mergeChatHistory(current, page, 1);
    assert(current.size() == 2);
    std::puts("Chat history: chronological page merge, overlap, split messages, live boundaries, "
              "receipts and scroll mapping PASS");
}
