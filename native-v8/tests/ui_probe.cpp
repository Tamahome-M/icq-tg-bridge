#include "application.h"
#include "window.h"
#include "storage.h"
#include "ui_settings.h"
#include "ui_language.h"
#include "input_indicator.h"
#include "system_menu.h"
#include "status_icon.h"
#include <ZListBox.h>
#include <ZMultiLineEdit.h>
#include <ZKbInputField.h>
#include <ZKeyDef.h>
#include <qapplication.h>
#include <qtimer.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <errno.h>
#include <unistd.h>
extern "C" void UTIL_SetPowerOnHandleStatus(int);
extern "C" void UTIL_SetFlipStatus(int);
extern "C" void UTIL_SetKeypadLockStatus(bool);
void checkPaint(QWidget &, const char *);
void checkUnreadPaint(QWidget &, unsigned);
struct NotificationCall {
    QString file;
    int volume, vibration;
    NotificationCall(const QString &f, int v, int b) : file(f), volume(v), vibration(b) {}
};
static std::vector<NotificationCall> notifications;
extern "C" void __wrap__ZN3tmm8Platform13notifyMessageERK7QStringii(tmm::Platform *,
                                                                    const QString &file, int volume,
                                                                    int vibration) {
    notifications.push_back(NotificationCall(file, volume, vibration));
}
void checkInputIndicator(tmm::InputIndicator &);
void scheduleNetworkWorker(int);
void runNetworkWorker();
void checkForeground(tmm::Platform &, QWidget &);
void checkVideoParent(QWidget &);
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
    static void notificationPolicy(Window &w, uint32_t id) {
        MessageRecord m = message(id, 300, false);
        size_t before = notifications.size();
        struct timespec stamp;
        clock_gettime(CLOCK_MONOTONIC, &stamp);
        w.startedAt_ = (unsigned long)stamp.tv_sec * 1000 + stamp.tv_nsec / 1000000;
        w.lastAlert_ = 0;
        w.notify(m);
        require(notifications.size() == before, "startup's first minute suppresses audio API");
        w.startedAt_ = 0;
        w.settings_.set("sound_unlocked", "tg.mp3");
        w.settings_.setInt("volume_unlocked", 30);
        w.settings_.setInt("vibration_unlocked", 100);
        w.notify(m);
        require(notifications.size() == before + 1 &&
                    notifications.back().file == "sounds/tg.mp3" &&
                    notifications.back().volume == 30 && notifications.back().vibration == 100,
                "normal notification reaches audio API with selected file, level and vibration");
        w.notify(m);
        require(notifications.size() == before + 1, "burst gate suppresses repeated audio calls");
        w.settings_.set("sound_locked", "message.mp3");
        w.settings_.setInt("volume_locked", 70);
        w.settings_.setInt("vibration_locked", 500);
        w.locked_ = true;
        w.lastAlert_ = 0;
        w.notify(m);
        require(notifications.size() == before + 2 &&
                    notifications.back().file == "sounds/message.mp3" &&
                    notifications.back().volume == 70 && notifications.back().vibration == 500,
                "PIN lock uses the separate locked notification profile");
        w.locked_ = false;
        w.closed_ = true;
        w.lastAlert_ = 0;
        w.notify(m);
        require(notifications.size() == before + 3 &&
                    notifications.back().file == "sounds/message.mp3" &&
                    notifications.back().volume == 70,
                "closed flip uses the locked notification profile");
        w.closed_ = false;
        w.lastAlert_ = 0;
        m.silent = true;
        w.notify(m);
        m.silent = false;
        w.quiet_.push_back(id);
        w.notify(m);
        w.quiet_.pop_back();
        w.silent_ = true;
        w.notify(m);
        w.silent_ = false;
        require(notifications.size() == before + 3 && w.lastAlert_ == 0,
                "bridge silence, quiet whitelist and global mute never enter audio API");
        w.settings_.set("sound_unlocked", "");
        w.settings_.setInt("vibration_unlocked", 0);
        w.lastAlert_ = 0;
    }
    static void menus(Window &w) {
        w.home();
        w.notice_ = QString::null;
        w.mainMenu();
        ZListBox *list = w.systemMenu_->list();
        require(list->isVisible() && list->count() == int(w.view().rows.size()),
                "command menu uses the actual Motorola list");
        unsigned revision = w.systemMenu_->revision();
        QKeyEvent down(QEvent::KeyPress, KEYCODE_DOWN, 0, 0);
        QApplication::sendEvent(list->viewport(), &down);
        require(w.view().selected == 1 && list->currentItem() == 1 &&
                    w.systemMenu_->revision() == revision,
                "native menu key moves once without rebuilding rows");
        w.update();
        require(w.systemMenu_->revision() == revision, "idle update reuses native menu objects");
        w.back();
        require(!list->isVisible(), "back from menu hides native list");
        View empty(View::Menu, QString::fromLatin1("Search"));
        w.push(empty);
        require(!list->isVisible() && !w.systemMenuVisible(),
                "empty results leave the no-messages hint visible");
        w.view().request = 101;
        w.update();
        require(!list->isVisible() && !w.systemMenuVisible(),
                "pending results leave the loading hint visible");
        w.view().request = 0;
        w.back();
        w.showSettings("account");
        ZSettingItem *setting = static_cast<ZSettingItem *>(list->firstItem());
        require(setting && setting->getSubItemCount(0) == 2 &&
                    setting->getSubItemText(0, 0) == uiText("UIN") &&
                    setting->getSubItemText(0, 1) ==
                        QString::fromUtf8(w.settings_.get("uin").c_str()),
                "settings use native label and value regions");
        w.chooseSetting("password");
        require(!list->isVisible() && w.editor_->isVisible(),
                "editor replaces native settings list");
        w.hide();
        w.update();
        require(list->isHidden() && !w.systemMenuVisible(),
                "background updates do not show a menu over the hidden editor");
        w.show();
        w.editorMenu();
        if (w.view().kind != View::Popup || !list->isVisible())
            fprintf(stderr,
                    "UI popup diagnostic: kind=%d context=%s editorHidden=%d editorVisible=%d "
                    "action=%s menu=%d listHidden=%d listVisible=%d parentVisible=%d locked=%d "
                    "rows=%u\n",
                    int(w.view().kind), w.view().context.c_str(), w.editor_->isHidden(),
                    w.editor_->isVisible(), w.editAction_.c_str(), w.systemMenuVisible(),
                    list->isHidden(), list->isVisible(), w.isVisible(), w.locked_,
                    unsigned(w.view().rows.size()));
        require(w.view().kind == View::Popup && list->isVisible(),
                "editor commands use bottom Motorola contextual popup");
        w.back();
        require(!list->isVisible() && w.editor_->isVisible(), "back restores original editor");
        w.finishEdit(false);
        w.finishSettings(false);
        w.showSettings("media");
        w.chooseSetting("video_kbps");
        int chosen = w.view().selected;
        require(list->isVisible() && list->currentItem() == chosen,
                "choice list retains the configured value selection");
        w.lock();
        require(!list->isVisible(), "PIN covers system menu");
        w.unlock();
        require(list->isVisible() && list->currentItem() == chosen,
                "unlock restores system menu selection");
        w.info("menu notice");
        require(list->geometry().bottom() < w.height() - 79,
                "native list leaves notification banner visible");
        w.notice_ = QString::null;
        View large(View::Files, QString::fromLatin1("Files"));
        for (unsigned i = 0; i < 120; ++i)
            large.rows.push_back(Row(QString::number(i), "back"));
        w.push(large);
        for (int i = 0; i < 100; ++i)
            w.key(KEYCODE_DOWN);
        require(w.view().selected == 100 && list->count() <= 32 &&
                    list->item(list->currentItem())->getSubItemText(0, 0) == "100",
                "large file list keeps bounded native rows and correct selection");
        for (int i = 0; i < 80; ++i)
            w.key(KEYCODE_UP);
        require(w.view().selected == 20 &&
                    list->item(list->currentItem())->getSubItemText(0, 0) == "20",
                "reverse navigation crosses native pages correctly");
        w.finishSettings(false);
        w.home();
        w.showSettings("media");
        require(list->isVisible() && list->count() < 32, "settings replace a large file page");
        setting = static_cast<ZSettingItem *>(list->firstItem());
        require(setting->getSubItemText(0, 0) == uiText("Фото: размер") &&
                    setting->getSubItemText(0, 1) == uiText("как в профиле моста"),
                "native settings preserve colon-containing label separately from value");
        w.finishSettings(false);
        w.home();
        require(!list->isVisible(), "returning to contacts removes menu overlay");
        w.lastActivity_ = 0;
        w.lightOn_ = false;
        w.hide();
        w.resume();
        w.tick();
        require(w.isVisible() && w.lightOn_ && w.lastActivity_ != 0,
                "restoring the dimmed application wakes light and resets idle time");
        w.hide();
        static_cast<Application *>(qApp)->slotRaise();
        require(w.isVisible() && w.lightOn_,
                "native application activation restores its main window");
        w.pending_[777] = "video";
        Event media;
        media.requestId = 777;
        media.path = "/state/downloaded.3gp";
        media.filename = "downloaded.3gp";
        w.hide();
        w.showMedia(media);
        require(!w.isVisible() && !w.player_.active() && w.loadedMediaReady_ &&
                    w.savedMediaPurpose_ == "video",
                "background video completion stays ready without opening a player window");
        w.pending_.erase(777);
        w.loadedMediaReady_ = false;
        w.playPath_.clear();
        w.savedMediaPurpose_.clear();
        w.notice_ = QString::null;
        w.resume();
    }

  public:
    static void run(Window &w) {
        fprintf(stderr, "UI BEGIN\n");
        fflush(stderr);
        w.timer_.stop();
        checkForeground(w.platform_, w);
        checkVideoParent(w);
        std::string initialError;
        w.settings_.set("host", "127.0.0.1");
        w.settings_.set("uin", "123456");
        w.settings_.set("password", "dummy");
        w.settings_.set("psk", "test-code");
        w.settings_.setInt("auto_connect", 0);
        w.settings_.setInt("auto_reconnect", 0);
        w.settings_.setInt("encryption", 0);
        w.settings_.set("network", "system");
        menus(w);
        w.settings_.set("uin", "");
        w.mainMenu();
        w.activate(w.view().rows[0]);
        require(w.view().kind == View::SettingsPage && w.view().context == "account",
                "connect menu keeps missing account settings visible");
        w.finishSettings(false);
        w.settings_.set("uin", "123456");
        w.home();
        w.settings_.set("host", "");
        w.mainMenu();
        w.activate(w.view().rows[0]);
        require(w.connectionState_ == Event::Disconnected && w.view().kind == View::Text,
                "missing server stays in application with readable error");
        w.back();
        require(w.view().kind == View::SettingsPage && w.view().context == "network",
                "back from configuration error opens network settings");
        w.finishSettings(false);
        w.settings_.set("host", "127.0.0.1");
        w.home();
        scheduleNetworkWorker(0);
        w.connectClient();
        runNetworkWorker();
        w.eventsReady();
        require(w.connectionState_ == Event::Disconnected &&
                    w.view().context == "connection-error" &&
                    w.view().rows[0].text.find("refused") >= 0,
                "actual ARM network failure returns to UI without exiting");
        w.back();
        scheduleNetworkWorker(EAGAIN);
        w.connectClient();
        w.eventsReady();
        require(w.connectionState_ == Event::Disconnected && w.view().context == "connection-error",
                "worker creation failure remains readable");
        w.back();
        scheduleNetworkWorker(0);
        Event retry;
        retry.type = Event::State;
        retry.state = Event::Reconnecting;
        w.consume(retry);
        w.mainMenu();
        require(w.view().rows[0].action == "disconnect", "reconnecting menu offers cancellation");
        w.activate(w.view().rows[0]);
        require(w.connectionState_ == Event::Disconnected && w.manualDisconnect_ &&
                    w.view().context == "main-menu" && w.view().rows[0].action == "connect",
                "cancel reconnect keeps Java main menu with connect action");
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
        w.settings_.setInt("use_groups", 1);
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
        w.home();
        w.consume(roster);
        require(w.contact(a.uin) && w.contact(a.uin)->name == "Alice", "initial roster");
        require(w.collapsed_["Telegram"] && w.view().rows.size() == 1 &&
                    w.view().rows[0].action == "group-toggle:Telegram",
                "initial contact groups start collapsed");
        w.activate(w.view().rows[0]);
        require(!w.collapsed_["Telegram"] && w.view().rows.size() == 2,
                "collapsed group opens on selection");
        Event incremental;
        incremental.type = Event::Roster;
        ContactRecord b = a;
        b.uin = 1000002;
        b.name = "Bob";
        incremental.contacts.push_back(b);
        w.consume(incremental);
        require(w.contact(a.uin) && w.contact(b.uin), "incremental roster preserves existing");
        require(!w.collapsed_["Telegram"] && w.view().rows.size() == 3,
                "roster refresh preserves an opened group");
        Event online;
        online.type = Event::State;
        online.state = Event::Online;
        w.consume(online);
        require(w.collapsed_["Telegram"] && w.view().rows.size() == 1,
                "a new login folds contact groups again");
        w.connectionState_ = Event::Disconnected; // Fixture does not create a real session.
        require(w.statusIcons_.width() == 224 && w.statusIcons_.height() == 16 &&
                    statusIcon(0) == 7 && statusIcon(0xffffffffU) == 6 && statusIcon(0x100) == 3 &&
                    statusIcon(2) == 2 && statusIcon(4) == 4 && statusIcon(0x13) == 2 &&
                    statusIcon(0x05) == 4 && statusIcon(0x2001) == 12,
                "Java daisy atlas and raw OSCAR status priorities");
        require(w.status(0x13) == uiText("Не беспокоить") &&
                    w.status(0x05) == uiText("Недоступен") &&
                    w.status(0x200) == uiText("Сеть недоступна"),
                "status labels agree with Java daisy priority");
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
        require(w.messageIcons_.width() == 96 && w.messageIcons_.height() == 16 &&
                    w.view().rows[0].value == 1 && w.view().rows[0].text.find("[1]") >= 0,
                "silent delivery marks its collapsed parent group unread");
        checkUnreadPaint(w, 1);
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
        notificationPolicy(w, a.uin);
        w.activate(w.view().rows[0]);
        require(w.view().rows.size() == 3 && w.view().rows[1].uin == a.uin &&
                    w.view().rows[1].value == w.chats_[a.uin].unread,
                "expanded chat keeps unread count and envelope independently of status");
        checkUnreadPaint(w, 2);
        w.openChat(a.uin);
        require(w.chats_[a.uin].unread == 0 && w.view().kind == View::Chat,
                "opening chat clears unread");
        w.lock();
        w.incoming(message(a.uin, 301, true));
        require(w.chats_[a.uin].unread == 1, "message in covered chat stays unread behind PIN");
        w.unlock();
        require(w.chats_[a.uin].unread == 0, "unlocking visible chat clears its unread marker");
        w.hide();
        w.incoming(message(a.uin, 302, true));
        require(w.chats_[a.uin].unread == 1, "background chat keeps unread marker");
        w.resume();
        require(w.chats_[a.uin].unread == 0, "foreground chat clears the unread marker");
        w.chatMenu();
        w.incoming(message(a.uin, 303, true));
        require(w.chats_[a.uin].unread == 1, "chat menu retains the unread marker until dismissed");
        w.back();
        require(w.chats_[a.uin].unread == 0, "returning from a menu marks the visible chat read");
        w.key(KEYCODE_RSK);
        bool camera = false, attachments = false;
        for (size_t i = 0; i < w.view().rows.size(); ++i) {
            camera = camera || w.view().rows[i].action == "capture-photo";
            attachments = attachments || w.view().rows[i].action == "attachments";
        }
        require(w.view().kind == View::Popup && camera && !attachments && w.view().uin == a.uin &&
                    w.view().selected == int(w.view().rows.size()) - 1,
                "chat uses Java bottom popup with direct camera action for recipient");
        w.back();
        w.edit(QString::fromLatin1("Message"), "message", "Draft survives PIN", a.uin);
        require(w.editor_->text() == "Draft survives PIN", "native editor draft");
        QApplication::sendPostedEvents();
        fprintf(stderr, "INPUT layout: visible=%d editor=%d,%d %dx%d indicator=%d,%d %dx%d\n",
                w.inputIndicator_->isVisible(), w.editor_->x(), w.editor_->y(), w.editor_->width(),
                w.editor_->height(), w.inputIndicator_->x(), w.inputIndicator_->y(),
                w.inputIndicator_->width(), w.inputIndicator_->height());
        require(w.inputIndicator_->isVisible() &&
                    w.editor_->y() >= w.inputIndicator_->geometry().bottom(),
                "native input indicator has a separate visible row");
        checkInputIndicator(*w.inputIndicator_);
        checkPaint(w, "editor parent");
        w.lock();
        require(w.locked_ && !w.editor_->isVisible(), "PIN hides native editor");
        require(!w.inputIndicator_->isVisible(), "PIN hides input status");
        checkPaint(w, "PIN");
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
        require(!w.inputIndicator_->isVisible(), "closing editor hides input status");
        require(w.storage_->loadDraft(a.uin) == "Draft survives PIN", "cancel preserves draft");
        w.showSettings("account");
        w.chooseSetting("password");
        require(w.editSecret_ && w.editor_->echoMode() == ZMultiLineEdit::Password &&
                    w.editor_->getInputField()->getType() == ZKbInputField::FIELD_TYPE_PASSWORD,
                "password uses native secret field semantics, not only masking");
        const QString dummyPassword = QString::fromUtf8(" Abc9é ");
        w.editor_->setText(dummyPassword);
        w.editor_->setCursorPosition(0, 3);
        w.editorMenu();
        bool exposesPassword = false;
        for (size_t i = 0; i < w.view().rows.size(); ++i)
            exposesPassword = exposesPassword || w.view().rows[i].action == "editor-copy" ||
                              w.view().rows[i].action == "editor-copy-all" ||
                              w.view().rows[i].action == "editor-cut";
        require(w.view().kind == View::Popup && !exposesPassword,
                "secret editor popup does not copy or cut password text");
        w.back();
        int line = -1, column = -1;
        w.editor_->getCursorPosition(&line, &column);
        require(w.editor_->isVisible() && w.editor_->echoMode() == ZMultiLineEdit::Password &&
                    w.editor_->text() == dummyPassword && line == 0 && column == 3 &&
                    w.editor_->getInputField()->getType() == ZKbInputField::FIELD_TYPE_PASSWORD,
                "password popup round trip preserves text, cursor and native input rules");
        w.suspend();
        w.resume();
        require(w.editor_->echoMode() == ZMultiLineEdit::Password,
                "background keeps password masked");
        w.flipChanged(true);
        w.flipChanged(false);
        require(w.editor_->echoMode() == ZMultiLineEdit::Password,
                "closing the flip keeps password masked");
        w.lock();
        w.unlock();
        require(w.editor_->echoMode() == ZMultiLineEdit::Password &&
                    w.editor_->text() == dummyPassword,
                "PIN preserves masked password and its text");
        w.finishEdit(true);
        require(w.settingsDraft_.get("password") == std::string(dummyPassword.utf8()) &&
                    w.settings_.get("password") != std::string(dummyPassword.utf8()),
                "account password edits stay in the settings draft until Save");
        w.finishSettings(true);
        Settings reloaded;
        require(reloaded.load(w.settings_.path(), initialError) &&
                    reloaded.get("password") == std::string(dummyPassword.utf8()),
                "saved account password preserves case, spaces and UTF-8 after reload");
        w.showSettings("account");
        w.chooseSetting("password");
        require(w.editor_->text() == dummyPassword &&
                    w.editor_->echoMode() == ZMultiLineEdit::Password,
                "reopening password starts masked with the exact saved value");
        w.finishEdit(false);
        w.finishSettings(false);
        w.openChat(a.uin);
        w.edit(QString::fromLatin1("Message"), "message", "Before ", a.uin);
        require(!w.editSecret_ &&
                    w.editor_->getInputField()->getType() == ZKbInputField::FIELD_TYPE_REGULAR &&
                    w.editor_->getInputField()->getOptions() == 0,
                "ordinary editor restores regular input rules after a password");
        w.editorMenu();
        require(w.view().rows[0].action != "editor-secret",
                "ordinary editor has no password visibility command");
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
        w.finishSettings(false);
        w.home();
        w.activate(Row(QString::null, "settings"));
        w.activate(Row(QString::null, "settings:network"));
        w.chooseSetting("encryption");
        require(w.settingsDraft_.getBool("encryption") && !w.settings_.getBool("encryption"),
                "network toggle remains staged until Save");
        w.finishSettings(true);
        require(w.settings_.getBool("encryption"), "saved network setting persists");
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
        checkPaint(w, "chat");
        const unsigned char *buffer = w.frame_.scanLine(0);
        for (unsigned i = 0; i < 12; ++i) {
            w.key(i % 2 ? KEYCODE_UP : KEYCODE_DOWN);
            checkPaint(w, "navigation");
            require(w.frame_.scanLine(0) == buffer, "frame buffer reused");
        }
        w.mainMenu();
        checkPaint(w, "menu");
        w.showSettings("media");
        w.chooseSetting("video_kbps");
        checkPaint(w, "choice");
        w.resize(240, 280);
        checkPaint(w, "resized");
        require(w.frame_.size() == w.size(), "buffer follows window resize");
        w.resize(240, 320);
        w.home();
        w.openChat(a.uin);
        if (selectedScene == "menu")
            w.mainMenu();
        else if (selectedScene == "statuses") {
            w.collapsed_["Telegram"] = w.collapsed_["Telegram/Каналы"] = w.collapsed_["MAX"] =
                false;
            w.home();
        } else if (selectedScene == "settings") {
            w.settings_.set("photo_size", "176x220");
            w.settings_.set("photo_kb", "20");
            w.showSettings("media");
        } else if (selectedScene == "choice") {
            w.showSettings("media");
            w.chooseSetting("video_kbps");
        } else if (selectedScene == "editor") {
            w.edit(QString::fromUtf8("Сообщение"), "message", "Привет! Проверка языка ввода.",
                   a.uin);
            checkInputIndicator(*w.inputIndicator_);
        }
        fprintf(stderr, "PAINT buffer=%d bytes\n", w.frame_.bytesPerLine() * w.frame_.height());
        fprintf(stderr, "UI PASS %u checks\n", checks);
    }
};
unsigned UiProbe::checks = 0;
} // namespace tmm
int main(int argc, char **argv) {
    tmm::Application app(argc, argv, QApplication::GuiServer);
    chdir("/work"); // Packaged assets copied to the runner's read-only build mount.
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
