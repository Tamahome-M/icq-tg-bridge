#include "window.h"
#include "storage.h"
#include "ui_settings.h"
#include "ui_language.h"
#include "ui_files.h"
#include "ui_links.h"
#include <ZKeyDef.h>
#include <sys/stat.h>
#include <unistd.h>
#include <stdio.h>
#include <time.h>
#include <algorithm>
namespace tmm {
static QString u(const char *s) {
    return uiText(s);
}
static QString u(const std::string &s) {
    return QString::fromUtf8(s.c_str());
}
static unsigned mediaKind(const std::string &path) {
    QString lower = u(path).lower();
    if (lower.right(4) == ".jpg" || lower.right(5) == ".jpeg" || lower.right(4) == ".png")
        return 1;
    if (lower.right(4) == ".3gp" || lower.right(4) == ".mp4" || lower.right(4) == ".3g2" ||
        lower.right(4) == ".avi" || lower.right(4) == ".mov")
        return 2;
    return 4;
}
static std::string captureFile(const Storage &storage, unsigned kind) {
    static unsigned serial;
    char suffix[80];
    snprintf(suffix, sizeof(suffix), "/capture-%lu-%u%s", (unsigned long)time(0), ++serial,
             kind == 1   ? ".jpg"
             : kind == 2 ? ".3gp"
                         : ".amr");
    return storage.accountDir() + suffix;
}
void Window::beginCapture(unsigned kind, uint32_t target) {
    if (!target) {
        info(u("Не выбран чат"));
        return;
    }
    if (capture_.busy() || outgoingRequest_) {
        info(u("Завершите текущую запись"));
        return;
    }
    discardAttachment();
    captureUin_ = target;
    captureKind_ = kind;
    capture_.setProfile(u(settingValue(settings_, "camera_size")),
                        u(settingValue(settings_, "camera_encoding")));
    capture_.setVoiceBitrate(settingNumber(settings_, "voice_kbps10")
                                 ? settingNumber(settings_, "voice_kbps10") * 100
                                 : 6700);
    if (kind == 3) {
        View recorder(View::Recording, u("Записать голосовое"));
        recorder.context = "recording-idle";
        recorder.uin = target;
        recorder.status = u("Записать голосовое");
        recorder.details = u("Нажмите «выбор» — запись");
        notice_ = QString::null;
        push(recorder);
        return;
    }
    const std::string path = captureFile(*storage_, kind);
    if (kind == 1)
        capture_.capturePhoto(u(path));
    else
        capture_.recordVideo(u(path), 30);
    resume();
}
void Window::startVoiceRecording() {
    if (view().kind != View::Recording || capture_.busy() || outgoingRequest_)
        return;
    view().context = "recording";
    view().status = u("Идёт запись...");
    view().details = u("Нажмите «выбор» — стоп");
    capture_.recordVoice(u(captureFile(*storage_, 3)), 60);
    update();
}
void Window::playerMenu() {
    // The Java Canvas exposes "Дальше" directly, not another player menu.
    if (view().context == "player-video" && !videoToken_.empty())
        nextVideo();
}
bool Window::mediaKey(int code) {
    const bool fire = code == KEYCODE_CENTER_SELECT || code == Key_Enter || code == KEYCODE_5;
    if (view().kind == View::Recording) {
        if (fire) {
            if (capture_.busy())
                capture_.stop();
            else
                startVoiceRecording();
        } else if (code == KEYCODE_LSK || code == KEYCODE_RSK || code == KEYCODE_CLEAR)
            back();
        return true;
    }
    if (view().kind == View::Transfer) {
        const bool outgoing =
            view().directory.find("upload") == 0 || view().context == "voice-sent";
        if (view().context == "transfer-failed" && fire && !capturePath_.empty())
            upload(capturePath_, captureKind_, captureUin_);
        else if (code == KEYCODE_LSK || code == KEYCODE_RSK || code == KEYCODE_CLEAR ||
                 (!outgoing && (code == KEYCODE_0 || fire))) {
            back();
            if (outgoing)
                discardAttachment();
        }
        return true;
    }
    if (view().kind != View::Player)
        return false;
    const bool voice = view().context == "player-voice";
    if (code == KEYCODE_LSK || code == KEYCODE_CLEAR || code == KEYCODE_0) {
        back();
        return true;
    }
    if (voice) {
        if (fire) {
            if (view().more || !player_.active())
                play(playPath_, true);
            else if (player_.pause(!paused_))
                paused_ = !paused_;
        } else if (code == KEYCODE_LEFT || code == KEYCODE_4) {
            if (view().more || !player_.active())
                play(playPath_, true);
            else {
                player_.seek(0);
                if (paused_ && player_.pause(false))
                    paused_ = false;
            }
        } else if (code == KEYCODE_RSK)
            back();
    } else {
        if (fire)
            back();
        else if (code == KEYCODE_3)
            nextVideo();
        else if (code == KEYCODE_RSK)
            playerMenu();
    }
    update();
    return true;
}
bool Window::activateMedia(const Row &chosen) {
    Row r = chosen;
    std::string action = r.action;
    uint32_t id = r.uin ? r.uin : view().uin;
    if (action == "video-menu") {
        const MessageRecord *m = selectedMessage();
        if (!m)
            return true;
        View choices(View::Choice, u("Смотреть видео"));
        choices.context = "video-choice";
        choices.uin = m->uin;
        if (!m->token.empty())
            choices.rows.push_back(Row(u("Смотреть"), "video", m->uin));
        if (!m->url.empty())
            choices.rows.push_back(Row(u("Смотреть в браузере"), "video-browser", m->uin));
        if (!choices.rows.empty())
            push(choices);
        return true;
    }
    if (action == "photo" || action == "video" || action == "voice" || action == "file") {
        if (view().context == "video-choice")
            back();
        requestMedia(action == "photo" ? 1 : action == "video" ? 2 : action == "voice" ? 3 : 4);
        return true;
    }
    if (action == "video-browser") {
        const MessageRecord *message = selectedMessage();
        std::string url = message ? message->url : "";
        if (view().context == "video-choice")
            back();
        if (!url.empty())
            openUrl(url);
        return true;
    }
    if (action == "urls") {
        const MessageRecord *m = selectedMessage();
        if (!m)
            return true;
        const std::vector<std::string> links = javaMessageUrls(m->text);
        if (links.size() == 1)
            openUrl(links[0]);
        else if (!links.empty()) {
            View urls(View::Choice, u("Открыть ссылку"));
            urls.context = "url-choice";
            for (size_t i = 0; i < links.size(); ++i)
                urls.rows.push_back(Row(u(links[i]), "url:" + links[i]));
            push(urls);
        }
        return true;
    }
    if (action.compare(0, 4, "url:") == 0) {
        const std::string url = action.substr(4);
        if (view().context == "url-choice")
            back();
        openUrl(url);
        return true;
    }
    if (action == "capture-photo" || action == "capture-voice" || action == "capture-video") {
        beginCapture(action == "capture-photo" ? 1 : action == "capture-video" ? 2 : 3, id);
        return true;
    }
    if (action == "upload-file" || action == "upload-media" || action == "attachments" ||
        action == "pick-photo" || action == "pick-video" || action == "pick-voice") {
        if (capture_.busy() || outgoingRequest_) {
            info(u("Отправка уже идёт"));
            return true;
        }
        discardAttachment();
        pickUin_ = id;
        pickKind_ = action == "upload-file" ? 4 : 5;
        files("", "upload");
        return true;
    }
    if (action == "pick-background") {
        files("", "background");
        return true;
    }
    if (action.compare(0, 10, "directory:") == 0 || action == "directory") {
        view().directory = action == "directory" ? std::string(r.text.utf8()) : action.substr(10);
        loadFiles();
        return true;
    }
    if (action == "file-select") {
        std::string path = view().directory + "/" + std::string(r.text.utf8());
        if (view().context == "background") {
            settings_.set("background_file", path);
            back();
            settingsChanged();
        } else if (view().context == "upload") {
            const unsigned kind = pickKind_ == 5 ? mediaKind(path) : 4;
            const uint32_t target = pickUin_;
            back();
            reviewAttachment(path, kind, target, false);
        }
        return true;
    }
    if (action == "record-stop") {
        capture_.stop();
        return true;
    }
    if (action == "record-cancel" || action == "transfer-cancel") {
        const bool outgoing = view().directory.find("upload") == 0;
        back();
        if (outgoing)
            discardAttachment();
        return true;
    }
    if (action == "player-next") {
        nextVideo();
        return true;
    }
    // Compatibility entry points are retained for stored hotkeys only, not menus.
    if (action == "capture-send" || action == "attachment-pending") {
        if (!capturePath_.empty())
            upload(capturePath_, captureKind_, captureUin_);
        return true;
    }
    return false;
}
} // namespace tmm
