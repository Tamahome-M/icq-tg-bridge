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
             : kind == 2 ? (captured ? "Кружочек" : "Видео")
             : kind == 3 ? "Голосовое"
                         : "Файл");
}
void Window::attachmentMenu(uint32_t target) {
    if (!target) {
        info(u("Не выбран чат"));
        return;
    }
    View v(View::Menu, u("Прикрепить"));
    v.uin = target;
    v.rows.push_back(Row(u("Снять фото"), "capture-photo", target));
    v.rows.push_back(Row(u("Записать кружочек"), "capture-video", target));
    v.rows.push_back(Row(u("Записать голосовое"), "capture-voice", target));
    v.rows.push_back(Row(u("Фото из памяти"), "pick-photo", target));
    v.rows.push_back(Row(u("Видео из памяти"), "pick-video", target));
    v.rows.push_back(Row(u("Голосовое из памяти"), "pick-voice", target));
    v.rows.push_back(Row(u("Файл из памяти"), "upload-file", target));
    push(v);
}
void Window::reviewAttachment(const std::string &path, unsigned kind, uint32_t target, bool owned) {
    struct stat st;
    if (!target || stat(path.c_str(), &st) || !S_ISREG(st.st_mode) || st.st_size <= 0) {
        info(u(!target ? "Не выбран чат" : "Файл недоступен или пуст"));
        return;
    }
    if (outgoingRequest_ || (!capturePath_.empty() && capturePath_ != path)) {
        info(u("Сначала завершите отправку выбранного вложения"));
        return;
    }
    capturePath_ = path;
    captureKind_ = kind;
    captureUin_ = target;
    captureOwned_ = owned;
    showAttachmentReview();
}
void Window::showAttachmentReview() {
    if (capturePath_.empty())
        return;
    View v(View::AttachmentReview, attachmentType(captureKind_, captureOwned_));
    v.context = "attachment-review";
    v.uin = captureUin_;
    struct stat st;
    v.details = u("Кому: ") + name(captureUin_) + "\n" + u(fileName(capturePath_));
    if (!stat(capturePath_.c_str(), &st))
        v.details += "\n" + mediaSize(st.st_size);
    v.rows.push_back(Row(u("Отправить"), "capture-send", captureUin_));
    if (captureKind_ != 4)
        v.rows.push_back(
            Row(u(captureKind_ == 3 ? "Прослушать" : "Посмотреть"), "capture-preview"));
    v.rows.push_back(Row(u(captureOwned_ ? (captureKind_ == 1 ? "Снять заново" : "Записать заново")
                                         : "Выбрать другой файл"),
                         "attachment-replace", captureUin_));
    v.rows.push_back(Row(u("Сведения"), "attachment-details"));
    v.rows.push_back(Row(u("Отмена"), "back"));
    if (view().context == "attachment-review") {
        view() = v;
        update();
    } else
        push(v);
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
                                           ((height() - 94) * 100) / std::max(1, image.height()))));
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
    v.details = u(sending ? "Кому: " : "Чат: ") + name(target) + "\n" + detail;
    v.status = u(sending ? "Подготовка отправки…" : "Ожидание данных…");
    v.rows.push_back(Row(u("Отмена"), "transfer-cancel"));
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
    uint32_t request = outgoingRequest_, target = captureUin_;
    outgoingRequest_ = 0;
    removeTransfer(request);
    if (success) {
        discardAttachment();
        for (size_t i = stack_.size(); i > 1; --i)
            if (stack_[i - 1].context == "attachment-review" ||
                stack_[i - 1].context == "outgoing-preview")
                stack_.erase(stack_.begin() + i - 1);
        openChat(target);
    } else
        showAttachmentReview();
    info(message);
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
        videoToken_ = c.token;
        videoUin_ = c.uin;
        videoSegment_ = 0;
    } else
        videoToken_.clear();
    if (send(c)) {
        pending_[c.requestId] = kind == 1   ? "photo"
                                : kind == 2 ? "video"
                                : kind == 3 ? "voice"
                                            : "file";
        pendingUin_[c.requestId] = c.uin;
        showTransfer(c.requestId, c.uin, u("Загрузка"), attachmentType(kind, false), false);
    }
}
void Window::showMedia(const Event &e) {
    std::string purpose = pending_[e.requestId];
    std::string prefix = storage_->accountDir() + "/cache/";
    if (e.path.compare(0, prefix.size(), prefix) == 0) {
        if (managedMediaPath_ != e.path) {
            player_.stop();
            if (!managedMediaPath_.empty())
                unlink(managedMediaPath_.c_str());
            managedMediaPath_ = e.path;
        }
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
    if (locked_ || closed_ || !isVisible()) {
        info(u("Вложение получено. Откройте через меню"));
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
    View v(View::Menu, u("Файл получен"));
    v.rows.push_back(Row(u(downloadName_), "file-details"));
    v.rows.push_back(Row(u("Сохранить в папку"), "save-media-file"));
    v.rows.push_back(Row(u("Открыть"), "open-media-file"));
    push(v);
}
void Window::nextVideo() {
    if (videoToken_.empty() || videoSegment_ >= 255)
        return;
    Command c(Command::Video);
    c.token = videoToken_;
    c.uin = videoUin_;
    c.offset = videoSegment_ + 1;
    c.requestId = client_.nextRequestId();
    int rotate = settingNumber(settings_, "video_rotate");
    c.mode = rotate == 1 ? 0x20 : rotate == 2 ? 0x10 : 0;
    if (send(c)) {
        ++videoSegment_;
        player_.stop();
        pending_[c.requestId] = "video";
        pendingUin_[c.requestId] = c.uin;
        showTransfer(c.requestId, c.uin, u("Загрузка"), u("Следующий фрагмент видео"), false);
    }
}
void Window::play(const std::string &path, bool audioOnly) {
    if (locked_ || closed_ || !isVisible()) {
        info(u("Откройте крышку и разблокируйте экран для просмотра"));
        return;
    }
    playPath_ = path;
    paused_ = false;
    playPosition_ = playDuration_ = 0;
    if (!player_.play(u(path), settings_.getInt("player_volume", 70), audioOnly))
        return;
    if (view().kind == View::Player)
        stack_.pop_back();
    QWidget *w = player_.videoWidget();
    if (w) {
        if (w->parentWidget() != this)
            w->reparent(this, QPoint(0, 30), false);
        w->setGeometry(0, 30, width(), height() - 88);
    }
    View v(View::Player, u("Плеер"));
    push(v);
}
void Window::openUrl(const std::string &url) {
    if (url.find("http://") != 0 && url.find("https://") != 0) {
        info(u("Допустимы только HTTP/HTTPS ссылки"));
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
    if (uint64_t(st.st_size) > maximum) {
        info(u("Файл превышает лимит: ") + mediaSize(maximum));
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
        c.text = suffix == ".png" ? "image/png" : "image/jpeg";
    else if (kind == 2)
        c.text = suffix == ".mp4"   ? "video/mp4"
                 : suffix == ".mov" ? "video/quicktime"
                                    : "video/3gpp";
    else if (kind == 3)
        c.text = suffix == ".amr"   ? "audio/amr"
                 : suffix == ".wav" ? "audio/wav"
                 : suffix == ".mp3" ? "audio/mpeg"
                                    : "audio/3gpp";
    c.requestId = client_.nextRequestId();
    c.media = mediaSettings(settings_);
    if (send(c)) {
        outgoingRequest_ = c.requestId;
        pending_[c.requestId] = "upload";
        pendingUin_[c.requestId] = target;
        showTransfer(c.requestId, target, u("Отправка"), u(fileName(path)), true);
    }
}
void Window::captureError(const QString &error) {
    if (!capture_.busy()) {
        for (size_t i = stack_.size(); i > 1; --i)
            if (stack_[i - 1].context == "recording")
                stack_.erase(stack_.begin() + i - 1);
    }
    note(std::string(error.utf8()));
    info(error);
}
void Window::captureCancelled() {
    for (size_t i = stack_.size(); i > 1; --i)
        if (stack_[i - 1].context == "recording")
            stack_.erase(stack_.begin() + i - 1);
    update();
}
void Window::captureReady(const QString &path, const QString &mime) {
    for (size_t i = stack_.size(); i > 1; --i)
        if (stack_[i - 1].context == "recording")
            stack_.erase(stack_.begin() + i - 1);
    unsigned kind = mime.startsWith("image/") ? 1 : mime.startsWith("video/") ? 2 : 3;
    reviewAttachment(std::string(path.utf8()), kind, captureUin_, true);
}
} // namespace tmm
