#ifndef TMM_CHAT_HISTORY_H
#define TMM_CHAT_HISTORY_H
#include "client.h"
namespace tmm {
// Both inputs are chronological. A page is a complete server interval;
// common message IDs anchor it within the already displayed conversation.
struct HistoryMerge {
    std::vector<unsigned> oldPositions;
    unsigned firstPage;
    HistoryMerge() : firstPage(0) {}
};
HistoryMerge mergeChatHistory(std::vector<MessageRecord> &current,
                              const std::vector<MessageRecord> &page, unsigned boundary);
} // namespace tmm
#endif
