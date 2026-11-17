#include "window.h"
#include "storage.h"
#include "ui_settings.h"
#include "ui_language.h"
#include "ui_files.h"
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
static std::vector<std::string> split(const std::string &s, char separator) {
    std::vector<std::string> r;
    size_t at = 0;
    for (;;) {
        size_t n = s.find(separator, at);
        r.push_back(s.substr(at, n == std::string::npos ? n : n - at));
        if (n == std::string::npos)
            break;
        at = n + 1;
    }
    return r;
}
void Window::mainMenu() {
    View v(View::Menu, u("TeleMotoMax Native"));
    const bool connecting =
        connectionState_ == Event::Connecting || connectionState_ == Event::Reconnecting;
    row(v,
        connectionState_ == Event::Online ? "Отключиться"
        : connecting                      ? "Отменить подключение"
                                          : "Подключиться",
        connectionState_ == Event::Online || connecting ? "disconnect" : "connect");
    row(v, "Статус", "status");
    row(v, "Контакты", "home");
    row(v, "Контакт-лист", "contact-list");
    if (loadedMediaReady_)
        row(v, "Полученное вложение", "media-received");
    if (!capturePath_.empty() && !outgoingRequest_)
        row(v, "Неотправленное вложение", "attachment-pending");
    row(v, "Настройки", "settings");
    row(v, silent_ ? "Включить оповещения" : "Без звука", "silent");
    row(v, "Блокировать", "lock");
    row(v, "Журнал связи", "log");
    row(v, "О программе", "about");
    row(v, "Свернуть", "minimize");
    row(v, "Выход", "exit");
    push(v);
}
void Window::contactListMenu() {
    View v(View::Menu, u("Контакт-лист"));
    row(v, "Все чаты", "all-chats");
    row(v, "Добавить контакт", "add-contact");
    row(v, "Поиск", "search");
    row(v, "Добавить группу", "add-group");
    row(v, "Переименовать группу", "group-rename-list");
    row(v, "Удалить группу", "group-delete-list");
    row(v, "Списки приватности", "privacy-lists");
    push(v);
}
void Window::contactMenu(uint32_t id) {
    if (!id)
        return;
    View v(View::Menu, name(id));
    v.uin = id;
    row(v, "Написать", "compose", id);
    ContactRecord *entry = contact(id);
    if (entry && !entry->inRoster)
        row(v, "Добавить контакт", "add-existing", id);
    row(v, "Информация", "info", id);
    row(v, "Локальные данные", "local-info", id);
    row(v, "Аватар", "avatar", id);
    row(v, "Переименовать", "rename-contact", id);
    row(v, "Переместить в группу", "move-contact", id);
    row(v, "Приватность", "privacy", id);
    row(v, "Запросить авторизацию", "auth-request", id);
    row(v, "Разрешить авторизацию", "auth-grant", id);
    row(v, "Отказать в авторизации", "auth-deny", id);
    row(v, "Удалить чат", "delete-confirm", id);
    row(v, "Удалиться из его КЛ", "remove-confirm", id);
    push(v);
}
void Window::chatMenu() {
    uint32_t id = view().uin;
    View v(View::Menu, name(id));
    v.uin = id;
    row(v, "Написать", "compose", id);
    row(v, "История с сервера", "history", id);
    row(v, "Локальная история", "local-history", id);
    if (!quoteId_.empty())
        row(v, "Цитировать сюда", "quote-here", id);
    row(v, "Получать без оповещений", "quiet", id);
    row(v, "Прикрепить", "attachments", id);
    row(v, "Контакт", "contact-menu", id);
    row(v, "Очистить этот чат", "clear-chat-confirm", id);
    row(v, "Очистить локальную историю", "clear-history-confirm", id);
    row(v, "Закрыть чат", "close-chat", id);
    push(v);
}
void Window::messageMenu() {
    const MessageRecord *m = selectedMessage();
    if (!m)
        return;
    View v(View::Menu, u("Сообщение"));
    v.uin = m->uin;
    row(v, "Полный текст", "message-text");
    row(v, "Копировать", "copy-message");
    if (!m->nativeId.empty())
        row(v, "Цитировать", "quote-select");
    if (m->discussionUin)
        row(v, "Обсуждение", "discussion", m->discussionUin);
    if (m->kind == 1 || m->kind == 2)
        row(v, "Смотреть фото", "photo");
    if (m->kind == 2 || !m->url.empty())
        row(v, "Смотреть видео", "video-menu");
    if (m->kind == 3)
        row(v, "Прослушать", "voice");
    if (m->kind == 4)
        row(v, "Получить файл", "file");
    if (m->text.find("http://") != std::string::npos ||
        m->text.find("https://") != std::string::npos || !m->url.empty())
        row(v, "Открыть ссылку", "urls");
    push(v);
}
void Window::playerMenu() {
    View v(View::Menu, u("Плеер"));
    row(v, paused_ ? "Продолжить" : "Пауза", "player-pause");
    if (view().context != "outgoing-preview")
        row(v, "Сохранить в папку", "save-media-file");
    if (view().context != "outgoing-preview" && !videoToken_.empty())
        row(v, "Следующий фрагмент", "player-next");
    row(v, "Остановить и закрыть", "player-stop");
    push(v);
}
void Window::settingsMenu() {
    View v(View::Menu, u("Настройки"));
    row(v, "Учётные записи", "accounts");
    row(v, "Сеть", "settings:network");
    row(v, "Интерфейс", "settings:interface");
    row(v, "Чат и история", "settings:chat");
    row(v, "Цветовая схема", "settings:theme");
    row(v, "Фоновая картинка", "settings:background");
    row(v, "Камера", "settings:camera");
    row(v, "Медиа", "settings:media");
    row(v, "Telegram", "settings:telegram");
    row(v, "MAX", "settings:max");
    row(v, "eXpress", "settings:express");
    row(v, "Оповещения", "settings:notifications");
    row(v, "Горячие клавиши", "hotkeys");
    row(v, "Часовой пояс", "settings:timezone");
    row(v, "Подсветка", "settings:backlight");
    row(v, "Шаблоны", "templates");
    row(v, "Сброс данных", "reset-confirm");
    push(v);
}
void Window::showSettings(const std::string &section) {
    View v(View::SettingsPage, u("Настройки"));
    v.context = section;
    const std::vector<SettingField> &fields = settingFields();
    for (size_t i = 0; i < fields.size(); ++i) {
        const SettingField &f = fields[i];
        if (section != f.section)
            continue;
        std::string value = settingValue(settings_, f.key), display = value;
        if (f.secret)
            display = std::string(value.size(), '*');
        else if (*f.choices) {
            std::vector<std::string> choices = split(f.choices, '|');
            for (size_t j = 0; j < choices.size(); ++j) {
                size_t n = choices[j].find('=');
                if (choices[j].substr(0, n) == value)
                    display = n == std::string::npos ? choices[j] : choices[j].substr(n + 1);
            }
        }
        v.rows.push_back(
            Row(u(f.label) + ": " + u(display.c_str()), std::string("field:") + f.key));
    }
    if (view().kind == View::SettingsPage && view().context == section) {
        v.selected = view().selected;
        view() = v;
        update();
    } else
        push(v);
}
void Window::chooseSetting(const std::string &key) {
    const SettingField *f = settingField(key);
    if (!f)
        return;
    if (key == "network_profile") {
        std::vector<std::string> profiles;
        std::string error;
        View v(View::Choice, u(f->label));
        v.context = key;
        v.rows.push_back(Row(u("По умолчанию"), "set:network_profile:"));
        if (!loadInternetProfiles(profiles, error))
            info(u(error));
        for (size_t i = 0; i < profiles.size(); ++i)
            v.rows.push_back(Row(u(profiles[i]), "set:network_profile:" + profiles[i]));
        push(v);
        return;
    }
    if (key == "background_file") {
        View v(View::Menu, u(f->label));
        row(v, "Нет", "set:background_file:");
        row(v, "Выбрать файл", "pick-background");
        push(v);
        return;
    }
    if (*f->choices) {
        View v(View::Choice, u(f->label));
        v.context = key;
        std::vector<std::string> values = split(f->choices, '|');
        for (size_t i = 0; i < values.size(); ++i) {
            size_t p = values[i].find('=');
            std::string value = values[i].substr(0, p),
                        label = p == std::string::npos ? values[i] : values[i].substr(p + 1);
            v.rows.push_back(Row(u(label.c_str()), "set:" + key + ":" + value));
            if (value == settingValue(settings_, key))
                v.selected = i;
        }
        push(v);
    } else {
        editKey_ = key;
        edit(u(f->label), "setting", settingValue(settings_, key), 0, f->secret,
             (key == "host" || key == "psk" || key == "password" || key == "dns_server" ||
              key == "uin" || key == "lock_pin")
                 ? f->maximum
                 : 12);
    }
}
void Window::commitSetting(const std::string &key, const std::string &value) {
    const SettingField *f = settingField(key);
    std::string error;
    if (!f || !validateSetting(*f, value, error)) {
        info(u(error));
        return;
    }
    bool scope =
        (key == "host" || key == "port" || key == "uin") && settingValue(settings_, key) != value;
    if (scope) {
        saveState();
        disconnectClient();
    }
    settings_.set(key, value);
    if (scope) {
        selectScope();
        home();
        settingsMenu();
        showSettings(f->section);
    }
    settingsChanged();
}
void Window::confirm(const QString &title, const std::string &action, uint32_t id, unsigned value) {
    View v(View::Menu, title);
    row(v, "Отмена", "back");
    v.rows.push_back(Row(u("Да, выполнить"), action, id, value));
    push(v);
}
void Window::activateSelected() {
    if (view().kind == View::Text) {
        if (!view().rows.empty())
            copy(view().rows[0].text);
        return;
    }
    if (view().kind == View::Chat || view().kind == View::History) {
        if (view().selected < (int)view().rows.size() &&
            view().rows[view().selected].action == "history-more")
            history(true, true);
        else
            messageMenu();
        return;
    }
    if (view().selected >= 0 && view().selected < (int)view().rows.size())
        activate(view().rows[view().selected]);
}
void Window::activate(const Row &chosen) {
    Row r = chosen;
    std::string action = r.action;
    uint32_t id = r.uin ? r.uin : view().uin;
    if (action == "back") {
        back();
        return;
    }
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
    if (action == "video-menu") {
        View v(View::Menu, u("Смотреть видео"));
        row(v, "Смотреть", "video");
        const MessageRecord *m = selectedMessage();
        if (m && !m->url.empty())
            row(v, "Открыть в браузере", "video-browser");
        push(v);
        return;
    }
    if (action == "photo" || action == "video" || action == "voice" || action == "file") {
        requestMedia(action == "photo" ? 1 : action == "video" ? 2 : action == "voice" ? 3 : 4);
        return;
    }
    if (action == "video-browser") {
        const MessageRecord *m = selectedMessage();
        if (m)
            openUrl(m->url);
        return;
    }
    if (action == "urls") {
        const MessageRecord *m = selectedMessage();
        if (!m)
            return;
        View v(View::Menu, u("Ссылки"));
        if (!m->url.empty())
            v.rows.push_back(Row(u(m->url), "url:" + m->url));
        size_t at = 0;
        while (at < m->text.size()) {
            size_t h = m->text.find("http", at);
            if (h == std::string::npos)
                break;
            size_t end = m->text.find_first_of(" \r\n\t<>", h);
            std::string url = m->text.substr(h, end == std::string::npos ? end : end - h);
            if (url.find("http://") == 0 || url.find("https://") == 0)
                v.rows.push_back(Row(u(url), "url:" + url));
            at = end == std::string::npos ? m->text.size() : end + 1;
        }
        push(v);
        return;
    }
    if (action.compare(0, 4, "url:") == 0) {
        openUrl(action.substr(4));
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
            chats_[id].messages.clear();
            chats_[id].unread = 0;
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
    if (action == "attachment-pending") {
        showAttachmentReview();
        return;
    }
    if (action == "attachments") {
        attachmentMenu(id);
        return;
    }
    if (action == "capture-photo" || action == "capture-voice" || action == "capture-video") {
        if (capture_.busy() || !capturePath_.empty() || outgoingRequest_) {
            if (!capturePath_.empty() && !outgoingRequest_)
                showAttachmentReview();
            else
                info(u("Завершите текущую запись"));
            return;
        }
        capture_.setProfile(u(settingValue(settings_, "camera_size")),
                            u(settingValue(settings_, "camera_encoding")));
        capture_.setVoiceBitrate(settingNumber(settings_, "voice_kbps10")
                                     ? settingNumber(settings_, "voice_kbps10") * 100
                                     : 6700);
        captureUin_ = id;
        captureKind_ = action == "capture-photo" ? 1 : action == "capture-video" ? 2 : 3;
        std::string path = storage_->accountDir() + "/capture-" + num((unsigned)time(0)) +
                           (captureKind_ == 1   ? ".jpg"
                            : captureKind_ == 2 ? ".3gp"
                                                : ".amr");
        if (captureKind_ == 1) {
            capture_.capturePhoto(u(path));
            resume();
        } else if (captureKind_ == 2) {
            capture_.recordVideo(u(path), 30);
            resume();
        } else {
            View v(View::Recording, u("Голосовое"));
            v.context = "recording";
            v.uin = id;
            v.details = u("Кому: ") + name(id);
            v.status = u("Запись: 0 с");
            row(v, "Готово", "record-stop");
            row(v, "Отмена", "record-cancel");
            push(v);
            capture_.recordVoice(u(path), settingNumber(settings_, "voice_seconds")
                                              ? settingNumber(settings_, "voice_seconds")
                                              : 60);
        }
        return;
    }
    if (action == "upload-file") {
        pickUin_ = id;
        pickKind_ = 4;
        files("", "upload");
        return;
    }
    if (action == "upload-media") {
        View v(View::Menu, u("Отправить медиа"));
        row(v, "Фото", "pick-photo", id);
        row(v, "Видео", "pick-video", id);
        row(v, "Звук", "pick-voice", id);
        push(v);
        return;
    }
    if (action == "pick-photo" || action == "pick-video" || action == "pick-voice") {
        pickUin_ = id;
        pickKind_ = action == "pick-photo" ? 1 : action == "pick-video" ? 2 : 3;
        files("", "upload");
        return;
    }
    if (action == "pick-background") {
        files("", "background");
        return;
    }
    if (action.compare(0, 10, "directory:") == 0 || action == "directory") {
        view().directory = action == "directory" ? std::string(r.text.utf8()) : action.substr(10);
        loadFiles();
        return;
    }
    if (action == "file-select") {
        std::string path = view().directory + "/" + std::string(r.text.utf8()),
                    purpose = view().context;
        if (purpose == "background") {
            settings_.set("background_file", path);
            back();
            settingsChanged();
        } else if (purpose == "upload")
            reviewAttachment(path, pickKind_, pickUin_, false);
        return;
    }
    if (action == "save-here") {
        std::string path = view().directory + "/" + downloadName_, error;
        if (!copyMediaFile(playPath_, path, error))
            info(u(error.empty() ? "Не удалось сохранить файл" : error));
        else {
            back();
            info(u("Сохранено: " + path));
        }
        return;
    }
    if (action == "record-stop") {
        capture_.stop();
        return;
    }
    if (action == "record-cancel") {
        capture_.cancel();
        back();
        return;
    }
    if (action == "capture-send") {
        if (capturePath_.empty()) {
            info(u("Вложение недоступно"));
            return;
        }
        upload(capturePath_, captureKind_, captureUin_);
        return;
    }
    if (action == "capture-delete") {
        back();
        return;
    }
    if (action == "capture-preview") {
        previewAttachment();
        return;
    }
    if (action == "attachment-details") {
        struct stat st;
        QString details = u("Кому: ") + name(captureUin_) + "\n" + u(capturePath_);
        if (!stat(capturePath_.c_str(), &st))
            details += "\n" + QString::number((unsigned long)st.st_size) + u(" байт");
        showText(u("Вложение"), details);
        return;
    }
    if (action == "attachment-replace") {
        uint32_t target = captureUin_;
        unsigned kind = captureKind_;
        bool owned = captureOwned_;
        back();
        if (!owned) {
            if (view().kind != View::Files || view().context != "upload" || pickUin_ != target ||
                pickKind_ != kind) {
                pickUin_ = target;
                pickKind_ = kind;
                files("", "upload");
            }
        } else
            activate(Row(QString::null,
                         kind == 1   ? "capture-photo"
                         : kind == 2 ? "capture-video"
                                     : "capture-voice",
                         target));
        return;
    }
    if (action == "transfer-cancel") {
        back();
        return;
    }
    if (action == "player-pause") {
        if (player_.pause(!paused_))
            paused_ = !paused_;
        back();
        return;
    }
    if (action == "player-next") {
        back();
        nextVideo();
        return;
    }
    if (action == "player-stop") {
        back();
        back();
        return;
    }
    if (action == "file-details") {
        showText(u("Файл"), u(downloadName_) + "\n" + u(playPath_));
        return;
    }
    if (action == "save-media-file") {
        files("", "save-media");
        return;
    }
    if (action == "open-media-file") {
        platform_.openFile(u(playPath_));
        return;
    }
    if (action == "media-received") {
        Event e;
        e.path = receivedPath_;
        e.filename = receivedName_;
        e.requestId = client_.nextRequestId();
        pending_[e.requestId] = savedMediaPurpose_;
        showMedia(e);
        pending_.erase(e.requestId);
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
    if (action == "editor-secret" && editSecret_) {
        editor_->setEchoMode(editor_->echoMode() == ZMultiLineEdit::Password
                                 ? ZMultiLineEdit::Normal
                                 : ZMultiLineEdit::Password);
        back();
        return;
    }
    if (action == "editor-copy-all") {
        copy(editor_->text());
        return;
    }
    if (action == "editor-copy") {
        editor_->copy();
        return;
    }
    if (action == "editor-cut") {
        editor_->cut();
        return;
    }
    if (action == "editor-paste") {
        editor_->paste();
        back();
        editor_->show();
        return;
    }
    if (action == "editor-clear") {
        editor_->clear();
        back();
        editor_->show();
        return;
    }
    if (action == "editor-back") {
        finishEdit(false);
        return;
    }
    if (action == "smileys") {
        View v(View::Menu, u("Смайлы"));
        const char *codes[] = {":)", ":(", ";)", ":D", ":P", "*IN_LOVE*", "(y)", "*THUMBS_UP*"};
        for (unsigned i = 0; i < 8; ++i)
            v.rows.push_back(Row(u(codes[i]), std::string("insert:") + codes[i]));
        push(v);
        return;
    }
    if (action.compare(0, 7, "insert:") == 0) {
        editor_->insert(u(action.substr(7)));
        while (stack_.size() > editDepth_)
            stack_.pop_back();
        editor_->show();
        editor_->setFocus();
        return;
    }
    if (action == "accounts") {
        View v(View::Menu, u("Учётные записи"));
        int count = settings_.getInt("accounts", 1);
        for (int i = 0; i < count; ++i) {
            std::string key = "account." + num(i) + ".uin",
                        label = settings_.get(key, i == 0 ? settingValue(settings_, "uin") : "");
            v.rows.push_back(
                Row(u(label.empty() ? "Учётная запись" : label), "account-switch", 0, i));
        }
        row(v, "Добавить", "account-add");
        row(v, "Изменить текущую", "settings:account");
        row(v, "Удалить текущую", "account-delete-confirm");
        push(v);
        return;
    }
    if (action == "account-switch") {
        switchAccount(r.value);
        back();
        return;
    }
    if (action == "account-add") {
        if (settings_.getInt("accounts", 1) >= 5) {
            info(u("Не больше пяти учётных записей"));
            return;
        }
        edit(u("UIN новой учётной записи"), "account-add", "");
        return;
    }
    if (action == "account-delete-confirm") {
        confirm(u("Удалить настройки учётной записи?"), "account-delete");
        return;
    }
    if (action == "account-delete") {
        int count = settings_.getInt("accounts", 1), at = settings_.getInt("account_index", 0);
        if (count < 2) {
            info(u("Нельзя удалить единственную учётную запись"));
            return;
        }
        disconnectClient();
        saveState();
        for (int i = at; i < count - 1; ++i) {
            settings_.set("account." + num(i) + ".uin",
                          settings_.get("account." + num(i + 1) + ".uin"));
            settings_.set("account." + num(i) + ".password",
                          settings_.get("account." + num(i + 1) + ".password"));
        }
        settings_.setInt("accounts", count - 1);
        settings_.set("uin", settings_.get("account.0.uin"));
        settings_.set("password", settings_.get("account.0.password"));
        settings_.setInt("account_index", 0);
        selectScope();
        home();
        settingsChanged();
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
              "+ TeleMotoMax 1.31\n") +
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
void Window::switchAccount(int target) {
    int previous = settings_.getInt("account_index", 0);
    if (target == previous)
        return;
    saveState();
    disconnectClient();
    settings_.set("account." + num(previous) + ".uin", settingValue(settings_, "uin"));
    settings_.set("account." + num(previous) + ".password", settingValue(settings_, "password"));
    settings_.setInt("account_index", target);
    settings_.set("uin", settings_.get("account." + num(target) + ".uin"));
    settings_.set("password", settings_.get("account." + num(target) + ".password"));
    selectScope();
    home();
    settingsChanged();
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
    std::string action = settings_.get("hotkey." + key, key == "#"      ? "lock"
                                                        : key == "call" ? "compose"
                                                                        : "none");
    if (action == "none")
        return;
    if (action == "top")
        view().selected = 0;
    else if (action == "bottom")
        view().selected = std::max(0, (int)view().rows.size() - 1);
    else if (action == "page-up")
        view().selected = std::max(0, view().selected - 6);
    else if (action == "page-down")
        view().selected = std::min((int)view().rows.size() - 1, view().selected + 6);
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
    else if (action == "fullscreen") {
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
