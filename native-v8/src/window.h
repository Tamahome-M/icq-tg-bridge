#ifndef TMM_NATIVE_WINDOW_H
#define TMM_NATIVE_WINDOW_H
#include <qwidget.h>
#include <qstring.h>
#include <qtimer.h>
#include <qpixmap.h>
#include <qsocketnotifier.h>
#include "client.h"
#include "settings.h"
#include "platform.h"
#include "media.h"
#include "capture.h"
#include <map>
#include <vector>
class ZMultiLineEdit;
namespace tmm {
class Storage;
class UiProbe;
class InputIndicator;
class SystemMenu;
class SystemChrome;
struct Row {
    QString text;
    std::string action;
    uint32_t uin;
    unsigned value;
    Row(const QString &t = QString::null, const std::string &a = "", uint32_t u = 0, unsigned v = 0)
        : text(t), action(a), uin(u), value(v) {}
};
struct View {
    enum Kind {
        Roster,
        Chat,
        History,
        Menu,
        SettingsPage,
        Choice,
        Files,
        Text,
        Picture,
        Player,
        Templates,
        Transfer,
        AttachmentReview,
        Recording
    };
    Kind kind;
    QString title;
    QString details, status;
    std::string context, directory;
    uint32_t uin, request, offset;
    int selected, top, scroll;
    bool more;
    uint64_t bytes, total;
    std::vector<Row> rows;
    std::vector<MessageRecord> messages;
    View(Kind k = Menu, const QString &t = QString::null)
        : kind(k), title(t), uin(0), request(0), offset(0), selected(0), top(0), scroll(0),
          more(false), bytes(0), total(0) {}
};
struct ChatState {
    std::vector<MessageRecord> messages;
    unsigned unread;
    unsigned long typingUntil, stamp;
    bool loaded;
    ChatState() : unread(0), typingUntil(0), stamp(0), loaded(false) {}
};
class Window : public QWidget {
    Q_OBJECT
  public:
    explicit Window(const std::string &dataDirectory);
    ~Window();
    void saveState();
    void suspend();
    void resume();

  protected:
    void paintEvent(QPaintEvent *);
    void keyPressEvent(QKeyEvent *);
    void resizeEvent(QResizeEvent *);
    void closeEvent(QCloseEvent *);
    void showEvent(QShowEvent *);
    bool eventFilter(QObject *, QEvent *);
  private slots:
    void eventsReady();
    void tick();
    void flipChanged(bool closed);
    void platformError(const QString &);
    void captureReady(const QString &, const QString &);
    void captureError(const QString &);
    void captureCancelled();
    void mediaFinished();
    void mediaPosition(unsigned int, unsigned int);
    void editorChanged();
    void inputStateChanged(int, bool);
    void systemThemeChanged();

  private:
    friend class UiProbe;
    Client client_;
    Settings settings_;
    Storage *storage_;
    Platform platform_;
    MediaController player_;
    CaptureController capture_;
    QSocketNotifier *notifier_;
    QTimer timer_;
    ZMultiLineEdit *editor_;
    InputIndicator *inputIndicator_;
    SystemMenu *systemMenu_;
    SystemChrome *systemChrome_;
    std::string data_, editAction_, editKey_, pendingFileAction_, playPath_, downloadName_,
        quoteId_, quoteText_, videoToken_, receivedPath_, receivedName_;
    uint32_t editUin_, quoteUin_, captureUin_, pickUin_, videoUin_, videoSegment_, outgoingRequest_;
    unsigned connectionState_, captureKind_, pickKind_, playPosition_, playDuration_, generation_,
        editDepth_, connectionProgress_;
    bool loadedMediaReady_, editSecret_, captureOwned_;
    bool connectionErrorShown_;
    bool locked_, closed_, editorWasVisible_, silent_, paused_, manualDisconnect_, lightOn_;
    unsigned long closedAt_, startedAt_, lastAlert_, lastActivity_, typingSentAt_;
    QString pin_, notice_, ticker_, editTitle_, connectionStage_;
    unsigned long noticeUntil_, tickerUntil_;
    int pictureZoom_, pictureRotation_;
    QPixmap picture_, background_, frame_, statusIcons_;
    std::vector<ContactRecord> contacts_;
    std::map<uint32_t, ChatState> chats_;
    std::vector<View> stack_;
    std::map<std::string, bool> collapsed_;
    std::vector<std::string> log_;
    std::vector<uint32_t> quiet_;
    std::string capturePath_, savedMediaPurpose_, managedMediaPath_;
    std::map<uint32_t, std::string> pending_;
    std::map<uint32_t, uint32_t> pendingUin_;
    View &view();
    const View &view() const;
    void syncVideoVisibility();
    void playerMenu();
    void push(const View &);
    void back();
    void home();
    void mainMenu();
    void contactMenu(uint32_t);
    void chatMenu();
    void messageMenu();
    void contactListMenu();
    void settingsMenu();
    void showSettings(const std::string &);
    void chooseSetting(const std::string &);
    void commitSetting(const std::string &, const std::string &);
    void refreshBackground();
    void applySettings();
    void activate(const Row &);
    void activateSelected();
    void key(int);
    void rebuildRoster();
    void rebuildChat();
    void openChat(uint32_t);
    void history(bool server, bool more = false);
    void showHistory(View &);
    void search(bool all = false, bool more = false);
    void showResults(const Event &);
    void showInfo(const Event &);
    ContactRecord *contact(uint32_t);
    const MessageRecord *selectedMessage() const;
    void edit(const QString &, const std::string &, const std::string &, uint32_t uin = 0,
              bool secret = false, int maximum = 4096);
    void finishEdit(bool accept);
    void editorMenu();
    void layoutEditor();
    void showTemplates(bool insert);
    void saveDraft();
    void confirm(const QString &, const std::string &, uint32_t uin = 0, unsigned value = 0);
    void showText(const QString &, const QString &);
    void info(const QString &);
    void note(const std::string &);
    void connectClient();
    void disconnectClient();
    void switchAccount(int);
    bool selectScope();
    bool send(Command);
    void consume(const Event &);
    void incoming(const MessageRecord &);
    void notify(const MessageRecord &);
    void trimChats();
    void quietToggle(uint32_t, bool);
    void lock();
    void unlock();
    void minimize();
    void requestExit();
    void files(const std::string &, const std::string &);
    void loadFiles();
    void requestMedia(unsigned);
    void showMedia(const Event &);
    void nextVideo();
    void play(const std::string &, bool audioOnly = false);
    void openUrl(const std::string &);
    void upload(const std::string &, unsigned, uint32_t);
    void attachmentMenu(uint32_t);
    void reviewAttachment(const std::string &, unsigned, uint32_t, bool);
    void showAttachmentReview();
    void discardAttachment();
    void previewAttachment();
    void completeAttachment(bool, const QString &);
    void retireTransfers();
    void removeTransfer(uint32_t);
    void showTransfer(uint32_t, uint32_t, const QString &, const QString &, bool upload);
    bool showPicture(const std::string &, const QString &, const std::string &context = "");
    bool connectionProgressVisible() const;
    void drawProgress(QPainter &, const QString &, const QString &, uint64_t, uint64_t);
    void drawAttachmentDetails(QPainter &);
    void copy(const QString &);
    QString copied() const;
    void hotkey(int);
    void settingsChanged();
    unsigned unread() const;
    QString name(uint32_t) const;
    QString status(uint32_t) const;
    QString messageText(const MessageRecord &) const;
    int rowHeight(const Row &) const;
    bool systemMenuVisible() const;
    void syncSystemMenu();
    void update();
    void drawFrame(QPainter &);
    void drawList(QPainter &);
    void drawHeader(QPainter &);
    void drawFooter(QPainter &);
};
} // namespace tmm
#endif
