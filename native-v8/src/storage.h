#ifndef TMM_NATIVE_STORAGE_H
#define TMM_NATIVE_STORAGE_H
#include "client.h"
#include <stddef.h>
namespace tmm {
// Call once after acquiring Instance, before starting any network worker.
// Only disposable downloads are removed; recordings and user files are kept.
bool cleanupCachedMedia(const std::string &baseDirectory, std::string &error);
class Storage {
    std::string base_, scope_;
    unsigned historyLimit_;
    std::string file(const char *kind, uint32_t uin) const;

  public:
    explicit Storage(const std::string &baseDirectory);
    void setHistoryLimit(unsigned count);
    bool setAccount(const std::string &host, unsigned port, uint32_t uin, std::string &error);
    std::string accountDir() const {
        return scope_;
    }
    bool loadHistory(uint32_t uin, std::vector<MessageRecord> &out, size_t limit = 200) const;
    bool appendHistory(uint32_t uin, const MessageRecord &message, std::string &error);
    bool updateReceipt(uint32_t uin, uint64_t cookie, unsigned delivery,
                       const std::string &nativeId, std::string &error);
    bool saveHistory(uint32_t uin, const std::vector<MessageRecord> &messages, std::string &error);
    bool clearHistory(uint32_t uin, std::string &error);
    bool clearAllHistory(std::string &error);
    std::string loadDraft(uint32_t uin) const;
    bool saveDraft(uint32_t uin, const std::string &text, std::string &error);
    std::vector<std::string> templates() const;
    bool saveTemplates(const std::vector<std::string> &items, std::string &error);
    bool loadRoster(std::vector<ContactRecord> &out) const;
    bool saveRoster(const std::vector<ContactRecord> &items, std::string &error);
    std::vector<uint32_t> quietChats() const;
    bool saveQuietChats(const std::vector<uint32_t> &items, std::string &error);
};
} // namespace tmm
#endif
