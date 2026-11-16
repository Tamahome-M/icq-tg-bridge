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
void Window::files(const std::string &directory, const std::string &action) {
    View v(View::Files, u("Файлы"));
    v.directory = directory;
    v.context = action;
    push(v);
    loadFiles();
}
void Window::loadFiles() {
    View &v = view();
    DIR *dir = opendir(v.directory.c_str());
    if (!dir) {
        info(u(std::string("Не открыть папку: ") + strerror(errno)));
        return;
    }
    v.title = u(v.directory);
    v.rows.clear();
    v.selected = v.top = 0;
    if (v.context == "save-media")
        v.rows.push_back(Row(u("Сохранить здесь: ") + u(downloadName_), "save-here"));
    if (v.directory != "/") {
        std::string parent = v.directory.substr(0, v.directory.find_last_of('/'));
        v.rows.push_back(Row(u(parent.empty() ? "/" : parent), "directory"));
    }
    std::vector<std::string> directories, files;
    errno = 0;
    struct dirent *entry;
    while ((entry = readdir(dir))) {
        std::string name = entry->d_name;
        if (name == "." || name == "..")
            continue;
        std::string path = v.directory + "/" + name;
        struct stat st;
        if (stat(path.c_str(), &st) < 0)
            continue;
        if (S_ISDIR(st.st_mode))
            directories.push_back(path);
        else if (S_ISREG(st.st_mode) && v.context != "save-media")
            files.push_back(name);
        if (directories.size() + files.size() >= 1000)
            break;
        errno = 0;
    }
    int error = errno;
    closedir(dir);
    if (error)
        info(u(std::string("Ошибка чтения папки: ") + strerror(error)));
    std::sort(directories.begin(), directories.end());
    std::sort(files.begin(), files.end());
    for (size_t i = 0; i < directories.size(); ++i)
        v.rows.push_back(Row(u(directories[i]), "directory"));
    for (size_t i = 0; i < files.size(); ++i)
        v.rows.push_back(Row(u(files[i]), "file-select"));
    update();
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
        View v(View::Menu, u("Загрузка вложения…"));
        v.context = "transfer";
        v.request = c.requestId;
        v.rows.push_back(Row(u("Отменить"), "transfer-cancel"));
        push(v);
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
    loadedMediaReady_ = true;
    if (locked_ || closed_) {
        info(u("Вложение получено. Откройте через меню после разблокировки"));
        return;
    }
    if (purpose == "photo" || purpose == "avatar") {
        QImage image;
        unsigned w, h;
        std::string error;
        if (!imageDimensions(e.path, w, h, error) || !image.load(u(e.path))) {
            info(u("Не удалось открыть изображение"));
            return;
        }
        picture_.convertFromImage(image);
        pictureRotation_ = 0;
        pictureZoom_ = std::max(25, std::min(100, (width() * 100) / std::max(1, image.width())));
        View v(View::Picture, u("Изображение"));
        push(v);
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
        View v(View::Menu, u("Следующий фрагмент…"));
        v.context = "transfer";
        v.request = c.requestId;
        v.rows.push_back(Row(u("Отменить"), "transfer-cancel"));
        push(v);
    }
}
void Window::play(const std::string &path, bool audioOnly) {
    if (locked_ || closed_) {
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
    if (stat(path.c_str(), &st) < 0 || !S_ISREG(st.st_mode) || st.st_size <= 0) {
        info(u("Файл недоступен"));
        return;
    }
    Command c(kind == 1   ? Command::UploadPhoto
              : kind == 2 ? Command::UploadVideo
              : kind == 3 ? Command::UploadVoice
                          : Command::UploadFile);
    c.path = path;
    c.uin = target;
    if (kind == 2 || kind == 3)
        c.duration = captureDuration(path.c_str());
    size_t ext = path.find_last_of('.');
    std::string suffix = ext == std::string::npos ? "" : path.substr(ext);
    if (kind == 1)
        c.text = suffix == ".png" ? "image/png" : suffix == ".gif" ? "image/gif" : "image/jpeg";
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
        pending_[c.requestId] = "upload";
        pendingUin_[c.requestId] = target;
        View v(View::Menu, u("Отправка файла…"));
        v.context = "transfer";
        v.request = c.requestId;
        v.rows.push_back(Row(u("Отменить"), "transfer-cancel"));
        push(v);
    }
}
void Window::captureReady(const QString &path, const QString &mime) {
    (void)mime;
    capturePath_ = std::string(path.utf8());
    if (view().context == "recording")
        stack_.pop_back();
    View v(View::Menu, u("Запись готова"));
    v.context = "capture-ready";
    v.uin = captureUin_;
    v.rows.push_back(Row(u("Посмотреть / прослушать"), "capture-preview"));
    v.rows.push_back(Row(u("Отправить"), "capture-send"));
    v.rows.push_back(Row(u("Удалить"), "capture-delete"));
    push(v);
}
} // namespace tmm
