#include "window.h"
#include "storage.h"
#include "ui_settings.h"
#include "ui_language.h"
#include "input_indicator.h"
#include <ZMultiLineEdit.h>
#include <ZKbInputField.h>
#include <qapplication.h>
#include <qclipboard.h>
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
void Window::layoutEditor() {
    if (!editor_ || !inputIndicator_)
        return;
    const int statusHeight = std::max(24, inputIndicator_->sizeHint().height());
    const bool hideTitle = editAction_ == "message" && settingFlag(settings_, "full_editor");
    inputIndicator_->setGeometry(2, hideTitle ? 1 : 29, width() - 4, statusHeight);
    // Motorola's skin may enforce a larger minimum than sizeHint().
    const int top = inputIndicator_->geometry().bottom() + 1;
    const int available = std::max(1, height() - top - 27);
    editor_->setGeometry(2, top, width() - 4, available);
}
void Window::edit(const QString &title, const std::string &action, const std::string &text,
                  uint32_t uin, bool secret, int maximum) {
    // A field may already be active (including during native startup/dialog
    // transitions). Merely calling setModalEditing(true) again does nothing,
    // leaving its cached UI interface and password rules from that activation.
    // End editing before changing the field and reactivate it below.
    editor_->setModalEditing(false);
    editor_->clearFocus();
    saveDraft();
    if (action == "template-edit" && !editAction_.empty()) {
        EditorState parent;
        parent.title = editTitle_;
        parent.text = editor_->text();
        parent.action = editAction_;
        parent.key = editKey_;
        parent.uin = editUin_;
        parent.depth = editDepth_;
        parent.secret = editSecret_;
        parent.maximum = editor_->maxLength();
        editor_->cursorPosition(&parent.cursorParagraph, &parent.cursorIndex);
        editorParents_.push_back(parent);
    }
    editAction_ = action;
    editUin_ = uin;
    editTitle_ = title;
    if (action == "message") {
        ContactRecord *receiver = contact(uin);
        if (receiver)
            editTitle_ = u(receiver->name) + u(" - Сообщение");
        maximum = std::max(2000, int(u(text).length()));
    }
    editDepth_ = stack_.size();
    editSecret_ = secret;
    ZKbInputField *field = editor_->getInputField();
    const SettingField *setting = action == "setting" ? settingField(editKey_) : 0;
    const std::string fieldKey = setting ? setting->key : "";
    const bool numeric = action == "add-contact" || fieldKey == "uin" || fieldKey == "lock_pin" ||
                         (setting && setting->maximum && !setting->secret && fieldKey != "host" &&
                          fieldKey != "dns_server" && fieldKey != "network_profile" &&
                          fieldKey != "background_file");
    field->setType(
        numeric
            ? (secret ? ZKbInputField::FIELD_TYPE_NUMPASSWORD : ZKbInputField::FIELD_TYPE_NUMERIC)
            : (secret ? ZKbInputField::FIELD_TYPE_PASSWORD : ZKbInputField::FIELD_TYPE_REGULAR));
    field->setOptions(secret ? ZKbInputField::FIELD_OPTION_DISABLE_COMPLETION |
                                   ZKbInputField::FIELD_OPTION_DISABLE_UAD |
                                   ZKbInputField::FIELD_OPTION_DEFAULT_LOWER_CASE
                             : (action == "message" && !settingFlag(settings_, "initial_caps")
                                    ? ZKbInputField::FIELD_OPTION_DEFAULT_LOWER_CASE
                                    : 0));
    editor_->setMaxLength(maximum);
    editor_->setEchoMode(secret ? ZMultiLineEdit::Password : ZMultiLineEdit::Normal);
    editor_->blockSignals(true);
    editor_->setText(u(text));
    editor_->blockSignals(false);
    layoutEditor();
    editor_->show();
    // Enter native editing now, so the language/case is known before typing.
    // Mere focus leaves Motorola's input filter inactive until the first key.
    editor_->setModalEditing(true);
    editor_->setFocus();
    update();
}
void Window::saveDraft() {
    if (editor_ && editAction_ == "message" && editUin_) {
        std::string error;
        if (!storage_->saveDraft(editUin_, std::string(editor_->text().utf8()), error))
            note(error);
    }
}
void Window::editorChanged() {
    if (editAction_ != "message" || !editUin_ || locked_)
        return;
    unsigned long t = (unsigned long)time(0);
    if (t - typingSentAt_ < 5)
        return;
    typingSentAt_ = t;
    Command c(Command::Typing);
    c.uin = editUin_;
    c.flag = !editor_->text().isEmpty();
    client_.submit(c);
}
void Window::finishEdit(bool accept) {
    if (editAction_.empty())
        return;
    std::string value(editor_->text().utf8()), action = editAction_, key = editKey_;
    uint32_t id = editUin_;
    if (!accept) {
        saveDraft();
    }
    if (accept && action == "message" && !value.empty()) {
        Command c(Command::SendMessage);
        c.uin = id;
        c.text = value;
        c.requestId = client_.nextRequestId();
        c.cookie = ((uint64_t)time(0) << 32) | c.requestId;
        if (!send(c))
            return;
        MessageRecord m;
        m.uin = id;
        m.outgoing = true;
        m.cookie = c.cookie;
        m.text = value;
        m.time = time(0);
        incoming(m);
    }
    if (accept && action == "message") {
        std::string error;
        if (!storage_->saveDraft(id, "", error))
            note(error);
    }
    if (accept && action == "setting") {
        const SettingField *f = settingField(key);
        std::string error;
        const Settings &draft = settingsEditing_ ? settingsDraft_ : settings_;
        const bool deferredDns = key == "dns_server" && !settingFlag(draft, "startup_dns");
        if (!f || (!deferredDns && value != settingValue(settings_, key) &&
                   !validateSetting(*f, value, error))) {
            info(u(error));
            return;
        }
    }
    editor_->hide();
    editSecret_ = false;
    editAction_.clear();
    editKey_.clear();
    while (stack_.size() > editDepth_)
        stack_.pop_back();
    setFocus();
    if (action == "template-edit" && !editorParents_.empty()) {
        const EditorState parent = editorParents_.back();
        editorParents_.pop_back();
        editKey_ = parent.key;
        edit(parent.title, parent.action, std::string(parent.text.utf8()), parent.uin,
             parent.secret, parent.maximum);
        editDepth_ = parent.depth;
        editor_->setCursorPosition(parent.cursorParagraph, parent.cursorIndex);
        // The original message stays suspended until the template list closes.
        editor_->hide();
        setFocus();
    }
    if (action == "message") {
        Command c(Command::Typing);
        c.uin = id;
        c.flag = false;
        client_.submit(c);
        if (accept) {
            while (stack_.size() > 1 && view().kind != View::Chat)
                stack_.pop_back();
            if (view().kind != View::Chat || view().uin != id)
                openChat(id);
            else
                rebuildChat();
        }
    }
    if (!accept) {
        update();
        return;
    }
    if (action == "setting") {
        commitSetting(key, value);
        return;
    }
    if (action == "history-search") {
        while (stack_.size() > 1 && view().kind != View::History)
            stack_.pop_back();
        if (view().kind == View::History) {
            view().directory = value;
            view().selected = view().top = 0;
            showHistory(view());
        }
        update();
        return;
    }
    if (action == "search") {
        View v(View::Menu, u("Результаты поиска"));
        v.context = "search";
        v.directory = value;
        push(v);
        search(false, true);
        return;
    }
    if (action == "add-contact") {
        char *end = 0;
        unsigned long n = strtoul(value.c_str(), &end, 10);
        if (value.empty() || *end || n == 0 || n > 0xffffffffUL) {
            info(u("Некорректный UIN"));
            return;
        }
        Command c(Command::AddContact);
        c.uin = n;
        c.text = value;
        send(c);
        return;
    }
    if (action == "add-group" || action == "group-rename" || action == "rename-contact" ||
        action == "auth-request" || action == "auth-deny") {
        Command c(action == "add-group"        ? Command::AddGroup
                  : action == "group-rename"   ? Command::RenameGroup
                  : action == "rename-contact" ? Command::RenameContact
                  : action == "auth-request"   ? Command::RequestAuthorization
                                               : Command::DenyAuthorization);
        c.uin = id;
        c.text = value;
        if (action == "group-rename")
            c.groupId = atoi(key.c_str());
        ContactRecord *contactItem = contact(id);
        if (contactItem) {
            c.itemId = contactItem->itemId;
            if (action != "group-rename")
                c.groupId = contactItem->groupId;
        }
        send(c);
        return;
    }
    if (action == "template-edit") {
        std::vector<std::string> templates = storage_->templates();
        value = std::string(u(value).stripWhiteSpace().utf8());
        if (key == "new" && !value.empty()) {
            if (templates.size() >= 100) {
                info(u("Слишком много шаблонов"));
                return;
            }
            templates.push_back(value);
        } else if (key != "new") {
            unsigned index = atoi(key.c_str());
            if (index < templates.size())
                templates[index] = value;
        }
        std::string error;
        if (!storage_->saveTemplates(templates, error))
            info(u(error));
        while (stack_.size() > 1 && view().kind != View::Templates)
            stack_.pop_back();
        const bool insertion = view().kind == View::Templates && view().context == "insert";
        if (view().kind == View::Templates)
            stack_.pop_back();
        showTemplates(insertion);
        return;
    }
    if (action == "account-add") {
        const SettingField *f = settingField("uin");
        std::string error;
        if (value.empty() || !validateSetting(*f, value, error)) {
            info(u("Некорректный UIN"));
            return;
        }
        int n = settings_.getInt("accounts", 1);
        settings_.set("account." + num(n) + ".uin", value);
        settings_.set("account." + num(n) + ".password", "");
        settings_.setInt("accounts", n + 1);
        switchAccount(n);
        showSettings("account");
        editKey_ = "password";
        edit(u("Пароль новой учётной записи"), "setting", "", 0, true, 64);
        return;
    }
    update();
}
void Window::editorMenu() {
    if (editAction_.empty())
        return;
    saveDraft();
    View v(View::Popup, u("Редактор"));
    v.context = "editor-menu";
    const bool message = editAction_ == "message";
    v.rows.push_back(Row(u(message ? "Отправить" : "ОК"), message ? "editor-send" : "editor-ok"));
    if (editSecret_)
        v.rows.push_back(Row(u(editor_->echoMode() == ZMultiLineEdit::Password ? "Показать пароль"
                                                                               : "Скрыть пароль"),
                             "editor-secret"));
    if (!editSecret_ && !editor_->text().isEmpty()) {
        v.rows.push_back(Row(u("Копировать выделенное"), "editor-copy"));
        v.rows.push_back(Row(u("Вырезать выделенное"), "editor-cut"));
        v.rows.push_back(Row(u("Копировать всё"), "editor-copy-all"));
    }
    // Reading QClipboard merely to decide whether to show Paste enters a
    // nested native event loop when another process owns the clipboard.
    // Keep the standard Motorola command and read only on an explicit Paste.
    v.rows.push_back(Row(u("Вставить"), "editor-paste"));
    if (message) {
        v.rows.push_back(Row(u("Смайлы"), "smileys"));
        v.rows.push_back(Row(u("Шаблоны"), "template-insert-list"));
        v.rows.push_back(Row(u("Стереть"), "editor-clear"));
    }
    v.rows.push_back(Row(u(message ? "Отмена" : "Назад"), "editor-cancel"));
    push(v);
}
void Window::showTemplates(bool insert) {
    View v(View::Templates, u("Шаблоны"));
    v.context = insert ? "insert" : "manage";
    std::vector<std::string> templates = storage_->templates();
    for (size_t i = 0; i < templates.size(); ++i)
        v.rows.push_back(Row(u(templates[i]), "template", 0, i));
    push(v);
}
} // namespace tmm
