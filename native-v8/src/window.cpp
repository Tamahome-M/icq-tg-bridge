#include "window.h"
#include "storage.h"
#include "ui_settings.h"
#include "ui_language.h"
#include "ui_files.h"
#include "instance.h"
#include "input_indicator.h"
#include "system_menu.h"
#include "system_chrome.h"
#include "status_icon.h"
#include "status_icon_v8.h"
#include "chat_layout.h"
#include <ZKbInputField.h>
#include <ZMultiLineEdit.h>
#include <ZKeyDef.h>
#include <qapplication.h>
#include <qclipboard.h>
#include <qpainter.h>
#include <qevent.h>
#include <qimage.h>
#include <qwmatrix.h>
#include <qfontmetrics.h>
#include <sys/time.h>
#include <time.h>
#include <stdlib.h>
#include <stdio.h>
#include <unistd.h>
#include <algorithm>
namespace tmm {
static const int listTextLeft = 5, listTextRight = 7;
static QString u(const char *s) {
    return uiText(s);
}
static QString u(const std::string &s) {
    return QString::fromUtf8(s.c_str());
}
static unsigned long now() {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t) == 0)
        return (unsigned long)t.tv_sec * 1000 + t.tv_nsec / 1000000;
    struct timeval v;
    gettimeofday(&v, 0);
    return (unsigned long)v.tv_sec * 1000 + v.tv_usec / 1000;
}
static QString number(unsigned n) {
    return QString::number(n);
}
static bool chatLoading(uint32_t id, const std::map<uint32_t, std::string> &requests,
                        const std::map<uint32_t, uint32_t> &targets) {
    for (std::map<uint32_t, std::string>::const_iterator request = requests.begin();
         request != requests.end(); ++request) {
        if (request->second != "last" && request->second != "chat-history" &&
            request->second != "restore-chat")
            continue;
        std::map<uint32_t, uint32_t>::const_iterator target = targets.find(request->first);
        if (target != targets.end() && target->second == id)
            return true;
    }
    return false;
}
Window::Window(const std::string &dir)
    : QWidget(0, "telemotomax", WRepaintNoErase | WResizeNoErase), storage_(new Storage(dir)),
      platform_(this), player_(this), capture_(this), notifier_(0), editor_(0), inputIndicator_(0),
      systemMenu_(0), systemChrome_(0), data_(dir), editUin_(0), quoteUin_(0), captureUin_(0),
      pickUin_(0), videoUin_(0), videoSegment_(0), outgoingRequest_(0),
      connectionState_(Event::Disconnected), captureKind_(0), pickKind_(0), playPosition_(0),
      playDuration_(0), generation_(0), editDepth_(0), connectionProgress_(0), settingsDepth_(0),
      loadedMediaReady_(false), editSecret_(false), captureOwned_(false), receivedDeferred_(false),
      connectionErrorShown_(false), settingsEditing_(false), resetComplete_(false), locked_(false),
      closed_(false), editorWasVisible_(false), silent_(false), paused_(false),
      manualDisconnect_(false), lightOn_(true), pinWrong_(false), closedAt_(0), startedAt_(now()),
      lastAlert_(0), lastActivity_(now()), typingSentAt_(0), noticeUntil_(0), tickerUntil_(0),
      indicatorsAt_(0), splashMinute_(0), pictureZoom_(100), pictureRotation_(0),
      infoAvatarUin_(0) {
    setCaption("TeleMotoMax Native");
    setFocusPolicy(StrongFocus);
    setBackgroundMode(NoBackground);
    statusIcons_.load("statuses.png");
    messageIcons_.load("messages.png");
    std::string error;
    if (!settings_.load(dir + "/settings", error)) {
        note(error);
        info(u(error));
    }
    if (migrateJavaSettings(settings_)) {
        std::string migrationError;
        if (!settings_.save(migrationError))
            note(migrationError);
    }
    setUiLanguage(settingValue(settings_, "language"));
    silent_ = settings_.getBool("silent", false);
    platform_.setWindow(this);
    capture_.setWindow(this);
    closed_ = platform_.flipClosed();
    if (closed_)
        closedAt_ = now();
    connect(&platform_, SIGNAL(flipChanged(bool)), this, SLOT(flipChanged(bool)));
    connect(&platform_, SIGNAL(error(const QString &)), this, SLOT(platformError(const QString &)));
    connect(&player_, SIGNAL(error(const QString &)), this, SLOT(platformError(const QString &)));
    connect(&player_, SIGNAL(finished()), this, SLOT(mediaFinished()));
    connect(&player_, SIGNAL(positionChanged(unsigned int, unsigned int)), this,
            SLOT(mediaPosition(unsigned int, unsigned int)));
    connect(&capture_, SIGNAL(error(const QString &)), this, SLOT(captureError(const QString &)));
    connect(&capture_, SIGNAL(cancelled()), this, SLOT(captureCancelled()));
    connect(&capture_, SIGNAL(ready(const QString &, const QString &)), this,
            SLOT(captureReady(const QString &, const QString &)));
    // Native input modes cache their UI interface at activation. Install it
    // before constructing any editor that may take focus during initialization.
    inputIndicator_ = new InputIndicator(this);
    connect(inputIndicator_->stateSource(), SIGNAL(signalKbStateChanged(int, bool)), this,
            SLOT(inputStateChanged(int, bool)));
    editor_ = new ZMultiLineEdit(this, true, 8);
    systemMenu_ = new SystemMenu(this, contacts_, statusIcons_, messageIcons_);
    systemChrome_ = new SystemChrome(*this);
    connect(qApp, SIGNAL(signalAppThemeChange()), this, SLOT(systemThemeChanged()));
    connect(qApp, SIGNAL(signalThemeChange()), this, SLOT(systemThemeChanged()));
    editor_->getInputField()->setOptions(
        ZKbInputField::FIELD_OPTION_IMSTATEOBSERVER,
        reinterpret_cast<long>(static_cast<QObject *>(inputIndicator_)));
    editor_->hide();
    editor_->setWordWrap(ZMultiLineEdit::WidgetWidth);
    editor_->setUndoDepth(8);
    editor_->installEventFilter(this);
    connect(editor_, SIGNAL(textChanged()), this, SLOT(editorChanged()));
    notifier_ = new QSocketNotifier(client_.eventFd(), QSocketNotifier::Read, this);
    connect(notifier_, SIGNAL(activated(int)), this, SLOT(eventsReady()));
    connect(&timer_, SIGNAL(timeout()), this, SLOT(tick()));
    timer_.start(1000);
    selectScope();
    home();
    applySettings();
    note("TeleMotoMax Native " TMM_NATIVE_VERSION "; OSCAR/TMM 1.32");
    if (settingFlag(settings_, "auto_connect"))
        connectClient();
    else if (settingFlag(settings_, "startup_dns") && validateNetworkSettings(settings_, error)) {
        client_.prefetchDns();
        generation_ = client_.sessionGeneration();
    }
}
Window::~Window() {
    saveState();
    client_.stop();
    player_.stop();
    capture_.cancel();
    outgoingRequest_ = 0;
    discardAttachment();
    mediaCache_.clear();
    if (!managedMediaPath_.empty())
        unlink(managedMediaPath_.c_str());
    // The native input field holds a non-owning observer pointer. End its
    // lifetime while the input indicator is still a live QObject child.
    delete editor_;
    editor_ = 0;
    delete systemMenu_;
    delete systemChrome_;
    delete storage_;
}
void Window::saveState() {
    if (resetComplete_)
        return;
    saveDraft();
    settings_.setBool("silent", silent_);
    std::string e;
    if (!settings_.save(e)) {
        note(e);
        info(u(e));
    }
    if (!storage_->saveRoster(contacts_, e)) {
        note(e);
        info(u(e));
    }
}
View &Window::view() {
    return stack_.back();
}
const View &Window::view() const {
    return stack_.back();
}
bool Window::systemMenuVisible() const {
    if (!systemMenu_ || stack_.empty() || view().rows.empty() || locked_ ||
        connectionProgressVisible() || (editor_ && !editor_->isHidden()))
        return false;
    View::Kind kind = view().kind;
    return kind == View::Roster || kind == View::Menu || kind == View::Popup ||
           kind == View::SettingsPage || kind == View::Choice || kind == View::Files ||
           kind == View::Templates || kind == View::AttachmentReview;
}
void Window::syncSystemMenu() {
    if (!systemMenu_ || stack_.empty())
        return;
    int bottom = height() - 27;
    systemMenu_->sync(view(), systemMenuVisible(), view().kind == View::AttachmentReview ? 145 : 29,
                      bottom);
}
void Window::update() {
    updateSystemStatusIcon();
    if (editor_ && !editor_->isHidden())
        layoutEditor();
    syncSystemMenu();
    QWidget::update();
}
void Window::syncVideoVisibility() {
    QWidget *video = player_.videoWidget();
    if (!video)
        return;
    if (!stack_.empty() && view().kind == View::Player && !locked_ && !closed_ && isVisible())
        video->show();
    else
        video->hide();
}
void Window::push(const View &v) {
    if (v.kind == View::Popup && view().kind != View::Popup)
        popupBackdrop_ = QPixmap::grabWidget(this);
    if (stack_.size() < 32)
        stack_.push_back(v);
    if (editor_)
        editor_->hide();
    syncVideoVisibility();
    update();
}
void Window::back() {
    if (editor_ && editor_->isVisible()) {
        finishEdit(false);
        return;
    }
    if (settingsPageActive()) {
        finishSettings(false);
        return;
    }
    if (stack_.size() > 1) {
        if (view().request) {
            Command c(Command::CancelRequest);
            c.requestId = view().request;
            client_.submit(c);
            pending_.erase(c.requestId);
            pendingUin_.erase(c.requestId);
            mediaRequests_.erase(c.requestId);
            if (outgoingRequest_ == c.requestId)
                outgoingRequest_ = 0;
        }
        if (view().kind == View::Recording && capture_.busy())
            capture_.cancel();
        if (view().context == "attachment-review")
            discardAttachment();
        if (view().kind == View::Picture)
            picture_ = QPixmap();
        if (view().kind == View::Player) {
            player_.stop();
            QWidget *w = player_.videoWidget();
            if (w)
                w->hide();
        }
        stack_.pop_back();
        bool popup = false;
        for (size_t i = 0; i < stack_.size(); ++i)
            popup = popup || stack_[i].kind == View::Popup;
        if (!popup)
            popupBackdrop_ = QPixmap();
        if (view().kind == View::Chat) {
            markVisibleChatRead();
            rebuildChat();
        } else if (view().kind == View::Roster)
            rebuildRoster();
    } else
        mainMenu();
    if (!editAction_.empty() && stack_.size() == editDepth_) {
        editor_->show();
        editor_->setFocus();
    }
    syncVideoVisibility();
    update();
}
void Window::home() {
    popupBackdrop_ = QPixmap();
    stack_.clear();
    stack_.push_back(View(View::Roster, u("Контакты")));
    syncVideoVisibility();
    rebuildRoster();
}
void Window::note(const std::string &s) {
    if (s.empty())
        return;
    time_t t = time(0);
    struct tm *tm = localtime(&t);
    char b[16];
    strftime(b, sizeof(b), "%H:%M:%S ", tm);
    log_.push_back(std::string(b) + s);
    if (log_.size() > 100)
        log_.erase(log_.begin());
}
void Window::info(const QString &s) {
    notice_ = s;
    noticeUntil_ = now() + 7000;
    update();
}
void Window::platformError(const QString &s) {
    note(std::string(s.utf8()));
    info(s);
}
void Window::showText(const QString &title, const QString &text) {
    View v(View::Text, title);
    v.rows.push_back(Row(text, "copy-view"));
    push(v);
}
void Window::copy(const QString &s) {
    QApplication::clipboard()->setText(s);
    info(u("Скопировано"));
}
QString Window::copied() const {
    return QApplication::clipboard()->text();
}
unsigned Window::unread() const {
    unsigned count = 0;
    for (std::map<uint32_t, ChatState>::const_iterator i = chats_.begin(); i != chats_.end(); ++i)
        count += i->second.unread;
    return count;
}
void Window::markVisibleChatRead() {
    if (stack_.empty() || locked_ || closed_ || !isVisible() || view().kind != View::Chat)
        return;
    std::map<uint32_t, ChatState>::iterator chat = chats_.find(view().uin);
    if (chat != chats_.end())
        chat->second.unread = 0;
}
QString Window::name(uint32_t id) const {
    for (size_t i = 0; i < contacts_.size(); ++i)
        if (contacts_[i].uin == id)
            return u(contacts_[i].name);
    return number(id);
}
QString Window::status(uint32_t value) const {
    switch (statusIcon(value)) {
    case 6:
        return u("Не в сети");
    case 3:
        return u("Сеть недоступна");
    case 1:
        return u("Свободен для общения");
    case 5:
        return u("Занят");
    case 2:
        return u("Не беспокоить");
    case 4:
        return u("Недоступен");
    case 0:
        return u("Отошёл");
    default:
        return u("В сети");
    }
}
ContactRecord *Window::contact(uint32_t id) {
    for (size_t i = 0; i < contacts_.size(); ++i)
        if (contacts_[i].uin == id)
            return &contacts_[i];
    return 0;
}
void Window::updateSystemStatusIcon() {
    StatusIconV8::configureApplication(
        settingNumber(settings_, "running_icon"),
        connectionState_ == Event::Online ? settings_.getInt("status", 0) : 0xffffffffU,
        unread() != 0);
}
void Window::applySettings() {
    client_.configure(clientSettings(settings_, storage_->accountDir() + "/cache", quiet_));
    updateSystemStatusIcon();
    setUiLanguage(settingValue(settings_, "language"));
    QFont bodyFont = QApplication::font();
    bodyFont.setPointSize(settingNumber(settings_, "font_size"));
    setFont(bodyFont);
    editor_->setFont(bodyFont);
    const unsigned history = settingFlag(settings_, "save_history")
                                 ? std::max(0, settingNumber(settings_, "history_count"))
                                 : 0;
    storage_->setHistoryLimit(history);
    if (!history) {
        std::string error;
        if (!storage_->clearAllHistory(error, true)) {
            note(error);
            info(u("Не удалось удалить локальную историю: ") + u(error));
        }
    }
    if (isVisible())
        showConfigured();
    update();
}
void Window::showConfigured() {
    Platform::showWindow(*this, settingFlag(settings_, "fullscreen"));
}
QColor Window::bodyColor(unsigned role) const {
    const QColorGroup &colors = palette().active();
    if (role == 1)
        return colors.base();
    if (role == 3)
        return colors.highlight();
    if (role == 4)
        return colors.button();
    if (role == 8)
        return colors.mid();
    return colors.text();
}
QFont Window::chatFont() const {
    QFont result = QApplication::font();
    result.setPointSize(settingNumber(settings_, "chat_font_size"));
    return result;
}
void Window::settingsChanged() {
    std::string error;
    if (!settings_.save(error)) {
        info(u(error));
        return;
    }
    applySettings();
    Command c(Command::Settings);
    c.media = mediaSettings(settings_);
    if (connectionState_ == Event::Online)
        send(c);
    if (view().kind == View::SettingsPage)
        showSettings(view().context);
}
void Window::resizeEvent(QResizeEvent *) {
    layoutEditor();
    syncSystemMenu();
    QWidget *w = player_.videoWidget();
    if (w && w->isVisible())
        w->setGeometry(0, 29, width(), std::max(1, height() - 56));
}
void Window::showEvent(QShowEvent *) {
    if (closedAt_ && settingNumber(settings_, "flip_lock_minutes") > 0 &&
        now() - closedAt_ >= (unsigned long)settingNumber(settings_, "flip_lock_minutes") * 60000)
        lock();
}
void Window::closeEvent(QCloseEvent *e) {
    e->ignore();
    minimize();
}
void Window::suspend() {
    pin_ = QString::null;
    pinWrong_ = false;
    if (editSecret_)
        editor_->setEchoMode(ZMultiLineEdit::Password);
    saveDraft();
    capture_.cancel();
}
void Window::resume() {
    // Platform refreshes the hardware flip state before requesting foreground.
    platform_.requestForeground(settingFlag(settings_, "fullscreen"));
    if (closed_)
        return;
    lastActivity_ = now();
    lightOn_ = true;
    markVisibleChatRead();
    if (!locked_ && editor_ && !editor_->isHidden())
        editor_->setFocus();
    else if (systemMenuVisible())
        systemMenu_->focus();
    else
        setFocus();
    openDeferredMedia();
    syncVideoVisibility();
    update();
}
void Window::minimize() {
    suspend();
    platform_.minimize();
}
void Window::flipChanged(bool closed) {
    if (closed_ == closed)
        return;
    closed_ = closed;
    if (closed) {
        if (editSecret_)
            editor_->setEchoMode(ZMultiLineEdit::Password);
        closedAt_ = now();
        if (capture_.busy())
            capture_.cancel();
    } else {
        if (closedAt_ && settingNumber(settings_, "flip_lock_minutes") > 0 &&
            now() - closedAt_ >=
                (unsigned long)settingNumber(settings_, "flip_lock_minutes") * 60000)
            lock();
        closedAt_ = 0;
        markVisibleChatRead();
        openDeferredMedia();
    }
    syncVideoVisibility();
    update();
}
void Window::lock() {
    if (locked_)
        return;
    locked_ = true;
    if (editSecret_)
        editor_->setEchoMode(ZMultiLineEdit::Password);
    platform_.clearExternalText();
    pin_ = QString::null;
    pinWrong_ = false;
    editorWasVisible_ = editor_ && editor_->isVisible();
    saveDraft();
    if (editor_)
        editor_->hide();
    capture_.cancel();
    QWidget *w = player_.videoWidget();
    if (w)
        w->hide();
    update();
}
void Window::unlock() {
    locked_ = false;
    pin_ = QString::null;
    pinWrong_ = false;
    if (editorWasVisible_)
        editor_->show();
    editorWasVisible_ = false;
    markVisibleChatRead();
    platform_.setBacklight(true);
    openDeferredMedia();
    syncVideoVisibility();
    update();
}
void Window::tick() {
    if (takeActivationRequest())
        resume();
    unsigned long ms = now();
    if (isVisible() && !closed_ && !locked_ && !connectionProgressVisible() &&
        ms - indicatorsAt_ >= 5000) {
        indicatorsAt_ = ms;
        if (systemChrome_->refreshIndicators())
            QWidget::update(0, 0, width(), 28);
    }
    if ((locked_ || connectionProgressVisible()) && isVisible() && !closed_ &&
        splashMinute_ != time(0) / 60) {
        splashMinute_ = time(0) / 60;
        update();
    }
    if (closed_ && closedAt_ && settingNumber(settings_, "flip_lock_minutes") > 0 &&
        ms - closedAt_ >= (unsigned long)settingNumber(settings_, "flip_lock_minutes") * 60000)
        lock();
    if (noticeUntil_ && ms >= noticeUntil_) {
        noticeUntil_ = 0;
        notice_ = QString::null;
        update();
    }
    if (tickerUntil_ && ms >= tickerUntil_) {
        tickerUntil_ = 0;
        ticker_ = QString::null;
        update();
    }
    if (!settingFlag(settings_, "manual_light") && lightOn_ &&
        settingNumber(settings_, "light_seconds") > 0 &&
        ms - lastActivity_ > (unsigned long)settingNumber(settings_, "light_seconds") * 1000) {
        platform_.setBacklight(false);
        lightOn_ = false;
    }
    if (!stack_.empty() && view().context == "recording" && capture_.busy()) {
        QString state = u("Запись: ") + number(capture_.durationSeconds()) + u(" с");
        if (view().status != state) {
            view().status = state;
            update();
        }
    }
    if (!stack_.empty() && view().kind == View::Chat) {
        ChatState &chat = chats_[view().uin];
        if (chat.typingUntil && ms >= chat.typingUntil) {
            chat.typingUntil = 0;
            update();
        }
    }
}
void Window::inputStateChanged(int windowId, bool active) {
    inputIndicator_->activate(windowId, active);
}
void Window::systemThemeChanged() {
    StatusIconV8::themeChanged();
    setPalette(QApplication::palette());
    if (systemChrome_)
        systemChrome_->refresh();
    update();
}
bool Window::eventFilter(QObject *object, QEvent *event) {
    if (systemMenu_ && systemMenu_->owns(object) &&
        (event->type() == QEvent::KeyPress || event->type() == QEvent::KeyRelease)) {
        if (event->type() == QEvent::KeyPress)
            key(static_cast<QKeyEvent *>(event)->key());
        return true;
    }
    if (object == editor_ && inputIndicator_) {
        if (event->type() == QEvent::Show) {
            layoutEditor();
            inputIndicator_->show();
        } else if (event->type() == QEvent::Hide)
            inputIndicator_->hide();
    }
    if (object == editor_ && event->type() == QEvent::KeyPress) {
        QKeyEvent *k = static_cast<QKeyEvent *>(event);
        lastActivity_ = now();
        if (locked_) {
            key(k->key());
            return true;
        }
        int code = k->key();
        if (settingFlag(settings_, "mirror_menu")) {
            if (code == KEYCODE_LSK)
                code = KEYCODE_RSK;
            else if (code == KEYCODE_RSK)
                code = KEYCODE_LSK;
        }
        if (code == KEYCODE_END) {
            minimize();
            return true;
        }
        if (code == KEYCODE_LSK) {
            finishEdit(false);
            return true;
        }
        if (code == KEYCODE_RSK) {
            editorMenu();
            return true;
        }
    }
    return QWidget::eventFilter(object, event);
}
void Window::keyPressEvent(QKeyEvent *e) {
    key(e->key());
    e->accept();
}
void Window::key(int code) {
    lastActivity_ = now();
    if (!lightOn_) {
        platform_.setBacklight(true);
        lightOn_ = true;
    }
    if (code == KEYCODE_END) {
        minimize();
        return;
    }
    if (locked_) {
        std::string pin = settingValue(settings_, "lock_pin");
        if (pin.empty()) {
            if (code == KEYCODE_POUND)
                unlock();
            return;
        }
        if (code >= KEYCODE_0 && code <= KEYCODE_9 && pin_.length() < 8) {
            pinWrong_ = false;
            pin_ += QChar((char)code);
        } else if (code == KEYCODE_CLEAR || code == KEYCODE_STAR) {
            pinWrong_ = false;
            if (pin_.length())
                pin_.truncate(pin_.length() - 1);
        } else if (code == KEYCODE_LSK || code == KEYCODE_RSK) {
            pinWrong_ = false;
            pin_ = QString::null;
        }
        if (std::string(pin_.utf8()) == pin)
            unlock();
        else if ((size_t)pin_.length() >= pin.size()) {
            pin_ = QString::null;
            pinWrong_ = true;
        }
        update();
        return;
    }
    if (settingFlag(settings_, "mirror_menu")) {
        if (code == KEYCODE_LSK)
            code = KEYCODE_RSK;
        else if (code == KEYCODE_RSK)
            code = KEYCODE_LSK;
    }
    if (javaKey(code))
        return;
    if (view().kind == View::Text && (code == KEYCODE_UP || code == KEYCODE_DOWN)) {
        int max = 0;
        if (!view().rows.empty())
            max = std::max(0, (fontMetrics()
                                   .boundingRect(0, 0, width() - 10, 100000, Qt::WordBreak,
                                                 view().rows[0].text)
                                   .height() -
                               height() + 60 + 24) /
                                  25);
        view().selected =
            std::max(0, std::min(max, view().selected + (code == KEYCODE_UP ? -1 : 1)));
        update();
        return;
    }
    if (code == KEYCODE_UP || code == KEYCODE_DOWN) {
        View &v = view();
        bool chat = v.kind == View::Chat || v.kind == View::History;
        int overflow = chat && v.selected >= 0 && v.selected < (int)v.rows.size()
                           ? std::max(0, rowHeight(v.rows[v.selected]) - (height() - 56))
                           : 0;
        if (code == KEYCODE_DOWN) {
            if (v.scroll < overflow)
                v.scroll = std::min(overflow, v.scroll + std::max(20, height() / 3));
            else if (v.selected + 1 < (int)v.rows.size()) {
                ++v.selected;
                v.scroll = 0;
            }
        } else {
            if (v.scroll > 0)
                v.scroll = std::max(0, v.scroll - std::max(20, height() / 3));
            else if (v.selected > 0) {
                --v.selected;
                v.scroll = 0;
            }
        }
        update();
        return;
    }
    if (code == KEYCODE_CENTER_SELECT || code == Key_Enter) {
        activateSelected();
        return;
    }
    if (code == KEYCODE_LEFT || code == KEYCODE_RIGHT) {
        if (view().kind == View::Chat) {
            std::vector<uint32_t> active;
            for (size_t n = 0; n < openChatOrder_.size(); ++n)
                if (chats_.find(openChatOrder_[n]) != chats_.end())
                    active.push_back(openChatOrder_[n]);
            if (!active.empty()) {
                size_t at = std::find(active.begin(), active.end(), view().uin) - active.begin();
                at = (at + (code == KEYCODE_RIGHT ? 1 : active.size() - 1)) % active.size();
                openChat(active[at]);
            }
        } else {
            int jump = std::max(1, (height() - 60) / 30);
            view().selected =
                std::max(0, std::min((int)view().rows.size() - 1,
                                     view().selected + (code == KEYCODE_RIGHT ? jump : -jump)));
            update();
        }
        return;
    }
    hotkey(code);
}
void Window::drawHeader(QPainter &p) {
    QString title = locked_ ? u("Заблокировано")
                            : (editor_ && editor_->isVisible() ? editTitle_ : view().title);
    bool roster = view().kind == View::Roster && !locked_;
    if (roster) {
        unsigned total = 0, on = 0;
        for (size_t i = 0; i < contacts_.size(); ++i)
            if (contacts_[i].type == 0 && contacts_[i].uin && !contacts_[i].deleted) {
                ++total;
                if (contacts_[i].status != 0xffffffffU && !(contacts_[i].status & 0x100))
                    ++on;
            }
        title = QString::number(on) + "/" + QString::number(total);
    } else if (view().kind == View::Chat && !locked_ && !(editor_ && editor_->isVisible())) {
        title = name(view().uin);
        unsigned index = 0, count = 0;
        for (size_t i = 0; i < openChatOrder_.size(); ++i)
            if (chats_.find(openChatOrder_[i]) != chats_.end()) {
                ++count;
                if (openChatOrder_[i] == view().uin)
                    index = count;
            }
        if (count > 1)
            title += " (" + QString::number(index) + "/" + QString::number(count) + ")";
    }
    if (view().kind == View::Picture)
        title += " " + number(pictureZoom_) + "%";
    if (connectionProgressVisible()) {
        title = u("Подключение");
        roster = false;
    }
    if (!locked_ && view().kind == View::Chat && chatLoading(view().uin, pending_, pendingUin_))
        title = u("Загрузка…");
    if (!locked_ && !connectionProgressVisible() && (!notice_.isEmpty() || !ticker_.isEmpty())) {
        title = notice_.isEmpty() ? ticker_ : notice_;
        for (unsigned i = 0; i < title.length(); ++i)
            if (title[i] == '\n' || title[i] == '\r')
                title[i] = QChar(' ');
        roster = false;
    }
    // Keep unread deliveries visible even inside another chat, a menu or PIN.
    if (unread())
        title = "[" + number(unread()) + "] " + title;
    int offset = settingNumber(settings_, "caption_offset") * width() / 100;
    systemChrome_->drawHeader(p, QRect(0, 0, width(), 28), title, offset + (roster ? 20 : 0));
    if (roster && !statusIcons_.isNull()) {
        unsigned own =
            connectionState_ == Event::Online ? settings_.getInt("status", 0) : 0xffffffffU;
        p.drawPixmap(4, 6, statusIcons_, statusIcon(own) * 16, 0, 16, 16);
    }
}
void Window::drawFooter(QPainter &p) {
    QString left = u("Назад"), right = u("Выбрать");
    const std::string &context = view().context;
    if (view().kind == View::Roster) {
        left = u("Меню");
        right = u("Выбрать");
    } else if (view().kind == View::Chat) {
        left = u("Закрыть");
        right = u("Меню");
    } else if (view().kind == View::History || view().kind == View::Templates)
        right = u("Меню");
    else if (view().kind == View::Popup)
        left = u("Отмена");
    else if (view().kind == View::Text || view().kind == View::Picture)
        right = QString::null;
    if (view().kind == View::Templates && context == "insert")
        left = u("Выбрать");
    if (context == "main-menu")
        left = contacts_.empty() ? QString::null : u("Чаты");
    if (settingsPageActive())
        right = u("Сохр.");
    if (context == "privacy-editor") {
        left = u("Отмена");
        right = u("Меню");
    }
    if (context == "contact-info" && !view().request)
        right = u("Меню");
    if (context == "quiet-settings") {
        left = u("Сохр.");
        right = u("Назад");
    }
    if (context == "chat-delete") {
        left = u("Отмена");
        right = u("ОК");
    }
    if (view().kind == View::Recording)
        right = QString::null;
    if (view().kind == View::Transfer)
        right = QString::null;
    if (view().kind == View::Player)
        right = context == "player-video" && !videoToken_.empty() ? u("Дальше") : QString::null;
    if (connectionProgressVisible()) {
        left = u("Отмена");
        right = QString::null;
    }
    if (editor_ && editor_->isVisible()) {
        left = u("Отмена");
        right = u("Меню");
    }
    if (locked_) {
        left = QString::null;
        right = settingValue(settings_, "lock_pin").empty() ? u("# — разблокировать")
                                                            : u("Введите PIN");
    }
    if (settingFlag(settings_, "mirror_menu")) {
        QString swap = left;
        left = right;
        right = swap;
    }
    systemChrome_->drawFooter(p, QRect(0, height() - 26, width(), 26), left, right);
}
const MessageRecord *Window::rowMessage(const View &v, const Row &r) const {
    if (r.action != "message-menu")
        return 0;
    if (v.kind == View::History)
        return r.value < v.messages.size() ? &v.messages[r.value] : 0;
    if (v.kind == View::Chat) {
        std::map<uint32_t, ChatState>::const_iterator chat = chats_.find(v.uin);
        if (chat != chats_.end() && r.value < chat->second.messages.size())
            return &chat->second.messages[r.value];
    }
    return 0;
}
ChatLayout Window::layoutMessage(const View &v, const Row &r) const {
    const MessageRecord *message = rowMessage(v, r);
    // Rows may predate a formatting preference or a contact-name refresh.
    // Use the record so current header/body formatting stays consistent.
    const QString formatted = message ? messageText(*message) : r.text;
    const ChatText text =
        splitChatText(formatted, message ? messageHeader(*message) : QString::null,
                      settingFlag(settings_, "show_newlines"), message && !message->time);
    const bool hasIcon =
        message && (settingFlag(settings_, "show_icons") ||
                    (message->outgoing && settingFlag(settings_, "show_receipts")));
    return layoutChatText(text, chatFont(), width() - listTextLeft - listTextRight,
                          hasIcon ? 17 : 0);
}
int Window::rowHeight(const Row &r) const {
    if (view().context == "contact-info" && r.action == "info-avatar-view")
        return infoAvatar_.isNull() ? 30 : infoAvatar_.height() + 8;
    if (view().kind != View::Chat && view().kind != View::History &&
        view().context != "contact-info")
        return std::max(30, fontMetrics().height() + 10);
    if (rowMessage(view(), r))
        return std::max(30, layoutMessage(view(), r).height + 10);
    QFontMetrics metrics(chatFont());
    return std::max(30,
                    metrics.boundingRect(0, 0, std::max(1, width() - listTextLeft - listTextRight),
                                         100000, Qt::WordBreak, r.text)
                            .height() +
                        10);
}
void Window::drawList(QPainter &p) {
    View &v = view();
    bool chat = v.kind == View::Chat || v.kind == View::History;
    bool fields = v.context == "contact-info";
    if (chat || fields)
        p.setFont(chatFont());
    const QFont regular = p.font();
    const int textWidth = std::max(1, width() - listTextLeft - listTextRight);
    QFont bold = regular;
    bold.setBold(true);
    int available = height() - 56;
    if (v.selected < v.top)
        v.top = v.selected;
    int used = 0;
    for (int i = v.top; i <= v.selected && i < (int)v.rows.size(); ++i)
        used += std::min(available, rowHeight(v.rows[i]));
    while (used > available && v.top < v.selected) {
        used -= std::min(available, rowHeight(v.rows[v.top]));
        ++v.top;
    }
    p.setClipRect(0, 29, width(), available);
    int y = 29;
    for (int i = v.top; i < (int)v.rows.size() && y < height() - 27; ++i) {
        const MessageRecord *m = chat ? rowMessage(v, v.rows[i]) : 0;
        const ChatLayout layout = m ? layoutMessage(v, v.rows[i]) : ChatLayout();
        const int h = m ? std::max(30, layout.height + 10) : rowHeight(v.rows[i]);
        bool selected = i == v.selected;
        const QColor selectedBackground =
            m ? chatSelectionColor(palette().active().base(), palette().active().text())
              : palette().active().highlight();
        if (selected)
            p.fillRect(0, y, width(), std::min(h, available), selectedBackground);
        const QColor ink =
            selected && !m ? palette().active().highlightedText() : palette().active().text();
        p.setPen(ink);
        int offset = selected ? v.scroll : 0;
        if (m) {
            int iy = y + 7 - offset;
            p.setPen(QPen(ink, 2));
            if (m->outgoing && settingFlag(settings_, "show_receipts")) {
                if (m->delivery) {
                    p.drawLine(8, iy + 5, 11, iy + 8);
                    p.drawLine(11, iy + 8, 18, iy);
                    if (m->delivery >= 2) {
                        p.drawLine(3, iy + 5, 6, iy + 8);
                        p.drawLine(6, iy + 8, 13, iy);
                    }
                } else {
                    p.drawEllipse(5, iy, 10, 10);
                    p.drawLine(10, iy + 2, 10, iy + 5);
                    p.drawLine(10, iy + 5, 13, iy + 5);
                }
            } else if (settingFlag(settings_, "show_icons")) {
                p.drawLine(listTextLeft, iy + 4, 16, iy + 4);
                int tip = m->outgoing ? listTextLeft : 16, base = m->outgoing ? 10 : 11;
                p.drawLine(base, iy, tip, iy + 4);
                p.drawLine(tip, iy + 4, base, iy + 8);
            }
            p.setPen(ink);
        }
        if (fields && v.rows[i].action == "info-avatar-view" && !infoAvatar_.isNull())
            p.drawPixmap((width() - infoAvatar_.width()) / 2, y + 4 - offset, infoAvatar_);
        else if (m) {
            const QColor headerInk = chatHeaderColor(
                m->outgoing, selected ? selectedBackground : palette().active().base());
            for (size_t run = 0; run < layout.runs.size(); ++run) {
                const ChatRun &part = layout.runs[run];
                const int top = y + 4 + part.y - offset;
                if (top + layout.lineHeight < 29 || top >= height() - 27)
                    continue;
                p.setFont(part.header ? bold : regular);
                p.setPen(part.header ? headerInk : ink);
                p.drawText(listTextLeft + part.x, top, std::max(1, textWidth - part.x),
                           layout.lineHeight, Qt::AlignLeft | Qt::AlignTop | Qt::SingleLine,
                           part.text);
            }
            p.setFont(regular);
        } else
            p.drawText(listTextLeft, y + 4 - offset, textWidth, h - 8,
                       Qt::AlignLeft |
                           ((chat || fields) ? Qt::WordBreak : Qt::AlignVCenter | Qt::SingleLine),
                       v.rows[i].text);
        y += std::min(h, available);
    }
    if (v.rows.empty()) {
        // Conversation requests do not use View::request: that field also
        // controls cancellation when going Back.
        const bool loading =
            v.request || (v.kind == View::Chat && chatLoading(v.uin, pending_, pendingUin_));
        p.setPen(Qt::gray);
        p.drawText(8, 55, width() - 16, 90, Qt::WordBreak,
                   u(loading ? "Загрузка…" : "Сообщений нет"));
    }
    p.setClipping(false);
    p.setFont(font());
}
void Window::paintEvent(QPaintEvent *event) {
    syncSystemMenu();
    if (frame_.size() != size())
        frame_.resize(size());
    if (frame_.isNull())
        return;
    QPainter buffered(&frame_);
    buffered.setFont(font());
    drawFrame(buffered);
    buffered.end();
    // Present a completed frame. Painting the background directly to the
    // framebuffer exposes a blank menu between key presses on the V8.
    // The QWidget painter keeps native editor/video children clipped out.
    QPainter screen(this);
    const QRect area = event->rect().intersect(rect());
    screen.drawPixmap(area.x(), area.y(), frame_, area.x(), area.y(), area.width(), area.height());
}
void Window::drawFrame(QPainter &p) {
    if (locked_ || connectionProgressVisible()) {
        drawSplash(p);
        if (!locked_ && !notice_.isEmpty())
            systemChrome_->drawHeader(p, QRect(0, 0, width(), 28), notice_);
        return;
    }
    splashLogo_ = QPixmap();
    if (view().kind == View::Popup && !locked_ && !popupBackdrop_.isNull()) {
        p.drawPixmap(0, 0, popupBackdrop_);
        drawHeader(p);
        drawFooter(p);
        return;
    }
    // Transparent native skin parts blend against the phone's palette in menus.
    p.fillRect(rect(), systemMenuVisible() ? palette().active().background() : bodyColor(1));
    if (!(editor_ && editor_->isVisible() && editAction_ == "message" &&
          settingFlag(settings_, "full_editor") && notice_.isEmpty() && ticker_.isEmpty()))
        drawHeader(p);
    drawFooter(p);
    if (view().kind == View::Transfer || view().kind == View::Recording) {
        drawProgress(p, view().details, view().status, view().bytes, view().total);
    } else if (view().kind == View::AttachmentReview) {
        drawAttachmentDetails(p);
    } else if (view().kind == View::Picture && !picture_.isNull()) {
        p.save();
        const QRect area(0, 29, width(), std::max(1, height() - 56));
        p.setClipRect(area);
        QWMatrix matrix;
        double scale = (double)pictureZoom_ / 100;
        matrix.scale(scale, scale);
        matrix.rotate(pictureRotation_);
        QPixmap image = picture_.xForm(matrix);
        p.drawPixmap((width() - image.width()) / 2, area.y() + (area.height() - image.height()) / 2,
                     image);
        p.restore();
    } else if (view().kind == View::Player) {
        drawPlayer(p);
    } else if (view().kind == View::Text && view().context != "contact-info" &&
               !view().rows.empty()) {
        p.setClipRect(0, 29, width(), height() - 56);
        p.setPen(bodyColor(2));
        p.drawText(5, 32 - view().selected * 25, width() - 10, 100000, Qt::WordBreak,
                   view().rows[0].text);
        p.setClipping(false);
    } else if (!systemMenuVisible())
        drawList(p);
}
void Window::mediaPosition(unsigned int p, unsigned int d) {
    playPosition_ = p;
    playDuration_ = d;
    if (!stack_.empty() && view().kind == View::Player)
        update();
}
void Window::mediaFinished() {
    paused_ = false;
    if (view().kind == View::Player) {
        view().more = true;
        update();
    }
}
} // namespace tmm
