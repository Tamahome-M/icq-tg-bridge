#include "chat_history.h"
#include <algorithm>
namespace tmm {
static bool same(const MessageRecord &a, const MessageRecord &b) {
    if (!a.nativeId.empty() && !b.nativeId.empty())
        return a.nativeId == b.nativeId;
    // Legacy server records have neither a cookie nor a native reference.
    // Compare their complete, server-formatted header as well as their body.
    return a.nativeId.empty() && b.nativeId.empty() && !a.time && !b.time && a.text == b.text &&
           a.outgoing == b.outgoing && a.kind == b.kind;
}
HistoryMerge mergeChatHistory(std::vector<MessageRecord> &current,
                              const std::vector<MessageRecord> &page, unsigned boundary) {
    HistoryMerge result;
    result.oldPositions.resize(current.size());
    if (page.empty()) {
        for (unsigned i = 0; i < current.size(); ++i)
            result.oldPositions[i] = i;
        result.firstPage = std::min(boundary, unsigned(current.size()));
        return result;
    }
    std::vector<MessageRecord> merged, waiting;
    merged.reserve(current.size() + page.size());
    bool pageAnchored = false;
    unsigned cursor = 0;
    boundary = std::min(boundary, unsigned(current.size()));
    for (unsigned p = 0; p < page.size(); ++p) {
        unsigned match = cursor;
        while (match < current.size() && !same(current[match], page[p]))
            ++match;
        if (match == current.size()) {
            waiting.push_back(page[p]);
            continue;
        }
        while (cursor < match) {
            result.oldPositions[cursor] = merged.size();
            merged.push_back(current[cursor++]);
        }
        if (!pageAnchored) {
            result.firstPage = merged.size();
            pageAnchored = true;
        }
        merged.insert(merged.end(), waiting.begin(), waiting.end());
        waiting.clear();
        do {
            result.oldPositions[cursor] = merged.size();
            MessageRecord existing = current[cursor++];
            if (page[p].kind && existing.kind == page[p].kind && !page[p].token.empty())
                existing.token = page[p].token;
            if (!page[p].url.empty() && existing.kind == page[p].kind)
                existing.url = page[p].url;
            if (page[p].discussionUin)
                existing.discussionUin = page[p].discussionUin;
            merged.push_back(existing);
        } while (!page[p].nativeId.empty() && cursor < current.size() &&
                 current[cursor].nativeId == page[p].nativeId);
    }
    if (!pageAnchored) {
        while (cursor < boundary) {
            result.oldPositions[cursor] = merged.size();
            merged.push_back(current[cursor++]);
        }
        result.firstPage = merged.size();
    }
    merged.insert(merged.end(), waiting.begin(), waiting.end());
    while (cursor < current.size()) {
        result.oldPositions[cursor] = merged.size();
        merged.push_back(current[cursor++]);
    }
    current.swap(merged);
    return result;
}
} // namespace tmm
