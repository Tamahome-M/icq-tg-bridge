#include "window.h"
#include "storage.h"
#include "ui_settings.h"
#include "ui_language.h"
#include "ui_files.h"
#include "ui_smileys.h"
#include "network_profile.h"
#include <unistd.h>
#include <sys/stat.h>
#include <ZMultiLineEdit.h>
#include <ZKeyDef.h>
#include <qapplication.h>
#include <qimage.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <algorithm>
namespace tmm {
static QString u(const char *s) {
    return uiText(s);
}
static QString u(const std::string &s) {
    return QString::fromUtf8(s.c_str());
}
static std::string num(unsigned n) {
    char b[32];
    snprintf(b, sizeof(b), "%u", n);
    return b;
}
static void row(View &v, const char *text, const char *action, uint32_t id = 0,
                unsigned value = 0) {
    v.rows.push_back(Row(u(text), action, id, value));
}
void Window::confirm(const QString &title, const std::string &action, uint32_t id, unsigned value) {
    View v(View::Menu, title);
    row(v, "Отмена", "back");
    v.rows.push_back(Row(u("Да, выполнить"), action, id, value));
    push(v);
}
void Window::activateSelected() {
    if (view().kind == View::Text) {
        if (view().context == "contact-info" && view().selected >= 0 &&
            view().selected < (int)view().rows.size() &&
            view().rows[view().selected].action.compare(0, 6, "phone:") == 0) {
            activate(view().rows[view().selected]);
            return;
        }
        if (view().context == "contact-info" && view().selected >= 0 &&
            view().selected < (int)view().rows.size() &&
            view().rows[view().selected].action == "info-avatar-view" && !infoAvatar_.isNull()) {
            picture_ = infoAvatar_;
            pictureRotation_ = 0;
            pictureZoom_ = 100;
            push(View(View::Picture, u("Фото")));
        }
        return;
    }
    if (view().kind == View::Templates && view().context == "insert" && view().rows.empty()) {
        activate(Row(QString::null, "template-return"));
        return;
    }
    if (view().kind == View::Chat || view().kind == View::History) {
        const MessageRecord *m = selectedMessage();
        if (!m)
            return;
        const bool historyView = view().kind == View::History;
        const char *action = (m->kind == 2 || !m->url.empty()) ? "video-menu"
                             : !historyView                    ? ""
                             : m->kind == 1                    ? "photo"
                             : m->kind == 3                    ? "voice"
                             : m->kind == 4                    ? "file"
                             : m->discussionUin                ? "discussion"
                                                               : "";
        if (*action)
            activate(Row(QString::null, action,
                         m->discussionUin && !m->kind ? m->discussionUin : m->uin));
        return;
    }
    if (view().context == "privacy-editor" ||
        (view().kind == View::Templates && view().context != "insert"))
        return;
    if (view().selected >= 0 && view().selected < (int)view().rows.size())
        activate(view().rows[view().selected]);
}
void Window::activate(const Row &chosen) {
    Row r = chosen;
    std::string action = r.action;
    uint32_t id = r.uin ? r.uin : view().uin;
    r.uin = id;
    if (action == "back") {
        back();
        return;
    }
    if (action == "phonebook" || action == "phone-page") {
        phonebookPage(r.value);
        return;
    }
    if (action.compare(0, 6, "phone:") == 0) {
        phoneActions(view().context == "contact-info" ? view().details : r.text, action.substr(6));
        return;
    }
    if (view().context == "phone-actions" &&
        (action == "phone-call" || action == "phone-copy" || action == "phone-save")) {
        // Both the Motorola editor and the clipboard may run a nested event loop.
        const std::string number = view().directory;
        const QString title = view().details;
        back();
        if (action == "phone-copy")
            copy(QString::fromLatin1(number.c_str()));
        else if (action == "phone-call") {
            if (!platform_.dialNumber(number))
                info(u("Не удалось открыть набор номера"));
        } else if (!platform_.newPhoneContact(title, number))
            info(u("Не удалось открыть контакты телефона"));
        return;
    }
    if (activateJavaMenu(r) || activateSettings(r))
        return;
    if (action == "editor-secret" || action == "editor-copy-all" || action == "editor-copy" ||
        action == "editor-cut" || action == "editor-paste" || action == "editor-clear") {
        // Dismiss only the command popup. Back on an underlying settings form
        // means Cancel, so it must never be invoked a second time here.
        if (view().kind == View::Popup)
            stack_.pop_back();
        if (action == "editor-secret" && editSecret_)
            editor_->setEchoMode(editor_->echoMode() == ZMultiLineEdit::Password
                                     ? ZMultiLineEdit::Normal
                                     : ZMultiLineEdit::Password);
        else if (action == "editor-copy-all")
            copy(editor_->text());
        else if (action == "editor-copy")
            editor_->copy();
        else if (action == "editor-cut")
            editor_->cut();
        else if (action == "editor-paste")
            editor_->paste();
        else if (action == "editor-clear")
            editor_->clear();
        editor_->show();
        editor_->setFocus();
        update();
        return;
    }
    if (view().kind == View::Popup) {
        stack_.pop_back();
        syncSystemMenu();
    }
    if (activateMedia(r))
        return;
    if (action == "home") {
        home();
        return;
    }
    if (action == "connect") {
        // Close the command menu before connectClient may open settings or an
        // error page. A hotkey can invoke this action without a menu.
        if (view().kind == View::Menu)
            back();
        if (connectionState_ == Event::Online || connectionState_ == Event::Connecting ||
            connectionState_ == Event::Reconnecting)
            disconnectClient();
        else
            connectClient();
        return;
    }
    if (action == "disconnect") {
        disconnectClient();
        back();
        return;
    }
    if (action == "main") {
        mainMenu();
        return;
    }
    if (action == "minimize") {
        minimize();
        return;
    }
    if (action == "lock") {
        lock();
        return;
    }
    if (action == "silent") {
        silent_ = !silent_;
        saveState();
        back();
        return;
    }
    if (action == "exit") {
        requestExit();
        return;
    }
    if (action == "exit-now") {
        saveState();
        client_.stop();
        qApp->quit();
        return;
    }
    if (action == "settings") {
        settingsMenu();
        return;
    }
    if (action.compare(0, 9, "settings:") == 0) {
        showSettings(action.substr(9));
        return;
    }
    if (action.compare(0, 6, "field:") == 0) {
        chooseSetting(action.substr(6));
        return;
    }
    if (action.compare(0, 4, "set:") == 0) {
        size_t at = action.find(':', 4);
        if (at != std::string::npos) {
            std::string key = action.substr(4, at - 4), value = action.substr(at + 1);
            back();
            commitSetting(key, value);
        }
        return;
    }
    if (action.compare(0, 13, "group-toggle:") == 0) {
        std::string group = action.substr(13);
        collapsed_[group] = !collapsed_[group];
        rebuildRoster();
        return;
    }
    if (action == "open") {
        if (view().context == "all-chats" && connectionState_ == Event::Online) {
            Command restore(Command::OpenChat);
            restore.uin = id;
            restore.requestId = client_.nextRequestId();
            pending_[restore.requestId] = "restore-chat";
            pendingUin_[restore.requestId] = id;
            if (!send(restore))
                return;
        }
        openChat(id);
        return;
    }
    if (action == "contact-list") {
        contactListMenu();
        return;
    }
    if (action == "contact-menu") {
        contactMenu(id);
        return;
    }
    if (action == "compose") {
        edit(u("Сообщение"), "message", storage_->loadDraft(id), id);
        return;
    }
    if (action == "message-menu") {
        messageMenu();
        return;
    }
    if (action == "history") {
        history(true);
        return;
    }
    if (action == "history-more") {
        history(true, true);
        return;
    }
    if (action == "local-history") {
        history(false);
        return;
    }
    if (action == "info" || action == "avatar") {
        Command c(action == "info" ? Command::ContactInfo : Command::Avatar);
        c.uin = id;
        c.requestId = client_.nextRequestId();
        if (send(c)) {
            pending_[c.requestId] = action;
            pendingUin_[c.requestId] = id;
            info(u("Запрос отправлен"));
        }
        return;
    }
    if (action == "local-info") {
        ContactRecord *c = contact(id);
        showText(u("Локальные данные"),
                 name(id) + "\nUIN " + QString::number(id) +
                     (c ? "\n" + status(c->status) + "\n" + u(c->group) : QString::null));
        return;
    }
    if (action == "info-copy" || action == "info-copy-all") {
        QString text;
        for (size_t i = 0; i < view().rows.size(); ++i)
            if (action == "info-copy-all" || int(i) == view().selected) {
                if (!text.isEmpty())
                    text += "\n";
                text += view().rows[i].text;
            }
        copy("[" + QString::number(view().uin) + "]\n" + text);
        return;
    }
    if (action == "copy-view") {
        if (!view().rows.empty())
            copy(view().rows[0].text);
        return;
    }
    if (action == "message-text" || action == "copy-message" || action == "quote-select") {
        const MessageRecord *m = selectedMessage();
        if (!m)
            return;
        if (action == "message-text")
            showText(name(m->uin), messageText(*m));
        else if (action == "copy-message")
            copy(u(m->text));
        else {
            quoteUin_ = m->sourceUin ? m->sourceUin : m->uin;
            quoteId_ = m->nativeId;
            quoteText_ = m->text;
            info(u("Выберите чат и «Цитировать сюда»"));
        }
        return;
    }
    if (action == "quote-here") {
        if (quoteId_.empty()) {
            info(u("Сначала выберите сообщение для цитирования"));
            return;
        }
        Command c(Command::Quote);
        c.uin = id;
        c.sourceUin = quoteUin_;
        c.nativeId = quoteId_;
        c.requestId = client_.nextRequestId();
        if (send(c)) {
            pending_[c.requestId] = "quote";
            info(u("Цитирование…"));
        }
        return;
    }
    if (action == "discussion") {
        const MessageRecord *m = selectedMessage();
        Command c(Command::Discussion);
        c.uin = id;
        c.requestId = client_.nextRequestId();
        if (m) {
            c.nativeId = m->nativeId;
            c.token = m->token;
        }
        if (send(c)) {
            View v(View::History, u("Обсуждение"));
            v.uin = id;
            v.context = "server";
            v.request = c.requestId;
            push(v);
            pending_[c.requestId] = "history";
        }
        return;
    }
    if (action == "quiet") {
        View v(View::Choice, u("Получать без оповещений"));
        row(v, "Обычная доставка", "quiet-off", id);
        row(v, "Без оповещений", "quiet-on", id);
        v.selected = std::find(quiet_.begin(), quiet_.end(), id) == quiet_.end() ? 0 : 1;
        push(v);
        return;
    }
    if (action == "quiet-on" || action == "quiet-off") {
        quietToggle(id, action == "quiet-on");
        back();
        return;
    }
    if (action == "history-search") {
        edit(u("Поиск в истории"), "history-search", "");
        return;
    }
    if (action == "history-search-clear") {
        back();
        view().directory.clear();
        showHistory(view());
        update();
        return;
    }
    if (action == "add-existing") {
        Command c(Command::AddContact);
        c.uin = id;
        c.text = std::string(name(id).utf8());
        send(c);
        return;
    }
    if (action == "all-chats") {
        search(true);
        return;
    }
    if (action == "search") {
        search(false);
        return;
    }
    if (action == "chats-more") {
        search(view().context == "all-chats", true);
        return;
    }
    if (action == "status") {
        View v(View::Choice, u("Статус"));
        row(v, "В сети", "status-set", 0, 0);
        row(v, "Отошёл", "status-set", 0, 1);
        row(v, "Недоступен", "status-set", 0, 2);
        row(v, "Не беспокоить", "status-set", 0, 4);
        row(v, "Занят", "status-set", 0, 16);
        row(v, "Свободен для общения", "status-set", 0, 32);
        row(v, "Невидимый", "status-set", 0, 256);
        push(v);
        return;
    }
    if (action == "status-set") {
        Command c(Command::Status);
        c.status = r.value;
        if (send(c)) {
            settings_.setInt("status", r.value);
            std::string e;
            settings_.save(e);
            updateSystemStatusIcon();
            back();
        }
        return;
    }
    if (action == "add-contact" || action == "add-group" || action == "rename-contact" ||
        action == "auth-request" || action == "auth-deny") {
        edit(action == "add-contact"      ? u("UIN контакта")
             : action == "add-group"      ? u("Название группы")
             : action == "rename-contact" ? u("Имя контакта")
                                          : u("Текст авторизации"),
             action, action == "rename-contact" ? std::string(name(id).utf8()) : "", id);
        return;
    }
    if (action == "auth-grant") {
        Command c(Command::GrantAuthorization);
        c.uin = id;
        send(c);
        return;
    }
    if (action == "delete-confirm" || action == "remove-confirm") {
        confirm(action == "delete-confirm" ? u("Удалить чат в сети?") : u("Удалиться из его КЛ?"),
                action == "delete-confirm" ? "delete" : "remove", id);
        return;
    }
    if (action == "delete" || action == "remove") {
        Command c(action == "delete" ? Command::DeleteChat : Command::RemoveMe);
        c.uin = id;
        ContactRecord *item = contact(id);
        if (item) {
            c.itemId = item->itemId;
            c.groupId = item->groupId;
        }
        send(c);
        back();
        return;
    }
    if (action == "move-contact" || action == "group-rename-list" ||
        action == "group-delete-list") {
        View v(View::Menu, u("Выберите группу"));
        std::map<unsigned, std::string> groups;
        for (size_t i = 0; i < contacts_.size(); ++i)
            if (contacts_[i].groupId)
                groups[contacts_[i].groupId] = contacts_[i].group;
        for (std::map<unsigned, std::string>::iterator i = groups.begin(); i != groups.end(); ++i)
            v.rows.push_back(Row(u(i->second),
                                 action == "move-contact"        ? "move"
                                 : action == "group-rename-list" ? "group-rename"
                                                                 : "group-delete-confirm",
                                 id, i->first));
        push(v);
        return;
    }
    if (action == "move") {
        Command c(Command::MoveContact);
        c.uin = id;
        c.groupId = r.value;
        ContactRecord *old = contact(id);
        if (old)
            c.itemId = old->itemId;
        send(c);
        back();
        return;
    }
    if (action == "group-rename") {
        editKey_ = num(r.value);
        edit(u("Название группы"), "group-rename", std::string(r.text.utf8()));
        return;
    }
    if (action == "group-delete-confirm") {
        confirm(u("Удалить группу?"), "group-delete", 0, r.value);
        return;
    }
    if (action == "group-delete") {
        Command c(Command::DeleteGroup);
        c.groupId = r.value;
        send(c);
        back();
        return;
    }
    if (action == "privacy") {
        View v(View::Menu, u("Приватность"));
        row(v, "Добавить в игнорируемые", "privacy-on", id, 14);
        row(v, "Убрать из игнорируемых", "privacy-off", id, 14);
        row(v, "Всегда видимый", "privacy-on", id, 2);
        row(v, "Убрать из видимых", "privacy-off", id, 2);
        row(v, "Всегда невидимый", "privacy-on", id, 3);
        row(v, "Убрать из невидимых", "privacy-off", id, 3);
        push(v);
        return;
    }
    if (action == "privacy-on" || action == "privacy-off") {
        Command c(Command::Privacy);
        c.uin = id;
        c.mode = r.value;
        c.flag = action == "privacy-on";
        send(c);
        back();
        return;
    }
    if (action == "privacy-lists") {
        View v(View::Menu, u("Списки приватности"));
        for (size_t i = 0; i < contacts_.size(); ++i)
            if (contacts_[i].privacy)
                v.rows.push_back(
                    Row(name(contacts_[i].uin) + " [" + QString::number(contacts_[i].privacy) + "]",
                        "privacy", contacts_[i].uin));
        push(v);
        return;
    }
    if (action == "clear-chat-confirm" || action == "clear-history-confirm") {
        confirm(u("Удалить локальные сообщения?"),
                action == "clear-chat-confirm" ? "clear-chat" : "clear-history", id);
        return;
    }
    if (action == "clear-chat" || action == "clear-history") {
        std::string e;
        if (action == "clear-chat") {
            ChatState &chat = chats_[id];
            if (chat.historyRequest) {
                Command cancel(Command::CancelRequest);
                cancel.requestId = chat.historyRequest;
                client_.submit(cancel);
                pending_.erase(chat.historyRequest);
                pendingUin_.erase(chat.historyRequest);
            }
            chat = ChatState();
            chat.loaded = true;
        } else if (!storage_->clearHistory(id, e))
            info(u(e));
        back();
        return;
    }
    if (action == "close-chat") {
        saveDraft();
        while (stack_.size() > 1)
            stack_.pop_back();
        rebuildRoster();
        return;
    }
    if (action == "templates") {
        showTemplates(false);
        return;
    }
    if (action == "template-insert-list") {
        showTemplates(true);
        return;
    }
    if (action == "template-new") {
        editKey_ = "new";
        edit(u("Новый шаблон"), "template-edit", "");
        return;
    }
    if (action == "template") {
        std::vector<std::string> t = storage_->templates();
        if (r.value >= t.size())
            return;
        if (view().context == "insert") {
            editor_->insert(u(t[r.value]));
            while (stack_.size() > editDepth_)
                stack_.pop_back();
            editor_->show();
            editor_->setFocus();
        } else {
            View v(View::Menu, u("Шаблон"));
            row(v, "Изменить", "template-edit", 0, r.value);
            row(v, "Удалить", "template-delete", 0, r.value);
            push(v);
        }
        return;
    }
    if (action == "template-edit") {
        std::vector<std::string> t = storage_->templates();
        if (r.value < t.size()) {
            editKey_ = num(r.value);
            edit(u("Шаблон"), "template-edit", t[r.value]);
        }
        return;
    }
    if (action == "template-delete") {
        std::vector<std::string> t = storage_->templates();
        if (r.value < t.size()) {
            t.erase(t.begin() + r.value);
            std::string e;
            if (!storage_->saveTemplates(t, e))
                info(u(e));
            back();
            back();
            showTemplates(false);
        }
        return;
    }
    if (action == "editor-back") {
        finishEdit(false);
        return;
    }
    if (action == "smileys") {
        View v(View::Menu, u("Смайлы"));
        v.context = "smileys";
        std::vector<SmileyDefinition> smileys;
        unsigned cellSize = 16;
        std::string error;
        if (!loadJavaSmileys("smiles.txt", smileys, cellSize, error)) {
            info(u(error));
            editor_->show();
            editor_->setFocus();
            return;
        }
        v.offset = cellSize;
        for (size_t i = 0; i < smileys.size(); ++i)
            v.rows.push_back(Row(u(smileys[i].code + "  " + smileys[i].label),
                                 "insert:" + smileys[i].code, 0, smileys[i].index));
        v.selected =
            std::max(0, std::min(int(v.rows.size()) - 1, settings_.getInt("smiley_cursor", 0)));
        push(v);
        return;
    }
    if (action.compare(0, 7, "insert:") == 0) {
        if (view().context == "smileys")
            settings_.setInt("smiley_cursor", view().selected);
        editor_->insert(u(" " + action.substr(7) + " "));
        while (stack_.size() > editDepth_)
            stack_.pop_back();
        editor_->show();
        editor_->setFocus();
        return;
    }
    if (action == "hotkeys") {
        View v(View::Menu, u("Горячие клавиши"));
        const char *keys[] = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "#", "call"};
        for (unsigned i = 0; i < 13; ++i)
            v.rows.push_back(
                Row(u(keys[i]) + ": " +
                        u(settings_.get(std::string("hotkey.") + keys[i],
                                        keys[i] == std::string("#") ? "lock" : "none")),
                    std::string("hotkey:") + keys[i]));
        push(v);
        return;
    }
    if (action.compare(0, 7, "hotkey:") == 0) {
        View v(View::Choice, u("Действие клавиши"));
        v.context = action.substr(7);
        const char *names[] = {"Нет",           "Информация",    "Написать",       "Подключение",
                               "Настройки",     "Меню",          "Блокировать",    "История",
                               "Свернуть",      "Полный экран",  "Без звука",      "Группы",
                               "Подсветка",     "В начало",      "В конец",        "Страница вверх",
                               "Страница вниз", "Следующий чат", "Предыдущий чат", "Вверх",
                               "Вниз",          "Выбрать"};
        const char *ids[] = {"none",    "info",      "compose",   "connect",       "settings",
                             "main",    "lock",      "history",   "minimize",      "fullscreen",
                             "silent",  "groups",    "light",     "top",           "bottom",
                             "page-up", "page-down", "next-chat", "previous-chat", "up",
                             "down",    "select"};
        for (unsigned i = 0; i < 22; ++i)
            v.rows.push_back(Row(u(names[i]), "hotkey-set:" + v.context + ":" + ids[i]));
        push(v);
        return;
    }
    if (action.compare(0, 11, "hotkey-set:") == 0) {
        size_t p = action.find(':', 11);
        settings_.set("hotkey." + action.substr(11, p - 11), action.substr(p + 1));
        settingsChanged();
        back();
        back();
        activate(Row(QString::null, "hotkeys"));
        return;
    }
    if (action == "reset-confirm") {
        confirm(u("Удалить настройки и локальную историю?"), "reset");
        return;
    }
    if (action == "reset") {
        disconnectClient();
        std::string e;
        storage_->clearAllHistory(e);
        storage_->saveTemplates(std::vector<std::string>(), e);
        storage_->saveQuietChats(std::vector<uint32_t>(), e);
        settings_.reset();
        const std::vector<SettingField> &f = settingFields();
        for (size_t i = 0; i < f.size(); ++i)
            settings_.set(f[i].key, f[i].initial);
        settings_.save(e);
        selectScope();
        home();
        applySettings();
        return;
    }
    if (action == "log") {
        QString text;
        for (size_t i = 0; i < log_.size(); ++i)
            text += u(log_[i]) + "\n";
        showText(u("Журнал связи"), text);
        return;
    }
    if (action == "about") {
        unsigned long total = 0, resident = 0;
        FILE *memory = fopen("/proc/self/statm", "r");
        if (memory) {
            if (fscanf(memory, "%lu %lu", &total, &resident) != 2)
                resident = 0;
            fclose(memory);
        }
        QString description =
            u("TeleMotoMax Native " TMM_NATIVE_VERSION "\nMotorola RAZR V8 / Qt 2\nПротокол OSCAR "
              "+ TeleMotoMax 1.32\n") +
            u(connectionState_ == Event::Online ? "Подключено" : "Отключено") + "\n" +
            QString::number(contacts_.size()) + u(" контактов");
        if (resident)
            description +=
                "\nRSS: " + QString::number(resident * (unsigned long)getpagesize() / 1024) + " KB";
        showText(u("О программе"), description);
        return;
    }
}
void Window::requestExit() {
    if (unread())
        confirm(u("Есть непрочитанные сообщения. Выйти?"), "exit-now");
    else
        activate(Row(QString::null, "exit-now"));
}
void Window::hotkey(int code) {
    std::string key;
    if (code >= KEYCODE_0 && code <= KEYCODE_9)
        key = std::string(1, (char)code);
    else if (code == KEYCODE_POUND)
        key = "#";
    else if (code == KEYCODE_STAR)
        key = "*";
    else if (code == KEYCODE_SEND)
        key = "call";
    else
        return;
    std::string action = settings_.get("hotkey." + key, javaHotkeyDefault(key));
    if (action == "none")
        return;
    if (action == "top")
        view().selected = 0;
    else if (action == "bottom")
        view().selected = std::max(0, (int)view().rows.size() - 1);
    else if (action == "page-up")
        view().selected = std::max(0, view().selected - 6);
    else if (action == "page-down")
        view().selected = std::max(0, std::min((int)view().rows.size() - 1, view().selected + 6));
    else if (action == "up")
        this->key(KEYCODE_UP);
    else if (action == "down")
        this->key(KEYCODE_DOWN);
    else if (action == "next-chat")
        this->key(KEYCODE_RIGHT);
    else if (action == "previous-chat")
        this->key(KEYCODE_LEFT);
    else if (action == "select")
        activateSelected();
    else if (action == "offline-toggle") {
        settings_.setBool("hide_offline", !settingFlag(settings_, "hide_offline"));
        rebuildRoster();
    } else if (action == "fullscreen") {
        settings_.setBool("fullscreen", !settingFlag(settings_, "fullscreen"));
        applySettings();
    } else if (action == "groups") {
        settings_.setBool("use_groups", !settingFlag(settings_, "use_groups"));
        rebuildRoster();
    } else if (action == "light") {
        lightOn_ = !lightOn_;
        platform_.setBacklight(lightOn_);
    } else {
        uint32_t id = view().uin;
        if (view().kind == View::Roster && view().selected < (int)view().rows.size())
            id = view().rows[view().selected].uin;
        activate(Row(QString::null, action, id));
    }
    update();
}
} // namespace tmm
