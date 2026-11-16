#include "application.h"
#include "window.h"
#include "storage.h"
#include "ui_settings.h"
#include "ui_language.h"
#include <ZMultiLineEdit.h>
#include <ZKeyDef.h>
#include <qapplication.h>
#include <qtimer.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
extern "C" void UTIL_SetPowerOnHandleStatus(int);
extern "C" void UTIL_SetFlipStatus(int);
extern "C" void UTIL_SetKeypadLockStatus(bool);
namespace tmm {
class UiProbe {
    static unsigned checks;
    static void require(bool value, const char *name) {
        if (!value) {
            fprintf(stderr, "UI FAIL: %s\n", name);
            exit(2);
        }
        ++checks;
        fprintf(stderr, "UI PASS: %s\n", name);
        fflush(stderr);
    }
    static MessageRecord message(uint32_t uin, unsigned serial, bool silent) {
        MessageRecord m;
        m.uin = uin;
        m.cookie = serial;
        m.text = "Hello from Telegram";
        m.senderName = "Alice";
        m.time = time(0);
        m.silent = silent;
        m.nativeId = std::string(8, (char)serial);
        return m;
    }

  public:
    static void run(Window &w) {
        fprintf(stderr, "UI BEGIN\n");
        fflush(stderr);
        w.timer_.stop();
        std::string initialError;
        w.settings_.set("host", "127.0.0.1");
        w.settings_.set("uin", "123456");
        w.settings_.set("password", "dummy");
        w.settings_.setInt("auto_connect", 0);
        require(w.selectScope(), "test account scope");
        w.storage_->clearAllHistory(initialError);
        w.chats_.clear();
        w.contacts_.clear();
        w.settings_.set("lock_pin", "1234");
        w.settings_.set("sound_unlocked", "");
        w.settings_.set("vibration_unlocked", "0");
        w.settings_.set("typing_sound", "");
        w.settings_.set("external_preview", "0");
        w.settings_.setInt("history_count", 200);
        w.settings_.setInt("chat_messages", 15);
        w.settings_.setInt("auto_connect", 0);
        w.applySettings();
        Event roster;
        roster.type = Event::Roster;
        roster.flag = true;
        ContactRecord group;
        group.type = 1;
        group.groupId = 1;
        group.name = "Telegram";
        roster.contacts.push_back(group);
        ContactRecord a;
        a.uin = 1000001;
        a.name = "Alice";
        a.groupId = 1;
        a.type = 0;
        a.inRoster = true;
        roster.contacts.push_back(a);
        w.consume(roster);
        require(w.contact(a.uin) && w.contact(a.uin)->name == "Alice", "initial roster");
        Event incremental;
        incremental.type = Event::Roster;
        ContactRecord b = a;
        b.uin = 1000002;
        b.name = "Bob";
        incremental.contacts.push_back(b);
        w.consume(incremental);
        require(w.contact(a.uin) && w.contact(b.uin), "incremental roster preserves existing");
        ContactRecord privacy;
        privacy.type = 14;
        privacy.uin = a.uin;
        incremental.contacts.clear();
        incremental.contacts.push_back(privacy);
        w.consume(incremental);
        require(w.contact(a.uin)->name == "Alice" && w.contact(a.uin)->privacy == 4,
                "privacy row preserves contact name");
        Event presence;
        presence.type = Event::Presence;
        presence.uin = a.uin;
        presence.status = 0x100;
        w.consume(presence);
        require(w.contact(a.uin)->status == 0x100, "network unavailable preserved");
        w.home();
        w.startedAt_ = 0;
        w.lastAlert_ = 0;
        w.incoming(message(a.uin, 1, true));
        require(w.unread() == 1 && w.lastAlert_ == 0,
                "silent arrival keeps unread without burst gate");
        w.incoming(message(a.uin, 2, false));
        require(w.unread() == 2 && w.lastAlert_ != 0, "next normal arrival alerts");
        w.incoming(message(a.uin, 2, false));
        require(w.unread() == 2, "duplicate delivery not recounted");
        MessageRecord part1 = message(a.uin, 71, true), part2 = part1;
        part2.cookie = 72;
        part1.text = part2.text = "repeated text piece";
        size_t before = w.chats_[a.uin].messages.size();
        w.incoming(part1);
        w.incoming(part2);
        require(w.chats_[a.uin].messages.size() == before + 2,
                "split identical text distinct cookies preserved");
        w.incoming(part2);
        require(w.chats_[a.uin].messages.size() == before + 2, "same cookie duplicate rejected");
        MessageRecord seed = part1;
        seed.cookie = 0;
        w.incoming(seed);
        require(w.chats_[a.uin].messages.size() == before + 2,
                "native id fallback dedups exact history seed");
        seed.text = "different piece";
        w.incoming(seed);
        require(w.chats_[a.uin].messages.size() == before + 3,
                "native id fallback preserves distinct text");
        w.openChat(a.uin);
        require(w.chats_[a.uin].unread == 0 && w.view().kind == View::Chat,
                "opening chat clears unread");
        w.key(KEYCODE_RSK);
        require(w.view().rows.size() > 10, "chat menu opens via key");
        w.back();
        w.edit(QString::fromLatin1("Message"), "message", "Draft survives PIN", a.uin);
        require(w.editor_->text() == "Draft survives PIN", "native editor draft");
        w.lock();
        require(w.locked_ && !w.editor_->isVisible(), "PIN hides native editor");
        w.minimize();
        require(!w.isVisible() && w.locked_, "minimize preserves PIN lock");
        w.platform_.requestForeground();
        require(w.isVisible() && w.locked_, "restore preserves PIN lock");
        w.key(KEYCODE_1);
        w.key(KEYCODE_2);
        w.key(KEYCODE_3);
        w.key(KEYCODE_4);
        require(!w.locked_ && w.editor_->isVisible() && w.editor_->text() == "Draft survives PIN",
                "PIN restores same editor and draft");
        w.finishEdit(false);
        require(w.storage_->loadDraft(a.uin) == "Draft survives PIN", "cancel preserves draft");
        w.edit(QString::fromLatin1("Message"), "message", "Before ", a.uin);
        w.editorMenu();
        w.activate(Row(QString::null, "smileys"));
        w.activate(Row(QString::null, "insert::)"));
        require(w.editor_->isVisible() && w.editor_->text().find(":)") >= 0 &&
                    w.stack_.size() == w.editDepth_,
                "insert returns to original editor");
        w.finishEdit(false);
        MessageRecord longMessage = message(a.uin, 3, true);
        longMessage.text = std::string(5000, 'x');
        w.incoming(longMessage);
        w.view().selected = w.view().rows.size() - 1;
        w.key(KEYCODE_DOWN);
        require(w.view().scroll > 0, "long message scrolls within selected row");
        w.key(KEYCODE_UP);
        require(w.view().scroll == 0, "long message scrolls back");
        w.home();
        for (unsigned i = 10; i < 25; ++i)
            w.incoming(message(1000000 + i, i, true));
        unsigned loaded = 0;
        for (std::map<uint32_t, ChatState>::iterator i = w.chats_.begin(); i != w.chats_.end(); ++i)
            if (i->second.loaded)
                ++loaded;
        require(loaded >= 15 && w.unread() >= 15, "unread chats remain in RAM");
        for (unsigned i = 10; i < 25; ++i)
            require(!w.chats_[1000000 + i].messages.empty(), "unread text retained");
        w.settings_.setInt("history_count", 0);
        w.applySettings();
        for (unsigned i = 30; i < 45; ++i)
            w.incoming(message(1000000 + i, i, true));
        require(!w.chats_[1000030].messages.empty(), "history off does not evict unread");
        w.settings_.setInt("history_count", 200);
        w.applySettings();
        for (std::map<uint32_t, ChatState>::iterator i = w.chats_.begin(); i != w.chats_.end(); ++i)
            i->second.unread = 0;
        w.trimChats();
        loaded = 0;
        for (std::map<uint32_t, ChatState>::iterator i = w.chats_.begin(); i != w.chats_.end(); ++i)
            if (i->second.loaded)
                ++loaded;
        require(loaded <= 8, "read chat cache bounded");
        MessageRecord outgoing = message(1000024, 100, true);
        outgoing.outgoing = true;
        w.incoming(outgoing);
        w.chats_[outgoing.uin].messages.clear();
        w.chats_[outgoing.uin].loaded = false;
        Event receipt;
        receipt.type = Event::Receipt;
        receipt.uin = outgoing.uin;
        receipt.cookie = outgoing.cookie;
        receipt.delivery = 2;
        receipt.nativeId = std::string(8, 'r');
        w.consume(receipt);
        std::vector<MessageRecord> saved;
        require(w.storage_->loadHistory(outgoing.uin, saved, 200) && !saved.empty() &&
                    saved.back().delivery == 2 && saved.back().nativeId == receipt.nativeId,
                "receipt updates evicted disk history");
        w.showSettings("media");
        require(w.view().rows.size() > 8, "media settings listed");
        w.chooseSetting("video_kbps");
        require(w.view().kind == View::Choice && w.view().rows.size() > 4, "media uses choices");
        w.back();
        w.home();
        w.activate(Row(QString::null, "settings"));
        w.activate(Row(QString::null, "settings:network"));
        w.chooseSetting("encryption");
        w.activate(Row(QString::null, "set:encryption:1"));
        require(w.settings_.getBool("encryption"), "setting choice persists");
        w.settings_.set("language", "en");
        w.applySettings();
        require(uiText("Настройки") == "Settings", "English UI translation");
        w.settings_.set("language", "ru");
        w.applySettings();
        w.quiet_.push_back(a.uin);
        w.quoteId_ = std::string(8, 'q');
        w.pending_[991] = "history";
        w.settings_.set("uin", "4295090752");
        require(!w.selectScope() && w.contacts_.empty() && w.chats_.empty() && w.quiet_.empty() &&
                    w.quoteId_.empty() && w.pending_.empty() && w.storage_->accountDir().empty(),
                "invalid account clears previous private scope");
        w.settings_.set("uin", "123456");
        require(w.selectScope(), "valid account restored");
        MessageRecord glyph = message(a.uin, 250, true);
        glyph.outgoing = true;
        glyph.delivery = 2;
        glyph.text = ":) *IN_LOVE*";
        QString safe = w.messageText(glyph);
        require(safe.find(QString::fromUtf8("✓")) < 0 && safe.find(QString::fromUtf8("↗")) < 0 &&
                    safe.find(QString::fromUtf8("☺")) < 0 && safe.find(":)") >= 0,
                "message icons independent of unsupported font glyphs");
        // End on a readable fixture scene for visual inspection; no network request.
        w.contacts_.clear();
        w.chats_.clear();
        ContactRecord demo = a;
        demo.name = "Сергей";
        demo.group = "Telegram";
        demo.status = 0;
        w.contacts_.push_back(demo);
        demo = b;
        demo.name = "MOTOZINE";
        demo.group = "Telegram/Каналы";
        demo.groupId = 2;
        demo.status = 0x100;
        w.contacts_.push_back(demo);
        demo.uin = 1000003;
        demo.name = "Мария";
        demo.group = "MAX";
        demo.groupId = 3;
        demo.status = 0;
        w.contacts_.push_back(demo);
        MessageRecord demoMessage = message(a.uin, 200, true);
        demoMessage.senderName = "Сергей";
        demoMessage.text = "Привет! Как работает новая версия на V8?";
        w.chats_[a.uin].messages.push_back(demoMessage);
        demoMessage = message(a.uin, 201, true);
        demoMessage.outgoing = true;
        demoMessage.delivery = 2;
        demoMessage.text = "Привет! Чаты, история и цитирование уже проверены.";
        w.chats_[a.uin].messages.push_back(demoMessage);
        demoMessage = message(a.uin, 202, true);
        demoMessage.senderName = "Сергей";
        demoMessage.text = "Отлично, отправляю видео.";
        demoMessage.kind = 2;
        w.chats_[a.uin].messages.push_back(demoMessage);
        w.chats_[a.uin].loaded = true;
        w.chats_[a.uin].unread = 2;
        w.chats_[b.uin].unread = 5;
        const char *scene = getenv("TMM_NATIVE_UI_SCENE");
        std::string selectedScene = scene ? scene : "chat";
        w.home();
        if (selectedScene == "settings")
            w.showSettings("media");
        else if (selectedScene != "roster")
            w.openChat(a.uin);
        w.notice_ = QString::null;
        w.noticeUntil_ = 0;
        w.resize(240, 320);
        w.show();
        w.repaint();
        fprintf(stderr, "UI PASS %u checks\n", checks);
    }
};
unsigned UiProbe::checks = 0;
} // namespace tmm
int main(int argc, char **argv) {
    tmm::Application app(argc, argv, QApplication::GuiServer);
    UTIL_SetPowerOnHandleStatus(10);
    UTIL_SetFlipStatus(SYSTEM_FLIP_OPEN);
    UTIL_SetKeypadLockStatus(false);
    const char *data = getenv("TMM_NATIVE_UI_TEST_DATA");
    std::string dir = data && *data ? data : "/state/data";
    std::string error;
    if (!tmm::ensureDirectory(dir, error)) {
        fprintf(stderr, "%s\n", error.c_str());
        return 1;
    }
    tmm::Window window(dir);
    app.setMainWidget(&window);
    window.resize(240, 320);
    window.show();
    app.processEvents();
    tmm::UiProbe::run(window);
    QTimer::singleShot(1500, &app, SLOT(quit()));
    return app.exec();
}
