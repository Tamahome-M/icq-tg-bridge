#include "window.h"
#include "storage.h"
#include "ui_settings.h"
#include "ui_language.h"
#include <ZMultiLineEdit.h>
#include <qapplication.h>
#include <qclipboard.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
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
void Window::edit(const QString &title, const std::string &action, const std::string &text,
                  uint32_t uin, bool secret, int maximum) {
    saveDraft();
    editAction_ = action;
    editUin_ = uin;
    editTitle_ = title;
    editDepth_ = stack_.size();
    editor_->setMaxLength(maximum);
    editor_->setEchoMode(secret ? ZMultiLineEdit::Password : ZMultiLineEdit::Normal);
    editor_->blockSignals(true);
    editor_->setText(u(text));
    editor_->blockSignals(false);
    editor_->setGeometry(2, 29, width() - 4,
                         settingFlag(settings_, "full_editor") ? height() - 56 : height() / 2);
    editor_->show();
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
    QString value = editor_->text();
    if (settingFlag(settings_, "initial_caps") && value.length() == 1 && value != value.upper()) {
        editor_->setText(value.upper());
        editor_->setCursorPosition(0, 1);
        return;
    }
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
    if (accept && action == "message") {
        if (value.empty()) {
            info(u("Введите сообщение"));
            return;
        }
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
        std::string error;
        storage_->saveDraft(id, "", error);
    }
    if (accept && action == "setting") {
        const SettingField *f = settingField(key);
        std::string error;
        if (!f || !validateSetting(*f, value, error)) {
            info(u(error));
            return;
        }
    }
    editor_->hide();
    editAction_.clear();
    editKey_.clear();
    while (stack_.size() > editDepth_)
        stack_.pop_back();
    setFocus();
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
        if (key == "new") {
            if (templates.size() >= 100) {
                info(u("Слишком много шаблонов"));
                return;
            }
            templates.push_back(value);
        } else {
            unsigned index = atoi(key.c_str());
            if (index < templates.size())
                templates[index] = value;
        }
        std::string error;
        if (!storage_->saveTemplates(templates, error))
            info(u(error));
        while (stack_.size() > 1 && view().kind != View::Templates)
            stack_.pop_back();
        if (view().kind == View::Templates)
            stack_.pop_back();
        showTemplates(false);
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
    editor_->hide();
    View v(View::Menu, u("Редактор"));
    v.context = "editor-menu";
    v.rows.push_back(Row(u("Копировать выделенное"), "editor-copy"));
    v.rows.push_back(Row(u("Вырезать выделенное"), "editor-cut"));
    v.rows.push_back(Row(u("Копировать всё"), "editor-copy-all"));
    v.rows.push_back(Row(u("Вставить"), "editor-paste"));
    v.rows.push_back(Row(u("Очистить"), "editor-clear"));
    v.rows.push_back(Row(u("Шаблоны"), "template-insert-list"));
    v.rows.push_back(Row(u("Смайлы"), "smileys"));
    v.rows.push_back(Row(u("Вернуться в редактор"), "back"));
    v.rows.push_back(Row(u("Закрыть редактор"), "editor-back"));
    push(v);
}
void Window::showTemplates(bool insert) {
    View v(View::Templates, u("Шаблоны"));
    v.context = insert ? "insert" : "manage";
    std::vector<std::string> templates = storage_->templates();
    for (size_t i = 0; i < templates.size(); ++i)
        v.rows.push_back(Row(u(templates[i]), "template", 0, i));
    if (!insert)
        v.rows.push_back(Row(u("Добавить шаблон"), "template-new"));
    push(v);
}
} // namespace tmm
