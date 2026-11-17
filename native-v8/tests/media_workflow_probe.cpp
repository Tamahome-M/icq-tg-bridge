// State-machine regression on the real native Window/Qt widgets. Only network
// submission is intercepted; no camera/microphone success is simulated.
#define FEAT_KEYPAD_SUPPORT
#include "application.h"
#include "window.h"
#include "storage.h"
#include "ui_language.h"
#include "system_menu.h"
#include <ZListBox.h>
#include <ZKeyDef.h>
#include <qimage.h>
#include <qtimer.h>
#include <sys/stat.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vector>
extern "C" void UTIL_SetPowerOnHandleStatus(int);
extern "C" void UTIL_SetFlipStatus(int);
extern "C" void UTIL_SetKeypadLockStatus(bool);
static std::vector<tmm::Command> submitted;
extern "C" bool __wrap__ZN3tmm6Client6submitERKNS_7CommandE(tmm::Client *, const tmm::Command &c) {
    submitted.push_back(c);
    return true;
}
namespace tmm {
class UiProbe {
    static unsigned checks_;
    static void require(bool value, const char *name) {
        if (!value) {
            fprintf(stderr, "MEDIA UI FAIL: %s\n", name);
            exit(2);
        }
        ++checks_;
        fprintf(stderr, "MEDIA UI PASS: %s\n", name);
    }
    static bool hasAction(Window &w, const char *action) {
        for (size_t i = 0; i < w.view().rows.size(); ++i)
            if (w.view().rows[i].action == action)
                return true;
        return false;
    }
    static void choose(Window &w, const char *action) {
        for (size_t i = 0; i < w.view().rows.size(); ++i)
            if (w.view().rows[i].action == action) {
                w.activate(w.view().rows[i]);
                return;
            }
        require(false, action);
    }
    static void file(const char *path) {
        FILE *f = fopen(path, "wb");
        require(f != 0, "create fixture file");
        require(fwrite("test file payload", 1, 17, f) == 17 && fclose(f) == 0,
                "write fixture file");
    }
    static void progress(Window &w, uint32_t request, uint64_t bytes, uint64_t total) {
        Event e(Event::Progress);
        e.requestId = request;
        e.bytes = bytes;
        e.total = total;
        w.consume(e);
    }
    static void result(Window &w, uint32_t request, bool ok) {
        Event e(Event::CommandResult);
        e.requestId = request;
        e.flag = ok;
        e.text = ok ? "confirmed" : "rejected";
        w.consume(e);
    }
    static void preview(Window &w, const char *path, const char *purpose) {
        Event e(Event::Media);
        e.path = path;
        e.filename = "phone-photo.jpg";
        e.requestId = 501;
        w.pending_[e.requestId] = purpose;
        w.showMedia(e);
        w.pending_.erase(e.requestId);
    }

  public:
    static void run(Window &w) {
        w.timer_.stop();
        w.settings_.setInt("auto_connect", 0);
        w.settings_.setInt("auto_reconnect", 0);
        // This fixture tests transitions, not physical sound/vibration devices.
        // Reconnecting from Online otherwise plays the configured native tone.
        w.settings_.setInt("disconnect_sound", 0);
        w.settings_.set("sound_unlocked", "");
        w.settings_.set("sound_locked", "");
        w.settings_.set("vibration_unlocked", "0");
        w.settings_.set("vibration_locked", "0");
        w.settings_.set("typing_sound", "");
        w.silent_ = true;
        w.settings_.set("host", "bridge.example.test");
        w.settings_.set("uin", "123456");
        require(w.selectScope(), "media account scope");
        w.connectionState_ = Event::Online;
        w.notice_ = QString::null;
        ContactRecord c;
        c.uin = 1000001;
        c.name = "Chat with a readable recipient name";
        c.inRoster = true;
        w.contacts_.push_back(c);
        w.openChat(c.uin);
        w.chatMenu();
        require(hasAction(w, "attachments") && !hasAction(w, "capture-photo"),
                "chat groups media into one attachment action");
        choose(w, "attachments");
        require(hasAction(w, "capture-photo") && hasAction(w, "capture-video") &&
                    hasAction(w, "pick-video") && hasAction(w, "upload-file"),
                "attachment menu distinguishes camera circle and ordinary file video");
        choose(w, "upload-file");
        require(w.view().kind == View::Files && w.view().directory.empty() &&
                    !w.view().rows.empty(),
                "picker opens storage choices without assuming MMC");
        file("/state/user-file.bin");
        w.view().directory = "/state";
        w.loadFiles();
        size_t before = submitted.size();
        bool selectedFile = false;
        for (size_t i = 0; i < w.view().rows.size(); ++i)
            if (w.view().rows[i].action == "file-select" &&
                w.view().rows[i].text == "user-file.bin") {
                w.activate(w.view().rows[i]);
                selectedFile = true;
                break;
            }
        require(selectedFile, "directory listing supplies the selectable file row");
        require(w.view().kind == View::AttachmentReview && w.captureUin_ == c.uin &&
                    !w.captureOwned_ && submitted.size() == before,
                "file selection opens recipient/name/size review without sending");
        choose(w, "capture-send");
        uint32_t request = w.outgoingRequest_;
        require(request && submitted.back().type == Command::UploadFile &&
                    w.view().kind == View::Transfer && !w.systemMenuVisible(),
                "send enters full-screen transfer rather than clipped one-row menu");
        progress(w, request, 25, 100);
        require(w.view().bytes == 25 && w.view().total == 100,
                "transfer keeps actual byte progress");
        progress(w, request, 100, 100);
        require(w.outgoingRequest_ == request &&
                    w.view().status == uiText("Ожидание подтверждения моста…"),
                "all bytes sent still wait for bridge ACK");
        w.back();
        require(!w.outgoingRequest_ && w.view().kind == View::AttachmentReview &&
                    submitted.back().type == Command::CancelRequest &&
                    access("/state/user-file.bin", F_OK) == 0,
                "cancel retains retry review and user-owned file");
        QString notice = w.notice_;
        result(w, request, true);
        require(w.view().kind == View::AttachmentReview && w.notice_ == notice,
                "late ACK of cancelled upload cannot report false success");
        choose(w, "capture-send");
        request = w.outgoingRequest_;
        result(w, request, true);
        require(w.view().kind == View::Chat && w.view().uin == c.uin && w.capturePath_.empty() &&
                    access("/state/user-file.bin", F_OK) == 0,
                "successful file send closes review and preserves original source");
        file("/state/ordinary-video.3gp");
        w.reviewAttachment("/state/ordinary-video.3gp", 2, c.uin, false);
        choose(w, "capture-send");
        require(submitted.back().type == Command::UploadFile && submitted.back().mode == 2,
                "ordinary selected video uses document mode2, not circle opcode");
        request = w.outgoingRequest_;
        result(w, request, false);
        require(!w.outgoingRequest_ && w.view().kind == View::AttachmentReview &&
                    access("/state/ordinary-video.3gp", F_OK) == 0,
                "negative ACK restores valid retry review");
        w.back();
        w.reviewAttachment("/state/ordinary-video.3gp", 2, c.uin, false);
        w.home();
        w.mainMenu();
        choose(w, "attachment-pending");
        choose(w, "attachment-replace");
        require(w.view().kind == View::Files && w.view().context == "upload" &&
                    w.pickUin_ == c.uin && w.pickKind_ == 2,
                "recovered review can choose another file with the same recipient and type");
        w.home();
        file("/state/captured-circle.3gp");
        w.reviewAttachment("/state/captured-circle.3gp", 2, c.uin, true);
        w.videoToken_ = std::string(16, 'v');
        View localPlayer(View::Player, uiText("Плеер"));
        localPlayer.context = "outgoing-preview";
        w.push(localPlayer);
        w.playerMenu();
        require(!hasAction(w, "player-next"),
                "local recording preview menu never offers unrelated downloaded segments");
        w.back();
        before = submitted.size();
        w.key(KEYCODE_3);
        require(submitted.size() == before,
                "local recording preview key3 cannot request a previous chat video");
        w.back();
        w.videoToken_.clear();
        choose(w, "capture-send");
        require(submitted.back().type == Command::UploadVideo && !w.capturePath_.empty(),
                "captured circle keeps its owned path until ACK");
        Event state(Event::State);
        state.state = Event::Reconnecting;
        w.consume(state);
        require(!w.outgoingRequest_ && w.view().kind == View::AttachmentReview &&
                    access("/state/captured-circle.3gp", F_OK) == 0,
                "reconnect restores owned capture review without permanent busy state");
        w.connectionState_ = Event::Online;
        choose(w, "capture-send");
        request = w.outgoingRequest_;
        Event error(Event::Error);
        error.requestId = request;
        error.text = "Upload error";
        w.consume(error);
        require(!w.outgoingRequest_ && w.view().kind == View::AttachmentReview &&
                    access("/state/captured-circle.3gp", F_OK) == 0,
                "upload error preserves recording for retry");
        choose(w, "capture-send");
        result(w, w.outgoingRequest_, true);
        require(w.capturePath_.empty() && access("/state/captured-circle.3gp", F_OK) != 0 &&
                    w.view().kind == View::Chat,
                "positive ACK deletes only the owned capture");
        View recording(View::Recording, uiText("Голосовое"));
        recording.context = "recording";
        w.push(recording);
        w.capture_.recordVoice(QString::fromLatin1("/state/missing-capture-parent/voice.amr"), 1);
        require(w.view().kind != View::Recording && !w.capture_.busy(),
                "real immediate capture error signal retires idle recording screen");
        w.push(recording);
        w.captureCancelled();
        require(w.view().kind != View::Recording, "terminal cancellation retires recording screen");
        QImage image(960, 1280, 32);
        image.fill(0xff224488);
        require(image.save("/state/phone-photo.jpg", "JPEG"), "real Qt image fixture");
        w.notice_ = QString::null;
        preview(w, "/state/phone-photo.jpg", "photo");
        int photoZoom = w.pictureZoom_;
        require(w.view().kind == View::Picture && photoZoom < 25 &&
                    image.height() * photoZoom / 100 <= w.height() - 94,
                "received photo fits both width and height below 25 percent");
        w.key(KEYCODE_UP);
        w.key(KEYCODE_RIGHT);
        require(w.pictureZoom_ > photoZoom && w.pictureRotation_ == 90,
                "received photo supports zoom and rotation");
        w.back();
        preview(w, "/state/phone-photo.jpg", "avatar");
        require(w.view().kind == View::Picture && w.pictureZoom_ == photoZoom &&
                    w.pictureRotation_ == 0,
                "avatar and received photo share the same viewer");
        w.back();
        std::string received = w.receivedPath_;
        w.reviewAttachment("/state/phone-photo.jpg", 1, c.uin, false);
        choose(w, "capture-preview");
        require(w.view().context == "outgoing-preview" && w.receivedPath_ == received &&
                    w.savedMediaPurpose_ == "avatar",
                "outgoing preview preserves received attachment state");
        w.back();
        w.back();
        require(access("/state/phone-photo.jpg", F_OK) == 0 && w.receivedPath_ == received,
                "discarding a selected photo keeps its file and received menu target");
        w.reviewAttachment("/state/phone-photo.jpg", 1, c.uin, false);
        choose(w, "capture-send");
        require(submitted.back().type == Command::UploadFile && submitted.back().mode == 1,
                "photo from memory uses full-size document photo mode1");
        w.back();
        w.back();
        w.notice_ = QString::null;
        w.home();
        w.connectionState_ = Event::Connecting;
        Event stage(Event::Progress);
        stage.bytes = 65;
        stage.total = 100;
        stage.text = "Protocol negotiation";
        w.consume(stage);
        require(w.connectionProgressVisible() && w.connectionProgress_ == 65 &&
                    w.connectionStage_ == QString::fromLatin1("Protocol negotiation"),
                "connection stages feed the full-screen progress view");
        w.key(KEYCODE_RSK);
        require(w.view().kind == View::Menu && hasAction(w, "disconnect"),
                "connection progress keeps cancellation menu accessible");
        w.back();
        w.key(KEYCODE_LSK);
        require(w.connectionState_ == Event::Disconnected, "connection progress cancel works");
        fprintf(stderr, "MEDIA UI COMPLETE: %u checks\n", checks_);
        scene(w, c.uin);
    }
    static void scene(Window &w, uint32_t target) {
        const char *scene = getenv("TMM_NATIVE_MEDIA_SCENE");
        w.notice_ = QString::null;
        w.connectionState_ = Event::Online;
        w.home();
        if (scene && !strcmp(scene, "roots"))
            w.files("", "upload");
        else if (scene && !strcmp(scene, "connection")) {
            w.connectionState_ = Event::Connecting;
            w.connectionProgress_ = 65;
            w.connectionStage_ = uiText("Согласование протокола");
        } else if (scene && !strcmp(scene, "review"))
            w.reviewAttachment("/state/phone-photo.jpg", 1, target, false);
        else if (scene && !strcmp(scene, "photo"))
            preview(w, "/state/phone-photo.jpg", "photo");
        else {
            bool ack = scene && !strcmp(scene, "ack");
            w.showTransfer(999, target, uiText(ack ? "Отправка" : "Загрузка"),
                           QString::fromLatin1("very-long-video-filename-from-an-attachment.3gp"),
                           ack);
            w.view().bytes = ack ? 100000 : 25000;
            // BART downloads announce parts, not their final byte length.
            w.view().total = ack ? 100000 : 0;
            w.view().status = ack ? uiText("Ожидание подтверждения моста…")
                                  : QString::fromUtf8("Получена часть 2 из 5");
        }
        w.update();
    }
};
unsigned UiProbe::checks_ = 0;
} // namespace tmm
int main(int argc, char **argv) {
    if (!getenv("V8_QWS_LOCAL_ONLY"))
        return 3;
    tmm::Application app(argc, argv, QApplication::GuiServer);
    UTIL_SetPowerOnHandleStatus(10);
    UTIL_SetFlipStatus(SYSTEM_FLIP_OPEN);
    UTIL_SetKeypadLockStatus(false);
    tmm::Window window("/state/media-ui-data");
    app.setMainWidget(&window);
    window.resize(240, 320);
    window.showFullScreen();
    tmm::UiProbe::run(window);
    QTimer::singleShot(1800, &app, SLOT(quit()));
    return app.exec();
}
