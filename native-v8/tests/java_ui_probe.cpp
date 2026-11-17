// Java V8 menu contracts (not a mock Window). Sources: MainMenu, JimmUI,
// ContactList, ChatHistory, HistoryViewer and Options from telemotomax/src.
// The V8 build enables CAMERA/AVATARS/MOTOMAGX, not HISTORY/PIM/TRAFFIC.
// Only bridge command submission and the arguments to real skin drawing are
// observed. No successful network, camera, microphone or audio is simulated.
#define FEAT_KEYPAD_SUPPORT
#include "application.h"
#include "window.h"
#include "storage.h"
#include "ui_settings.h"
#include "ui_language.h"
#include "system_chrome.h"
#include "system_menu.h"
#include <ZListBox.h>
#include <ZKeyDef.h>
#include <ZMultiLineEdit.h>
#include <qapplication.h>
#include <qpainter.h>
#include <qpixmap.h>
#include <qtimer.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <vector>
extern "C" void UTIL_SetPowerOnHandleStatus(int);
extern "C" void UTIL_SetFlipStatus(int);
extern "C" void UTIL_SetKeypadLockStatus(bool);
static std::vector<tmm::Command> submitted;
static QString drawnLeft, drawnRight;
static unsigned systemIconMode;
static uint32_t systemIconStatus;
extern "C" void __wrap__ZN3tmm12StatusIconV820configureApplicationEjj(unsigned mode,
                                                                      uint32_t status) {
    systemIconMode = mode;
    systemIconStatus = status;
}
extern "C" bool __wrap__ZN3tmm6Client6submitERKNS_7CommandE(tmm::Client *, const tmm::Command &c) {
    submitted.push_back(c);
    return true;
}
extern "C" void __real__ZN3tmm12SystemChrome10drawFooterER8QPainterRK5QRectRK7QStringS8_(
    tmm::SystemChrome *, QPainter &, const QRect &, const QString &, const QString &);
extern "C" void __wrap__ZN3tmm12SystemChrome10drawFooterER8QPainterRK5QRectRK7QStringS8_(
    tmm::SystemChrome *skin, QPainter &p, const QRect &r, const QString &left,
    const QString &right) {
    drawnLeft = left;
    drawnRight = right;
    __real__ZN3tmm12SystemChrome10drawFooterER8QPainterRK5QRectRK7QStringS8_(skin, p, r, left,
                                                                             right);
}
namespace tmm {
namespace {
struct Expected {
    const char *label, *action;
};
#define COUNT(a) (sizeof(a) / sizeof(a[0]))
const Expected offlineMain[] = {{"Подключиться", "connect"},
                                {"Статус", "status"},
                                {"Контакты", "contact-list"},
                                {"Чаты", "home"},
                                {"Настройки", "settings"},
                                {"Откл. звук", "silent"},
                                {"О программе", "about"},
                                {"Свернуть", "minimize"},
                                {"Выход", "exit"}};
const Expected onlineMain[] = {{"Блокировка клавиатуры", "lock"},
                               {"Отключиться", "disconnect"},
                               {"Статус", "status"},
                               {"Контакты", "contact-list"},
                               {"Чаты", "home"},
                               {"Настройки", "settings"},
                               {"Откл. звук", "silent"},
                               {"О программе", "about"},
                               {"Свернуть", "minimize"},
                               {"Выход", "exit"}};
const Expected contactList[] = {{"Все чаты", "all-chats"},
                                {"Добавить контакт", "add-contact"},
                                {"Добавить группу", "add-group"},
                                {"Найти контакт", "search"},
                                {"Удалить группу", "group-delete-list"},
                                {"Переим. группу", "group-rename-list"},
                                {"Прив. списки", "privacy-lists"}};
const Expected contactOnline[] = {{"Сообщения", ""},
                                  {"Сообщение", "compose"},
                                  {"Запрос авторизации", "auth-request"},
                                  {"Информация", ""},
                                  {"Информация", "info"},
                                  {"Инфо о клиенте", "local-info"},
                                  {"Списки", ""},
                                  {"Удалить", "delete-confirm"},
                                  {"Удалиться из его КЛ", "remove-confirm"},
                                  {"Переименовать", "rename-contact"},
                                  {"Перен. в группу", "move-contact"},
                                  {"В игнор. список", "privacy-on"},
                                  {"В невид. список", "privacy-on"},
                                  {"В видим. список", "privacy-on"}};
const Expected contactOffline[] = {{"Сообщения", ""}, {"Информация", ""}, {"Информация", "info"}};
// VirtualList.sortMenu: descending priority, stable ties; bottom command selected.
const Expected plainChat[] = {{"Удалить чат...", "chat-delete"},
                              {"Меню контакта", "contact-menu"},
                              {"История с сервера", "history"},
                              {"Получать без оповещений", "quiet"},
                              {"Копировать", "copy-message"},
                              {"Снять фото", "capture-photo"},
                              {"Записать голосовое", "capture-voice"},
                              {"Записать кружок", "capture-video"},
                              {"Отправить файл", "upload-file"},
                              {"Отправить фото/видео", "upload-media"},
                              {"Ответ...", "compose"}};
const Expected fullChat[] = {{"Открыть ссылку", "urls"},
                             {"Удалить чат...", "chat-delete"},
                             {"Меню контакта", "contact-menu"},
                             {"Добавить контакт...", "add-existing"},
                             {"История с сервера", "history"},
                             {"Получать без оповещений", "quiet"},
                             {"Копировать", "copy-message"},
                             {"Снять фото", "capture-photo"},
                             {"Записать голосовое", "capture-voice"},
                             {"Записать кружок", "capture-video"},
                             {"Отправить файл", "upload-file"},
                             {"Отправить фото/видео", "upload-media"},
                             {"Обсуждение", "discussion"},
                             {"Цитировать", "quote-select"},
                             {"Цитировать сюда", "quote-here"},
                             {"Показать фото", "photo"},
                             {"Смотреть видео", "video-menu"},
                             {"Ответ...", "compose"},
                             {"Запрос авторизации", "auth-request"}};
const Expected fullHistory[] = {{"Обсуждение", "discussion"},     {"Ещё", "history-more"},
                                {"Цитировать", "quote-select"},   {"Цитировать сюда", "quote-here"},
                                {"Смотреть видео", "video-menu"}, {"Показать фото", "photo"}};
const Expected settings[] = {{"Учетная запись", "settings:account"},
                             {"Сеть", "settings:network"},
                             {"Интерфейс", "settings:interface"},
                             {"Камера", "settings:camera"},
                             {"Медиа", "settings:media"},
                             {"Сеть Telegram", "settings:telegram"},
                             {"Сеть MAX", "settings:max"},
                             {"Сеть eXpress", "settings:express"},
                             {"Горячие клавиши", "hotkeys"},
                             {"Оповещения", "settings:notifications"},
                             {"Часовой пояс", "settings:timezone"},
                             {"Шаблоны", "templates"},
                             {"Сброс настроек", "reset-confirm"}};
const Expected statuses[] = {{"Онлайн", "status-set"},     {"Свободен для беседы", "status-set"},
                             {"Отсутствую", "status-set"}, {"Недоступен", "status-set"},
                             {"Занят", "status-set"},      {"Не беспокоить", "status-set"},
                             {"Невидимый", "status-set"},  {"Невидим для всех", "status-set"},
                             {"Злой", "status-set"},       {"Депрессия", "status-set"},
                             {"Дома", "status-set"},       {"На работе", "status-set"},
                             {"Обедаю", "status-set"}};
const unsigned statusValues[] = {0,   32,     1,      4,      16,     2,     256,
                                 512, 0x3000, 0x4000, 0x5000, 0x6000, 0x2001};
const Expected deleteChoices[] = {{"Этого контакта", "chat-delete-selection"},
                                  {"Всех кроме этого", "chat-delete-selection"},
                                  {"Всех контактов", "chat-delete-selection"}};
} // namespace
class UiProbe {
    static unsigned checks_;
    static void require(bool value, const char *reason) {
        if (!value) {
            fprintf(stderr, "JAVA UI FAIL: %s\n", reason);
            exit(2);
        }
        ++checks_;
        fprintf(stderr, "JAVA UI PASS: %s\n", reason);
        fflush(stderr);
    }
    static void menu(Window &w, const Expected *items, size_t count, const char *reason) {
        bool equal = w.view().rows.size() == count;
        for (size_t i = 0; i < count && i < w.view().rows.size(); ++i)
            if (w.view().rows[i].text != uiText(items[i].label) ||
                w.view().rows[i].action != items[i].action) {
                fprintf(stderr, "JAVA UI row %u: got '%s' [%s], expected '%s' [%s]\n", unsigned(i),
                        w.view().rows[i].text.utf8().data(), w.view().rows[i].action.c_str(),
                        items[i].label, items[i].action);
                equal = false;
            }
        if (!equal)
            fprintf(stderr, "JAVA UI rows: got %u expected %u (%s)\n",
                    unsigned(w.view().rows.size()), unsigned(count), w.view().context.c_str());
        require(equal, reason);
    }
    static int index(Window &w, const std::string &action) {
        for (size_t i = 0; i < w.view().rows.size(); ++i)
            if (w.view().rows[i].action == action)
                return i;
        return -1;
    }
    static ZSettingItem *nativeSetting(Window &w, int at) {
        // SDK item(index) is wrongly narrowed to ZListBoxItem; setting rows
        // are sibling ZSettingItems. Walk the correctly typed common base.
        ZListItem *item = w.systemMenu_->list()->firstItem();
        for (int i = 0; item && i < at; ++i)
            item = item->next();
        return static_cast<ZSettingItem *>(item);
    }
    static void choose(Window &w, const std::string &action) {
        int at = index(w, action);
        require(at >= 0, ("action present: " + action).c_str());
        Row r = w.view().rows[at];
        w.activate(r);
    }
    static void footer(Window &w, const char *left, const char *right, const char *reason) {
        QPixmap picture(w.size());
        QPainter painter(&picture);
        drawnLeft = drawnRight = "unobserved";
        w.drawFooter(painter);
        painter.end();
        require(drawnLeft == uiText(left) && drawnRight == uiText(right), reason);
    }
    static MessageRecord message(uint32_t id, unsigned kind = 0) {
        MessageRecord m;
        m.uin = id;
        m.text = "Привет, V8";
        m.time = 1700000000;
        m.kind = kind;
        m.silent = true;
        return m;
    }
    static void reset(Window &w) {
        if (!w.editAction_.empty())
            w.finishEdit(false);
        if (w.settingsEditing_)
            w.finishSettings(false);
        w.home();
        w.notice_ = QString::null;
        w.noticeUntil_ = 0;
        w.pending_.clear();
        w.pendingUin_.clear();
    }
    static void chat(Window &w, const MessageRecord &m) {
        reset(w);
        ChatState &c = w.chats_[m.uin];
        c.messages.clear();
        c.messages.push_back(m);
        c.loaded = true;
        w.openChat(m.uin);
        w.view().selected = 0;
    }
    static void history(Window &w, const MessageRecord &m, bool more) {
        reset(w);
        View v(View::History, w.name(m.uin));
        v.uin = m.uin;
        v.messages.push_back(m);
        v.more = more;
        w.showHistory(v);
        w.push(v);
    }
    static void mainAndRoster(Window &w, uint32_t id) {
        w.connectionState_ = Event::Disconnected;
        w.silent_ = false;
        const std::vector<ContactRecord> savedContacts = w.contacts_;
        w.contacts_.clear();
        w.mainMenu();
        require(w.view().rows.size() == COUNT(offlineMain) - 1 && index(w, "home") < 0,
                "empty roster main menu omits Chats");
        footer(w, "", "Выбрать", "empty roster main menu has no Chats softkey");
        w.contacts_ = savedContacts;
        w.mainMenu();
        menu(w, offlineMain, COUNT(offlineMain), "offline main menu exactly matches Java");
        footer(w, "Чаты", "Выбрать", "main softkeys are Chats / Select");
        w.key(KEYCODE_LSK);
        require(w.view().kind == View::Roster, "main Chats softkey returns to roster");
        footer(w, "Меню", "Выбрать", "roster softkeys are Menu / Select");
        w.key(KEYCODE_LSK);
        require(w.view().context == "main-menu", "roster Menu opens main menu");
        choose(w, "contact-list");
        menu(w, contactList, COUNT(contactList),
             "contact management items/order exactly match Java");
        w.back();
        choose(w, "silent");
        require(w.silent_ && w.view().context == "main-menu" &&
                    w.view().rows[index(w, "silent")].text == uiText("Вкл. звук"),
                "sound toggle updates Java main menu in place");
        choose(w, "silent");
        w.connectionState_ = Event::Online;
        w.mainMenu();
        menu(w, onlineMain, COUNT(onlineMain), "connected main menu exactly matches Java");
        choose(w, "disconnect");
        menu(w, offlineMain, COUNT(offlineMain),
             "disconnect retains main menu and updates actions");
        w.connectionState_ = Event::Reconnecting;
        w.mainMenu();
        require(w.view().rows[0].action == "disconnect" &&
                    w.view().rows[0].text == uiText("Отменить подключение"),
                "reconnect cancellation remains available");
        w.connectionState_ = Event::Disconnected;
        reset(w);
        w.settings_.setInt("use_groups", 1);
        w.rebuildRoster();
        int group = index(w, "group-toggle:Telegram");
        require(group >= 0, "roster has Telegram group");
        w.view().selected = group;
        w.key(KEYCODE_RSK);
        require(!w.collapsed_["Telegram"], "roster Select expands a group");
        int contact = -1;
        for (size_t i = 0; i < w.view().rows.size(); ++i)
            if (w.view().rows[i].uin == id && w.view().rows[i].action == "open")
                contact = i;
        require(contact >= 0, "expanded roster contains target contact");
        w.view().selected = contact;
        w.key(KEYCODE_RSK);
        require(w.view().kind == View::Chat && w.view().uin == id,
                "roster Select opens selected contact without an invented contact popup");
        footer(w, "Закрыть", "Меню", "chat softkeys are Close / Menu");
        size_t depth = w.stack_.size();
        w.key(KEYCODE_CENTER_SELECT);
        require(w.view().kind == View::Chat && w.stack_.size() == depth,
                "Fire on plain chat text has no generic Message window");
        w.key(KEYCODE_RSK);
        menu(w, plainChat, COUNT(plainChat),
             "plain chat command labels and priority order match Java");
        require(w.view().kind == View::Popup && w.view().context == "chat-menu" &&
                    w.view().selected == int(w.view().rows.size()) - 1 &&
                    index(w, "attachments") < 0 && index(w, "message-text") < 0,
                "chat commands open a bottom popup selected at last command without extra menus");
        w.key(KEYCODE_LSK);
        require(w.view().kind == View::Chat, "popup Cancel restores chat");
        w.key(KEYCODE_LSK);
        require(w.view().kind == View::Roster, "chat Close returns to roster");
    }
    static void contactMenus(Window &w, uint32_t id) {
        reset(w);
        ContactRecord *c = w.contact(id);
        c->status = 0;
        c->noAuth = true;
        c->privacy = 0;
        w.connectionState_ = Event::Online;
        w.contactMenu(id);
        menu(w, contactOnline, COUNT(contactOnline), "contact sections/actions match Java online");
        require(w.view().selected == 1 && w.view().rows[1].uin == id,
                "contact menu starts at first selectable action");
        choose(w, "info");
        require(w.view().context == "contact-info" && w.view().request &&
                    submitted.back().type == Command::ContactInfo && submitted.back().uin == id,
                "online Information requests selected contact on a waiting screen");
        const size_t informationDepth = w.stack_.size();
        Event information(Event::ContactInfo);
        information.uin = id;
        information.requestId = w.view().request;
        information.fields["Описание"] = "Fixture description";
        w.consume(information);
        require(
            w.view().context == "contact-info" && !w.view().request &&
                w.stack_.size() == informationDepth && w.view().rows.size() >= 4,
            "contact information replaces waiting view without stale requests or duplicate Back");
        footer(w, "Назад", "Меню", "loaded contact information exposes its Menu softkey");
        w.back();
        w.key(KEYCODE_UP);
        require(w.view().selected == int(w.view().rows.size()) - 1,
                "contact menu wraps and skips section headers");
        w.back();
        c->privacy = 7;
        w.contactMenu(id);
        require(w.view().rows[w.view().rows.size() - 3].text == uiText("Отменить игнор. список") &&
                    w.view().rows[w.view().rows.size() - 2].text ==
                        uiText("Отменить невид. список") &&
                    w.view().rows.back().text == uiText("Отменить видим. список"),
                "contact privacy entries reflect each existing membership");
        w.back();
        c->noAuth = false;
        c->privacy = 0;
        c->status = 0xffffffffU;
        w.connectionState_ = Event::Disconnected;
        w.contactMenu(id);
        menu(w, contactOffline, COUNT(contactOffline),
             "offline contact menu omits unavailable actions");
        require(w.view().selected == 2, "offline contact menu skips both information headers");
        choose(w, "info");
        require(w.view().context == "contact-info" && !w.view().request &&
                    w.view().rows[0].text.find("1000001") >= 0,
                "offline Information displays cached contact UIN");
        reset(w);
    }
    static void messageMenus(Window &w, uint32_t id) {
        ContactRecord *c = w.contact(id);
        c->noAuth = true;
        c->inRoster = false;
        MessageRecord m = message(id, 2);
        m.url = "http://example.test/video";
        m.text = "Привет, V8 http://example.test/link";
        m.token = "video-token";
        m.nativeId = std::string(8, 'n');
        m.discussionUin = 1000002;
        w.quoteId_ = std::string(8, 'q');
        chat(w, m);
        w.chatMenu();
        menu(w, fullChat, COUNT(fullChat), "all conditional chat actions retain Java label/order");
        require(w.view().rows[index(w, "discussion")].uin == m.discussionUin &&
                    w.view().rows[index(w, "compose")].uin == id,
                "discussion target differs from compose recipient");
        w.back();
        w.pending_[700] = "quote";
        w.chatMenu();
        require(index(w, "quote-here") < 0, "quote paste hidden while bridge quote is pending");
        w.back();
        w.pending_.clear();
        w.key(KEYCODE_CENTER_SELECT);
        require(w.view().context == "video-choice",
                "Fire on chat video opens the two-action video menu");
        const Expected videoChoices[] = {{"Смотреть", "video"},
                                         {"Смотреть в браузере", "video-browser"}};
        menu(w, videoChoices, COUNT(videoChoices),
             "video choices match Java viewer and browser actions");
        reset(w);
        history(w, m, true);
        footer(w, "Назад", "Меню", "server history softkeys are Back / Menu");
        w.key(KEYCODE_RSK);
        menu(w, fullHistory, COUNT(fullHistory),
             "server history context popup matches Java actions only");
        require(w.view().selected == int(w.view().rows.size()) - 1,
                "server history popup selects last command");
        for (unsigned kind = 1; kind <= 4; ++kind) {
            m = message(id, kind);
            m.token = "token";
            history(w, m, false);
            w.messageMenu();
            require(w.view().kind == View::Popup && w.view().rows.size() == (kind == 2 ? 3U : 2U) &&
                        index(w, kind == 1   ? "photo"
                                 : kind == 2 ? "video-menu"
                                 : kind == 3 ? "voice"
                                             : "file") >= 0,
                    "history token exposes just quote-paste and matching media actions");
        }
        w.quoteId_.clear();
        chat(w, message(id));
        w.chatMenu();
        choose(w, "quiet");
        footer(w, "Сохр.", "Назад", "quiet form has Java Save / Back softkeys");
        choose(w, "quiet-choice");
        const Expected quietChoices[] = {{"Обычная доставка", "quiet-draft"},
                                         {"Без оповещений", "quiet-draft"}};
        menu(w, quietChoices, COUNT(quietChoices), "quiet delivery choices match Java");
        w.activate(w.view().rows[1]);
        require(w.view().context == "quiet-settings" && w.view().offset == 1 && w.quiet_.empty(),
                "quiet delivery choice remains staged");
        w.key(KEYCODE_RSK);
        require(w.view().kind == View::Chat && w.quiet_.empty(),
                "quiet Back cancels staged choice");
        w.chatMenu();
        choose(w, "quiet");
        choose(w, "quiet-choice");
        w.activate(w.view().rows[1]);
        w.key(KEYCODE_LSK);
        require(w.view().context == "quiet-settings" && w.quiet_.size() == 1 && w.quiet_[0] == id,
                "quiet Save applies whitelist and stays in form as Java does");
        reset(w);
        w.quiet_.clear();
        m = message(id);
        history(w, m, false);
        size_t depth = w.stack_.size();
        w.key(KEYCODE_RSK);
        require(w.view().kind == View::History && w.stack_.size() == depth,
                "plain history with no actions has no invented popup");
        c = w.contact(id);
        c->noAuth = false;
        c->inRoster = true;
        reset(w);
    }
    static void statusAndDelete(Window &w, uint32_t id) {
        w.connectionState_ = Event::Disconnected;
        w.mainMenu();
        choose(w, "status");
        menu(w, statuses, COUNT(statuses), "all thirteen Java statuses have exact labels/order");
        bool values = true;
        for (size_t i = 0; i < COUNT(statusValues); ++i)
            values = values && w.view().rows[i].value == statusValues[i];
        require(values, "status values preserve NA=4 and DND=2");
        submitted.clear();
        w.activate(w.view().rows[5]);
        require(w.settings_.getInt("status") == 2 && submitted.empty(),
                "offline DND saves locally without sending status");
        Settings reloaded;
        std::string error;
        require(reloaded.load(w.settings_.path(), error) && reloaded.getInt("status") == 2,
                "offline status survives a real settings file reload");
        w.connectionState_ = Event::Online;
        choose(w, "status");
        w.activate(w.view().rows[3]);
        require(w.settings_.getInt("status") == 4 && !submitted.empty() &&
                    submitted.back().type == Command::Status && submitted.back().status == 4,
                "online NA sends the correct OSCAR status");
        chat(w, message(id));
        w.chatMenu();
        choose(w, "chat-delete");
        menu(w, deleteChoices, COUNT(deleteChoices), "delete chat has Java's three scopes");
        footer(w, "Отмена", "ОК", "delete selector softkeys match Java");
        w.chats_[1000002].loaded = true;
        w.chats_[1000003].loaded = true;
        w.activate(w.view().rows[1]);
        require(w.view().kind == View::Roster && w.chats_.size() == 1 &&
                    w.chats_.find(id) != w.chats_.end(),
                "Delete all except this preserves selected chat and returns roster");
    }
    static void settingsDrafts(Window &w) {
        reset(w);
        w.settingsMenu();
        menu(w, settings, COUNT(settings), "settings top-level labels/order match Java V8");
        w.showSettings("interface");
        // Options.java: one form, four separator groups, no detached Chat/Light page.
        const char *interfaceActions[] = {"field:lock_pin",       "field:flip_lock_minutes",
                                          "settings-heading",     "field:display_date",
                                          "field:fullscreen",     "field:running_icon",
                                          "field:mirror_menu",    "field:font_size",
                                          "settings-heading",     "field:use_groups",
                                          "field:hide_empty",     "field:hide_offline",
                                          "field:show_deleted",   "field:sort_by",
                                          "settings-heading",     "field:cp1251",
                                          "field:initial_caps",   "field:show_receipts",
                                          "field:save_history",   "field:server_history_count",
                                          "field:chat_messages",  "settings-heading",
                                          "field:chat_font_size", "field:show_icons",
                                          "field:show_sender",    "field:show_time",
                                          "field:show_newlines",  "field:show_smileys",
                                          "field:full_editor",    "field:light_seconds",
                                          "field:manual_light",   "field:caption_offset"};
        bool interfaceOrder = w.view().rows.size() == COUNT(interfaceActions);
        for (size_t i = 0; i < COUNT(interfaceActions) && i < w.view().rows.size(); ++i)
            interfaceOrder = interfaceOrder && w.view().rows[i].action == interfaceActions[i];
        require(interfaceOrder, "interface form retains all Java field groups and order");
        footer(w, "Назад", "Сохр.", "interface has Back / Save softkeys");
        w.chooseSetting("running_icon");
        require(w.view().kind == View::Choice && w.view().rows.size() == 3 &&
                    index(w, "set:running_icon:1") >= 0 && index(w, "set:running_icon:2") >= 0 &&
                    index(w, "set:running_icon:0") >= 0,
                "running icon has explicit header, idle-screen and off choices");
        w.activate(w.view().rows[index(w, "set:running_icon:2")]);
        require(w.view().context == "interface" &&
                    settingNumber(w.settingsDraft_, "running_icon") == 2 &&
                    settingNumber(w.settings_, "running_icon") == 1,
                "icon placement is staged with the other interface settings");
        bool previous = settingFlag(w.settings_, "display_date");
        size_t depth = w.stack_.size();
        w.chooseSetting("display_date");
        require(w.view().context == "interface" && w.stack_.size() == depth &&
                    settingFlag(w.settingsDraft_, "display_date") != previous &&
                    settingFlag(w.settings_, "display_date") == previous,
                "boolean toggles in the form without opening a choice or committing");
        w.key(KEYCODE_LSK);
        require(!w.settingsEditing_ && w.view().context == "settings-menu" &&
                    settingFlag(w.settings_, "display_date") == previous,
                "interface Back discards all draft changes");
        require(settingNumber(w.settings_, "running_icon") == 1,
                "Back discards staged icon placement");
        w.showSettings("interface");
        w.commitSetting("running_icon", "2");
        w.chooseSetting("display_date");
        w.key(KEYCODE_RSK);
        require(!w.settingsEditing_ && settingFlag(w.settings_, "display_date") != previous,
                "interface Save commits staged changes and closes the form");
        Settings iconReload;
        std::string iconError;
        require(iconReload.load(w.settings_.path(), iconError) &&
                    iconReload.get("running_icon") == "2",
                "Save persists icon placement across restart");
        const std::string savedUin = settingValue(w.settings_, "uin");
        const std::string savedPassword = settingValue(w.settings_, "password");
        w.showSettings("account");
        footer(w, "Назад", "Сохр.", "single account uses Back / Save softkeys");
        require(w.view().rows.size() == 2 && index(w, "field:uin") == 0 &&
                    index(w, "field:password") == 1 && index(w, "account-add") < 0 &&
                    index(w, "account-choose") < 0,
                "only UIN and password remain in the account form");
        ZSettingItem *accountUin = nativeSetting(w, index(w, "field:uin"));
        ZSettingItem *accountPassword = nativeSetting(w, index(w, "field:password"));
        require(accountUin->getSubItemText(0, 0) == uiText("UIN") &&
                    accountUin->getSubItemText(0, 1) == QString::fromUtf8(savedUin.c_str()) &&
                    accountPassword->getSubItemText(0, 0) == uiText("Пароль") &&
                    accountPassword->getSubItemText(0, 1) ==
                        QString::fromLatin1(std::string(savedPassword.size(), '*').c_str()),
                "single credentials keep native label and secret regions");
        w.commitSetting("password", "cancelled-password");
        w.key(KEYCODE_LSK);
        require(!w.settingsEditing_ && settingValue(w.settings_, "password") == savedPassword,
                "account Back discards staged password");
        w.showSettings("account");
        w.commitSetting("password", "new-password");
        w.key(KEYCODE_RSK);
        Settings reloaded;
        std::string accountError;
        require(!w.settingsEditing_ && reloaded.load(w.settings_.path(), accountError) &&
                    reloaded.get("uin") == savedUin && reloaded.get("password") == "new-password",
                "account Save persists exactly the single credentials");
        const int oldFont = settingNumber(w.settings_, "font_size");
        const int oldChatFont = settingNumber(w.settings_, "chat_font_size");
        w.showSettings("interface");
        w.chooseSetting("font_size");
        require(w.view().kind == View::Choice && w.view().rows.size() == 7 &&
                    index(w, "set:font_size:12") >= 0 && index(w, "set:font_size:24") >= 0,
                "interface font is a size dropdown rather than a small-font toggle");
        w.activate(w.view().rows[index(w, "set:font_size:20")]);
        w.chooseSetting("chat_font_size");
        w.activate(w.view().rows[index(w, "set:chat_font_size:18")]);
        require(settingNumber(w.settingsDraft_, "font_size") == 20 &&
                    settingNumber(w.settingsDraft_, "chat_font_size") == 18 &&
                    w.font().pointSize() == oldFont && w.chatFont().pointSize() == oldChatFont,
                "font choices are staged until Save");
        w.key(KEYCODE_LSK);
        require(w.font().pointSize() == oldFont && w.chatFont().pointSize() == oldChatFont,
                "Back preserves both current font sizes");
        w.showSettings("interface");
        w.commitSetting("font_size", "20");
        w.commitSetting("chat_font_size", "18");
        w.key(KEYCODE_RSK);
        Settings fontReload;
        require(fontReload.load(w.settings_.path(), accountError) &&
                    fontReload.getInt("font_size") == 20 &&
                    fontReload.getInt("chat_font_size") == 18 && w.font().pointSize() == 20 &&
                    w.chatFont().pointSize() == 18 && w.editor_->font().pointSize() == 20,
                "Save applies and persists separate interface/chat/editor font sizes");
        QPixmap fontFrame(w.size());
        QPainter fontPainter(&fontFrame);
        w.drawFrame(fontPainter);
        fontPainter.end();
        const ZListBox::ListItemRegion firstRegion = static_cast<ZListBox::ListItemRegion>(0);
        require(w.systemMenu_->list()->getItemFont(firstRegion, false).pointSize() == 20 &&
                    w.systemMenu_->list()->getItemFont(firstRegion, true).pointSize() == 20,
                "native menu region fonts follow the saved interface size");
        require(w.bodyColor(1) == w.palette().active().base() &&
                    w.bodyColor(2) == w.palette().active().text() &&
                    w.bodyColor(3) == w.palette().active().highlight(),
                "chat colors come from the native system palette");
        w.settings_.setInt("font_size", oldFont);
        w.settings_.setInt("chat_font_size", oldChatFont);
        w.applySettings();
        w.showSettings("network");
        w.chooseSetting("host");
        w.editor_->setText("bridge.copy.test");
        w.editorMenu();
        choose(w, "editor-copy-all");
        require(w.editor_->isVisible() && w.editAction_ == "setting" && w.editKey_ == "host" &&
                    w.settingsEditing_ && w.view().context == "network" &&
                    w.copied() == "bridge.copy.test",
                "editor Copy closes only popup and preserves active network draft/form");
        w.editor_->setCursorPosition(0, w.editor_->text().length());
        w.copy(".extra");
        w.editorMenu();
        choose(w, "editor-paste");
        require(w.editor_->isVisible() && w.editor_->text() == "bridge.copy.test.extra" &&
                    w.editAction_ == "setting" && w.editKey_ == "host" && w.settingsEditing_ &&
                    w.view().context == "network",
                "editor Paste closes only popup and preserves active field and draft");
        reset(w);
    }
    static void templates(Window &w, uint32_t id) {
        std::vector<std::string> templates;
        templates.push_back("One");
        std::string error;
        require(w.storage_->saveTemplates(templates, error), "real template storage fixture");
        chat(w, message(id));
        w.edit(uiText("Сообщение"), "message", "draft", id);
        w.editor_->setCursorPosition(0, 2);
        w.editorMenu();
        choose(w, "template-insert-list");
        require(w.view().kind == View::Templates && w.view().context == "insert" &&
                    !w.editor_->isVisible(),
                "compose Templates suspends original native editor");
        footer(w, "Выбрать", "Меню", "insert template list softkeys are Select / Menu");
        w.key(KEYCODE_RSK);
        const Expected templateMenu[] = {{"Назад", "template-return"},
                                         {"Новый", "template-new"},
                                         {"Удалить", "template-delete-confirm"},
                                         {"Стереть всё", "templates-clear-confirm"}};
        menu(w, templateMenu, COUNT(templateMenu), "insert template commands match Java");
        require(w.view().selected == int(w.view().rows.size()) - 1,
                "template popup opens on the last command as Java VirtualList does");
        choose(w, "template-new");
        require(w.editAction_ == "template-edit" && w.editorParents_.size() == 1 &&
                    w.editor_->isVisible(),
                "New template opens nested editor retaining compose state");
        w.editor_->setText("Two");
        w.finishEdit(true);
        require(w.view().kind == View::Templates && w.view().context == "insert" &&
                    w.editAction_ == "message" && w.editUin_ == id &&
                    w.editor_->text() == "draft" && !w.editor_->isVisible() &&
                    w.storage_->templates().size() == 2,
                "saving nested template returns to list with original compose text/UIN");
        w.view().selected = 1;
        w.key(KEYCODE_LSK);
        int paragraph = -1, position = -1;
        w.editor_->getCursorPosition(&paragraph, &position);
        require(w.editor_->isVisible() && w.editAction_ == "message" && w.editUin_ == id &&
                    w.editor_->text() == "drTwoaft" && paragraph == 0 && position == 5 &&
                    w.editorParents_.empty(),
                "template inserts at preserved caret into original compose editor");
        w.editorMenu();
        choose(w, "template-insert-list");
        w.key(KEYCODE_RSK);
        choose(w, "template-new");
        w.editor_->setText("Discarded");
        w.finishEdit(false);
        require(w.view().kind == View::Templates && w.editAction_ == "message" &&
                    w.storage_->templates().size() == 2,
                "nested template Cancel does not save text");
        w.key(KEYCODE_CLEAR);
        require(w.editor_->isVisible() && w.editor_->text() == "drTwoaft" &&
                    w.editAction_ == "message" && w.editUin_ == id,
                "Back from template list resumes the same compose editor");
        reset(w);
    }
    static void smileys(Window &w, uint32_t id) {
        chat(w, message(id));
        w.settings_.setInt("smiley_cursor", 31);
        w.edit(uiText("Сообщение"), "message", "draft", id);
        w.editor_->setCursorPosition(0, 2);
        w.editorMenu();
        choose(w, "smileys");
        const char *codes[] = {":-)",      ":-(",  ";-)",     ":-P",         "*JOKINGLY*", ":'(",
                               "*KISSED*", ":-D",  "*STOP*",  "*IN_LOVE*",   ">:o",        ":-!",
                               "*DRINK*",  ":-\\", "*TIRED*", "*THUMBS_UP*", ":-X",        "[:-}",
                               "@=",       "O:-)", "8-)",     "@}->--",      ":-[",        "=-O",
                               "]:->",     ":-*",  ":-$",     "*KISSING*",   ";-D",        "%-)",
                               "X-)",      "=)"};
        const char *labels[] = {"Smile",     "Sad",        "Ironic",     "Amused",     "Jokingly",
                                "Crying",    "Kissed",     "Very happy", "Stop",       "In love",
                                "Angry",     "Sick",       "Beer",       "Suspirious", "Tired",
                                "Thumbs up", "Shut up",    "Headphones", "Bomb",       "Angel",
                                "Boss",      "Rose",       "Embrassed",  "Wow!",       "Devil",
                                "Kiss",      "Indefinite", "Kissing",    "Green",      "Crazy",
                                "Spy",       "On the side"};
        bool complete = w.view().context == "smileys" && w.view().rows.size() == COUNT(codes);
        for (size_t i = 0; i < COUNT(codes) && i < w.view().rows.size(); ++i)
            complete =
                complete &&
                w.view().rows[i].text ==
                    QString::fromLatin1((std::string(codes[i]) + "  " + labels[i]).c_str()) &&
                w.view().rows[i].action == std::string("insert:") + codes[i] &&
                w.view().rows[i].value == i;
        require(complete,
                "all thirty-two Java standard smileys retain codes, names, icons and order");
        require(w.view().selected == 31 && w.view().offset == 16,
                "smiley picker restores selected cursor and sixteen-pixel cell size");
        ZListBox *list = w.systemMenu_->list();
        QList<QPixmap> icons = list->item(list->currentItem())->getSubItemIcon(0, 0);
        require(icons.count() == 1 && icons.first() && !icons.first()->isNull() &&
                    icons.first()->width() == 16 && icons.first()->height() == 16,
                "native smiley row contains real sixteen-pixel sprite from Java asset");
        w.view().selected = 9;
        w.activateSelected();
        require(w.editor_->isVisible() && w.editAction_ == "message" && w.editUin_ == id &&
                    w.editor_->text() == "dr *IN_LOVE* aft" &&
                    w.settings_.getInt("smiley_cursor") == 9,
                "smiley inserts its canonical code with surrounding spaces at preserved caret");
        w.editorMenu();
        choose(w, "smileys");
        require(w.view().selected == 9, "reopened smiley picker retains last chosen smiley");
        w.key(KEYCODE_LSK);
        require(w.editor_->isVisible() && w.editor_->text() == "dr *IN_LOVE* aft",
                "smiley Back resumes unchanged original compose editor");
        reset(w);
    }
    static void privacy(Window &w, uint32_t id) {
        w.connectionState_ = Event::Online;
        w.contact(id)->privacy = 0;
        w.activate(Row(QString::null, "privacy-lists"));
        require(w.view().context == "privacy-editor" && w.view().rows.size() == 3,
                "privacy table includes all contacts and omits group records");
        footer(w, "Отмена", "Меню", "privacy table softkeys are Cancel / Menu");
        for (size_t i = 0; i < w.view().rows.size(); ++i)
            if (w.view().rows[i].uin == id)
                w.view().selected = i;
        w.key(KEYCODE_RIGHT);
        require(w.view().offset == 1, "privacy Right selects invisible column");
        w.key(KEYCODE_RSK);
        const Expected privacyMenu[] = {{"Информация", "privacy-info"},
                                        {"Сохранить", "privacy-save"},
                                        {"Измен.", "privacy-change"}};
        menu(w, privacyMenu, COUNT(privacyMenu),
             "privacy popup preserves Java command priority order");
        w.key(KEYCODE_CENTER_SELECT);
        require(w.view().context == "privacy-editor" &&
                    w.view().rows[w.view().selected].value == 2 && w.contact(id)->privacy == 0,
                "privacy change modifies only draft selected cell");
        ZSettingItem *privacyRow = nativeSetting(w, w.systemMenu_->list()->currentItem());
        require(privacyRow->getSubItemCount(0) == 2 &&
                    privacyRow->getSubItemText(0, 0) == w.name(id) &&
                    privacyRow->getSubItemText(0, 1) == "D[ ] <I[x]> V[ ]",
                "native privacy table visibly refreshes both checked cell and selected column");
        w.key(KEYCODE_LSK);
        require(w.view().context != "privacy-editor" && w.contact(id)->privacy == 0,
                "privacy Cancel discards staged membership");
        w.activate(Row(QString::null, "privacy-lists"));
        for (size_t i = 0; i < w.view().rows.size(); ++i)
            if (w.view().rows[i].uin == id)
                w.view().selected = i;
        w.view().offset = 1;
        w.activate(Row(QString::null, "privacy-change"));
        submitted.clear();
        w.activate(Row(QString::null, "privacy-save"));
        require(submitted.size() == 1 && submitted[0].type == Command::Privacy &&
                    submitted[0].uin == id && submitted[0].mode == 3 && submitted[0].flag &&
                    w.view().more && w.view().request,
                "privacy Save submits selected membership and waits for real bridge ACK");
        const uint32_t request = w.view().request;
        Event result(Event::CommandResult);
        result.requestId = request;
        result.flag = false;
        result.text = "denied";
        w.consume(result);
        require(w.view().context == "privacy-editor" && !w.view().more && !w.view().request &&
                    w.contact(id)->privacy == 0,
                "privacy rejection keeps draft retryable without claiming success");
        submitted.clear();
        w.activate(Row(QString::null, "privacy-save"));
        require(submitted.size() == 1 && w.view().request,
                "privacy rejected draft can retry the pending edit");
        result.requestId = w.view().request;
        Event roster(Event::Roster);
        ContactRecord changed;
        changed.type = 3;
        changed.uin = id;
        roster.contacts.push_back(changed);
        w.consume(roster);
        require(w.view().context == "privacy-editor" && w.view().more &&
                    w.contact(id)->privacy == 2,
                "SSI state update arrives before acknowledgement without closing the editor");
        result.flag = true;
        w.consume(result);
        require(w.view().context != "privacy-editor" && w.contact(id)->privacy == 2,
                "privacy success closes only after SSI state and matching acknowledgement");
        reset(w);
    }
    static void localHistory(Window &w, uint32_t id) {
        reset(w);
        const Settings previous = w.settings_;
        const bool previousSilent = w.silent_;
        w.silent_ = true;
        w.settings_.setBool("save_history", true);
        w.settings_.setInt("history_count", 200);
        w.settings_.setInt("timezone", 3);
        w.settings_.setInt("daylight", 0);
        w.settings_.setInt("time_offset_minutes", 0);
        w.settings_.setBool("show_time", true);
        w.settings_.setBool("display_date", true);
        w.settings_.setBool("show_sender", true);
        w.settings_.setBool("show_newlines", true);
        w.applySettings();
        std::string error;
        MessageRecord saved = message(id);
        saved.cookie = 1234;
        saved.text = "old on-disk message";
        require(w.storage_->appendHistory(id, saved, error), "seed real local history");
        const std::string path = w.storage_->accountDir() + "/history-1000001.dat";
        Storage other(w.data_);
        require(other.setAccount("second.example", 5190, 123456, error) &&
                    other.appendHistory(id, saved, error),
                "seed second account history");
        const std::string otherPath = other.accountDir() + "/history-1000001.dat";
        w.openChat(id);
        const size_t inMemory = w.chats_[id].messages.size();
        w.showSettings("interface");
        w.chooseSetting("save_history");
        require(!settingFlag(w.settingsDraft_, "save_history") &&
                    settingFlag(w.settings_, "save_history") && access(path.c_str(), F_OK) == 0,
                "history switch is staged without deleting files");
        w.finishSettings(false);
        require(settingFlag(w.settings_, "save_history") && access(path.c_str(), F_OK) == 0,
                "Back cancels disabling history without deletion");
        w.showSettings("interface");
        w.chooseSetting("save_history");
        w.finishSettings(true);
        require(!settingFlag(w.settings_, "save_history") && access(path.c_str(), F_OK) < 0 &&
                    access(otherPath.c_str(), F_OK) < 0 && w.chats_[id].messages.size() == inMemory,
                "Save disables history, removes every account archive and retains live chat");
        MessageRecord live = message(id);
        live.cookie = 2345;
        live.outgoing = true;
        w.incoming(live);
        Event receipt(Event::Receipt);
        receipt.uin = id;
        receipt.cookie = live.cookie;
        receipt.delivery = 2;
        receipt.nativeId = std::string(8, 'r');
        w.consume(receipt);
        require(w.chats_[id].messages.back().delivery == 2 &&
                    w.chats_[id].messages.back().nativeId == receipt.nativeId &&
                    access(path.c_str(), F_OK) < 0,
                "messages and receipts stay usable in RAM without recreating history");
        Settings reloaded;
        require(reloaded.load(w.settings_.path(), error) && !settingFlag(reloaded, "save_history"),
                "disabled history survives reload");
        w.saveState();
        require(w.selectScope(), "recreate empty chat state from the saved account");
        w.applySettings();
        w.connectionState_ = Event::Online;
        submitted.clear();
        w.openChat(id);
        require(w.chats_[id].messages.empty() && submitted.size() == 1 &&
                    submitted[0].type == Command::History && submitted[0].uin == id &&
                    submitted[0].limit == 1 && submitted[0].offset == 0,
                "fresh chat requests exactly one history record like Java");
        const uint32_t preload = submitted[0].requestId;
        w.openChat(id);
        require(submitted.size() == 1, "reopening empty chat deduplicates its active preload");
        MessageRecord historical = message(id);
        historical.time = 0;
        historical.nativeId = std::string(8, 'h');
        historical.text = "[17.11 12:05] Nick: text";
        require(w.messageText(historical) == QString::fromUtf8(historical.text.c_str()),
                "formatted server history has no epoch date, duplicate author or extra newline");
        Event last(Event::History);
        last.uin = id;
        last.requestId = preload;
        last.messages.push_back(historical);
        w.consume(last);
        require(w.chats_[id].messages.size() == 1 && w.chats_[id].unread == 0 &&
                    w.view().rows[0].text == QString::fromUtf8(historical.text.c_str()) &&
                    access(path.c_str(), F_OK) < 0,
                "preloaded server message renders once, stays read and never persists when off");
        submitted.clear();
        w.openChat(id);
        require(submitted.empty(), "populated session chat does not refetch its last message");
        w.chats_[id].messages.clear();
        w.connectionState_ = Event::Disconnected;
        w.openChat(id);
        require(submitted.empty(), "offline empty chat waits for connection");
        Event online(Event::State);
        online.state = Event::Online;
        w.consume(online);
        require(submitted.size() == 1 && submitted[0].type == Command::History &&
                    submitted[0].limit == 1,
                "connecting an already open empty chat starts preload");
        last.requestId = submitted[0].requestId;
        live.outgoing = false;
        live.text = "new live message";
        ++live.cookie;
        w.incoming(live);
        w.consume(last);
        require(w.chats_[id].messages.size() == 1 && w.chats_[id].messages[0].text == live.text,
                "late preload cannot append older text after a live message");
        w.chats_[id].messages.clear();
        submitted.clear();
        w.openChat(id);
        Event failure(Event::Error);
        failure.requestId = submitted[0].requestId;
        failure.uin = id;
        failure.text = "history temporarily unavailable";
        w.consume(failure);
        w.openChat(id);
        require(submitted.size() == 2 && submitted[1].type == Command::History,
                "failed preload can retry on next chat open");
        last.requestId = submitted[1].requestId;
        w.home();
        w.consume(last);
        require(w.chats_[id].messages.size() == 1 && w.chats_[id].unread == 0,
                "preload finishing off screen never creates unread notifications");
        w.showSettings("interface");
        w.chooseSetting("save_history");
        w.finishSettings(true);
        ++live.cookie;
        w.incoming(live);
        require(settingFlag(w.settings_, "save_history") && access(path.c_str(), F_OK) == 0,
                "reenabling local history permits new saves");
        live.time = 1700000000;
        live.senderName = "Nick";
        live.outgoing = false;
        w.settings_.setBool("show_newlines", false);
        require(w.messageText(live) == QString::fromLatin1("15.11 01:13 Nick: new live message"),
                "real message timestamp and configured timezone still render normally");
        // Restoring a chat from All Chats remains its own bridge operation.
        w.chats_[id].messages.clear();
        submitted.clear();
        w.search(true);
        w.activate(Row(QString::null, "open", id));
        require(submitted.size() == 2 && submitted[0].type == Command::AllChats &&
                    submitted[1].type == Command::OpenChat,
                "All Chats still restores the selected chat without a duplicate preload");
        w.settings_ = previous;
        w.silent_ = previousSilent;
        w.applySettings();
        reset(w);
    }
    static void inlineHistory(Window &w, uint32_t id) {
        reset(w);
        w.pending_.clear();
        w.pendingUin_.clear();
        w.chats_[id] = ChatState();
        w.chats_[id].loaded = true;
        w.connectionState_ = Event::Online;
        w.settings_.setBool("save_history", false);
        w.applySettings();
        submitted.clear();
        w.openChat(id);
        require(submitted.size() == 1 && submitted.back().limit == 1,
                "empty chat starts its single-message preload");
        const uint32_t lastRequest = submitted.back().requestId;
        w.history(true);
        require(w.view().kind == View::Chat && submitted.size() == 1 && w.chats_[id].historyQueued,
                "history stays in chat and queues behind an active preload");
        MessageRecord m = message(id);
        m.nativeId = "C";
        m.text = "third";
        m.cookie = 0;
        m.time = 0;
        Event last(Event::History);
        last.requestId = lastRequest;
        last.uin = id;
        last.messages.push_back(m);
        w.consume(last);
        require(submitted.size() == 2 && submitted.back().type == Command::History &&
                    submitted.back().limit ==
                        unsigned(settingNumber(w.settings_, "server_history_count")) &&
                    w.chats_[id].historyRequest == submitted.back().requestId,
                "preload completion starts the queued page exactly once");
        const uint32_t request = submitted.back().requestId;
        w.history(true);
        require(submitted.size() == 2, "repeat history taps do not duplicate the pending request");
        m.nativeId = "D";
        m.text = "live fourth";
        m.cookie = 777;
        m.time = 1700000020;
        w.incoming(m);
        w.view().selected = 1;
        w.view().top = 1;
        w.view().scroll = 8;
        Event page(Event::History);
        page.requestId = request;
        page.uin = id;
        page.more = true;
        page.offset = 3;
        m.cookie = 0;
        m.time = 0;
        m.nativeId = "A";
        m.text = "first";
        page.messages.push_back(m);
        m.nativeId = "B";
        m.text = "second";
        page.messages.push_back(m);
        m.nativeId = "C";
        m.text = "third";
        page.messages.push_back(m);
        w.consume(page);
        require(
            w.view().kind == View::Chat && w.chats_[id].messages.size() == 4 &&
                w.chats_[id].messages[0].nativeId == "A" &&
                w.chats_[id].messages[3].nativeId == "D" && w.chats_[id].unread == 0 &&
                w.view().selected == 3 && w.view().top == 3 && w.view().scroll == 8,
            "server page merges before live arrival, preserving selection, scroll and read state");
        w.chatMenu();
        require(index(w, "history-more") >= 0, "chat menu exposes the next server page");
        w.back();
        w.history(true, true);
        require(submitted.back().type == Command::History && submitted.back().offset == 3 &&
                    w.view().kind == View::Chat,
                "next history page uses its chat cursor without another window");
        const uint32_t older = submitted.back().requestId;
        w.openChat(id + 1, false);
        page.requestId = older;
        page.offset = 4;
        page.more = false;
        page.messages.clear();
        m.nativeId = "0";
        m.text = "oldest";
        page.messages.push_back(m);
        w.consume(page);
        require(w.view().uin == id + 1 && w.chats_[id].messages.size() == 5 &&
                    w.chats_[id].messages[0].nativeId == "0",
                "background history updates only its owning chat");
        w.openChat(id, false);
        const size_t doneCount = submitted.size();
        w.history(true);
        require(submitted.size() == doneCount, "end-of-history blocks redundant requests");
        w.resetServerHistory();
        w.settings_.setInt("chat_messages", 1);
        m.nativeId = "E";
        m.cookie = 778;
        m.time = 1700000030;
        w.incoming(m);
        require(w.chats_[id].messages.size() == 6 && w.chats_[id].historyLoaded,
                "reconnect retains already loaded server history beyond the live-chat cap");
        w.history(true);
        Event error(Event::Error);
        error.requestId = submitted.back().requestId;
        error.uin = id;
        error.text = "try history later";
        w.consume(error);
        require(!w.chats_[id].historyRequest && w.view().kind == View::Chat &&
                    w.notice_ == QString::fromLatin1("try history later"),
                "history error is visible in chat and releases its request for retry");
        w.history(true);
        require(w.chats_[id].historyRequest && w.chats_[id].messages.size() == 6,
                "history retry does not clear the conversation");
        w.resetServerHistory();
        w.pending_.clear();
        w.pendingUin_.clear();
        w.settings_.setInt("chat_messages", 15);
        w.settings_.setBool("save_history", true);
        w.applySettings();
        reset(w);
        View discussion(View::History, w.name(id));
        discussion.context = "server";
        discussion.uin = id;
        discussion.offset = 17;
        discussion.more = true;
        m.nativeId = "comment-B";
        discussion.messages.push_back(m);
        w.showHistory(discussion);
        w.push(discussion);
        w.key(KEYCODE_RSK);
        choose(w, "history-more");
        require(w.view().kind == View::History && w.view().offset == 17 &&
                    submitted.back().type == Command::History && submitted.back().offset == 17 &&
                    w.pending_[submitted.back().requestId] == "history",
                "discussion More retains the thread viewer and its own cursor");
        Event comments(Event::History);
        comments.requestId = submitted.back().requestId;
        comments.uin = id;
        comments.offset = 18;
        comments.more = false;
        m.nativeId = "comment-A";
        comments.messages.push_back(m);
        w.consume(comments);
        require(
            w.view().kind == View::History && w.view().offset == 18 && !w.view().request &&
                !w.view().more && w.view().messages.size() == 2 &&
                w.view().messages[0].nativeId == "comment-A",
            "discussion continuation appends older context in its thread without opening a chat");
        reset(w);
    }
    static void systemPresence(Window &w) {
        w.settings_.setInt("running_icon", 1);
        w.settings_.setInt("status", 16);
        w.connectionState_ = Event::Disconnected;
        w.applySettings();
        require(systemIconMode == 1 && systemIconStatus == 0xffffffffU,
                "disconnected system icon receives the grey offline status");
        Event state(Event::State);
        state.state = Event::Connecting;
        w.consume(state);
        require(systemIconStatus == 0xffffffffU, "connecting keeps the system icon offline");
        state.state = Event::Online;
        w.consume(state);
        require(systemIconStatus == 16, "online system icon receives the selected presence");
        w.activate(Row(QString::null, "status-set", 0, 32));
        require(systemIconStatus == 32, "changing presence updates the system icon immediately");
        state.state = Event::Reconnecting;
        w.consume(state);
        require(systemIconStatus == 0xffffffffU, "reconnect immediately greys the system icon");
        w.settings_.setInt("status", 0);
        w.connectionState_ = Event::Online;
        w.applySettings();
    }
    static void scene(Window &w, uint32_t id) {
        reset(w);
        w.connectionState_ = Event::Online;
        w.contact(id)->status = 0;
        w.contact(id)->noAuth = true;
        const char *value = getenv("TMM_NATIVE_JAVA_SCENE");
        std::string selected = value ? value : "chat-menu";
        if (selected == "main")
            w.mainMenu();
        else if (selected == "contact")
            w.contactMenu(id);
        else if (selected == "settings")
            w.settingsMenu();
        else if (selected == "interface")
            w.showSettings("interface");
        else if (selected == "privacy")
            w.activate(Row(QString::null, "privacy-lists"));
        else if (selected == "history") {
            MessageRecord m = message(id, 2);
            m.token = "example-video";
            m.nativeId = std::string(8, 'h');
            history(w, m, true);
        } else {
            MessageRecord m = message(id, 2);
            m.token = "example-video";
            m.nativeId = std::string(8, 'v');
            chat(w, m);
            w.chatMenu();
        }
        w.notice_ = QString::null;
        w.noticeUntil_ = 0;
        w.resize(240, 320);
        w.show();
        w.repaint();
        fprintf(stderr, "JAVA UI SCENE %s\n", selected.c_str());
    }

  public:
    static void run(Window &w) {
        w.timer_.stop();
        w.silent_ = true;
        w.settings_.set("language", "ru");
        w.settings_.set("host", "bridge.example.test");
        w.settings_.set("uin", "123456");
        w.settings_.set("password", "dummy");
        w.settings_.set("network", "system");
        w.settings_.setInt("auto_connect", 0);
        w.settings_.setInt("auto_reconnect", 0);
        w.settings_.setInt("disconnect_sound", 0);
        w.settings_.setInt("initial_caps", 0);
        w.settings_.setInt("mirror_menu", 0);
        w.settings_.setInt("hide_offline", 0);
        w.settings_.setInt("use_groups", 1);
        w.settings_.set("sound_unlocked", "");
        w.settings_.set("sound_locked", "");
        w.settings_.set("vibration_unlocked", "0");
        w.settings_.set("vibration_locked", "0");
        require(w.selectScope(), "real test account scope");
        std::string error;
        w.storage_->clearAllHistory(error);
        w.contacts_.clear();
        w.chats_.clear();
        w.collapsed_.clear();
        w.quiet_.clear();
        w.applySettings();
        ContactRecord group;
        group.type = 1;
        group.groupId = 1;
        group.name = "Telegram";
        w.contacts_.push_back(group);
        for (unsigned i = 0; i < 3; ++i) {
            ContactRecord c;
            c.uin = 1000001 + i;
            c.name = i == 0 ? "Сергей" : i == 1 ? "Мария" : "Канал";
            c.group = "Telegram";
            c.groupId = 1;
            c.inRoster = true;
            c.status = 0;
            w.contacts_.push_back(c);
            w.chats_[c.uin].loaded = true;
            w.chats_[c.uin].messages.push_back(message(c.uin));
        }
        reset(w);
        mainAndRoster(w, 1000001);
        contactMenus(w, 1000001);
        messageMenus(w, 1000001);
        statusAndDelete(w, 1000001);
        settingsDrafts(w);
        templates(w, 1000001);
        smileys(w, 1000001);
        privacy(w, 1000001);
        localHistory(w, 1000001);
        inlineHistory(w, 1000001);
        systemPresence(w);
        scene(w, 1000001);
        fprintf(stderr, "JAVA UI PASS %u checks\n", checks_);
    }
};
unsigned UiProbe::checks_ = 0;
} // namespace tmm
int main(int argc, char **argv) {
    tmm::Application app(argc, argv, QApplication::GuiServer);
    chdir("/work");
    UTIL_SetPowerOnHandleStatus(10);
    UTIL_SetFlipStatus(SYSTEM_FLIP_OPEN);
    UTIL_SetKeypadLockStatus(false);
    const char *data = getenv("TMM_NATIVE_JAVA_TEST_DATA");
    const std::string dir = data && *data ? data : "/state/java-ui-data";
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
    QTimer::singleShot(1800, &app, SLOT(quit()));
    return app.exec();
}
