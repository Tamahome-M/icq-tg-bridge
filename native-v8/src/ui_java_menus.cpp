#include "window.h"
#include "storage.h"
#include "ui_settings.h"
#include "ui_language.h"
#include "ui_links.h"
#include <algorithm>
#include <stdio.h>
#include <unistd.h>

namespace tmm {
namespace {
QString u(const char *s) {
    return uiText(s);
}
QString u(const std::string &s) {
    return QString::fromUtf8(s.c_str());
}
void row(View &v, const char *text, const char *action, uint32_t id = 0, unsigned value = 0) {
    v.rows.push_back(Row(u(text), action, id, value));
}
bool hasUrl(const MessageRecord *message) {
    return message && !javaMessageUrls(message->text).empty();
}
bool byName(const Row &a, const Row &b) {
    return a.text.lower() < b.text.lower();
}
const unsigned privacyBits[] = {4, 2, 1};
const unsigned privacyTypes[] = {14, 3, 2};
} // namespace

void Window::mainMenu() {
    View v(View::Menu, u("Меню"));
    v.context = "main-menu";
    if (connectionState_ == Event::Online) {
        row(v, "Блокировка клавиатуры", "lock");
        row(v, "Отключиться", "disconnect");
    } else if (connectionState_ == Event::Connecting || connectionState_ == Event::Reconnecting)
        row(v, "Отменить подключение", "disconnect");
    else
        row(v, "Подключиться", "connect");
    row(v, "Статус", "status");
    row(v, "Контакты", "contact-list");
    bool haveContacts = false;
    for (size_t i = 0; i < contacts_.size(); ++i)
        haveContacts = haveContacts || (contacts_[i].type == 0 && contacts_[i].uin);
    if (haveContacts)
        row(v, "Чаты", "home");
    row(v, "Настройки", "settings");
    row(v, silent_ ? "Вкл. звук" : "Откл. звук", "silent");
    row(v, "О программе", "about");
    row(v, "Свернуть", "minimize");
    row(v, "Выход", "exit");
    if (!stack_.empty() && view().context == "main-menu") {
        v.selected = std::max(0, std::min(view().selected, int(v.rows.size()) - 1));
        view() = v;
        update();
    } else
        push(v);
}

void Window::contactListMenu() {
    View v(View::Menu, u("Контакты"));
    v.context = "contact-list-menu";
    row(v, "Все чаты", "all-chats");
    row(v, "Добавить контакт", "add-contact");
    row(v, "Добавить группу", "add-group");
    row(v, "Найти контакт", "search");
    row(v, "Удалить группу", "group-delete-list");
    row(v, "Переим. группу", "group-rename-list");
    row(v, "Прив. списки", "privacy-lists");
    push(v);
}

void Window::contactMenu(uint32_t id) {
    if (!id)
        return;
    const ContactRecord *entry = contact(id);
    const bool connected = connectionState_ == Event::Online;
    View v(View::Menu, u("Меню контакта"));
    v.context = "contact-menu";
    v.uin = id;
    row(v, "Сообщения", "");
    if (connected) {
        row(v, "Сообщение", "compose", id);
        if (entry && entry->noAuth)
            row(v, "Запрос авторизации", "auth-request", id);
    }
    row(v, "Информация", "");
    row(v, "Информация", "info", id);
    if (entry && entry->status != 0xffffffffU)
        row(v, "Инфо о клиенте", "local-info", id);
    if (connected) {
        row(v, "Списки", "");
        row(v, "Удалить", "delete-confirm", id);
        row(v, "Удалиться из его КЛ", "remove-confirm", id);
        if (entry && entry->groupId) {
            row(v, "Переименовать", "rename-contact", id);
            row(v, "Перен. в группу", "move-contact", id);
        }
        unsigned privacy = entry ? entry->privacy : 0;
        row(v, privacy & 4 ? "Отменить игнор. список" : "В игнор. список",
            privacy & 4 ? "privacy-off" : "privacy-on", id, 14);
        row(v, privacy & 2 ? "Отменить невид. список" : "В невид. список",
            privacy & 2 ? "privacy-off" : "privacy-on", id, 3);
        row(v, privacy & 1 ? "Отменить видим. список" : "В видим. список",
            privacy & 1 ? "privacy-off" : "privacy-on", id, 2);
    }
    v.selected = connected ? 1 : 2;
    push(v);
}

void Window::chatMenu() {
    uint32_t id = view().uin;
    const MessageRecord *message = selectedMessage();
    const ContactRecord *entry = contact(id);
    View v(View::Popup, name(id));
    v.context = "chat-menu";
    v.uin = id;
    // VirtualList sorts descending Command priority, keeping equal priorities
    // stable, and opens its bottom popup with the final command selected.
    if (hasUrl(message))
        row(v, "Открыть ссылку", "urls", id);    // priority 9
    row(v, "Удалить чат...", "chat-delete", id); // 8
    row(v, "Меню контакта", "contact-menu", id); // 7
    if (entry && !entry->inRoster)
        row(v, "Добавить контакт...", "add-existing", id); // 5
    row(v, "История с сервера", "history", id);
    std::map<uint32_t, ChatState>::const_iterator chat = chats_.find(id);
    if (chat != chats_.end() && chat->second.historyStarted && chat->second.historyMore)
        row(v, "Ещё с сервера", "history-more", id);
    row(v, "Получать без оповещений", "quiet", id);
    row(v, "Копировать", "copy-message", id); // 4
    row(v, "Снять фото", "capture-photo", id);
    row(v, "Записать голосовое", "capture-voice", id);
    row(v, "Записать кружок", "capture-video", id);
    row(v, "Отправить файл", "upload-file", id);
    row(v, "Отправить фото/видео", "upload-media", id);
    if (message && message->discussionUin)
        row(v, "Обсуждение", "discussion", message->discussionUin);
    if (message && !message->nativeId.empty())
        row(v, "Цитировать", "quote-select", id); // 3
    bool quoting = false;
    for (std::map<uint32_t, std::string>::const_iterator i = pending_.begin(); i != pending_.end();
         ++i)
        quoting = quoting || i->second == "quote";
    if (!quoteId_.empty() && !quoting)
        row(v, "Цитировать сюда", "quote-here", id);
    if (message && !message->token.empty() && (message->kind == 1 || message->kind == 2))
        row(v, "Показать фото", "photo", id);
    if (message && (!message->url.empty() || (!message->token.empty() && message->kind == 2)))
        row(v, "Смотреть видео", "video-menu", id);
    if (message && !message->token.empty() && message->kind == 3)
        row(v, "Прослушать", "voice", id);
    if (message && !message->token.empty() && message->kind == 4)
        row(v, "Скачать файл", "file", id);
    row(v, "Ответ...", "compose", id); // 1
    if (entry && entry->noAuth)
        row(v, "Запрос авторизации", "auth-request", id);
    v.selected = v.rows.size() - 1;
    push(v);
}

void Window::messageMenu() {
    // Chat commands refer to the current message; Java has one contextual
    // popup, rather than an extra full-screen 'Message' menu on Select.
    if (view().kind != View::History) {
        chatMenu();
        return;
    }
    const MessageRecord *message = selectedMessage();
    View v(View::Popup, view().title);
    v.context = "history-menu";
    v.uin = view().uin;
    if (message && message->discussionUin)
        row(v, "Обсуждение", "discussion", message->discussionUin); // 4
    if (view().more)
        row(v, "Ещё", "history-more", v.uin); // 3
    if (message && !message->nativeId.empty())
        row(v, "Цитировать", "quote-select", v.uin);
    bool quoting = false;
    for (std::map<uint32_t, std::string>::const_iterator i = pending_.begin(); i != pending_.end();
         ++i)
        quoting = quoting || i->second == "quote";
    if (!quoteId_.empty() && !quoting)
        row(v, "Цитировать сюда", "quote-here", v.uin);
    if (message && !message->url.empty())
        row(v, "Смотреть видео", "video-menu", v.uin);
    if (message && !message->token.empty()) {
        if (message->kind == 1 || message->kind == 2)
            row(v, "Показать фото", "photo", v.uin);
        if (message->kind == 2 && message->url.empty())
            row(v, "Смотреть видео", "video-menu", v.uin);
        if (message->kind == 3)
            row(v, "Прослушать", "voice", v.uin);
        if (message->kind == 4)
            row(v, "Скачать файл", "file", v.uin);
    }
    if (v.rows.empty())
        return;
    v.selected = v.rows.size() - 1;
    push(v);
}

bool Window::activateJavaMenu(const Row &chosen) {
    Row r = chosen;
    uint32_t id = r.uin ? r.uin : view().uin;
    const std::string action = r.action;
    if (action.empty())
        return true;
    if (action == "silent") {
        silent_ = !silent_;
        saveState();
        if (view().context == "main-menu")
            mainMenu();
        else
            update();
        return true;
    }
    if (action == "disconnect" && view().context == "main-menu") {
        disconnectClient();
        mainMenu();
        return true;
    }
    if (action == "status") {
        View v(View::Choice, u("Статус"));
        v.context = "status-menu";
        const char *names[] = {"Онлайн", "Свободен для беседы", "Отсутствую", "Недоступен",
                               "Занят",  "Не беспокоить",       "Невидимый",  "Невидим для всех",
                               "Злой",   "Депрессия",           "Дома",       "На работе",
                               "Обедаю"};
        const unsigned statuses[] = {0,   32,     1,      4,      16,     2,     256,
                                     512, 0x3000, 0x4000, 0x5000, 0x6000, 0x2001};
        unsigned current = settings_.getInt("status", 0);
        for (unsigned i = 0; i < sizeof(statuses) / sizeof(statuses[0]); ++i) {
            row(v, names[i], "status-set", 0, statuses[i]);
            if (statuses[i] == current)
                v.selected = i;
        }
        push(v);
        return true;
    }
    if (action == "status-set") {
        settings_.setInt("status", r.value);
        std::string error;
        if (!settings_.save(error)) {
            info(u(error));
            return true;
        }
        updateSystemStatusIcon();
        if (connectionState_ == Event::Online) {
            Command c(Command::Status);
            c.status = r.value;
            send(c);
        }
        back();
        return true;
    }
    if (action == "chat-delete") {
        if (view().kind == View::Popup)
            back();
        View v(View::Choice, u("Удалить чат"));
        v.context = "chat-delete";
        v.uin = id;
        row(v, "Этого контакта", "chat-delete-selection", id, 0);
        row(v, "Всех кроме этого", "chat-delete-selection", id, 1);
        row(v, "Всех контактов", "chat-delete-selection", id, 2);
        push(v);
        return true;
    }
    if (action == "chat-delete-selection") {
        saveDraft();
        for (std::map<uint32_t, ChatState>::iterator i = chats_.begin(); i != chats_.end();) {
            bool erase = r.value == 2 || (r.value == 0 ? i->first == id : i->first != id);
            if (erase)
                chats_.erase(i++);
            else
                ++i;
        }
        home();
        return true;
    }
    if (action == "info") {
        if (view().kind == View::Popup)
            back();
        View v(View::Text, QString::number(id));
        v.context = "contact-info";
        v.uin = id;
        if (connectionState_ == Event::Online) {
            Command c(Command::ContactInfo);
            c.uin = id;
            c.requestId = client_.nextRequestId();
            if (!send(c))
                return true;
            pending_[c.requestId] = "info";
            pendingUin_[c.requestId] = id;
            v.request = c.requestId;
            v.rows.push_back(Row(u("Пожалуйста, ждите ...")));
        } else
            v.rows.push_back(Row(name(id) + "\nUIN: " + QString::number(id)));
        push(v);
        return true;
    }
    if (action == "local-info") {
        showText(u("Инфо о клиенте"), u("Мост не передаёт программу собеседника."));
        return true;
    }
    if (action == "quiet") {
        if (view().kind == View::Popup)
            back();
        View v(View::SettingsPage, u("Получать без оповещений"));
        v.context = "quiet-settings";
        v.uin = id;
        v.offset = std::find(quiet_.begin(), quiet_.end(), id) != quiet_.end();
        v.details = u("Чат остаётся заглушённым. Новые сообщения отмечаются без звука.");
        v.rows.push_back(Row(name(id) + ": " + u(v.offset ? "Без оповещений" : "Обычная доставка"),
                             "quiet-choice", id));
        push(v);
        return true;
    }
    if (action == "quiet-choice") {
        View v(View::Choice, u("Получать без оповещений"));
        v.context = "quiet-choice";
        v.uin = id;
        row(v, "Обычная доставка", "quiet-draft", id, 0);
        row(v, "Без оповещений", "quiet-draft", id, 1);
        v.selected = view().offset ? 1 : 0;
        push(v);
        return true;
    }
    if (action == "quiet-draft") {
        back();
        if (view().context == "quiet-settings") {
            view().offset = r.value;
            view().rows[0].text =
                name(view().uin) + ": " + u(r.value ? "Без оповещений" : "Обычная доставка");
            update();
        }
        return true;
    }
    if (action == "quiet-save") {
        if (view().context == "quiet-settings")
            quietToggle(view().uin, view().offset != 0);
        return true;
    }
    if (action == "privacy-lists") {
        View v(View::Menu, u("Прив. списки"));
        v.context = "privacy-editor";
        for (size_t i = 0; i < contacts_.size(); ++i)
            if (contacts_[i].type == 0 && contacts_[i].uin)
                v.rows.push_back(Row(u(contacts_[i].name), "privacy-row", contacts_[i].uin,
                                     contacts_[i].privacy & 7));
        std::sort(v.rows.begin(), v.rows.end(), byName);
        push(v);
        return true;
    }
    if (action == "privacy-column") {
        if (view().context == "privacy-editor" && !view().more) {
            view().offset = std::min(2U, r.value);
            update();
        }
        return true;
    }
    if (action == "privacy-row")
        return true; // As in Java: Select does not immediately change a checkbox.
    if (action == "privacy-menu") {
        if (view().context != "privacy-editor")
            return true;
        View v(View::Popup, u("Прив. списки"));
        v.context = "privacy-menu";
        row(v, "Информация", "privacy-info");
        row(v, "Сохранить", "privacy-save");
        row(v, "Измен.", "privacy-change");
        v.selected = v.rows.size() - 1;
        push(v);
        return true;
    }
    if (action == "privacy-change" || action == "privacy-info" || action == "privacy-save") {
        if (view().kind == View::Popup)
            back();
        if (view().context != "privacy-editor")
            return true;
        View &v = view();
        if (v.more) {
            info(u("Сохранение..."));
            return true;
        }
        if (action == "privacy-save") {
            v.more = true;
            continueJavaPrivacySave();
            return true;
        }
        if (v.selected < 0 || v.selected >= int(v.rows.size()))
            return true;
        Row &selected = v.rows[v.selected];
        if (action == "privacy-info")
            return activateJavaMenu(Row(QString::null, "info", selected.uin));
        selected.value ^= privacyBits[std::min(2U, v.offset)];
        if (selected.value & privacyBits[std::min(2U, v.offset)]) {
            if (v.offset == 1)
                selected.value &= ~1U;
            else if (v.offset == 2)
                selected.value &= ~2U;
        }
        update();
        return true;
    }
    if (action == "privacy-on" || action == "privacy-off") {
        const ContactRecord *entry = contact(id);
        if (action == "privacy-on" && entry &&
            ((r.value == 2 && (entry->privacy & 2)) || (r.value == 3 && (entry->privacy & 1)))) {
            Command remove(Command::Privacy);
            remove.uin = id;
            remove.mode = r.value == 2 ? 3 : 2;
            remove.flag = false;
            if (!send(remove))
                return true;
        }
        Command c(Command::Privacy);
        c.uin = id;
        c.mode = r.value;
        c.flag = action == "privacy-on";
        if (send(c))
            back();
        return true;
    }
    if (action == "about") {
        QString text = u("TeleMotoMax Native " TMM_NATIVE_VERSION "\nMotorola RAZR V8 / Qt 2\n") +
                       u(connectionState_ == Event::Online ? "Подключено" : "Отключено");
        unsigned long pages = 0, resident = 0;
        FILE *memory = fopen("/proc/self/statm", "r");
        if (memory) {
            if (fscanf(memory, "%lu %lu", &pages, &resident) == 2)
                text +=
                    "\nRSS: " + QString::number(resident * (unsigned long)getpagesize() / 1024) +
                    " KB";
            fclose(memory);
        }
        text += "\n\nhttps://github.com/Tamahome-M/icq-tg-bridge\n";
        if (!log_.empty()) {
            text += u("\nСвязь:\n");
            for (size_t i = 0; i < log_.size(); ++i)
                text += u(log_[i]) + "\n";
        }
        showText(u("О программе"), text);
        view().context = "about";
        return true;
    }
    return false;
}

void Window::continueJavaPrivacySave() {
    for (size_t index = 0; index < stack_.size(); ++index) {
        View &v = stack_[index];
        if (v.context != "privacy-editor" || !v.more || v.request)
            continue;
        // One outstanding edit avoids overflowing the worker's bounded command
        // queue; SSI roster state precedes its ACK, so the next scan advances.
        for (size_t i = 0; i < v.rows.size(); ++i) {
            const ContactRecord *entry = contact(v.rows[i].uin);
            if (!entry)
                continue;
            for (unsigned adding = 0; adding < 2; ++adding)
                for (unsigned col = 0; col < 3; ++col) {
                    bool desired = (v.rows[i].value & privacyBits[col]) != 0;
                    if (desired != (adding != 0) ||
                        desired == ((entry->privacy & privacyBits[col]) != 0))
                        continue;
                    Command command(Command::Privacy);
                    command.uin = entry->uin;
                    command.mode = privacyTypes[col];
                    command.flag = desired;
                    command.requestId = client_.nextRequestId();
                    if (!send(command)) {
                        v.more = false;
                        return;
                    }
                    v.request = command.requestId;
                    pending_[command.requestId] = "privacy-save";
                    pendingUin_[command.requestId] = command.uin;
                    v.details = u("Сохранение...");
                    update();
                    return;
                }
        }
        v.more = false;
        if (index + 1 == stack_.size())
            back();
        else {
            stack_.erase(stack_.begin() + index);
            update();
        }
        return;
    }
}

bool Window::consumeJavaMenu(const Event &event) {
    if (event.type == Event::State &&
        (event.state == Event::Disconnected || event.state == Event::Reconnecting)) {
        for (size_t i = 0; i < stack_.size(); ++i)
            if (stack_[i].context == "privacy-editor" && stack_[i].more) {
                stack_[i].more = false;
                stack_[i].request = 0;
                stack_[i].details = u("Сохранение прервано: нет соединения");
            }
        return false;
    }
    std::map<uint32_t, std::string>::iterator pending = pending_.find(event.requestId);
    if (pending == pending_.end() || pending->second != "privacy-save" ||
        (event.type != Event::CommandResult && event.type != Event::Error))
        return false;
    pending_.erase(pending);
    pendingUin_.erase(event.requestId);
    for (size_t i = 0; i < stack_.size(); ++i) {
        View &v = stack_[i];
        if (v.context != "privacy-editor" || v.request != event.requestId)
            continue;
        v.request = 0;
        if (event.type == Event::Error || !event.flag) {
            v.more = false;
            v.details = u(event.text.empty() ? "Изменение контакта отклонено" : event.text);
            info(v.details);
        } else
            continueJavaPrivacySave();
        return true;
    }
    return true;
}
} // namespace tmm
