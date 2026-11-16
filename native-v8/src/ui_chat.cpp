#include "window.h"
#include "storage.h"
#include "ui_settings.h"
#include "ui_language.h"
#include <ZMultiLineEdit.h>
#include <qapplication.h>
#include <qimage.h>
#include <qevent.h>
#include <sys/stat.h>
#include <time.h>
#include <stdio.h>
#include <unistd.h>
#include <stdlib.h>
#include <algorithm>
namespace tmm {
static QString u(const char *s) {
    return uiText(s);
}
static QString u(const std::string &s) {
    return QString::fromUtf8(s.c_str());
}
static void replaceText(QString &text, const char *from, const QString &to) {
    int at = 0;
    QString source = QString::fromLatin1(from);
    while ((at = text.find(source, at)) >= 0) {
        text.replace(at, source.length(), to);
        at += to.length();
    }
}
static unsigned long now() {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (unsigned long)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}
static std::string num(unsigned n) {
    char b[32];
    snprintf(b, sizeof(b), "%u", n);
    return b;
}
static bool online(uint32_t s) {
    return s != 0xffffffffU && !(s & 0x100);
}
bool Window::selectScope() {
    capture_.cancel();
    player_.stop();
    if (!managedMediaPath_.empty()) {
        unlink(managedMediaPath_.c_str());
        managedMediaPath_.clear();
    }
    if (!capturePath_.empty()) {
        unlink(capturePath_.c_str());
        capturePath_.clear();
    }
    for (std::map<uint32_t, std::string>::iterator i = captureUploads_.begin();
         i != captureUploads_.end(); ++i)
        unlink(i->second.c_str());
    captureUploads_.clear();
    loadedMediaReady_ = false;
    savedMediaPurpose_.clear();
    playPath_.clear();
    pickUin_ = captureUin_ = 0;
    pending_.clear();
    pendingUin_.clear();
    quoteId_.clear();
    quoteText_.clear();
    quoteUin_ = 0;
    contacts_.clear();
    chats_.clear();
    quiet_.clear();
    videoToken_.clear();
    videoUin_ = videoSegment_ = 0;
    picture_ = QPixmap();
    std::string e;
    std::string account = settingValue(settings_, "uin");
    const SettingField *f = settingField("uin");
    bool valid = f && validateSetting(*f, account, e);
    uint32_t accountUin = valid && !account.empty() ? (uint32_t)strtoul(account.c_str(), 0, 10) : 0;
    if (!storage_->setAccount(settingValue(settings_, "host"), settingNumber(settings_, "port"),
                              accountUin, e)) {
        if (!valid || (!account.empty() && !accountUin))
            info(u("Некорректный UIN"));
        else if (!account.empty())
            info(u(e));
        return false;
    }
    storage_->loadRoster(contacts_);
    for (size_t i = 0; i < contacts_.size(); ++i)
        contacts_[i].status = 0xffffffffU;
    quiet_ = storage_->quietChats();
    return true;
}
void Window::connectClient() {
    std::string account = settingValue(settings_, "uin");
    std::string accountError;
    const SettingField *accountField = settingField("uin");
    if (account.empty() || !accountField ||
        !validateSetting(*accountField, account, accountError) ||
        settingValue(settings_, "password").empty()) {
        info(u("Заполните UIN и пароль в настройках"));
        showSettings("account");
        return;
    }
    if (connectionState_ == Event::Connecting || connectionState_ == Event::Online)
        return;
    if (storage_->accountDir().empty() && !selectScope())
        return;
    manualDisconnect_ = false;
    ClientConfig cfg = clientSettings(settings_, storage_->accountDir() + "/cache", quiet_);
    client_.configure(cfg);
    client_.start();
    generation_ = client_.sessionGeneration();
    connectionState_ = Event::Connecting;
    note("Подключение к " + cfg.host);
    info(u("Подключение… В меню можно отменить"));
    update();
}
void Window::disconnectClient() {
    manualDisconnect_ = true;
    client_.stop();
    generation_ = 0;
    pending_.clear();
    pendingUin_.clear();
    for (size_t i = 0; i < stack_.size(); ++i)
        stack_[i].request = 0;
    connectionState_ = Event::Disconnected;
    note("Отключено вручную");
    update();
}
bool Window::send(Command c) {
    if (!c.requestId)
        c.requestId = client_.nextRequestId();
    if (!client_.submit(c)) {
        pending_.erase(c.requestId);
        pendingUin_.erase(c.requestId);
        info(u("Нет соединения или очередь запросов заполнена"));
        return false;
    }
    if (c.type != Command::Typing && c.type != Command::CancelRequest &&
        pending_.find(c.requestId) == pending_.end())
        pending_[c.requestId] = "command";
    return true;
}
void Window::eventsReady() {
    std::vector<Event> events;
    client_.drainEvents(events);
    for (size_t i = 0; i < events.size(); ++i)
        if (events[i].generation == generation_)
            consume(events[i]);
        else if (events[i].type == Event::Media && !events[i].path.empty())
            unlink(events[i].path.c_str());
}
void Window::consume(const Event &e) {
    if (e.type == Event::State) {
        unsigned before = connectionState_;
        connectionState_ = e.state;
        note(e.text);
        if (e.state == Event::Disconnected || e.state == Event::Reconnecting) {
            pending_.clear();
            pendingUin_.clear();
            for (size_t i = 0; i < stack_.size(); ++i)
                stack_[i].request = 0;
            for (size_t i = 0; i < contacts_.size(); ++i)
                contacts_[i].status = 0xffffffffU;
            if (before == Event::Online && !manualDisconnect_ && !silent_ &&
                settingFlag(settings_, "disconnect_sound"))
                platform_.notifyDisconnected(settingNumber(settings_, "disconnect_volume"));
        }
        if (view().kind == View::Roster)
            rebuildRoster();
        update();
        return;
    }
    if (e.type == Event::Roster) {
        if (e.flag) {
            for (size_t i = 0; i < contacts_.size(); ++i) {
                contacts_[i].inRoster = false;
                contacts_[i].deleted = true;
                contacts_[i].privacy = 0;
                contacts_[i].status = 0xffffffffU;
            }
        }
        for (size_t i = 0; i < e.contacts.size(); ++i) {
            const ContactRecord &r = e.contacts[i];
            if (r.type == 2 || r.type == 3 || r.type == 14) {
                ContactRecord *c = contact(r.uin);
                if (c) {
                    unsigned mask = r.type == 2 ? 1 : r.type == 3 ? 2 : 4;
                    if (r.deleted)
                        c->privacy &= ~mask;
                    else
                        c->privacy |= mask;
                }
                continue;
            }
            size_t at = 0;
            while (at < contacts_.size() &&
                   !(r.type == 1 ? contacts_[at].type == 1 && contacts_[at].groupId == r.groupId
                                 : contacts_[at].type == 0 && contacts_[at].uin == r.uin))
                ++at;
            if (at == contacts_.size()) {
                if (!r.deleted)
                    contacts_.push_back(r);
            } else if (r.deleted) {
                contacts_[at].deleted = true;
                contacts_[at].inRoster = false;
            } else {
                unsigned privacy = contacts_[at].privacy;
                uint32_t status = contacts_[at].status;
                contacts_[at] = r;
                contacts_[at].privacy = privacy;
                contacts_[at].status = status;
            }
        }
        for (size_t i = 0; i < contacts_.size(); ++i)
            if (contacts_[i].type == 0) {
                for (size_t j = 0; j < contacts_.size(); ++j)
                    if (contacts_[j].type == 1 && contacts_[j].groupId == contacts_[i].groupId) {
                        contacts_[i].group = contacts_[j].name;
                        break;
                    }
            }
        std::string error;
        if (!storage_->saveRoster(contacts_, error))
            note(error);
        if (view().kind == View::Roster)
            rebuildRoster();
        return;
    }
    if (e.type == Event::Presence) {
        ContactRecord *c = contact(e.uin);
        if (c) {
            c->status = e.status;
            if (!e.contacts.empty())
                c->avatarHash = e.contacts[0].avatarHash;
        }
        if (view().kind == View::Roster)
            rebuildRoster();
        return;
    }
    if (e.type == Event::Message) {
        if (e.requestId) {
            pending_.erase(e.requestId);
            pendingUin_.erase(e.requestId);
        }
        for (size_t i = 0; i < e.messages.size(); ++i)
            incoming(e.messages[i]);
        return;
    }
    if (e.type == Event::Receipt) {
        std::map<uint32_t, ChatState>::iterator chat = chats_.find(e.uin);
        if (chat != chats_.end()) {
            for (size_t j = 0; j < chat->second.messages.size(); ++j) {
                MessageRecord &m = chat->second.messages[j];
                if (m.cookie == e.cookie && m.outgoing) {
                    m.delivery = std::max(m.delivery, e.delivery);
                    if (!e.nativeId.empty())
                        m.nativeId = e.nativeId;
                }
            }
        }
        std::string error;
        if (e.uin && !storage_->updateReceipt(e.uin, e.cookie, e.delivery, e.nativeId, error))
            note(error);
        if (view().kind == View::Chat)
            rebuildChat();
        return;
    }
    if (e.type == Event::Typing) {
        if (chats_.find(e.uin) != chats_.end())
            chats_[e.uin].typingUntil = e.flag ? now() + 10000 : 0;
        if (e.flag && std::find(quiet_.begin(), quiet_.end(), e.uin) == quiet_.end() && !silent_ &&
            now() - startedAt_ > 60000 && !settingValue(settings_, "typing_sound").empty())
            platform_.notifyMessage(u(settingValue(settings_, "typing_sound") == "tone"
                                          ? "tone"
                                          : "sounds/" + settingValue(settings_, "typing_sound")),
                                    settingNumber(settings_, "typing_volume"), 0);
        update();
        return;
    }
    if (e.type == Event::History) {
        for (size_t v = 0; v < stack_.size(); ++v) {
            if (stack_[v].request != e.requestId)
                continue;
            View &target = stack_[v];
            target.request = 0;
            target.more = e.more;
            target.offset = e.offset;
            target.messages.insert(target.messages.end(), e.messages.begin(), e.messages.end());
            while (target.messages.size() > 200) {
                target.messages.erase(target.messages.begin());
                if (target.selected > 0)
                    --target.selected;
            }
            showHistory(target);
        }
        if (pending_[e.requestId] == "last") {
            for (size_t i = 0; i < e.messages.size(); ++i) {
                MessageRecord m = e.messages[i];
                m.silent = true;
                incoming(m);
            }
        }
        pending_.erase(e.requestId);
        pendingUin_.erase(e.requestId);
        update();
        return;
    }
    if (e.type == Event::Chats) {
        showResults(e);
        pending_.erase(e.requestId);
        return;
    }
    if (e.type == Event::ContactInfo) {
        if (!e.contacts.empty()) {
            for (size_t i = 0; i < e.contacts.size(); ++i) {
                ContactRecord *c = contact(e.contacts[i].uin);
                if (c) {
                    if (!e.contacts[i].name.empty())
                        c->name = e.contacts[i].name;
                } else
                    contacts_.push_back(e.contacts[i]);
            }
        }
        if (pending_[e.requestId] == "info")
            showInfo(e);
        pending_.erase(e.requestId);
        if (view().kind == View::Roster)
            rebuildRoster();
        return;
    }
    if (e.type == Event::Progress) {
        if (pending_.find(e.requestId) != pending_.end())
            info(u("Передано ") + QString::number((unsigned long)e.bytes) + " / " +
                 QString::number((unsigned long)e.total));
        return;
    }
    if (e.type == Event::Media) {
        if (pending_.find(e.requestId) != pending_.end()) {
            if (view().context == "transfer" && view().request == e.requestId) {
                view().request = 0;
                stack_.pop_back();
            }
            showMedia(e);
            pending_.erase(e.requestId);
            pendingUin_.erase(e.requestId);
        } else if (!e.path.empty())
            unlink(e.path.c_str());
        return;
    }
    if (e.type == Event::QuoteResult || e.type == Event::CommandResult) {
        pending_.erase(e.requestId);
        pendingUin_.erase(e.requestId);
        if (captureUploads_.find(e.requestId) != captureUploads_.end()) {
            if (e.flag)
                unlink(captureUploads_[e.requestId].c_str());
            else
                capturePath_ = captureUploads_[e.requestId];
            captureUploads_.erase(e.requestId);
        }
        for (size_t i = 0; i < stack_.size(); ++i)
            if (stack_[i].request == e.requestId)
                stack_[i].request = 0;
        if (view().context == "transfer" && view().request == 0)
            back();
        info(u(e.text.empty() ? (e.flag ? "Готово" : "Операция не выполнена") : e.text));
        return;
    }
    if (e.type == Event::Error) {
        if (e.requestId && pending_.find(e.requestId) == pending_.end())
            return;
        if (captureUploads_.find(e.requestId) != captureUploads_.end()) {
            capturePath_ = captureUploads_[e.requestId];
            captureUploads_.erase(e.requestId);
        }
        note(e.text);
        for (size_t i = 0; i < stack_.size(); ++i)
            if (stack_[i].request == e.requestId)
                stack_[i].request = 0;
        pending_.erase(e.requestId);
        pendingUin_.erase(e.requestId);
        info(u(e.text));
        return;
    }
}
void Window::incoming(const MessageRecord &m) {
    ChatState &chat = chats_[m.uin];
    chat.stamp = now();
    if (!chat.loaded) {
        storage_->loadHistory(m.uin, chat.messages, settingNumber(settings_, "chat_messages"));
        chat.loaded = true;
    }
    for (size_t i = 0; i < chat.messages.size(); ++i) {
        const MessageRecord &previous = chat.messages[i];
        // A bridge message can be split into multiple ICBMs sharing nativeId.
        // Distinct nonzero cookies are distinct pieces, even for repeated text.
        bool duplicate = m.cookie && previous.cookie
                             ? m.cookie == previous.cookie
                             : !m.nativeId.empty() && previous.nativeId == m.nativeId &&
                                   previous.text == m.text && previous.kind == m.kind &&
                                   previous.token == m.token;
        if (duplicate)
            return;
    }
    chat.messages.push_back(m);
    unsigned cap = std::max(1, settingNumber(settings_, "chat_messages"));
    while (chat.messages.size() > cap)
        chat.messages.erase(chat.messages.begin());
    std::string error;
    if (settingNumber(settings_, "history_count") > 0 && !storage_->appendHistory(m.uin, m, error))
        note(error);
    if (!contact(m.uin)) {
        ContactRecord c;
        c.uin = m.uin;
        c.name = m.senderName.empty() ? num(m.uin) : m.senderName;
        contacts_.push_back(c);
        Command request(Command::ContactInfo);
        request.uin = m.uin;
        request.requestId = client_.nextRequestId();
        pending_[request.requestId] = "identity";
        send(request);
    }
    bool visible =
        !locked_ && !closed_ && isVisible() && view().kind == View::Chat && view().uin == m.uin;
    if (!m.outgoing && !visible)
        ++chat.unread;
    if (!m.outgoing)
        notify(m);
    if (view().kind == View::Chat && view().uin == m.uin)
        rebuildChat();
    if (view().kind == View::Roster)
        rebuildRoster();
    trimChats();
    update();
}
void Window::notify(const MessageRecord &m) {
    if (m.silent || std::find(quiet_.begin(), quiet_.end(), m.uin) != quiet_.end() || silent_ ||
        now() - startedAt_ < 60000)
        return;
    unsigned long ms = now();
    if (lastAlert_ && ms - lastAlert_ < 1500)
        return;
    lastAlert_ = ms;
    bool quietProfile = locked_ || closed_;
    std::string sound = settingValue(settings_, quietProfile ? "sound_locked" : "sound_unlocked");
    int volume = settingNumber(settings_, quietProfile ? "volume_locked" : "volume_unlocked");
    int vibration =
        settingNumber(settings_, quietProfile ? "vibration_locked" : "vibration_unlocked");
    platform_.notifyMessage(sound.empty() ? QString::null
                                          : u(sound == "tone" ? sound : "sounds/" + sound),
                            volume, vibration);
    if (closed_) {
        bool preview = settingFlag(settings_, "external_preview") && !locked_;
        platform_.externalText(preview ? name(m.uin) : u("TeleMotoMax"),
                               preview ? u(m.text)
                                       : QString::number(unread()) + u(" новых сообщений"));
    }
    if (settingFlag(settings_, "ticker") && !locked_) {
        ticker_ = name(m.uin) + ": " + u(m.text);
        tickerUntil_ = ms + 5000;
    }
}
void Window::rebuildRoster() {
    if (stack_.empty() || view().kind != View::Roster)
        return;
    View &v = view();
    uint32_t old = 0;
    if (v.selected >= 0 && v.selected < (int)v.rows.size())
        old = v.rows[v.selected].uin;
    v.rows.clear();
    std::map<std::string, std::vector<size_t> > groups;
    std::map<std::string, unsigned> total, on;
    bool grouped = settingFlag(settings_, "use_groups");
    for (size_t i = 0; i < contacts_.size(); ++i) {
        const ContactRecord &c = contacts_[i];
        if (c.type == 1 && grouped && !c.deleted) {
            groups[c.name];
            continue;
        }
        if (c.type != 0 || !c.uin)
            continue;
        std::map<uint32_t, ChatState>::const_iterator chat = chats_.find(c.uin);
        bool unread = chat != chats_.end() && chat->second.unread;
        if (c.deleted && !settingFlag(settings_, "show_deleted") && !unread)
            continue;
        std::string group = grouped ? c.group : "";
        std::string parent = group;
        for (;;) {
            groups[parent];
            ++total[parent];
            if (online(c.status))
                ++on[parent];
            size_t slash = parent.find_last_of('/');
            if (slash == std::string::npos)
                break;
            parent = parent.substr(0, slash);
        }
        if (!settingFlag(settings_, "hide_offline") || online(c.status) || unread)
            groups[group].push_back(i);
    }
    for (std::map<std::string, std::vector<size_t> >::iterator g = groups.begin();
         g != groups.end(); ++g) {
        std::string parent = g->first;
        bool hidden = false;
        unsigned depth = 0;
        while (parent.find('/') != std::string::npos) {
            parent = parent.substr(0, parent.find_last_of('/'));
            ++depth;
            if (collapsed_[parent])
                hidden = true;
        }
        if (hidden)
            continue;
        if (settingFlag(settings_, "hide_empty") && total[g->first] == 0)
            continue;
        if (!g->first.empty()) {
            std::string shortName = g->first.substr(g->first.find_last_of('/') == std::string::npos
                                                        ? 0
                                                        : g->first.find_last_of('/') + 1);
            QString indent;
            indent.fill(' ', depth * 2);
            v.rows.push_back(Row(indent + u(collapsed_[g->first] ? "+ " : "- ") + u(shortName) +
                                     " (" + QString::number(on[g->first]) + "/" +
                                     QString::number(total[g->first]) + ")",
                                 "group-toggle:" + g->first));
            if (collapsed_[g->first])
                continue;
        }
        std::vector<size_t> &items = g->second;
        for (size_t a = 1; a < items.size(); ++a) {
            size_t b = a;
            while (b) {
                const ContactRecord &left = contacts_[items[b]], &right = contacts_[items[b - 1]];
                bool before =
                    settingValue(settings_, "sort_by") == "name"
                        ? left.name < right.name
                        : (online(left.status) != online(right.status) ? online(left.status)
                                                                       : left.name < right.name);
                if (!before)
                    break;
                std::swap(items[b], items[b - 1]);
                --b;
            }
        }
        for (size_t k = 0; k < items.size(); ++k) {
            ContactRecord &c = contacts_[items[k]];
            QString label = u(c.name);
            std::map<uint32_t, ChatState>::const_iterator chat = chats_.find(c.uin);
            if (chat != chats_.end() && chat->second.unread)
                label += " [" + QString::number(chat->second.unread) + "]";
            v.rows.push_back(Row(label, "open", c.uin));
            if (c.uin == old)
                v.selected = v.rows.size() - 1;
        }
    }
    v.selected = std::max(0, std::min(v.selected, (int)v.rows.size() - 1));
    update();
}
QString Window::messageText(const MessageRecord &m) const {
    QString text;
    time_t stamp =
        m.time +
        (settingNumber(settings_, "timezone") + settingNumber(settings_, "daylight")) * 3600 +
        settingNumber(settings_, "time_offset_minutes") * 60;
    struct tm *tm = gmtime(&stamp);
    char when[32];
    strftime(when, sizeof(when), settingFlag(settings_, "display_date") ? "%d.%m %H:%M" : "%H:%M",
             tm);
    if (settingFlag(settings_, "show_time"))
        text += u(when) + " ";
    if (settingFlag(settings_, "show_sender"))
        text += (m.outgoing
                     ? u("Я")
                     : u(m.senderName.empty() ? std::string(name(m.uin).utf8()) : m.senderName)) +
                ": ";
    if (settingFlag(settings_, "show_newlines"))
        text += "\n";
    text += u(m.text);
    if (settingFlag(settings_, "show_smileys")) {
        replaceText(text, "*IN_LOVE*", "<3");
        replaceText(text, "*THUMBS_UP*", "(y)");
        replaceText(text, "*ROFL*", ":D");
    }
    if (m.kind)
        text += "\n" + u(m.kind == 1   ? "[фото]"
                         : m.kind == 2 ? "[видео]"
                         : m.kind == 3 ? "[голосовое]"
                                       : "[файл]");
    return text;
}
void Window::openChat(uint32_t id) {
    if (!id)
        return;
    saveDraft();
    while (stack_.size() > 1)
        stack_.pop_back();
    View chat(View::Chat, name(id));
    chat.uin = id;
    push(chat);
    ChatState &state = chats_[id];
    state.stamp = now();
    if (!state.loaded) {
        storage_->loadHistory(id, state.messages, settingNumber(settings_, "chat_messages"));
        state.loaded = true;
    }
    state.unread = 0;
    trimChats();
    rebuildChat();
    if (state.messages.empty() && connectionState_ == Event::Online) {
        Command c(Command::OpenChat);
        c.uin = id;
        c.requestId = client_.nextRequestId();
        pending_[c.requestId] = "last";
        pendingUin_[c.requestId] = id;
        send(c);
    }
}
void Window::rebuildChat() {
    if (view().kind != View::Chat)
        return;
    View &v = view();
    ChatState &chat = chats_[v.uin];
    int old = v.rows.size();
    v.rows.clear();
    v.title = name(v.uin) + (chat.typingUntil ? u(" — печатает") : QString::null);
    for (size_t i = 0; i < chat.messages.size(); ++i)
        v.rows.push_back(Row(messageText(chat.messages[i]), "message-menu", v.uin, i));
    if (v.selected >= old - 1)
        v.selected = std::max(0, (int)v.rows.size() - 1);
    update();
}
void Window::showHistory(View &v) {
    v.rows.clear();
    for (size_t i = 0; i < v.messages.size(); ++i)
        if (v.directory.empty() || u(v.messages[i].text).lower().find(u(v.directory).lower()) >= 0)
            v.rows.push_back(Row(messageText(v.messages[i]), "message-menu", v.uin, i));
    if (v.more)
        v.rows.push_back(Row(u("Ещё сообщения"), "history-more", v.uin));
}
void Window::history(bool server, bool more) {
    uint32_t id = view().uin;
    if (!id)
        return;
    if (!more) {
        View v(View::History, (server ? u("История сервера: ") : u("История: ")) + name(id));
        v.uin = id;
        v.context = server ? "server" : "local";
        push(v);
    }
    if (!server) {
        storage_->loadHistory(id, view().messages, settingNumber(settings_, "history_count"));
        showHistory(view());
        update();
        return;
    }
    if (view().request)
        return;
    Command c(Command::History);
    c.uin = id;
    c.offset = view().offset;
    c.limit = 10;
    c.requestId = client_.nextRequestId();
    if (send(c)) {
        view().request = c.requestId;
        pending_[c.requestId] = "history";
        pendingUin_[c.requestId] = id;
    }
    update();
}
const MessageRecord *Window::selectedMessage() const {
    const View *v = 0;
    for (size_t n = stack_.size(); n > 0; --n)
        if (stack_[n - 1].kind == View::Chat || stack_[n - 1].kind == View::History) {
            v = &stack_[n - 1];
            break;
        }
    if (!v || v->selected < 0)
        return 0;
    if (v->kind == View::History) {
        return (size_t)v->selected < v->rows.size() &&
                       v->rows[v->selected].action == "message-menu" &&
                       v->rows[v->selected].value < v->messages.size()
                   ? &v->messages[v->rows[v->selected].value]
                   : 0;
    }
    std::map<uint32_t, ChatState>::const_iterator c = chats_.find(v->uin);
    return c != chats_.end() && (size_t)v->selected < c->second.messages.size()
               ? &c->second.messages[v->selected]
               : 0;
}
void Window::search(bool all, bool more) {
    if (more && view().request)
        return;
    if (!more) {
        if (!all) {
            edit(u("Поиск контактов"), "search", "");
            return;
        }
        View v(View::Menu, u("Все чаты"));
        v.context = "all-chats";
        push(v);
    }
    Command c(all ? Command::AllChats : Command::Search);
    c.offset = view().offset;
    c.limit = 20;
    c.text = view().directory;
    c.requestId = client_.nextRequestId();
    if (send(c)) {
        view().request = c.requestId;
        pending_[c.requestId] = all ? "all-chats" : "search";
    }
    update();
}
void Window::showResults(const Event &e) {
    for (size_t i = 0; i < stack_.size(); ++i) {
        View &v = stack_[i];
        if (v.request != e.requestId)
            continue;
        v.request = 0;
        if (!v.rows.empty() && v.rows.back().action == "chats-more")
            v.rows.pop_back();
        for (size_t j = 0; j < e.contacts.size(); ++j) {
            const ContactRecord &c = e.contacts[j];
            v.rows.push_back(Row(u(c.name) + " (" + QString::number(c.uin) + ")", "open", c.uin));
            if (!contact(c.uin))
                contacts_.push_back(c);
        }
        while (v.rows.size() > 200) {
            v.rows.erase(v.rows.begin());
            if (v.selected > 0)
                --v.selected;
        }
        v.more = e.more;
        v.offset = e.offset;
        if (e.more)
            v.rows.push_back(Row(u("Ещё чаты"), "chats-more"));
    }
    update();
}
void Window::showInfo(const Event &e) {
    QString text = name(e.uin) + "\nUIN: " + QString::number(e.uin) + "\n";
    ContactRecord *c = contact(e.uin);
    if (c)
        text += status(c->status) + "\n" + u(c->group) + "\n";
    for (std::map<std::string, std::string>::const_iterator i = e.fields.begin();
         i != e.fields.end(); ++i)
        text += u(i->first) + ": " + u(i->second) + "\n";
    if (!e.text.empty())
        text += u(e.text);
    showText(u("Информация"), text);
}
void Window::trimChats() {
    size_t loaded = 0;
    for (std::map<uint32_t, ChatState>::iterator i = chats_.begin(); i != chats_.end(); ++i)
        if (i->second.loaded)
            ++loaded;
    while (loaded > 8) {
        std::map<uint32_t, ChatState>::iterator oldest = chats_.end();
        for (std::map<uint32_t, ChatState>::iterator i = chats_.begin(); i != chats_.end(); ++i) {
            if (!i->second.loaded || i->second.unread ||
                (!editAction_.empty() && i->first == editUin_))
                continue;
            bool visible = false;
            for (size_t j = 0; j < stack_.size(); ++j)
                if (stack_[j].kind == View::Chat && stack_[j].uin == i->first) {
                    visible = true;
                    break;
                }
            if (visible)
                continue;
            if (oldest == chats_.end() || i->second.stamp < oldest->second.stamp)
                oldest = i;
        }
        if (oldest == chats_.end())
            break;
        std::vector<MessageRecord>().swap(oldest->second.messages);
        oldest->second.loaded = false;
        --loaded;
    }
}
void Window::quietToggle(uint32_t id, bool enabled) {
    std::vector<uint32_t> values = quiet_;
    std::vector<uint32_t>::iterator found = std::find(values.begin(), values.end(), id);
    if (enabled && found == values.end()) {
        if (values.size() >= 256) {
            info(u("В тихом списке уже 256 чатов"));
            return;
        }
        values.push_back(id);
    }
    if (!enabled && found != values.end())
        values.erase(found);
    std::string error;
    if (!storage_->saveQuietChats(values, error)) {
        info(u(error));
        return;
    }
    quiet_ = values;
    Command c(Command::QuietChats);
    c.uins = quiet_;
    if (connectionState_ == Event::Online && !send(c))
        info(u("Сохранено. Применится при подключении"));
    else
        info(u("Сохранено"));
}
} // namespace tmm
