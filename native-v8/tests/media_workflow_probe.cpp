// Real Window/Qt/file operations. Only command submission is observed by the
// linker. The fullscreen checks use the real video widget with a simulated decoder.
#define FEAT_KEYPAD_SUPPORT
#include "application.h"
#include <qtimer.h>
#define private public
#include "media.h"
#undef private
#include "window.h"
#include "storage.h"
#include "ui_language.h"
#include <ZKeyDef.h>
#include <qimage.h>
#include <qmetaobject.h>
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
static bool simulateVideo, seekable;
static unsigned seekTarget;
static int engineVolume;
extern "C" bool __real__ZN3tmm15MediaController4playERK7QStringib(tmm::MediaController *,
                                                                  const QString &, int, bool);
extern "C" bool __wrap__ZN3tmm15MediaController4playERK7QStringib(tmm::MediaController *media,
                                                                  const QString &file, int volume,
                                                                  bool audio) {
    if (!simulateVideo || audio)
        return __real__ZN3tmm15MediaController4playERK7QStringib(media, file, volume, audio);
    media->videoActive_ = media->ensureVideoWidget() != 0;
    return media->videoActive_;
}
extern "C" bool __real__ZN3tmm15MediaController4seekEj(tmm::MediaController *, unsigned);
extern "C" bool __wrap__ZN3tmm15MediaController4seekEj(tmm::MediaController *media,
                                                       unsigned target) {
    if (!simulateVideo)
        return __real__ZN3tmm15MediaController4seekEj(media, target);
    seekTarget = target;
    return seekable;
}
extern "C" void __real__ZN3tmm15MediaController9setVolumeEi(tmm::MediaController *, int);
extern "C" void __wrap__ZN3tmm15MediaController9setVolumeEi(tmm::MediaController *media,
                                                            int volume) {
    if (simulateVideo)
        engineVolume = volume;
    else
        __real__ZN3tmm15MediaController9setVolumeEi(media, volume);
}
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
    static void captured(Window &window, const char *path, const char *mime) {
        QMetaData *signal =
            window.capture_.metaObject()->signal("ready(const QString&,const QString&)", true);
        require(signal && !window.capture_.signalsBlocked(),
                "parented camera controller has an unblocked native Qt ready signal");
        typedef void (QObject::*Ready)(const QString &, const QString &);
        (window.capture_.*reinterpret_cast<Ready>(signal->ptr))(QString::fromLatin1(path),
                                                                QString::fromLatin1(mime));
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
        bool fullRoot = false;
        for (size_t i = 0; i < window.view().rows.size(); ++i)
            if (window.view().rows[i].action == "directory:/")
                fullRoot = true;
        require(fullRoot, "filesystem root stays available alongside the phone media root");
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
        put("/state/phone/Photo.GIF");
        pick(window, contact.uin, "upload-media", "Photo.GIF");
        require(submitted.back().type == Command::UploadFile && submitted.back().mode == 1 &&
                    submitted.back().text == "image/gif",
                "GIF photos are sent as photos rather than unrecognized documents");
        ack(window, window.outgoingRequest_, true);
        require(ensureDirectory("/state/outside", error), "photo outside mystuff fixture");
        put("/state/outside/Photo.BMP");
        window.activate(Row(QString::null, "upload-media", contact.uin));
        require(choose(window, "directory:/") && choose(window, "directory:/state") &&
                    choose(window, "directory:/state/outside"),
                "root browsing reaches media outside the predefined phone folders");
        window.activate(Row(QString::fromLatin1("Photo.BMP"), "file-select"));
        require(submitted.back().mode == 1 && submitted.back().text == "image/bmp" &&
                    submitted.back().path == "/state/outside/Photo.BMP",
                "outside BMP photo retains its actual path and photo media kind");
        ack(window, window.outgoingRequest_, true);
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
        put("/state/owned-photo.jpg");
        window.captureUin_ = contact.uin;
        captured(window, "/state/owned-photo.jpg", "image/jpeg");
        require(window.outgoingRequest_ && submitted.back().type == Command::UploadPhoto &&
                    submitted.back().uin == contact.uin,
                "actual Qt ready signal starts photo upload to the selected chat");
        ack(window, window.outgoingRequest_, true);
        require(access("/state/owned-photo.jpg", F_OK) != 0 && window.view().kind == View::Chat,
                "successful photo ACK retires the owned camera result");
        put("/state/owned-circle.3gp");
        window.captureUin_ = contact.uin;
        captured(window, "/state/owned-circle.3gp", "video/3gpp");
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
        require(window.view().kind == View::Picture && zoom == 25,
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
        for (unsigned rotation = 0; rotation < 3; ++rotation) {
            window.settings_.setInt("video_rotate", rotation);
            window.requestMedia(2);
            const Command videoRequest = submitted.back();
            require(videoRequest.type == Command::Video &&
                        videoRequest.mode == (rotation == 1   ? 0x20
                                              : rotation == 2 ? 0x10
                                                              : 0) &&
                        videoRequest.media.find(8)->second == (rotation == 2 ? 2u : 1u) &&
                        videoRequest.media.find(21)->second == 2,
                    "native auto/always/never rotation and MPEG-4 reach the bridge");
            window.nextVideo();
            require(submitted.back().type == Command::Video && submitted.back().offset == 1 &&
                        submitted.back().mode == videoRequest.mode &&
                        submitted.back().media == videoRequest.media,
                    "next segment preserves rotation and codec settings");
            window.back();
            window.back();
        }
        window.settings_.setInt("video_rotate", 0);
        window.settings_.setInt("video_seconds", 3600);
        window.settings_.setInt("video_kbps", 1024);
        window.settings_.setInt("video_kb", 524288);
        window.requestMedia(2);
        require(submitted.back().media[7] == 3600 && submitted.back().media[6] == 1024 &&
                    submitted.back().media[12] == 65535 && submitted.back().media[22] == 512 &&
                    submitted.back().media[23] == 1,
                "one-hour high-quality video carries large limits without u16 truncation");
        window.back();
        window.settings_.setInt("video_seconds", 0);
        window.settings_.setInt("video_kbps", 0);
        window.settings_.setInt("video_kb", 0);
        cacheReopen(window, cache, contact.uin);
        window.openChat(contact.uin, false);
        videoControls(window);
        fprintf(stderr, "MEDIA UI COMPLETE: %u checks\n", checks_);
        scene(window, contact.uin);
    }
    static void press(Window &window, int code) {
        QKeyEvent key(QEvent::KeyPress, code, 0, 0);
        QApplication::sendEvent(&window, &key);
    }
    static void videoControls(Window &window) {
        simulateVideo = seekable = true;
        window.settings_.setInt("player_volume", 70);
        window.play("/state/local.3gp", false, true);
        QWidget *surface = window.player_.videoWidget();
        require(
            surface && surface->isVisible() && surface->geometry() == window.rect() &&
                surface->focusPolicy() == QWidget::NoFocus && window.fullScreenMedia(),
            "outgoing video preview uses a full-size Motorola surface and leaves keys with Window");
        window.mediaPosition(2500, 27000);
        press(window, KEYCODE_RIGHT);
        require(seekTarget == 12500 && window.playPosition_ == 12500,
                "Right seeks forward ten seconds");
        press(window, KEYCODE_6);
        press(window, KEYCODE_6);
        require(seekTarget == 26500 && window.playPosition_ == 26500, "repeat seeks clamp at end");
        seekable = false;
        press(window, KEYCODE_LEFT);
        require(seekTarget == 16500 && window.playPosition_ == 26500,
                "failed seek preserves position");
        seekable = true;
        for (int i = 0; i < 3; ++i)
            press(window, KEYCODE_4);
        require(seekTarget == 0 && window.playPosition_ == 0, "backward seeks clamp at start");
        press(window, KEYCODE_SIDE_UP);
        require(engineVolume == 86, "side volume up advances one of seven hardware levels");
        for (int i = 0; i < 9; ++i)
            press(window, KEYCODE_SIDE_DOWN);
        require(engineVolume == 0 && !window.settings_.getInt("player_volume"),
                "side volume reaches mute");
        for (int i = 0; i < 9; ++i)
            press(window, KEYCODE_SIDE_UP);
        require(engineVolume == 100, "side volume clamps at maximum");
        const size_t before = submitted.size();
        press(window, KEYCODE_3);
        require(submitted.size() == before && window.fullScreenMedia(),
                "camera preview has no next network segment");
        window.lock();
        require(surface->isHidden(), "locking covers video");
        window.unlock();
        require(surface->isVisible() && surface->geometry() == window.rect(),
                "unlock restores fullscreen video");
        press(window, KEYCODE_LSK);
        require(!window.fullScreenMedia() && surface->isHidden() &&
                    window.view().kind == View::Chat,
                "back closes video surface and returns to chat");
        window.play("/state/local.3gp", false);
        const QString reason = QString::fromLatin1("Decoder stopped");
        window.player_.pendingError_ = reason;
        window.player_.pending_ = 3;
        window.player_.dispatch();
        require(window.view().status == reason && surface->isHidden(),
                "decoder failure remains readable inside the fullscreen viewer");
        press(window, KEYCODE_0);
        simulateVideo = false;
    }
    static void cacheReopen(Window &window, const std::string &cache, uint32_t target) {
        window.openChat(target, false);
        window.chats_[target].messages.clear();
        MessageRecord photo;
        photo.uin = target;
        photo.kind = 1;
        photo.token = std::string(16, 'p');
        window.chats_[target].messages.push_back(photo);
        window.rebuildChat();
        size_t before = submitted.size();
        window.requestMedia(1);
        require(submitted.size() == before + 1 && submitted.back().type == Command::Photo,
                "first photo open requests the bridge");
        const Command first = submitted.back();
        QImage jpeg(240, 320, 32);
        jpeg.fill(0xff224488);
        Event ready(Event::Media);
        ready.requestId = first.requestId;
        ready.path = cache + "media-photo-a.jpg";
        ready.filename = "photo.jpg";
        require(jpeg.save(QString::fromLatin1(ready.path.c_str()), "JPEG"),
                "cache fixture is a real JPEG");
        window.consume(ready);
        require(window.view().kind == View::Picture && window.mediaCache_.owns(ready.path),
                "completed photo enters disk cache and the real Qt viewer");
        QPixmap canvas(window.size());
        QPainter painter(&canvas);
        window.drawFrame(painter);
        painter.end();
        const QImage image = canvas.convertToImage();
        const unsigned center = image.pixel(image.width() / 2, image.height() / 2);
        require(window.fullScreenMedia() && window.pictureZoom_ == 100 &&
                    image.pixel(0, 0) == center &&
                    image.pixel(image.width() - 1, image.height() - 1) == center,
                "portrait photo covers first and last display rows without status or softkey bars");
        window.back();
        require(!window.fullScreenMedia(), "leaving photo restores the chat frame");
        require(window.picture_.isNull(), "closing a cached photo releases decoded pixels");
        before = submitted.size();
        window.requestMedia(1);
        require(submitted.size() == before && window.view().kind == View::Picture &&
                    window.playPath_ == ready.path,
                "reopening a photo reads the cache without submitting a download");
        window.back();
        photo.token.assign(16, 'q');
        window.chats_[target].messages.push_back(photo);
        window.rebuildChat();
        window.view().selected = 1;
        window.requestMedia(1);
        ready.requestId = submitted.back().requestId;
        const std::string firstPath = ready.path;
        ready.path = cache + "media-photo-b.jpg";
        require(jpeg.save(QString::fromLatin1(ready.path.c_str()), "JPEG"),
                "second cache JPEG fixture");
        window.consume(ready);
        window.back();
        window.view().selected = 0;
        before = submitted.size();
        window.requestMedia(1);
        require(submitted.size() == before && window.playPath_ == firstPath,
                "viewing another photo preserves the earlier cached photo");
        window.back();
        unlink(firstPath.c_str());
        before = submitted.size();
        window.requestMedia(1);
        require(submitted.size() == before + 1 && window.view().kind == View::Transfer,
                "a cache file removed from disk is downloaded again");
        const unsigned cancelled = submitted.back().requestId;
        window.back();
        require(window.mediaRequests_.find(cancelled) == window.mediaRequests_.end(),
                "cancel removes the pending cache entry");
        photo.kind = 2;
        photo.token.assign(16, 'v');
        photo.text = "[видео](http://bridge.test/v/1234567890abcdef) 0:08\nVideo caption";
        window.chats_[target].messages.clear();
        window.chats_[target].messages.push_back(photo);
        window.rebuildChat();
        window.view().selected = 0;
        require(window.view().rows[0].text.find("http://") < 0 &&
                    window.view().rows[0].text.find("Video caption") >= 0 &&
                    window.chats_[target].messages[0].text == photo.text,
                "video display hides its URL while preserving caption and original message");
        window.requestMedia(2);
        const Command video = submitted.back();
        ready.requestId = video.requestId;
        ready.path = cache + "media-video.3gp";
        ready.filename = "video.3gp";
        put(ready.path);
        window.lock();
        window.consume(ready);
        require(window.receivedDeferred_ && window.mediaCache_.owns(ready.path),
                "complete background video is retained on disk without starting hardware playback");
        before = submitted.size();
        window.requestMedia(2);
        require(submitted.size() == before && window.receivedPath_ == ready.path,
                "reopening complete video uses cache without requesting the bridge");
        window.nextVideo();
        require(submitted.back().type == Command::Video && submitted.back().offset == 1 &&
                    submitted.back().media == video.media,
                "next video segment uses the same conversion profile and a distinct cache key");
        window.back();
        window.receivedDeferred_ = false;
        window.unlock();
        window.home();
        require(window.selectScope() && access(ready.path.c_str(), F_OK) != 0,
                "changing account scope removes only the owned media cache");
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
    chdir("/work"); // Match the launcher resource directory, as ui-probe does.
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
