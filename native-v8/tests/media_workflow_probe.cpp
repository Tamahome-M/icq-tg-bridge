// Real Window/Qt/file operations. Only command submission is observed by the
// linker; no physical camera, microphone, player or network success is claimed.
#define FEAT_KEYPAD_SUPPORT
#include "application.h"
#include "window.h"
#include "storage.h"
#include "ui_language.h"
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
    static void require(bool value, const char *reason) {
        if (!value) {
            fprintf(stderr, "MEDIA UI FAIL: %s\n", reason);
            exit(2);
        }
        ++checks_;
        fprintf(stderr, "MEDIA UI PASS: %s\n", reason);
    }
    static void put(const std::string &path, const char *data = "fixture payload") {
        FILE *file = fopen(path.c_str(), "wb");
        require(file != 0, "fixture file is writable");
        const size_t length = strlen(data);
        require(fwrite(data, 1, length, file) == length && !fclose(file),
                "fixture payload written");
    }
    static bool choose(Window &window, const std::string &action) {
        for (size_t i = 0; i < window.view().rows.size(); ++i)
            if (window.view().rows[i].action == action) {
                window.activate(window.view().rows[i]);
                return true;
            }
        return false;
    }
    static void ack(Window &window, uint32_t request, bool ok) {
        Event event(Event::CommandResult);
        event.requestId = request;
        event.flag = ok;
        event.text = ok ? "confirmed" : "rejected";
        window.consume(event);
    }
    static void received(Window &window, const std::string &path, const char *purpose,
                         const char *name = "same-name.bin") {
        Event event(Event::Media);
        event.path = path;
        event.filename = name;
        event.requestId = 710;
        window.pending_[event.requestId] = purpose;
        window.showMedia(event);
        window.pending_.erase(event.requestId);
    }
    static void pick(Window &window, uint32_t target, const char *action, const char *name) {
        window.activate(Row(QString::null, action, target));
        require(window.view().kind == View::Files && window.view().title == "Root",
                "Java file action opens Root directly");
        require(choose(window, "directory:/state/phone"), "Root contains an actual phone root");
        bool selected = false;
        for (size_t i = 0; i < window.view().rows.size(); ++i)
            if (window.view().rows[i].action == "file-select" &&
                window.view().rows[i].text == QString::fromLatin1(name)) {
                window.activate(window.view().rows[i]);
                selected = true;
                break;
            }
        require(selected && window.view().kind == View::Transfer && window.outgoingRequest_,
                "choosing a real file row sends immediately without a review window");
    }

  public:
    static void run(Window &window) {
        window.timer_.stop();
        window.silent_ = true;
        window.settings_.setInt("auto_connect", 0);
        window.settings_.setInt("auto_reconnect", 0);
        window.settings_.setInt("disconnect_sound", 0);
        window.settings_.set("sound_unlocked", "");
        window.settings_.set("sound_locked", "");
        window.settings_.set("vibration_unlocked", "0");
        window.settings_.set("vibration_locked", "0");
        window.settings_.set("host", "bridge.example.test");
        window.settings_.set("uin", "123456");
        require(window.selectScope(), "media account scope");
        std::string error;
        require(ensureDirectory("/state/phone", error), "phone storage fixture");
        setenv("MYSTUFF_DATA_PATH", "/state/phone", 1);
        const std::string cache = window.storage_->accountDir() + "/cache/";
        require(ensureDirectory(cache, error), "real account media cache");
        ContactRecord contact;
        contact.uin = 1000001;
        contact.name = "Сергей";
        contact.inRoster = true;
        window.contacts_.push_back(contact);
        window.connectionState_ = Event::Online;
        window.openChat(contact.uin);
        window.notice_ = QString::null;
        put("/state/phone/Photo.JPEG");
        pick(window, contact.uin, "upload-file", "Photo.JPEG");
        require(submitted.back().type == Command::UploadFile && submitted.back().mode == 0,
                "Send file keeps a photo as an ordinary document");
        const uint32_t cancelled = window.outgoingRequest_;
        window.mediaKey(KEYCODE_LSK);
        require(!window.outgoingRequest_ && access("/state/phone/Photo.JPEG", F_OK) == 0,
                "Back cancels file upload and preserves the user's original");
        QString notice = window.notice_;
        ack(window, cancelled, true);
        require(window.notice_ == notice, "late cancelled ACK is ignored");
        pick(window, contact.uin, "upload-media", "Photo.JPEG");
        require(submitted.back().type == Command::UploadFile && submitted.back().mode == 1,
                "Send photo/video detects JPEG suffix case-insensitively");
        ack(window, window.outgoingRequest_, true);
        require(window.view().kind == View::Chat && access("/state/phone/Photo.JPEG", F_OK) == 0,
                "photo ACK returns to the original chat without deleting its source");
        put("/state/phone/movie.MOV");
        pick(window, contact.uin, "upload-media", "movie.MOV");
        require(submitted.back().type == Command::UploadFile && submitted.back().mode == 2,
                "media picker routes MOV as ordinary video, never a circle");
        ack(window, window.outgoingRequest_, true);
        put("/state/phone/sound.MP3");
        pick(window, contact.uin, "upload-media", "sound.MP3");
        require(submitted.back().type == Command::UploadFile && submitted.back().mode == 0,
                "unknown photo/video suffix remains a document as in Java");
        ack(window, window.outgoingRequest_, true);
        // A supplied result tests only the GUI boundary; it does not simulate
        // successful physical shooting/recording or validate camera hardware.
        put("/state/owned-circle.3gp");
        window.captureUin_ = contact.uin;
        window.captureReady(QString::fromLatin1("/state/owned-circle.3gp"), "video/3gpp");
        require(window.outgoingRequest_ && submitted.back().type == Command::UploadVideo,
                "provided camera result starts circle upload without a review screen");
        ack(window, window.outgoingRequest_, false);
        require(window.view().context == "transfer-failed" &&
                    access("/state/owned-circle.3gp", F_OK) == 0,
                "negative ACK retains the owned recording on a plain failure screen");
        window.mediaKey(KEYCODE_5);
        require(window.outgoingRequest_ && submitted.back().type == Command::UploadVideo,
                "retained recording can retry without another review menu");
        Event state(Event::State);
        state.state = Event::Reconnecting;
        window.consume(state);
        require(!window.outgoingRequest_ && window.view().context == "transfer-failed" &&
                    access("/state/owned-circle.3gp", F_OK) == 0,
                "reconnect preserves the recording and a usable failure screen");
        window.connectionState_ = Event::Online;
        window.mediaKey(KEYCODE_5);
        ack(window, window.outgoingRequest_, true);
        require(access("/state/owned-circle.3gp", F_OK) != 0 && window.view().kind == View::Chat,
                "only successful ACK deletes the owned temporary recording");
        size_t before = submitted.size();
        window.beginCapture(3, contact.uin);
        require(window.view().context == "recording-idle" && !window.capture_.busy() &&
                    submitted.size() == before,
                "voice screen waits for Fire before opening the microphone");
        // Make the genuine reserve() fail before any microphone/thread is opened.
        std::string account = window.storage_->accountDir();
        require(!rename(account.c_str(), (account + "-held").c_str()),
                "temporarily hide account directory");
        window.mediaKey(KEYCODE_5);
        require(!window.capture_.busy() && window.view().context == "recording-idle" &&
                    window.view().status == uiText("Голосовое недоступно"),
                "Fire starts capture and the real reserve-error signal leaves a retryable voice "
                "screen");
        require(!rename((account + "-held").c_str(), account.c_str()), "restore account directory");
        window.back();
        put(cache + "file-one", "first original");
        received(window, cache + "file-one", "file");
        require(window.view().context == "file-saved" &&
                    window.receivedPath_ == "/state/phone/tmm/same-name.bin" &&
                    access((cache + "file-one").c_str(), F_OK) != 0 &&
                    access("/state/phone/tmm/same-name.bin", F_OK) == 0,
                "download commits directly to phone/tmm then shows Saved without a file menu");
        window.back();
        put(cache + "file-two", "second original");
        received(window, cache + "file-two", "file");
        require(window.receivedPath_ == "/state/phone/tmm/same-name-1.bin" &&
                    access("/state/phone/tmm/same-name.bin", F_OK) == 0,
                "download name collision creates a suffix and preserves the first file");
        window.back();
        put(cache + "file-three", "background original");
        window.hide();
        received(window, cache + "file-three", "file");
        require(window.receivedDeferred_ && !window.isVisible() &&
                    access("/state/phone/tmm/same-name-2.bin", F_OK) == 0,
                "background file saves immediately without opening hidden UI");
        window.show();
        window.openDeferredMedia();
        require(!window.receivedDeferred_ && window.view().context == "file-saved" &&
                    access("/state/phone/tmm/same-name-3.bin", F_OK) != 0,
                "foreground opens the deferred Saved window without duplicating the file");
        window.back();
        QImage image(960, 1280, 32);
        image.fill(0xff224488);
        require(image.save("/state/phone/photo.jpg", "JPEG"), "real Qt JPEG fixture");
        received(window, "/state/phone/photo.jpg", "photo", "photo.jpg");
        const int zoom = window.pictureZoom_;
        require(window.view().kind == View::Picture && zoom < 25,
                "received photo uses the common fitted image viewer");
        window.key(KEYCODE_UP);
        window.key(KEYCODE_RIGHT);
        require(window.pictureZoom_ > zoom && window.pictureRotation_ == 90,
                "explicitly requested zoom and rotation remain available");
        window.key(KEYCODE_5);
        require(window.view().kind != View::Picture, "Java Fire5 closes the picture viewer");
        received(window, "/state/phone/photo.jpg", "avatar", "photo.jpg");
        require(window.pictureZoom_ == zoom && window.pictureRotation_ == 0,
                "avatar and received photo use identical viewer setup");
        window.back();
        MessageRecord video;
        video.uin = contact.uin;
        video.kind = 2;
        video.token = std::string(16, 'a');
        video.url = "http://bridge.example.test/video";
        window.chats_[contact.uin].messages.push_back(video);
        window.rebuildChat();
        window.view().selected = window.view().rows.size() - 1;
        before = submitted.size();
        window.activateMedia(Row(QString::null, "video-menu", contact.uin));
        require(window.view().context == "video-choice" && window.view().rows.size() == 2 &&
                    window.view().rows[1].text == uiText("Смотреть в браузере") &&
                    submitted.size() == before,
                "Java video submenu appears before requesting any video bytes");
        window.activateMedia(window.view().rows[0]);
        require(submitted.back().type == Command::Video && window.view().context == "transfer",
                "Watch closes the chooser and starts the selected video's download");
        window.back();
        window.notice_ = QString::null;
        fprintf(stderr, "MEDIA UI COMPLETE: %u checks\n", checks_);
        scene(window, contact.uin);
    }
    static void scene(Window &window, uint32_t target) {
        const char *scene = getenv("TMM_NATIVE_MEDIA_SCENE");
        window.home();
        window.connectionState_ = Event::Online;
        window.notice_ = QString::null;
        if (scene && !strcmp(scene, "roots"))
            window.files("", "upload");
        else if (scene && !strcmp(scene, "photo"))
            received(window, "/state/phone/photo.jpg", "photo", "photo.jpg");
        else if (scene && !strcmp(scene, "voice"))
            window.beginCapture(3, target);
        else if (scene && !strcmp(scene, "connection")) {
            window.connectionState_ = Event::Connecting;
            window.connectionProgress_ = 65;
            window.connectionStage_ = uiText("Согласование протокола");
        } else {
            window.showTransfer(999, target, uiText("Смотреть видео"), QString::null, false);
            window.view().directory = "video";
            window.view().bytes = 25000;
            window.view().status = QString::fromUtf8("Загрузка видео... 2/5");
            window.view().details = QString::fromUtf8("24/60 КБ");
        }
        window.update();
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
