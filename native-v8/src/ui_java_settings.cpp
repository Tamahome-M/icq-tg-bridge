#include "window.h"
#include "storage.h"
#include "ui_settings.h"
#include "ui_language.h"
#include "network_profile.h"
#include <ZMultiLineEdit.h>
#include <qapplication.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <algorithm>
namespace tmm {
namespace {
QString u(const char *s) {
    return uiText(s);
}
QString u(const std::string &s) {
    return QString::fromUtf8(s.c_str());
}
std::string num(unsigned n) {
    char b[32];
    snprintf(b, sizeof(b), "%u", n);
    return b;
}
void row(View &v, const char *text, const char *action, unsigned value = 0) {
    v.rows.push_back(Row(u(text), action, 0, value));
}
std::vector<std::string> split(const std::string &s, char separator) {
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
std::string choiceLabel(const SettingField &f, const std::string &value) {
    std::vector<std::string> choices = split(f.choices, '|');
    for (size_t i = 0; i < choices.size(); ++i) {
        size_t equal = choices[i].find('=');
        if (choices[i].substr(0, equal) == value)
            return equal == std::string::npos ? choices[i] : choices[i].substr(equal + 1);
    }
    if (std::string(f.key) == "background_kind" && value == "legacy")
        return "Сохраненное изображение";
    return value;
}
void fieldRow(View &v, const Settings &s, const SettingField &f, const std::string &key,
              const QString &label = QString::null) {
    const std::string value = settingValue(s, key);
    QString display = f.secret ? QString::fromLatin1(std::string(value.size(), '*').c_str())
                               : u(*f.choices ? choiceLabel(f, value) : value);
    v.rows.push_back(Row((label.isEmpty() ? u(f.label) : label) + ": " + display, "field:" + key));
}
unsigned accountCount(const Settings &s) {
    return std::max(1, std::min(5, s.getInt("accounts", 1)));
}
void seedAccounts(Settings &draft, const Settings &live) {
    unsigned count = accountCount(live);
    unsigned active = std::min(count - 1, (unsigned)std::max(0, live.getInt("account_index", 0)));
    draft.setInt("accounts", count);
    draft.setInt("account_index", active);
    for (unsigned i = 0; i < count; ++i) {
        const std::string prefix = "account." + num(i) + ".";
        draft.set(prefix + "uin",
                  live.get(prefix + "uin", i == active ? settingValue(live, "uin") : ""));
        draft.set(prefix + "password",
                  live.get(prefix + "password", i == active ? settingValue(live, "password") : ""));
    }
    draft.set("account." + num(active) + ".uin", settingValue(live, "uin"));
    draft.set("account." + num(active) + ".password", settingValue(live, "password"));
}
} // namespace
void Window::settingsMenu() {
    View v(View::Menu, u("Настройки"));
    v.context = "settings-menu";
    row(v, "Учетная запись", "accounts");
    row(v, "Сеть", "settings:network");
    row(v, "Интерфейс", "settings:interface");
    row(v, "Цветовая схема", "settings:theme");
    row(v, "Фоновое изобр.", "settings:background");
    row(v, "Камера", "settings:camera");
    row(v, "Медиа", "settings:media");
    row(v, "Сеть Telegram", "settings:telegram");
    row(v, "Сеть MAX", "settings:max");
    row(v, "Сеть eXpress", "settings:express");
    row(v, "Горячие клавиши", "hotkeys");
    row(v, "Оповещения", "settings:notifications");
    row(v, "Часовой пояс", "settings:timezone");
    row(v, "Шаблоны", "templates");
    row(v, "Сброс настроек", "reset-confirm");
    push(v);
}
bool Window::settingsPageActive() const {
    return settingsEditing_ && !stack_.empty() &&
           (view().kind == View::SettingsPage || view().context == "settings-theme");
}
void Window::showSettings(const std::string &requested) {
    std::string section = requested == "chat" || requested == "backlight" ? "interface" : requested;
    if (!settingsEditing_ || settingsSection_ != section) {
        if (settingsEditing_)
            finishSettings(false);
        settingsDraft_ = settings_;
        settingsSection_ = section;
        settingsDepth_ = stack_.size();
        settingsEditing_ = true;
        if (section == "account")
            seedAccounts(settingsDraft_, settings_);
        if (section == "timezone") {
            time_t stamp =
                time(0) +
                (settingNumber(settings_, "timezone") + settingNumber(settings_, "daylight")) *
                    3600 +
                settingNumber(settings_, "time_offset_minutes") * 60;
            struct tm *local = gmtime(&stamp);
            settingsDraft_.setInt("local_hour", local ? local->tm_hour : 0);
        }
    }
    if (section == "theme") {
        View v(View::Choice, u("Цветовая схема"));
        v.context = "settings-theme";
        const SettingField &f = *settingField("theme");
        std::vector<std::string> choices = split(f.choices, '|');
        for (size_t i = 0; i < choices.size(); ++i) {
            size_t equal = choices[i].find('=');
            const std::string value = choices[i].substr(0, equal);
            v.rows.push_back(Row(u(choices[i].substr(equal + 1)), "set:theme:" + value, 0, i));
            if (value == settingValue(settingsDraft_, "theme"))
                v.selected = i;
        }
        if (view().context == v.context) {
            view() = v;
            update();
        } else
            push(v);
        return;
    }
    View v(View::SettingsPage, u("Настройки"));
    v.context = section;
    if (section == "account") {
        unsigned count = accountCount(settingsDraft_);
        if (count > 1) {
            unsigned active = std::min(
                count - 1, (unsigned)std::max(0, settingsDraft_.getInt("account_index", 0)));
            const std::string value = settingsDraft_.get("account." + num(active) + ".uin");
            v.rows.push_back(Row(u("Учетная запись") + ": " + u(value.empty() ? "---" : value),
                                 "account-choose"));
        }
        for (unsigned i = 0; i < count; ++i) {
            const std::string suffix = count > 1 ? "-" + num(i + 1) : "";
            if (count > 1)
                row(v, "---", "settings-heading");
            fieldRow(v, settingsDraft_, *settingField("uin"), "account." + num(i) + ".uin",
                     u("UIN") + u(suffix));
            fieldRow(v, settingsDraft_, *settingField("password"),
                     "account." + num(i) + ".password", u("Пароль") + u(suffix));
        }
    } else if (section == "hotkeys") {
        v.title = u("Список клавиш");
        const char *keys[] = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "#"};
        for (unsigned i = 0; i < 12; ++i) {
            const std::string action =
                settingsDraft_.get(std::string("hotkey.") + keys[i], javaHotkeyDefault(keys[i]));
            v.rows.push_back(Row(u(keys[i]) + ": " + u(javaHotkeyLabel(action)),
                                 std::string("hotkey:") + keys[i]));
        }
    } else {
        const std::vector<SettingField> &fields = settingFields();
        for (size_t i = 0; i < fields.size(); ++i) {
            const SettingField &f = fields[i];
            if (section != f.section)
                continue;
            const char *group = settingGroup(f.key);
            if (*group)
                v.rows.push_back(Row(u(group), "settings-heading"));
            fieldRow(v, settingsDraft_, f, f.key);
            if (std::string(f.key) == "dns_server")
                row(v, "Изменения DNS — после перезапуска.", "settings-heading");
        }
    }
    if (!v.rows.empty()) {
        while (v.selected < int(v.rows.size()) && (v.rows[v.selected].action.empty() ||
                                                   v.rows[v.selected].action == "settings-heading"))
            ++v.selected;
        if (v.selected == int(v.rows.size()))
            v.selected = 0;
    }
    if (view().kind == View::SettingsPage && view().context == section) {
        v.selected = std::min(view().selected, std::max(0, int(v.rows.size()) - 1));
        while (v.selected + 1 < int(v.rows.size()) &&
               v.rows[v.selected].action == "settings-heading")
            ++v.selected;
        v.top = view().top;
        v.offset = view().offset;
        view() = v;
        update();
    } else {
        if (section == "timezone") {
            time_t now = time(0);
            struct tm *gmt = gmtime(&now);
            v.offset = gmt ? gmt->tm_hour : 0;
        }
        push(v);
    }
}
void Window::showHotkeys() {
    showSettings("hotkeys");
}
void Window::chooseSetting(const std::string &key) {
    const SettingField *f = settingField(key);
    if (!f || !settingsEditing_)
        return;
    if (settingIsToggle(key)) {
        commitSetting(key, settingFlag(settingsDraft_, key) ? "0" : "1");
        return;
    }
    View v(View::Choice, u(f->label));
    v.context = "setting-choice";
    std::string current = settingValue(settingsDraft_, key);
    if (key == "network_profile") {
        std::vector<std::string> profiles;
        std::string error;
        v.rows.push_back(Row(u("По умолчанию"), "set:" + key + ":"));
        if (!loadInternetProfiles(profiles, error))
            info(u(error));
        for (size_t i = 0; i < profiles.size(); ++i) {
            v.rows.push_back(Row(u(profiles[i]), "set:" + key + ":" + profiles[i]));
            if (profiles[i] == current)
                v.selected = i + 1;
        }
    } else if (key == "local_hour") {
        time_t now = time(0) +
                     (settingNumber(settingsDraft_, "timezone") +
                      settingNumber(settingsDraft_, "daylight")) *
                         3600 +
                     settingNumber(settingsDraft_, "time_offset_minutes") * 60;
        struct tm *tmv = gmtime(&now);
        unsigned minute = tmv ? tmv->tm_min : 0;
        for (unsigned i = 0; i < 24; ++i) {
            char caption[16];
            snprintf(caption, sizeof(caption), "%u:%02u", i, minute);
            v.rows.push_back(Row(u(caption), "set:local_hour:" + num(i)));
            if (num(i) == current)
                v.selected = i;
        }
    } else if (*f->choices) {
        std::vector<std::string> values = split(f->choices, '|');
        bool found = false;
        for (size_t i = 0; i < values.size(); ++i) {
            size_t equal = values[i].find('=');
            const std::string value = values[i].substr(0, equal);
            v.rows.push_back(
                Row(u(equal == std::string::npos ? value : values[i].substr(equal + 1)),
                    "set:" + key + ":" + value));
            if (value == current) {
                v.selected = i;
                found = true;
            }
        }
        if (!found) {
            v.selected = v.rows.size();
            v.rows.push_back(
                Row(u(key == "background_kind" && current == "legacy" ? "Сохраненное изображение"
                                                                      : current),
                    "set:" + key + ":" + current));
        }
    } else {
        editKey_ = key;
        const std::string fieldKey = f->key;
        int maximum = 12;
        if (fieldKey == "host" || fieldKey == "psk" || fieldKey == "dns_server" ||
            fieldKey == "uin" || fieldKey == "lock_pin" || fieldKey == "network_profile")
            maximum = f->maximum;
        else if (fieldKey == "password")
            maximum = std::max(32, int(u(current).length()));
        else if (fieldKey == "port" || fieldKey == "media_memory_kb")
            maximum = 5;
        else if (fieldKey == "reconnect_attempts" || fieldKey == "light_seconds" ||
                 fieldKey == "caption_offset")
            maximum = 2;
        else if (fieldKey == "ping_seconds" || fieldKey == "flip_lock_minutes" ||
                 fieldKey == "server_history_count" || fieldKey == "chat_messages")
            maximum = 3;
        else if (fieldKey == "telegram_limit" || fieldKey == "max_limit" ||
                 fieldKey == "express_limit")
            maximum = 4;
        // Never truncate a value already saved by an older native release.
        maximum = std::max(maximum, int(u(current).length()));
        edit(u(f->label), "setting", current, 0, f->secret, maximum);
        return;
    }
    push(v);
}
void Window::commitSetting(const std::string &key, const std::string &value) {
    const SettingField *f = settingField(key);
    std::string error;
    const Settings &base = settingsEditing_ ? settingsDraft_ : settings_;
    bool deferredDns = key == "dns_server" && !settingFlag(base, "startup_dns");
    bool preserved = value == settingValue(settings_, key);
    if (!f || (!deferredDns && !preserved && !validateSetting(*f, value, error))) {
        info(u(error.empty() ? "Значение отсутствует в списке" : error));
        return;
    }
    if (settingsEditing_) {
        settingsDraft_.set(key, value);
        showSettings(settingsSection_);
        return;
    }
    // Compatibility for internal callers that change one implementation value.
    settings_.set(key, value);
    settingsChanged();
}
void Window::finishSettings(bool accept) {
    if (!settingsEditing_)
        return;
    std::string error;
    if (accept) {
        if (settingsSection_ == "theme" && view().context == "settings-theme" &&
            !view().rows.empty()) {
            std::string action = view().rows[view().selected].action;
            settingsDraft_.set("theme", action.substr(std::string("set:theme:").size()));
        }
        const std::vector<SettingField> &fields = settingFields();
        for (size_t i = 0; i < fields.size(); ++i) {
            const SettingField &f = fields[i];
            if (settingsSection_ != f.section ||
                settingValue(settingsDraft_, f.key) == settingValue(settings_, f.key))
                continue;
            if (std::string(f.key) == "dns_server" && !settingFlag(settingsDraft_, "startup_dns"))
                continue;
            if (!validateSetting(f, settingValue(settingsDraft_, f.key), error)) {
                info(u(error));
                return;
            }
        }
        if (settingsSection_ == "network" && !validateNetworkSettings(settingsDraft_, error)) {
            info(u(error));
            return;
        }
        if (settingsSection_ == "account") {
            unsigned count = accountCount(settingsDraft_);
            unsigned active = std::min(
                count - 1, (unsigned)std::max(0, settingsDraft_.getInt("account_index", 0)));
            for (unsigned i = 0; i < count; ++i) {
                std::string prefix = "account." + num(i) + ".";
                if (!validateSetting(*settingField("uin"), settingsDraft_.get(prefix + "uin"),
                                     error) ||
                    !validateSetting(*settingField("password"),
                                     settingsDraft_.get(prefix + "password"), error)) {
                    info(u(error));
                    return;
                }
            }
            settingsDraft_.set("uin", settingsDraft_.get("account." + num(active) + ".uin"));
            settingsDraft_.set("password",
                               settingsDraft_.get("account." + num(active) + ".password"));
        }
        if (settingFlag(settingsDraft_, "small_font") != settingFlag(settings_, "small_font"))
            settingsDraft_.setInt("font_size", settingFlag(settingsDraft_, "small_font") ? 14 : 16);
        if (settingFlag(settingsDraft_, "chat_small_font") !=
            settingFlag(settings_, "chat_small_font"))
            settingsDraft_.setInt("chat_font_size",
                                  settingFlag(settingsDraft_, "chat_small_font") ? 14 : 16);
        if (settingValue(settingsDraft_, "background_kind") !=
            settingValue(settings_, "background_kind")) {
            std::string kind = settingValue(settingsDraft_, "background_kind");
            settingsDraft_.set("background_file", kind == "builtin" ? "back.png" : "");
            if (kind == "builtin")
                settingsDraft_.set("background_mode", "center");
        }
        if (settingsSection_ == "timezone") {
            int offset = settingNumber(settingsDraft_, "local_hour") -
                         settingNumber(settingsDraft_, "timezone") -
                         settingNumber(settingsDraft_, "daylight") -
                         int(settingsDepth_ < stack_.size() ? stack_[settingsDepth_].offset : 0);
            while (offset >= 12)
                offset -= 24;
            while (offset < -12)
                offset += 24;
            settingsDraft_.setInt("time_offset_minutes",
                                  offset * 60 +
                                      settingNumber(settings_, "time_offset_minutes") % 60);
        }
        bool scope = settingValue(settingsDraft_, "host") != settingValue(settings_, "host") ||
                     settingValue(settingsDraft_, "port") != settingValue(settings_, "port") ||
                     settingValue(settingsDraft_, "uin") != settingValue(settings_, "uin");
        Settings previous = settings_;
        if (scope) {
            saveState();
            disconnectClient();
        }
        settings_ = settingsDraft_;
        if (!settings_.save(error)) {
            settings_ = previous;
            info(u(error));
            return;
        }
        if (scope)
            selectScope();
    }
    const unsigned depth = settingsDepth_;
    settingsEditing_ = false;
    settingsSection_.clear();
    while (stack_.size() > depth && stack_.size() > 1)
        stack_.pop_back();
    if (accept) {
        applySettings();
        Command settings(Command::Settings);
        settings.media = mediaSettings(settings_);
        if (connectionState_ == Event::Online)
            send(settings);
    }
    update();
}
void Window::templateMenu(bool insertion) {
    View v(View::Popup, u("Шаблоны"));
    v.context = "template-menu";
    if (insertion)
        row(v, "Назад", "template-return");
    row(v, "Новый", "template-new");
    row(v, "Удалить", "template-delete-confirm");
    row(v, "Стереть всё", "templates-clear-confirm");
    v.selected = v.rows.empty() ? 0 : int(v.rows.size()) - 1;
    push(v);
}
bool Window::activateSettings(const Row &chosen) {
    Row r = chosen;
    const std::string action = r.action;
    if (action == "settings-heading")
        return true;
    if (action == "editor-send" || action == "editor-ok") {
        finishEdit(true);
        return true;
    }
    if (action == "editor-cancel") {
        finishEdit(false);
        return true;
    }
    if (action == "settings-save") {
        finishSettings(true);
        return true;
    }
    if (action == "settings-cancel") {
        finishSettings(false);
        return true;
    }
    if (action == "accounts") {
        showSettings("account");
        return true;
    }
    if (action == "hotkeys") {
        showHotkeys();
        return true;
    }
    if (action.compare(0, 9, "settings:") == 0) {
        showSettings(action.substr(9));
        return true;
    }
    if (action.compare(0, 6, "field:") == 0) {
        chooseSetting(action.substr(6));
        return true;
    }
    if (action.compare(0, 4, "set:") == 0) {
        size_t colon = action.find(':', 4);
        if (colon != std::string::npos) {
            const std::string key = action.substr(4, colon - 4), value = action.substr(colon + 1);
            if (view().context != "settings-theme")
                back();
            commitSetting(key, value);
        }
        return true;
    }
    if (action == "settings-commands") {
        View v(View::Popup, u("Настройки"));
        v.context = "settings-commands";
        row(v, "Сохр.", "settings-save");
        if (settingsSection_ == "account") {
            if (accountCount(settingsDraft_) < 3)
                row(v, "Новая учетная запись", "account-add");
            if (accountCount(settingsDraft_) > 1)
                row(v, "Удалить учетную запись", "account-delete-list");
        } else if (settingsSection_ == "hotkeys")
            row(v, "Выбрать", "settings-choose");
        row(v, "Назад", "settings-cancel");
        push(v);
        return true;
    }
    if (action == "settings-choose") {
        back();
        if (!view().rows.empty())
            activate(view().rows[view().selected]);
        return true;
    }
    if (action == "account-add") {
        if (!settingsEditing_)
            showSettings("account");
        unsigned count = accountCount(settingsDraft_);
        if (count >= 3) {
            info(u("Не больше трех учетных записей"));
            return true;
        }
        settingsDraft_.set("account." + num(count) + ".uin", "");
        settingsDraft_.set("account." + num(count) + ".password", "");
        settingsDraft_.setInt("accounts", count + 1);
        while (stack_.size() > settingsDepth_ + 1)
            stack_.pop_back();
        showSettings("account");
        return true;
    }
    if (action == "account-choose" || action == "account-delete-list" ||
        action == "account-delete-confirm") {
        if (!settingsEditing_)
            showSettings("account");
        View v(View::Choice, u(action == "account-choose" ? "Учетная запись" : "Удалить"));
        v.context = "account-choice";
        unsigned count = accountCount(settingsDraft_);
        for (unsigned i = 0; i < count; ++i) {
            std::string value = settingsDraft_.get("account." + num(i) + ".uin");
            v.rows.push_back(
                Row(u(value.empty() ? "---" : value),
                    action == "account-choose" ? "account-draft-select" : "account-draft-delete", 0,
                    i));
        }
        v.selected =
            std::min(count - 1, (unsigned)std::max(0, settingsDraft_.getInt("account_index", 0)));
        push(v);
        return true;
    }
    if (action == "account-draft-select" || action == "account-draft-delete") {
        if (action == "account-draft-select")
            settingsDraft_.setInt("account_index", r.value);
        else {
            unsigned count = accountCount(settingsDraft_);
            if (count <= 1 || r.value >= count)
                return true;
            for (unsigned i = r.value; i + 1 < count; ++i) {
                settingsDraft_.set("account." + num(i) + ".uin",
                                   settingsDraft_.get("account." + num(i + 1) + ".uin"));
                settingsDraft_.set("account." + num(i) + ".password",
                                   settingsDraft_.get("account." + num(i + 1) + ".password"));
            }
            settingsDraft_.set("account." + num(count - 1) + ".uin", "");
            settingsDraft_.set("account." + num(count - 1) + ".password", "");
            unsigned active = std::max(0, settingsDraft_.getInt("account_index", 0));
            if (active > r.value)
                --active;
            settingsDraft_.setInt("accounts", count - 1);
            settingsDraft_.setInt("account_index", std::min(count - 2, active));
        }
        back();
        showSettings("account");
        return true;
    }
    if (action.compare(0, 7, "hotkey:") == 0) {
        if (!settingsEditing_)
            showHotkeys();
        View v(View::Choice, u("Список действий"));
        v.context = "hotkey-choice";
        const std::string key = action.substr(7),
                          current = settingsDraft_.get("hotkey." + key, javaHotkeyDefault(key));
        const std::vector<HotkeySetting> &actions = javaHotkeyActions();
        bool found = false;
        for (size_t i = 0; i < actions.size(); ++i) {
            v.rows.push_back(
                Row(u(actions[i].label), "hotkey-set:" + key + ":" + actions[i].action));
            if (current == actions[i].action) {
                v.selected = i;
                found = true;
            }
        }
        if (!found) {
            v.selected = v.rows.size();
            v.rows.push_back(Row(u(javaHotkeyLabel(current)), "hotkey-set:" + key + ":" + current));
        }
        push(v);
        return true;
    }
    if (action.compare(0, 11, "hotkey-set:") == 0) {
        size_t colon = action.find(':', 11);
        if (colon != std::string::npos)
            settingsDraft_.set("hotkey." + action.substr(11, colon - 11), action.substr(colon + 1));
        back();
        showHotkeys();
        return true;
    }
    if (action == "templates") {
        showTemplates(false);
        return true;
    }
    if (action == "template-menu") {
        templateMenu(view().context == "insert");
        return true;
    }
    if (action == "template-return") {
        while (stack_.size() > 1 && view().kind != View::Templates)
            stack_.pop_back();
        if (view().kind == View::Templates)
            back();
        return true;
    }
    if (action == "template-new") {
        if (view().context == "template-menu")
            back();
        edit(u("Новый шаблон"), "template-edit", "", 0, false, 1000);
        editKey_ = "new";
        return true;
    }
    if (action == "template") {
        if (view().context != "insert")
            return true;
        std::vector<std::string> templates = storage_->templates();
        if (r.value < templates.size())
            editor_->insert(u(templates[r.value]));
        while (stack_.size() > editDepth_)
            stack_.pop_back();
        editor_->show();
        editor_->setFocus();
        update();
        return true;
    }
    if (action == "template-delete-confirm" || action == "templates-clear-confirm") {
        if (view().context == "template-menu")
            back();
        if (action == "template-delete-confirm" && view().rows.empty())
            return true;
        unsigned index = view().selected;
        QString question = u("Стереть всё?");
        if (action == "template-delete-confirm")
            question = u("Удалить") + " '" + view().rows[index].text + "' ?";
        View v(View::Menu, u("Внимание"));
        v.context = "template-confirm";
        v.details = question;
        row(v, "Да", action == "template-delete-confirm" ? "template-delete" : "templates-clear",
            index);
        row(v, "Нет", "back");
        push(v);
        return true;
    }
    if (action == "template-delete" || action == "templates-clear") {
        std::vector<std::string> templates = storage_->templates();
        if (action == "templates-clear")
            templates.clear();
        else if (r.value < templates.size())
            templates.erase(templates.begin() + r.value);
        std::string error;
        if (!storage_->saveTemplates(templates, error)) {
            info(u(error));
            return true;
        }
        while (stack_.size() > 1 && view().kind != View::Templates)
            stack_.pop_back();
        bool insertion = view().kind == View::Templates && view().context == "insert";
        if (view().kind == View::Templates)
            stack_.pop_back();
        showTemplates(insertion);
        return true;
    }
    if (action == "reset-confirm") {
        View v(View::Menu, u("Сброс настроек"));
        v.context = "settings-reset";
        v.details = u("Вы действительно хотите сбросить все настройки (учетные записи, историю, "
                      "настройки и т.д.)? Приложение будет закрыто!");
        row(v, "* Нет", "back");
        row(v, "* Да", "reset");
        push(v);
        return true;
    }
    if (action == "reset") {
        if (!client_.stopAndWait()) {
            info(u("Не удалось остановить соединение. Повторите сброс."));
            return true;
        }
        std::string error;
        if (!storage_->resetAll(error)) {
            info(u(error));
            return true;
        }
        Settings previous = settings_;
        settings_.reset();
        const std::vector<SettingField> &fields = settingFields();
        for (size_t i = 0; i < fields.size(); ++i)
            settings_.set(fields[i].key, fields[i].initial);
        settings_.set("java_ui_version", "1");
        if (!settings_.save(error)) {
            settings_ = previous;
            info(u(error));
            return true;
        }
        // The destructor must not restore the old roster/draft after reset.
        resetComplete_ = true;
        qApp->quit();
        return true;
    }
    return false;
}
} // namespace tmm
