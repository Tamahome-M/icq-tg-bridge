#include "window.h"
#include "storage.h"
#include "ui_settings.h"
#include "ui_language.h"
#include "ui_files.h"
#include "capture_media.h"
#include <dirent.h>
#include <errno.h>
#include <unistd.h>
#include <qfileinfo.h>
#include <ZMultiLineEdit.h>
#include <qdir.h>
#include <qfile.h>
#include <qimage.h>
#include <qstringlist.h>
#include <sys/stat.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <algorithm>
#include <stdlib.h>
#include <set>
namespace tmm {
static QString u(const char *s) {
    return uiText(s);
}
static QString u(const std::string &s) {
    return QString::fromUtf8(s.c_str());
}
static std::string fileName(const std::string &path) {
    size_t slash = path.find_last_of("/\\");
    return path.substr(slash == std::string::npos ? 0 : slash + 1);
}
static QString mediaSize(uint64_t bytes) {
    char value[48];
    snprintf(value, sizeof(value), "%llu", (unsigned long long)bytes);
    return QString::fromLatin1(value) + u(" байт");
}
static QString attachmentType(unsigned kind, bool captured) {
    return u(kind == 1   ? "Фото"
             : kind == 2 ? (captured ? "Кружок" : "Видео")
             : kind == 3 ? "Голосовое"
                         : "Файл");
}
static QString uploadFailure(unsigned kind) {
    return u(kind == 1   ? "Снимок не отправлен"
             : kind == 2 ? "Кружок не отправлен"
             : kind == 3 ? "Голосовое не отправлено"
                         : "Файл не отправлен");
}
// Kept as an internal entry point for callers restoring an interrupted upload.
// Java has no attachment-review menu: selection/capture starts the upload.
void Window::reviewAttachment(const std::string &path, unsigned kind, uint32_t target, bool owned) {
    struct stat st;
    if (!target || stat(path.c_str(), &st) || !S_ISREG(st.st_mode) || st.st_size <= 0) {
        info(u(!target ? "Не выбран чат" : "Файл недоступен или пуст"));
        return;
    }
    if (outgoingRequest_) {
        info(u("Отправка уже идёт"));
        return;
    }
    if (!capturePath_.empty() && capturePath_ != path)
        discardAttachment();
    capturePath_ = path;
    captureKind_ = kind;
    captureUin_ = target;
    captureOwned_ = owned;
    upload(path, kind, target);
}
void Window::showAttachmentReview() {
    if (capturePath_.empty())
        return;
    View v(View::Transfer, attachmentType(captureKind_, captureOwned_));
    v.context = "transfer-failed";
    v.directory = "upload";
    v.uin = captureUin_;
    v.status = uploadFailure(captureKind_);
    v.details = u(fileName(capturePath_));
    if (view().context == "transfer-failed") {
        view() = v;
        update();
    } else
        push(v);
}
void Window::attachmentMenu(uint32_t target) {
    // Legacy hotkeys follow the Java "Отправить фото/видео" entry point.
    pickUin_ = target;
    pickKind_ = 5;
    files("", "upload");
}
void Window::discardAttachment() {
    if (outgoingRequest_)
        return;
    if (!capturePath_.empty()) {
        if (playPath_ == capturePath_) {
            player_.stop();
            playPath_ = receivedPath_;
            downloadName_ = receivedName_;
        }
        if (captureOwned_)
            unlink(capturePath_.c_str());
    }
    capturePath_.clear();
    captureOwned_ = false;
    captureKind_ = 0;
    captureUin_ = 0;
}
bool Window::showPicture(const std::string &path, const QString &title,
                         const std::string &context) {
    QImage image;
    unsigned w, h;
    std::string error;
    if (!imageDimensions(path, w, h, error) || !image.load(u(path))) {
        info(u(error.empty() ? "Не удалось открыть изображение" : error));
        return false;
    }
    picture_.convertFromImage(image);
    pictureRotation_ = 0;
    pictureZoom_ =
        std::max(1, std::min(100, std::min((width() * 100) / std::max(1, image.width()),
                                           ((height() - 56) * 100) / std::max(1, image.height()))));
    View v(View::Picture, title);
    v.context = context;
    push(v);
    return true;
}
void Window::previewAttachment() {
    if (capturePath_.empty()) {
        info(u("Вложение недоступно"));
        return;
    }
    if (captureKind_ == 1)
        showPicture(capturePath_, u("Фото"), "outgoing-preview");
    else if (captureKind_ == 2 || captureKind_ == 3) {
        play(capturePath_, captureKind_ == 3);
        if (view().kind == View::Player)
            view().context = "outgoing-preview";
    }
}
bool Window::connectionProgressVisible() const {
    return !stack_.empty() && !locked_ && (!editor_ || editor_->isHidden()) &&
           (connectionState_ == Event::Connecting || connectionState_ == Event::Reconnecting) &&
           (view().kind == View::Roster || view().kind == View::Chat);
}
void Window::showTransfer(uint32_t request, uint32_t target, const QString &title,
                          const QString &detail, bool sending) {
    View v(View::Transfer, title);
    v.context = "transfer";
    v.request = request;
    v.uin = target;
    v.directory = sending ? (captureKind_ == 1   ? "upload-photo"
                             : captureKind_ == 2 ? "upload-video"
                             : captureKind_ == 3 ? "upload-voice"
                                                 : "upload-file")
                          : "download";
    v.details = detail;
    v.status = u(sending ? "Отправляю..." : "Пожалуйста, ждите ...");
    notice_ = QString::null;
    push(v);
}
void Window::removeTransfer(uint32_t request) {
    for (size_t i = stack_.size(); i > 1; --i)
        if (stack_[i - 1].context == "transfer" && stack_[i - 1].request == request)
            stack_.erase(stack_.begin() + i - 1);
    syncVideoVisibility();
    update();
}
void Window::completeAttachment(bool success, const QString &message) {
    uint32_t request = outgoingRequest_;
    unsigned kind = captureKind_;
    outgoingRequest_ = 0;
    removeTransfer(request);
    if (success) {
        discardAttachment();
        if (kind == 3) {
            View done(View::Transfer, u("Записать голосовое"));
            done.context = "voice-sent";
            done.status = u("Отправлено");
            push(done);
            QTimer::singleShot(1200, this, SLOT(mediaReturn()));
        }
        return;
    }
    showAttachmentReview();
    view().details += message.isEmpty() ? QString::null : "\n" + message;
    update();
}
void Window::mediaReturn() {
    if (!stack_.empty() && view().context == "voice-sent")
        back();
}
void Window::retireTransfers() {
    bool restore = outgoingRequest_ != 0;
    outgoingRequest_ = 0;
    for (size_t i = stack_.size(); i > 1; --i)
        if (stack_[i - 1].context == "transfer")
            stack_.erase(stack_.begin() + i - 1);
    if (restore && !capturePath_.empty())
        showAttachmentReview();
    syncVideoVisibility();
}
void Window::requestMedia(unsigned kind) {
    const MessageRecord *m = selectedMessage();
    if (!m || m->token.empty()) {
        info(u("У сообщения нет вложения"));
        return;
    }
    Command c(kind == 1   ? Command::Photo
              : kind == 2 ? Command::Video
              : kind == 3 ? Command::Voice
                          : Command::File);
    c.uin = m->uin;
    c.token = m->token;
    c.nativeId = m->nativeId;
    c.requestId = client_.nextRequestId();
    c.media = mediaSettings(settings_);
    if (kind == 1 || kind == 2) {
        int rotate = settingNumber(settings_, kind == 1 ? "photo_rotate" : "video_rotate");
        c.mode = rotate == 1 ? 0x20 : rotate == 2 ? 0x10 : 0;
    }
    if (kind == 2) {
        mediaCache_.reserve(uint64_t(videoLimitKB(settings_)) * 1024);
        videoToken_ = c.token;
        videoUin_ = c.uin;
        videoSegment_ = 0;
    } else
        videoToken_.clear();
    const char *purpose = kind == 1 ? "photo" : kind == 2 ? "video" : kind == 3 ? "voice" : "file";
    if ((kind == 1 || kind == 2) && openCachedMedia(c, purpose))
        return;
    if (send(c)) {
        pending_[c.requestId] = purpose;
        if (kind == 1 || kind == 2)
            mediaRequests_[c.requestId] = MediaCache::requestKey(c);
        pendingUin_[c.requestId] = c.uin;
        showTransfer(c.requestId, c.uin, attachmentType(kind, false), QString::null, false);
        view().directory = kind == 1 ? "photo" : kind == 2 ? "video" : kind == 3 ? "voice" : "file";
        view().status = u(kind == 1   ? "Загрузка фото..."
                          : kind == 2 ? "Мост готовит видео..."
                          : kind == 3 ? "Мост готовит голосовое..."
                                      : "Скачиваю файл...");
        update();
    }
}
bool Window::openCachedMedia(const Command &command, const std::string &purpose) {
    Event received(Event::Media);
    if (!mediaCache_.find(MediaCache::requestKey(command), received.path, received.filename))
        return false;
    received.requestId = command.requestId;
    pending_[received.requestId] = purpose;
    showMedia(received);
    pending_.erase(received.requestId);
    return true;
}
static bool saveDownloadedFile(const std::string &source, const std::string &name,
                               std::string &destination, std::string &error) {
    std::vector<std::string> roots;
    const char *environment = getenv("MYSTUFF_DATA_PATH");
    if (environment && *environment)
        roots.push_back(environment);
    roots.push_back("/ezxlocal/download/mystuff");
    roots.push_back("/mmc/mmca1");
    roots.push_back("/mnt/mmc/mmca1");
    std::set<std::string> visited;
    for (size_t root = 0; root < roots.size(); ++root) {
        std::string canonical;
        if (!readableMediaDirectory(roots[root], canonical) || !visited.insert(canonical).second)
            continue;
        std::string directories[] = {canonical + "/tmm", canonical};
        for (unsigned directory = 0; directory < 2; ++directory) {
            if (!directory && mkdir(directories[directory].c_str(), 0700) && errno != EEXIST)
                continue;
            std::string resolved;
            if (!readableMediaDirectory(directories[directory], resolved))
                continue;
            size_t dot = name.find_last_of('.');
            std::string base = dot != std::string::npos && dot ? name.substr(0, dot) : name;
            std::string extension = dot != std::string::npos && dot ? name.substr(dot) : "";
            for (unsigned collision = 0; collision < 1000; ++collision) {
                char suffix[24];
                snprintf(suffix, sizeof(suffix), "-%u", collision);
                std::string candidate =
                    resolved + "/" + (collision ? base + suffix + extension : name);
                struct stat st;
                if (!stat(candidate.c_str(), &st))
                    continue;
                if (copyMediaFile(source, candidate, error)) {
                    destination = candidate;
                    return true;
                }
                // O_EXCL also protects a name created between stat and copy.
                if (!stat(candidate.c_str(), &st))
                    continue;
                break;
            }
        }
    }
    if (error.empty())
        error = "Некуда сохранить файл";
    return false;
}
void Window::showMedia(const Event &e) {
    std::string purpose = pending_[e.requestId];
    std::string prefix = storage_->accountDir() + "/cache/";
    if (e.path.compare(0, prefix.size(), prefix) == 0) {
        if (managedMediaPath_ != e.path) {
            player_.stop();
            if (!managedMediaPath_.empty() && !mediaCache_.owns(managedMediaPath_))
                unlink(managedMediaPath_.c_str());
            managedMediaPath_ = e.path;
        }
    }
    std::map<uint32_t, std::string>::iterator cacheRequest = mediaRequests_.find(e.requestId);
    if (cacheRequest != mediaRequests_.end()) {
        if (purpose == "photo" || purpose == "video")
            mediaCache_.store(cacheRequest->second, e.path, e.filename);
        mediaRequests_.erase(cacheRequest);
    }
    playPath_ = e.path;
    downloadName_ = e.filename;
    if (downloadName_.empty()) {
        size_t slash = e.path.find_last_of('/');
        downloadName_ = e.path.substr(slash == std::string::npos ? 0 : slash + 1);
    }
    size_t slash = downloadName_.find_last_of("/\\");
    if (slash != std::string::npos)
        downloadName_ = downloadName_.substr(slash + 1);
    if (downloadName_.empty() || downloadName_ == "." || downloadName_ == "..")
        downloadName_ = "attachment.bin";
    savedMediaPurpose_ = purpose;
    receivedPath_ = e.path;
    receivedName_ = downloadName_;
    loadedMediaReady_ = true;
    receivedDeferred_ = false;
    if (purpose == "file") {
        // Java saves documents directly to a writable phone root/tmm directory.
        // Commit a unique destination first, then release only our cache file.
        std::string destination, error;
        View v(View::Transfer, u("Скачать файл"));
        v.context = "file-saved";
        if (saveDownloadedFile(e.path, downloadName_, destination, error)) {
            if (managedMediaPath_ == e.path) {
                unlink(managedMediaPath_.c_str());
                managedMediaPath_.clear();
            }
            playPath_ = receivedPath_ = destination;
            downloadName_ = receivedName_ = fileName(destination);
            struct stat st;
            v.status = u("Сохранено:");
            v.details = u(destination);
            if (!stat(destination.c_str(), &st))
                v.details += "\n" + QString::number((unsigned long)(st.st_size / 1024)) + " КБ";
        } else {
            v.context = "media-error";
            v.status = u("Файл не получен:");
            v.details = u(error);
        }
        if (locked_ || closed_ || !isVisible()) {
            receivedDeferred_ = true;
            info(v.status + "\n" + v.details);
        } else
            push(v);
        return;
    }
    if (locked_ || closed_ || !isVisible()) {
        receivedDeferred_ = true;
        info(u("Вложение получено"));
        return;
    }
    if (purpose == "photo" || purpose == "avatar") {
        showPicture(e.path, u("Изображение"));
        return;
    }
    if (purpose == "video" || purpose == "voice") {
        play(e.path, purpose == "voice");
        return;
    }
    info(u("Вложение получено"));
}
void Window::openDeferredMedia() {
    if (!receivedDeferred_ || receivedPath_.empty() || locked_ || closed_ || !isVisible())
        return;
    receivedDeferred_ = false;
    const std::string cache = storage_->accountDir() + "/cache/";
    if (savedMediaPurpose_ == "file" && receivedPath_.compare(0, cache.size(), cache) != 0) {
        struct stat st;
        View saved(View::Transfer, u("Скачать файл"));
        saved.context = "file-saved";
        saved.status = u("Сохранено:");
        saved.details = u(receivedPath_);
        if (!stat(receivedPath_.c_str(), &st))
            saved.details += "\n" + QString::number((unsigned long)(st.st_size / 1024)) + " КБ";
        else {
            saved.context = "media-error";
            saved.status = u("Файл не получен:");
        }
        push(saved);
        return;
    }
    Event received(Event::Media);
    received.path = receivedPath_;
    received.filename = receivedName_;
    received.requestId = client_.nextRequestId();
    pending_[received.requestId] = savedMediaPurpose_;
    showMedia(received);
    pending_.erase(received.requestId);
}
void Window::nextVideo() {
    if (videoToken_.empty() || videoSegment_ >= 255)
        return;
    Command c(Command::Video);
    c.token = videoToken_;
    c.uin = videoUin_;
    c.offset = videoSegment_ + 1;
    c.requestId = client_.nextRequestId();
    c.media = mediaSettings(settings_);
    int rotate = settingNumber(settings_, "video_rotate");
    mediaCache_.reserve(uint64_t(videoLimitKB(settings_)) * 1024);
    c.mode = rotate == 1 ? 0x20 : rotate == 2 ? 0x10 : 0;
    const unsigned previousSegment = videoSegment_;
    videoSegment_ = c.offset;
    if (openCachedMedia(c, "video"))
        return;
    if (send(c)) {
        player_.stop();
        pending_[c.requestId] = "video";
        mediaRequests_[c.requestId] = MediaCache::requestKey(c);
        pendingUin_[c.requestId] = c.uin;
        // Java replaces the segment screen, rather than stacking another
        // completed Player underneath every requested part.
        if (view().kind == View::Player)
            stack_.pop_back();
        showTransfer(c.requestId, c.uin, u("Смотреть видео"), QString::null, false);
        view().directory = "video";
        view().status =
            u("Мост готовит видео...") + " (" + QString::number(videoSegment_ + 1) + ")";
        update();
    } else
        videoSegment_ = previousSegment;
}
void Window::play(const std::string &path, bool audioOnly) {
    if (locked_ || closed_ || !isVisible()) {
        info(u("Откройте крышку и разблокируйте экран для просмотра"));
        return;
    }
    playPath_ = path;
    paused_ = false;
    playPosition_ = playDuration_ = 0;
    platform_.stopNotificationSound();
    if (!player_.play(u(path), settings_.getInt("player_volume", 70), audioOnly))
        return;
    if (view().kind == View::Player)
        stack_.pop_back();
    QWidget *w = player_.videoWidget();
    if (w) {
        if (w->parentWidget() != this)
            w->reparent(this, QPoint(0, 30), false);
        w->setGeometry(0, 29, width(), std::max(1, height() - 56));
    }
    View v(View::Player, u(audioOnly ? "Прослушать" : "Смотреть видео"));
    v.context = audioOnly ? "player-voice" : "player-video";
    push(v);
}
void Window::openUrl(const std::string &url) {
    if (url.find("http://") != 0 && url.find("https://") != 0 && url.find("ftp://") != 0 &&
        url.find("mailto:") != 0) {
        info(u("Неверный адрес"));
        return;
    }
    platform_.openUrl(u(url));
}
void Window::upload(const std::string &path, unsigned kind, uint32_t target) {
    struct stat st;
    if (!target || stat(path.c_str(), &st) < 0 || !S_ISREG(st.st_mode) || st.st_size <= 0) {
        info(u(!target ? "Не выбран чат" : "Файл недоступен или пуст"));
        return;
    }
    if (outgoingRequest_) {
        info(u("Отправка уже идёт"));
        return;
    }
    // Full photos and ordinary videos from memory use the document protocol.
    // Its mode selects photo/video without turning every video into a circle.
    bool document = kind == 4 || (!captureOwned_ && (kind == 1 || kind == 2));
    unsigned limit = settingNumber(settings_, "media_memory_kb");
    uint64_t maximum = limit ? uint64_t(limit) * 1024 : 8 * 1024 * 1024;
    if (!document)
        maximum = std::min<uint64_t>(maximum, 4 * 1024 * 1024);
    if (document)
        maximum = std::min<uint64_t>(maximum, 5 * 1024 * 1024);
    if (uint64_t(st.st_size) > maximum) {
        showAttachmentReview();
        view().details += "\n" + u("Файл превышает лимит: ") + mediaSize(maximum);
        update();
        return;
    }
    Command c(document    ? Command::UploadFile
              : kind == 1 ? Command::UploadPhoto
              : kind == 2 ? Command::UploadVideo
                          : Command::UploadVoice);
    c.mode = document && kind != 4 ? kind : 0;
    c.path = path;
    c.uin = target;
    if (kind == 2 || kind == 3)
        c.duration = captureDuration(path.c_str());
    std::string suffix;
    size_t ext = path.find_last_of('.');
    if (ext != std::string::npos)
        suffix = std::string(u(path.substr(ext)).lower().utf8());
    if (kind == 1)
        c.text = suffix == ".png"   ? "image/png"
                 : suffix == ".gif" ? "image/gif"
                 : suffix == ".bmp" ? "image/bmp"
                                    : "image/jpeg";
    else if (kind == 2)
        c.text = suffix == ".mp4"   ? "video/mp4"
                 : suffix == ".mov" ? "video/quicktime"
                 : suffix == ".avi" ? "video/x-msvideo"
                 : suffix == ".3g2" ? "video/3gpp2"
                                    : "video/3gpp";
    else if (kind == 3)
        c.text = suffix == ".amr"   ? "audio/amr"
                 : suffix == ".wav" ? "audio/wav"
                 : suffix == ".mp3" ? "audio/mpeg"
                                    : "audio/3gpp";
    c.requestId = client_.nextRequestId();
    c.media = mediaSettings(settings_);
    if (send(c)) {
        if (view().context == "transfer-failed")
            stack_.pop_back();
        outgoingRequest_ = c.requestId;
        pending_[c.requestId] = "upload";
        pendingUin_[c.requestId] = target;
        showTransfer(c.requestId, target, attachmentType(kind, captureOwned_), u(fileName(path)),
                     true);
        view().status = u(document ? "Отправляю файл" : "Отправляю...");
        update();
    } else {
        showAttachmentReview();
        view().details += "\n" + u("Нет соединения или очередь запросов заполнена");
        update();
    }
}
void Window::captureError(const QString &error) {
    note(std::string(error.utf8()));
    if (!capture_.busy() && !stack_.empty() && view().kind == View::Recording) {
        view().context = "recording-idle";
        view().status = u("Голосовое недоступно");
        view().details = error;
        update();
    } else
        info(error);
}
void Window::captureCancelled() {
    for (size_t i = stack_.size(); i > 1; --i)
        if (stack_[i - 1].context == "recording" || stack_[i - 1].context == "recording-stopping")
            stack_.erase(stack_.begin() + i - 1);
    update();
}
void Window::captureReady(const QString &path, const QString &mime) {
    for (size_t i = stack_.size(); i > 1; --i)
        if (stack_[i - 1].context == "recording" || stack_[i - 1].context == "recording-stopping")
            stack_.erase(stack_.begin() + i - 1);
    unsigned kind = mime.startsWith("image/") ? 1 : mime.startsWith("video/") ? 2 : 3;
    reviewAttachment(std::string(path.utf8()), kind, captureUin_, true);
}
} // namespace tmm
