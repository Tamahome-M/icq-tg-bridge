#include "storage.h"
#include "settings.h"
#include <assert.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>
#include <stdio.h>
#include <fstream>
using namespace tmm;
int main() {
    char pattern[] = "/tmp/tmm-storage-XXXXXX";
    char *root = mkdtemp(pattern);
    assert(root);
    std::string base = root, error;
    Settings s;
    assert(s.load(base + "/settings", error));
    s.set("account.0.password", "secret\n\tпароль");
    s.setInt("integer", 42);
    s.setBool("flag", true);
    assert(s.save(error));
    Settings loaded;
    assert(loaded.load(base + "/settings", error));
    assert(loaded.get("account.0.password") == s.get("account.0.password"));
    assert(loaded.getInt("integer") == 42);
    assert(loaded.getBool("flag"));
    assert(atomicWrite(base + "/broken", "TMMN1\n61\t62", error));
    assert(!loaded.load(base + "/broken", error));
    assert(loaded.getInt("integer") == 42);
    assert(!loaded.save(error));
    assert(readBounded(base + "/broken", error, 100) && error == "TMMN1\n61\t62");
    loaded.reset();
    assert(loaded.save(error));
    // An unsuccessful atomic replacement leaves the destination and no .new
    // files. A directory is an unavoidable rename failure even when run as root.
    assert(mkdir((base + "/directory").c_str(), 0700) == 0);
    assert(!atomicWrite(base + "/directory", "data", error));
    struct stat st;
    assert(stat((base + "/directory").c_str(), &st) == 0 && S_ISDIR(st.st_mode));
    assert(symlink((base + "/settings").c_str(), (base + "/link").c_str()) == 0);
    std::string contents;
    assert(!readBounded(base + "/link", contents, 1024));
    Storage a(base);
    a.setHistoryLimit(500);
    assert(a.setAccount("bridge.example", 5190, 123456, error));
    const std::string first = a.accountDir();
    std::vector<MessageRecord> messages;
    assert(a.loadHistory(1000001, messages));
    assert(messages.empty());
    MessageRecord m;
    m.uin = 1000001;
    m.sourceUin = 1000002;
    m.discussionUin = 1000003;
    m.time = 1780000000;
    m.cookie = 0x0102030405060708ULL;
    m.text = "Привет";
    m.nativeId = "tg:123:456";
    m.token = std::string("\0\1\xff", 3);
    m.url = "http://local/video";
    m.senderName = "Имя";
    m.kind = 3;
    m.silent = true;
    m.outgoing = true;
    assert(a.appendHistory(m.uin, m, error));
    m.delivery = 2;
    assert(a.appendHistory(m.uin, m, error));
    assert(a.loadHistory(m.uin, messages));
    assert(messages.size() == 1);
    assert(messages[0].delivery == 2 && messages[0].token == m.token &&
           messages[0].cookie == m.cookie && messages[0].discussionUin == m.discussionUin);
    MessageRecord late = m;
    late.delivery = 0;
    late.nativeId.clear();
    assert(a.appendHistory(m.uin, late, error));
    assert(a.loadHistory(m.uin, messages) && messages.size() == 1 && messages[0].delivery == 2 &&
           messages[0].nativeId == m.nativeId);
    a.setHistoryLimit(0);
    assert(a.updateReceipt(m.uin, m.cookie, 1, "max:new-id", error));
    assert(a.loadHistory(m.uin, messages) && messages.size() == 1 && messages[0].delivery == 2 &&
           messages[0].nativeId == "max:new-id");
    a.setHistoryLimit(500);
    // One provider message can be split into several OSCAR deliveries, all
    // sharing the same quote locator, even with identical fragment text.
    MessageRecord fragment = messages[0];
    fragment.cookie++;
    assert(a.appendHistory(m.uin, fragment, error));
    assert(a.loadHistory(m.uin, messages) && messages.size() == 2);
    assert(a.appendHistory(m.uin, fragment, error));
    assert(a.loadHistory(m.uin, messages) && messages.size() == 2);
    // A server-history record without a delivery cookie matches only the
    // corresponding content, not every fragment with this provider locator.
    fragment.cookie = 0;
    fragment.text = "Ещё один фрагмент";
    assert(a.appendHistory(m.uin, fragment, error));
    assert(a.loadHistory(m.uin, messages) && messages.size() == 3);
    assert(a.appendHistory(m.uin, fragment, error));
    assert(a.loadHistory(m.uin, messages) && messages.size() == 3);
    assert(a.saveDraft(m.uin, "Черновик", error));
    std::vector<uint32_t> quiet;
    quiet.push_back(m.uin);
    quiet.push_back(m.uin);
    quiet.push_back(0);
    assert(a.saveQuietChats(quiet, error));
    assert(a.quietChats().size() == 1);
    std::vector<std::string> templates;
    templates.push_back("Да\nНет");
    assert(a.saveTemplates(templates, error));
    assert(a.templates() == templates);
    std::vector<ContactRecord> contacts(1);
    contacts[0].uin = m.uin;
    contacts[0].name = "Чат";
    contacts[0].status = 0;
    contacts[0].inRoster = true;
    contacts[0].group = "Telegram";
    assert(a.saveRoster(contacts, error));
    contacts.clear();
    assert(a.loadRoster(contacts));
    assert(contacts.size() == 1 && contacts[0].status == 0xffffffffU && contacts[0].name == "Чат");
    // Same UIN on another bridge/account must never expose existing data.
    assert(a.setAccount("other.example", 5190, 123456, error));
    assert(a.accountDir() != first);
    assert(a.loadDraft(m.uin).empty());
    assert(a.quietChats().empty());
    assert(a.loadHistory(m.uin, messages) && messages.empty());
    assert(a.setAccount("bridge.example", 5190, 654321, error));
    assert(a.loadDraft(m.uin).empty());
    assert(a.setAccount("bridge.example", 5190, 123456, error));
    assert(a.loadDraft(m.uin) == "Черновик");
    messages.assign(600, m);
    for (unsigned i = 0; i < messages.size(); ++i) {
        messages[i].cookie = i + 1;
        messages[i].nativeId = "";
        messages[i].text = std::string(5000, 'x');
    }
    assert(a.saveHistory(m.uin, messages, error));
    assert(a.loadHistory(m.uin, messages, 500));
    assert(!messages.empty() && messages.size() < 500 && messages.back().cookie == 600);
    assert(a.loadHistory(m.uin, messages, 3) && messages.size() == 3 &&
           messages.front().cookie == 598);
    // Truncated local data is not silently destroyed by an incoming message.
    assert(atomicWrite(first + "/history-1000001.dat", "TMH1\0", error));
    assert(!a.appendHistory(m.uin, m, error));
    assert(readBounded(first + "/history-1000001.dat", contents, 100) && contents == "TMH1");
    assert(a.clearAllHistory(error));
    assert(a.loadHistory(m.uin, messages) && messages.empty());
    assert(a.loadDraft(m.uin) == "Черновик");
    assert(a.templates() == templates);
    assert(a.clearHistory(m.uin, error));
    assert(ensureDirectory(first + "/cache", error));
    assert(atomicWrite(first + "/cache/media-Ab12xZ.jpg", "download", error));
    assert(atomicWrite(first + "/cache/my-photo.jpg", "user file", error));
    assert(atomicWrite(first + "/capture-123.jpg", "unsent photo", error));
    assert(cleanupCachedMedia(base, error));
    assert(access((first + "/cache/media-Ab12xZ.jpg").c_str(), F_OK) < 0);
    assert(access((first + "/cache/my-photo.jpg").c_str(), F_OK) == 0);
    assert(access((first + "/capture-123.jpg").c_str(), F_OK) == 0);
    // Reset spans every managed account, but never a user file or link target.
    assert(atomicWrite(first + "/cache/media-Ab12xZ.3gp", "download", error));
    assert(atomicWrite(first + "/cache/media-not-random.jpg", "unknown", error));
    assert(atomicWrite(first + "/capture-123-1.jpg", "owned capture", error));
    assert(atomicWrite(first + "/notes.txt", "user note", error));
    assert(atomicWrite(first + "/history-1000001.dat.new-Ab12xZ", "interrupted save", error));
    assert(atomicWrite(base + "/outside.dat", "external target", error));
    assert(unlink((first + "/roster.dat").c_str()) == 0);
    assert(symlink((base + "/outside.dat").c_str(), (first + "/roster.dat").c_str()) == 0);
    assert(a.setAccount("other.example", 5190, 123456, error));
    const std::string second = a.accountDir();
    assert(a.saveDraft(m.uin, "Another draft", error));
    assert(a.saveTemplates(templates, error));
    assert(a.appendHistory(m.uin, m, error));
    assert(ensureDirectory(base + "/accounts/not-an-account", error));
    assert(atomicWrite(base + "/accounts/not-an-account/history-1.dat", "user file", error));
    const std::string linked = base + "/accounts/" + std::string(64, 'f');
    assert(symlink((base + "/accounts/not-an-account").c_str(), linked.c_str()) == 0);
    assert(a.resetAll(error));
    assert(access((first + "/draft-1000001.dat").c_str(), F_OK) < 0);
    assert(access((first + "/templates.dat").c_str(), F_OK) < 0);
    assert(access((first + "/quiet.dat").c_str(), F_OK) < 0);
    assert(access((first + "/capture-123-1.jpg").c_str(), F_OK) < 0);
    assert(access((first + "/history-1000001.dat.new-Ab12xZ").c_str(), F_OK) < 0);
    assert(access((first + "/cache/media-Ab12xZ.3gp").c_str(), F_OK) < 0);
    assert(access((second + "/history-1000001.dat").c_str(), F_OK) < 0);
    assert(access((second + "/draft-1000001.dat").c_str(), F_OK) < 0);
    assert(access((second + "/templates.dat").c_str(), F_OK) < 0);
    assert(access((first + "/cache/my-photo.jpg").c_str(), F_OK) == 0);
    assert(access((first + "/cache/media-not-random.jpg").c_str(), F_OK) == 0);
    assert(access((first + "/capture-123.jpg").c_str(), F_OK) == 0);
    assert(access((first + "/notes.txt").c_str(), F_OK) == 0);
    assert(readBounded(base + "/outside.dat", contents, 100) && contents == "external target");
    assert(lstat((first + "/roster.dat").c_str(), &st) == 0 && S_ISLNK(st.st_mode));
    assert(lstat(linked.c_str(), &st) == 0 && S_ISLNK(st.st_mode));
    assert(readBounded(base + "/accounts/not-an-account/history-1.dat", contents, 100) &&
           contents == "user file");
    // A redirected accounts root must fail instead of traversing its target.
    assert(ensureDirectory(base + "/redirected", error));
    assert(symlink((base + "/accounts").c_str(), (base + "/redirected/accounts").c_str()) == 0);
    Storage redirected(base + "/redirected");
    assert(!redirected.resetAll(error) && !error.empty());
    assert(access((base + "/accounts/not-an-account/history-1.dat").c_str(), F_OK) == 0);
    printf("storage/settings and constrained all-account reset OK (%s)\n", root);
    return 0;
}
