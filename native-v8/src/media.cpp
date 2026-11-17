#include "media.h"
#include <qwidget.h>
#include <ezxsound.h>
#include <dlfcn.h>
#include <cstdlib>
#include <cstring>
#include <linux/limits.h>
namespace tmm {
namespace {
template <class T> T function(void *p) {
    T result;
    std::memcpy(&result, &p, sizeof(result));
    return result;
}
typedef QObject *(*Create)(void *, void *);
typedef QObject *(*CreateRingtone)(void *);
typedef void (*Delete)(QObject *);
typedef bool (*Open)(QObject *, const char *, int);
typedef bool (*Play)(QObject *, int);
typedef bool (*Call)(QObject *);
typedef unsigned int (*Volume)(QObject *, unsigned int);
typedef bool (*Mute)(QObject *, bool);
typedef bool (*Seek)(QObject *, unsigned int);
typedef unsigned short (*Code)(QObject *);
int bounded(int v) {
    return v < 0 ? 0 : (v > 100 ? 100 : v);
}
} // namespace
MediaController::MediaController(QObject *parent, bool notification)
    : QObject(parent), library_(0), videoLibrary_(0), engine_(0), video_(0), device_(0), table_(0),
      elapsed_(0), duration_(0), pending_(0), active_(false), failed_(false), videoActive_(false),
      notification_(notification), volume_(70) {
    connect(&startup_, SIGNAL(timeout()), this, SLOT(startupTimeout()));
    connect(&completion_, SIGNAL(timeout()), this, SLOT(dispatch()));
}
MediaController::~MediaController() {
    stop();
    if (video_) {
        QWidget *widget = video_;
        video_ = 0;
        function<void (*)(void *)>(dlsym(videoLibrary_, "_ZN14MP_VideoWidgetD1Ev"))(widget);
        std::free(widget);
    }
}
bool MediaController::load() {
    if (table_)
        return true;
    if (!library_)
        library_ = dlopen("libezx_mp_playerengine.so.1", RTLD_NOW | RTLD_GLOBAL);
    if (!library_) {
        emit error(QString::fromUtf8("Недоступен плеер Motorola"));
        return false;
    }
    void *vtable = dlsym(library_, "_ZTV17MediaPlayerEngine");
    if (!vtable || !dlsym(library_, notification_ ? "MP_CreateRingtone" : "MP_CreateMediaPlayer") ||
        !dlsym(library_, notification_ ? "MP_DeleteRingtone" : "MP_DeleteMediaPlayer")) {
        emit error(QString::fromUtf8("Несовместимый плеер Motorola"));
        return false;
    }
    void **candidate = static_cast<void **>(vtable) + 2;
    const unsigned offsets[] = {0x54, 0x68, 0x6c, 0x70, 0x80, 0x84, 0x8c, 0xb4, 0xbc};
    const unsigned long addresses[] = {0x41f93a70, 0x41f929f8, 0x41f8e2a0, 0x41f8e5b8, 0x41f8e84c,
                                       0x41f8eacc, 0x41f8ebf4, 0x41f8f114, 0x41f8f910};
    for (unsigned i = 0; i < sizeof(offsets) / sizeof(offsets[0]); ++i)
        if (reinterpret_cast<unsigned long>(candidate[offsets[i] / 4]) -
                reinterpret_cast<unsigned long>(vtable) !=
            addresses[i] - 0x41fa8de8UL) {
            emit error(QString::fromUtf8("Неизвестный ABI плеера V8"));
            return false;
        }
    table_ = candidate;
    return true;
}
QWidget *MediaController::videoWidget() {
    return videoActive_ ? video_ : 0;
}
QWidget *MediaController::ensureVideoWidget() {
    if (video_)
        return video_;
    if (sizeof(void *) != 4)
        return 0;
    if (!videoLibrary_)
        videoLibrary_ = dlopen("libezx_mp_utility.so.1", RTLD_NOW | RTLD_GLOBAL);
    if (!videoLibrary_)
        return 0;
    void *ctor = dlsym(videoLibrary_, "_ZN14MP_VideoWidgetC1EP7QWidgetPKcj");
    void *dtor = dlsym(videoLibrary_, "_ZN14MP_VideoWidgetD1Ev");
    void *vtable = dlsym(videoLibrary_, "_ZTV14MP_VideoWidget");
    if (!ctor || !dtor || !vtable)
        return 0;
    // Supplied V8 utility constructor: sizeof=248, Ezx_VideoDevice at +196.
    // Constructor relative offset pins the layout; unknown firmware is refused.
    if (reinterpret_cast<unsigned long>(ctor) - reinterpret_cast<unsigned long>(vtable) !=
        0x41ffcdccUL - 0x42006c90UL)
        return 0;
    void *storage = std::malloc(248);
    if (!storage)
        return 0;
    QObject *owner = parent();
    // The SDK's inline isWidgetType bitfield test disagrees with the V8 Qt
    // build. Query the native metaobject instead of reading that SDK field.
    QWidget *surface = owner && owner->inherits("QWidget") ? static_cast<QWidget *>(owner) : 0;
    function<void (*)(void *, QWidget *, const char *, unsigned)>(ctor)(storage, surface,
                                                                        "telemotomax-video", 0);
    video_ = static_cast<QWidget *>(storage);
    connect(video_, SIGNAL(destroyed()), this, SLOT(videoDestroyed()));
    video_->resize(240, 280);
    video_->hide();
    return video_;
}
bool MediaController::play(const QString &path, int volume, bool audioOnly) {
    // A second alert must not close and immediately reopen the same device.
    // The native sound service may still be releasing it and return MPError 7.
    if (notification_ && active_)
        return true;
    stop();
    if (!load())
        return false;
    char resolved[PATH_MAX];
    if (!realpath(path.local8Bit().data(), resolved)) {
        emit error(QString::fromUtf8("Файл не найден"));
        return false;
    }
    bool video = !notification_ && !audioOnly &&
                 (path.lower().right(4) == ".3gp" || path.lower().right(4) == ".mp4");
    if (video && !ensureVideoWidget()) {
        emit error(QString::fromUtf8("Недоступен видеовыход V8"));
        return false;
    }
    device_ = new AM_NORMAL_DEV_INTERFACE;
    device_->flush();
    device_->close();
    // Motorola has a separate short-alert backend. It shares the verified
    // MediaPlayerEngine ABI but does not start the full media playback path.
    engine_ = notification_
                  ? function<CreateRingtone>(dlsym(library_, "MP_CreateRingtone"))(device_)
                  : function<Create>(dlsym(library_, "MP_CreateMediaPlayer"))(
                        device_, video ? reinterpret_cast<char *>(video_) + 196 : 0);
    if (!engine_) {
        release();
        emit error(QString::fromUtf8("Не удалось создать плеер"));
        return false;
    }
    void **actual;
    std::memcpy(&actual, engine_, sizeof(actual));
    if (actual != table_) {
        release();
        emit error(QString::fromUtf8("Несовместимый объект плеера"));
        return false;
    }
    if (!connect(engine_, SIGNAL(positionChanged(unsigned int, unsigned int)), this,
                 SLOT(position(unsigned int, unsigned int))) ||
        !connect(engine_, SIGNAL(playFinished()), this, SLOT(ended())) ||
        !connect(engine_, SIGNAL(errorOccurred(MPError)), this, SLOT(playbackError())) ||
        !connect(engine_, SIGNAL(audioDeviceUnavailable()), this, SLOT(unavailable()))) {
        release();
        emit error(QString::fromUtf8("Нет событий плеера"));
        return false;
    }
    active_ = true;
    failed_ = false;
    videoActive_ = video;
    elapsed_ = duration_ = 0;
    volume_ = bounded(volume);
    bool ok = function<Open>(table_[0x54 / 4])(engine_, resolved, 0);
    if (ok && !failed_) {
        function<Mute>(table_[0x8c / 4])(engine_, false);
        setVolume(volume_);
        ok = function<Play>(table_[0x6c / 4])(engine_, 1);
    }
    if (!ok || failed_) {
        if (!failed_)
            playbackError();
        release();
        return false;
    }
    if (video)
        video_->show();
    startup_.start(15000, true);
    return true;
}
void MediaController::release() {
    startup_.stop();
    if (engine_) {
        disconnect(engine_, 0, this, 0);
        function<Delete>(
            dlsym(library_, notification_ ? "MP_DeleteRingtone" : "MP_DeleteMediaPlayer"))(engine_);
        engine_ = 0;
    }
    delete device_;
    device_ = 0;
    active_ = false;
    videoActive_ = false;
    if (video_)
        video_->hide();
}
void MediaController::stop() {
    completion_.stop();
    pending_ = 0;
    pendingError_ = QString::null;
    release();
    failed_ = false;
}
void MediaController::setVolume(int value) {
    volume_ = bounded(value);
    if (engine_)
        function<Volume>(table_[0x84 / 4])(engine_, (volume_ * 7 + 50) / 100);
}
bool MediaController::pause(bool paused) {
    if (!active_ || !engine_)
        return false;
    bool ok = paused ? function<Call>(table_[0x70 / 4])(engine_)
                     : function<Play>(table_[0x6c / 4])(engine_, 1);
    if (ok && !failed_) {
        if (paused)
            startup_.stop();
        else if (!elapsed_)
            startup_.start(15000, true);
    }
    return ok && !failed_;
}
bool MediaController::seek(unsigned int ms) {
    return active_ && engine_ && function<Call>(table_[0xb4 / 4])(engine_) &&
           function<Seek>(table_[0x80 / 4])(engine_, ms);
}
bool MediaController::active() const {
    return active_;
}
void MediaController::ended() {
    if (active_ && !failed_) {
        startup_.stop();
        pending_ = 2;
        completion_.start(0, true);
    }
}
void MediaController::position(unsigned int elapsed, unsigned int duration) {
    if (active_ && !failed_) {
        if (elapsed)
            startup_.stop();
        elapsed_ = elapsed;
        duration_ = duration;
        if (!pending_)
            pending_ = 1;
        completion_.start(0, true);
    }
}
void MediaController::playbackError() {
    if (!engine_ || failed_)
        return;
    failed_ = true;
    startup_.stop();
    unsigned code = function<Code>(table_[0xbc / 4])(engine_);
    pendingError_ = code == 7
                        ? QString::fromUtf8("Звуковое устройство занято (Motorola: 7)")
                        : QString::fromUtf8("Ошибка плеера Motorola: ") + QString::number(code);
    pending_ = 3;
    completion_.start(0, true);
}
void MediaController::unavailable() {
    if (active_ && !failed_) {
        failed_ = true;
        startup_.stop();
        pendingError_ = QString::fromUtf8("Звуковое устройство занято");
        pending_ = 3;
        completion_.start(0, true);
    }
}
void MediaController::startupTimeout() {
    if (active_) {
        failed_ = true;
        pendingError_ = QString::fromUtf8("Плеер не подтвердил запуск");
        pending_ = 3;
        completion_.start(0, true);
    }
}
void MediaController::dispatch() {
    int event = pending_;
    pending_ = 0;
    if (event == 3) {
        QString reason = pendingError_;
        pendingError_ = QString::null;
        release();
        emit error(reason);
    } else if (event == 2) {
        release();
        emit finished();
    } else if (event == 1 && active_)
        emit positionChanged(elapsed_, duration_);
}
void MediaController::videoDestroyed() {
    video_ = 0;
}
} // namespace tmm
