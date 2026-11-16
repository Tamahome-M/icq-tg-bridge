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
Window::Window(const std::string &dir)
    : QWidget(0, "telemotomax", WRepaintNoErase | WResizeNoErase), storage_(new Storage(dir)),
      platform_(this), player_(this), capture_(this), notifier_(0), editor_(0), inputIndicator_(0),
      systemMenu_(0), systemChrome_(0), data_(dir), editUin_(0), quoteUin_(0), captureUin_(0),
      pickUin_(0), videoUin_(0), videoSegment_(0), connectionState_(Event::Disconnected),
      captureKind_(0), pickKind_(0), playPosition_(0), playDuration_(0), generation_(0),
      editDepth_(0), loadedMediaReady_(false), editSecret_(false), connectionErrorShown_(false),
      locked_(false), closed_(false), editorWasVisible_(false), silent_(false), paused_(false),
      manualDisconnect_(false), lightOn_(true), closedAt_(0), startedAt_(now()), lastAlert_(0),
      lastActivity_(now()), typingSentAt_(0), noticeUntil_(0), tickerUntil_(0), pictureZoom_(100),
      pictureRotation_(0) {
    setCaption("TeleMotoMax Native");
    setFocusPolicy(StrongFocus);
    setBackgroundMode(NoBackground);
    statusIcons_.load("statuses.png");
    std::string error;
    if (!settings_.load(dir + "/settings", error)) {
        note(error);
        info(u(error));
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
    connect(&capture_, SIGNAL(error(const QString &)), this, SLOT(platformError(const QString &)));
    connect(&capture_, SIGNAL(ready(const QString &, const QString &)), this,
            SLOT(captureReady(const QString &, const QString &)));
    // Native input modes cache their UI interface at activation. Install it
    // before constructing any editor that may take focus during initialization.
    inputIndicator_ = new InputIndicator(this);
    connect(inputIndicator_->stateSource(), SIGNAL(signalKbStateChanged(int, bool)), this,
            SLOT(inputStateChanged(int, bool)));
    editor_ = new ZMultiLineEdit(this, true, 8);
    systemMenu_ = new SystemMenu(this);
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
    note("TeleMotoMax Native " TMM_NATIVE_VERSION "; OSCAR/TMM 1.31");
    client_.configure(clientSettings(settings_, storage_->accountDir() + "/cache", quiet_));
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
        (editor_ && !editor_->isHidden()))
        return false;
    View::Kind kind = view().kind;
    return kind == View::Menu || kind == View::SettingsPage || kind == View::Choice ||
           kind == View::Files || kind == View::Templates;
}
void Window::syncSystemMenu() {
    if (!systemMenu_ || stack_.empty())
        return;
    int bottom = height() - 27;
    if (!notice_.isEmpty())
        bottom -= 52;
    else if (!ticker_.isEmpty())
        bottom -= 25;
    systemMenu_->sync(view(), systemMenuVisible(), 29, bottom);
}
void Window::update() {
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
    if (stack_.size() > 1) {
        if (view().request) {
            Command c(Command::CancelRequest);
            c.requestId = view().request;
            client_.submit(c);
            pending_.erase(c.requestId);
            pendingUin_.erase(c.requestId);
            if (captureUploads_.find(c.requestId) != captureUploads_.end()) {
                capturePath_ = captureUploads_[c.requestId];
                captureUploads_.erase(c.requestId);
            }
        }
        if (view().context == "recording")
            capture_.cancel();
        if (view().context == "capture-ready" && !capturePath_.empty()) {
            unlink(capturePath_.c_str());
            capturePath_.clear();
        }
        if (view().kind == View::Picture)
            picture_ = QPixmap();
        if (view().kind == View::Player) {
            player_.stop();
            QWidget *w = player_.videoWidget();
            if (w)
                w->hide();
        }
        stack_.pop_back();
        if (view().kind == View::Chat)
            rebuildChat();
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
void Window::applySettings() {
    setUiLanguage(settingValue(settings_, "language"));
    setFont(QFont("Helvetica", settingNumber(settings_, "font_size")));
    storage_->setHistoryLimit(settingNumber(settings_, "history_count"));
    if (isVisible()) {
        if (settingFlag(settings_, "fullscreen"))
            showFullScreen();
        else
            showNormal();
    }
    refreshBackground();
    update();
}
void Window::refreshBackground() {
    std::string f = settingValue(settings_, "background_file");
    background_ = QPixmap();
    if (!f.empty()) {
        unsigned w, h;
        std::string error;
        if (imageDimensions(f, w, h, error)) {
            QImage image;
            if (image.load(u(f))) {
                int bw = width(), bh = height() - 56;
                if (settingValue(settings_, "background_mode") == "fit") {
                    if (w * bh > h * bw)
                        bh = std::max(1, (int)(h * bw / w));
                    else
                        bw = std::max(1, (int)(w * bh / h));
                }
                if (settingValue(settings_, "background_mode") != "tile")
                    image = image.smoothScale(std::max(1, bw), std::max(1, bh));
                background_.convertFromImage(image);
            }
        } else {
            note(error);
            info(u(error));
        }
    }
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
        w->setGeometry(0, 30, width(), height() - 88);
    refreshBackground();
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
    if (editSecret_)
        editor_->setEchoMode(ZMultiLineEdit::Password);
    saveDraft();
    capture_.cancel();
}
void Window::resume() {
    // Platform refreshes the hardware flip state before requesting foreground.
    platform_.requestForeground();
    if (closed_)
        return;
    lastActivity_ = now();
    lightOn_ = true;
    if (!locked_ && editor_ && !editor_->isHidden())
        editor_->setFocus();
    else if (systemMenuVisible())
        systemMenu_->focus();
    else
        setFocus();
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
    if (editorWasVisible_)
        editor_->show();
    editorWasVisible_ = false;
    platform_.setBacklight(true);
    syncVideoVisibility();
    update();
}
void Window::tick() {
    if (takeActivationRequest())
        resume();
    unsigned long ms = now();
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
            finishEdit(true);
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
        if (code >= KEYCODE_0 && code <= KEYCODE_9 && pin_.length() < 8)
            pin_ += QChar((char)code);
        else if (code == KEYCODE_CLEAR && pin_.length())
            pin_.truncate(pin_.length() - 1);
        if (std::string(pin_.utf8()) == pin)
            unlock();
        else if ((size_t)pin_.length() >= pin.size()) {
            pin_ = QString::null;
            info(u("Неверный PIN"));
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
    if (view().kind == View::Picture) {
        if (code == KEYCODE_UP) {
            int zoom = std::min(400, pictureZoom_ + 25);
            unsigned long pixels = (unsigned long)picture_.width() * picture_.height();
            if (pixels / 100 * zoom / 100 * zoom <= 2000000UL)
                pictureZoom_ = zoom;
        } else if (code == KEYCODE_DOWN)
            pictureZoom_ = std::max(25, pictureZoom_ - 25);
        else if (code == KEYCODE_RIGHT)
            pictureRotation_ = (pictureRotation_ + 90) % 360;
        else if (code == KEYCODE_LEFT)
            pictureRotation_ = (pictureRotation_ + 270) % 360;
        else if (code == KEYCODE_RSK || code == KEYCODE_CLEAR)
            back();
        else if (code == KEYCODE_LSK)
            files("/mmc/mmca1", "save-media");
        update();
        return;
    }
    if (view().kind == View::Player) {
        if (code == KEYCODE_3 && !videoToken_.empty()) {
            nextVideo();
            return;
        }
        if (code == KEYCODE_CENTER_SELECT || code == KEYCODE_SEND) {
            if (player_.pause(!paused_))
                paused_ = !paused_;
        } else if (code == KEYCODE_LEFT)
            player_.seek(playPosition_ > 10000 ? playPosition_ - 10000 : 0);
        else if (code == KEYCODE_RIGHT)
            player_.seek(playPosition_ + 10000);
        else if (code == KEYCODE_UP || code == KEYCODE_DOWN) {
            int v = settings_.getInt("player_volume", 70) + (code == KEYCODE_UP ? 10 : -10);
            v = std::max(0, std::min(100, v));
            settings_.setInt("player_volume", v);
            player_.setVolume(v);
        } else if (code == KEYCODE_RSK || code == KEYCODE_CLEAR)
            back();
        else if (code == KEYCODE_LSK)
            playerMenu();
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
    if (code == KEYCODE_RSK || code == KEYCODE_CLEAR) {
        if (view().kind == View::Chat)
            chatMenu();
        else
            back();
        return;
    }
    if (code == KEYCODE_LSK) {
        if (view().kind == View::Chat)
            edit(u("Сообщение"), "message", storage_->loadDraft(view().uin), view().uin);
        else if (view().kind == View::Roster)
            mainMenu();
        else if (view().kind == View::History) {
            View menu(View::Menu, u("История"));
            menu.uin = view().uin;
            menu.rows.push_back(Row(u("Поиск"), "history-search"));
            menu.rows.push_back(Row(u("Очистить поиск"), "history-search-clear"));
            menu.rows.push_back(Row(u("К сообщению"), "back"));
            push(menu);
        } else
            activateSelected();
        return;
    }
    if (code == KEYCODE_LEFT || code == KEYCODE_RIGHT) {
        if (view().kind == View::Chat) {
            std::map<uint32_t, ChatState>::iterator i = chats_.find(view().uin);
            if (code == KEYCODE_RIGHT) {
                if (++i == chats_.end())
                    i = chats_.begin();
            } else {
                if (i == chats_.begin())
                    i = chats_.end();
                --i;
            }
            openChat(i->first);
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
    if (unread())
        title += " [" + number(unread()) + "]";
    systemChrome_->drawHeader(p, QRect(0, 0, width(), 28), title,
                              settingNumber(settings_, "caption_offset"));
}
void Window::drawFooter(QPainter &p) {
    QString left = u("Выбрать"), right = u("Назад");
    if (view().kind == View::Roster || view().kind == View::History)
        left = u("Меню");
    if (view().kind == View::Chat) {
        left = u("Написать");
        right = u("Меню");
    }
    if (view().kind == View::Picture)
        left = u("Сохранить");
    if (view().kind == View::Player)
        left = u("Меню");
    if (editor_ && editor_->isVisible()) {
        left = u("Отправить");
        if (editAction_ != "message")
            left = u("Сохранить");
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
int Window::rowHeight(const Row &r) const {
    if (view().kind != View::Chat && view().kind != View::History)
        return 30;
    QFontMetrics metrics(QFont("Helvetica", settingNumber(settings_, "chat_font_size")));
    return std::max(
        30, metrics.boundingRect(0, 0,
                                 std::max(1, width() - ((settingFlag(settings_, "show_icons") ||
                                                         settingFlag(settings_, "show_receipts"))
                                                            ? 30
                                                            : 12)),
                                 100000, Qt::WordBreak, r.text)
                    .height() +
                10);
}
void Window::drawList(QPainter &p) {
    View &v = view();
    bool chat = v.kind == View::Chat || v.kind == View::History;
    if (chat)
        p.setFont(QFont("Helvetica", settingNumber(settings_, "chat_font_size")));
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
        int h = rowHeight(v.rows[i]);
        bool selected = i == v.selected;
        if (selected)
            p.fillRect(0, y, width(), std::min(h, available), QColor(75, 123, 159));
        const MessageRecord *m = 0;
        if (chat && v.rows[i].action == "message-menu") {
            if (v.kind == View::History && v.rows[i].value < v.messages.size())
                m = &v.messages[v.rows[i].value];
            else {
                std::map<uint32_t, ChatState>::const_iterator c = chats_.find(v.uin);
                if (c != chats_.end() && v.rows[i].value < c->second.messages.size())
                    m = &c->second.messages[v.rows[i].value];
            }
        }
        QColor text = settingValue(settings_, "theme") == "dark" ? Qt::white : Qt::black;
        if (m && settingFlag(settings_, "colored_text"))
            text = m->outgoing ? QColor(25, 100, 55) : QColor(30, 60, 120);
        QColor ink = selected ? Qt::white : text;
        p.setPen(ink);
        bool decorated = chat && (settingFlag(settings_, "show_icons") ||
                                  settingFlag(settings_, "show_receipts"));
        int left = decorated ? 22 : 5;
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
                p.drawLine(5, iy + 4, 16, iy + 4);
                int tip = m->outgoing ? 5 : 16, base = m->outgoing ? 10 : 11;
                p.drawLine(base, iy, tip, iy + 4);
                p.drawLine(tip, iy + 4, base, iy + 8);
            }
            p.setPen(ink);
        }
        if (v.kind == View::Roster && v.rows[i].uin) {
            ContactRecord *c = contact(v.rows[i].uin);
            if (c) {
                left = 24;
                if (!statusIcons_.isNull()) {
                    p.drawPixmap(4, y + (h - 16) / 2, statusIcons_, statusIcon(c->status) * 16, 0,
                                 16, 16);
                } else {
                    QColor presence = selected                   ? Qt::white
                                      : c->status == 0xffffffffU ? Qt::gray
                                      : (c->status & 0x100)      ? QColor(190, 50, 45)
                                                                 : QColor(35, 145, 60);
                    p.setPen(QPen(presence, 2));
                    if (c->status != 0xffffffffU && (c->status & 0x100)) {
                        p.drawLine(5, y + 10, 12, y + 17);
                        p.drawLine(12, y + 10, 5, y + 17);
                    } else {
                        if (c->status != 0xffffffffU)
                            p.setBrush(presence);
                        p.drawEllipse(5, y + 10, 8, 8);
                        p.setBrush(Qt::NoBrush);
                    }
                    p.setPen(ink);
                }
            }
        }
        p.drawText(left, y + 4 - offset, width() - left - 7, h - 8,
                   Qt::AlignLeft | (chat ? Qt::WordBreak : Qt::AlignVCenter | Qt::SingleLine),
                   v.rows[i].text);
        y += std::min(h, available);
    }
    if (v.rows.empty()) {
        p.setPen(Qt::gray);
        p.drawText(8, 55, width() - 16, 90, Qt::WordBreak,
                   v.request ? u("Загрузка…") : u("Сообщений нет"));
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
    bool dark = settingValue(settings_, "theme") == "dark";
    // Transparent native skin parts blend against the phone's palette in menus.
    p.fillRect(rect(), systemMenuVisible() ? palette().active().background()
                       : dark              ? QColor(20, 22, 25)
                       : settingValue(settings_, "theme") == "blue"  ? QColor(216, 235, 252)
                       : settingValue(settings_, "theme") == "green" ? QColor(222, 246, 224)
                                                                     : QColor(245, 246, 248));
    if (!background_.isNull() && !locked_ && !systemMenuVisible()) {
        if (settingValue(settings_, "background_mode") == "tile")
            p.drawTiledPixmap(rect(), background_);
        else
            p.drawPixmap((width() - background_.width()) / 2,
                         28 + (height() - 56 - background_.height()) / 2, background_);
    }
    drawHeader(p);
    drawFooter(p);
    if (locked_) {
        p.setPen(dark ? Qt::white : Qt::black);
        QString stars;
        stars.fill('*', pin_.length());
        QString text = settingValue(settings_, "lock_pin").empty()
                           ? u("Нажмите # для разблокировки")
                           : u("Введите PIN\n") + stars;
        p.drawText(10, 55, width() - 20, height() - 100, Qt::AlignCenter | Qt::WordBreak, text);
        return;
    }
    if (view().kind == View::Picture && !picture_.isNull()) {
        QWMatrix matrix;
        double scale = (double)pictureZoom_ / 100;
        matrix.scale(scale, scale);
        matrix.rotate(pictureRotation_);
        QPixmap image = picture_.xForm(matrix);
        p.drawPixmap((width() - image.width()) / 2, (height() - image.height()) / 2, image);
    } else if (view().kind == View::Player) {
        p.setPen(dark ? Qt::white : Qt::black);
        p.drawText(8, height() - 85, width() - 16, 48, Qt::WordBreak,
                   (paused_ ? u("Пауза") : u("Воспроизведение")) + " " +
                       number(playPosition_ / 1000) + " / " + number(playDuration_ / 1000) +
                       u(" с\n←/→ ±10с; ↑/↓ громкость"));
    } else if (view().kind == View::Text && !view().rows.empty()) {
        p.setClipRect(0, 29, width(), height() - 56);
        p.setPen(dark ? Qt::white : Qt::black);
        p.drawText(5, 32 - view().selected * 25, width() - 10, 100000, Qt::WordBreak,
                   view().rows[0].text);
        p.setClipping(false);
    } else if (!systemMenuVisible())
        drawList(p);
    if (!notice_.isEmpty()) {
        p.fillRect(0, height() - 79, width(), 52, QColor(255, 245, 190));
        p.setPen(Qt::black);
        p.drawText(5, height() - 78, width() - 10, 50, Qt::WordBreak, notice_);
    } else if (!ticker_.isEmpty()) {
        p.fillRect(0, height() - 52, width(), 25, QColor(255, 245, 190));
        p.setPen(Qt::black);
        p.drawText(4, height() - 52, width() - 8, 25, Qt::SingleLine | Qt::AlignVCenter, ticker_);
    }
}
void Window::mediaPosition(unsigned int p, unsigned int d) {
    playPosition_ = p;
    playDuration_ = d;
    if (!stack_.empty() && view().kind == View::Player)
        update();
}
void Window::mediaFinished() {
    paused_ = false;
    info(u("Воспроизведение завершено"));
}
} // namespace tmm
