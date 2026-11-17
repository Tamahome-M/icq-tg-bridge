#include "capture.h"
#include "capture_codec.h"
#include "capture_media.h"
#include "camera_ui_v8.h"
#include <qdialog.h>
#include <qimage.h>
#include <qfileinfo.h>
#include <ezxsound.h>
#include <pthread.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <fcntl.h>
#include <dlfcn.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
namespace tmm {
namespace {
template <class T> T fn(void *p) {
    T f;
    std::memcpy(&f, &p, sizeof(f));
    return f;
}
unsigned long now() {
    timeval value;
    gettimeofday(&value, 0);
    return static_cast<unsigned long>(value.tv_sec) * 1000 + value.tv_usec / 1000;
}
bool reserve(const QString &path) {
    int fd = ::open(path.local8Bit().data(), O_WRONLY | O_CREAT | O_EXCL, 0600);
    if (fd < 0)
        return false;
    ::close(fd);
    return true;
}
bool copyFile(const QString &from, const QString &to) {
    if (from == to)
        return QFileInfo(to).size() > 0;
    FILE *in = std::fopen(from.local8Bit().data(), "rb");
    if (!in)
        return false;
    FILE *out = std::fopen(to.local8Bit().data(), "wb");
    if (!out) {
        std::fclose(in);
        return false;
    }
    char buffer[8192];
    size_t n;
    unsigned total = 0;
    bool ok = true;
    while ((n = std::fread(buffer, 1, sizeof(buffer), in)) != 0) {
        total += n;
        if (total > 16 * 1024 * 1024 || std::fwrite(buffer, 1, n, out) != n) {
            ok = false;
            break;
        }
    }
    if (std::ferror(in) || std::ferror(out))
        ok = false;
    if (std::fclose(out))
        ok = false;
    std::fclose(in);
    return ok && total > 0;
}
} // namespace
// Use the stock VoiceNote input device (0x303) and 160-sample AMR frames.
// Keep the native 4000-sample packet size. Only the worker touches the AAL
// handle: pause/close share AAL_read's mutex and cannot safely cancel it from UI.
class VoiceCapture {
  public:
    VoiceCapture(const char *path, int seconds, unsigned bitrate)
        : path_(path), seconds_(seconds), bitrate_(bitrate), started_(false), stop_(false),
          done_(false), error_(0), frames_(0) {
        pthread_mutex_init(&mutex_, 0);
    }
    ~VoiceCapture() {
        stop();
        if (started_)
            pthread_join(thread_, 0);
        pthread_mutex_destroy(&mutex_);
    }
    bool start() {
        started_ = pthread_create(&thread_, 0, entry, this) == 0;
        return started_;
    }
    void stop() {
        pthread_mutex_lock(&mutex_);
        stop_ = true;
        pthread_mutex_unlock(&mutex_);
    }
    bool done() {
        pthread_mutex_lock(&mutex_);
        bool value = done_;
        pthread_mutex_unlock(&mutex_);
        return value;
    }
    unsigned error() const {
        return error_;
    }
    unsigned frames() {
        pthread_mutex_lock(&mutex_);
        unsigned value = frames_;
        pthread_mutex_unlock(&mutex_);
        return value;
    }

  private:
    bool stopped() {
        pthread_mutex_lock(&mutex_);
        bool value = stop_;
        pthread_mutex_unlock(&mutex_);
        return value;
    }
    static void *entry(void *p) {
        VoiceCapture *self = static_cast<VoiceCapture *>(p);
        self->record();
        pthread_mutex_lock(&self->mutex_);
        self->done_ = true;
        pthread_mutex_unlock(&self->mutex_);
        return 0;
    }
    void record() {
        AmrWriter writer;
        if (!writer.open(path_.c_str(), bitrate_)) {
            error_ = writer.error();
            return;
        }
        if (stopped())
            return;
        AM_NORMAL_DEV_INTERFACE input(static_cast<SOUNDM_AUDIO_NORMALDEV_TYPE_ENUM_T>(0x303));
        const unsigned chunk = 4000; // Stock VoiceNote PCM packet at 8 kHz.
        short samples[chunk], frame[160];
        unsigned filled = 0, deadline = now() + 5000;
        while (!stopped() && frames_ < static_cast<unsigned>(seconds_) * 50) {
            if (input.canRead() != 0) {
                if (static_cast<long>(now() - deadline) >= 0) {
                    error_ = 201;
                    break;
                }
                usleep(20000);
                continue;
            }
            // canRead may wait for the audio service. A Stop received during
            // that wait must not start another blocking PCM read afterward.
            if (stopped())
                break;
            int count = input.read(samples, chunk);
            if (stopped())
                break;
            if (count < 0 || count > static_cast<int>(chunk)) {
                error_ = 202;
                break;
            }
            if (!count) {
                if (static_cast<long>(now() - deadline) >= 0) {
                    error_ = 201;
                    break;
                }
                usleep(20000);
                continue;
            }
            deadline = now() + 5000;
            for (int i = 0;
                 i < count && !stopped() && frames_ < static_cast<unsigned>(seconds_) * 50;) {
                unsigned take = 160 - filled;
                if (take > static_cast<unsigned>(count - i))
                    take = count - i;
                std::memcpy(frame + filled, samples + i, take * sizeof(short));
                filled += take;
                i += take;
                if (filled == 160) {
                    if (!writer.write(frame)) {
                        error_ = writer.error();
                        break;
                    }
                    filled = 0;
                    pthread_mutex_lock(&mutex_);
                    ++frames_;
                    pthread_mutex_unlock(&mutex_);
                }
            }
            if (error_)
                break;
        }
        input.close();
        if (!writer.close() && !error_)
            error_ = writer.error();
    }
    std::string path_;
    int seconds_;
    unsigned bitrate_;
    pthread_t thread_;
    pthread_mutex_t mutex_;
    bool started_, stop_, done_;
    unsigned error_, frames_;
};
CaptureController::CaptureController(QObject *p)
    : QObject(p), window_(0), dialog_(0), busy_(false), cancelled_(false), cameraLibrary_(0),
      cameraEngineLibrary_(0), voice_(0), size_("480x640"), encoding_("jpeg"), voiceBitrate_(6700),
      duration_(0), videoSeconds_(0) {
    connect(&timer_, SIGNAL(timeout()), this, SLOT(poll()));
}
CaptureController::~CaptureController() {
    cancel();
    timer_.stop();
    delete voice_;
    voice_ = 0;
    if (busy_ && !destination_.isEmpty())
        unlink(destination_.local8Bit().data());
}
void CaptureController::setWindow(QWidget *w) {
    window_ = w;
}
QStringList CaptureController::supportedSizes() {
    return QStringList::split('|', "960x1280|480x640|640x480|320x240|240x320|160x120");
}
QStringList CaptureController::supportedEncodings() {
    return QStringList::split('|', "jpeg");
}
void CaptureController::setProfile(const QString &size, const QString &encoding) {
    if (supportedSizes().contains(size) && encoding.lower() == "jpeg") {
        size_ = size;
        encoding_ = "jpeg";
    }
}
void CaptureController::setVoiceBitrate(unsigned bitrate) {
    // The client presents 4.8/5.2/8.0 kbit/s, whereas native AMR expects
    // the exact 4750/5150/7950 bit/s modes.
    if (bitrate == 4800)
        bitrate = 4750;
    else if (bitrate == 5200)
        bitrate = 5150;
    else if (bitrate == 8000)
        bitrate = 7950;
    const unsigned rates[] = {4750, 5150, 5900, 6700, 7400, 7950, 10200, 12200};
    for (unsigned i = 0; i < 8; ++i)
        if (rates[i] == bitrate)
            voiceBitrate_ = bitrate;
}
bool CaptureController::busy() const {
    return busy_;
}
void CaptureController::fitPhotoSize(int &width, int &height, int maximumWidth, int maximumHeight) {
    if (width <= 0 || height <= 0 || maximumWidth <= 0 || maximumHeight <= 0 ||
        (width <= maximumWidth && height <= maximumHeight))
        return;
    if (static_cast<long>(width) * maximumHeight > static_cast<long>(height) * maximumWidth) {
        height = static_cast<long>(height) * maximumWidth / width;
        width = maximumWidth;
        if (!height)
            height = 1;
    } else {
        width = static_cast<long>(width) * maximumHeight / height;
        height = maximumHeight;
        if (!width)
            width = 1;
    }
}
unsigned CaptureController::durationSeconds() const {
    return voice_ ? voice_->frames() / 50 : duration_;
}
void CaptureController::capturePhoto(const QString &path) {
    camera(path, false, 0);
}
void CaptureController::recordVideo(const QString &path, int seconds) {
    camera(path, true, seconds);
}
void CaptureController::recordVoice(const QString &path, int seconds) {
    if (busy_) {
        emit error(QString::fromUtf8("Запись уже идёт"));
        return;
    }
    if (seconds < 1)
        seconds = 1;
    if (seconds > 600)
        seconds = 600;
    if (!reserve(path)) {
        emit error(QString::fromUtf8("Не удалось создать файл записи"));
        return;
    }
    destination_ = path;
    cancelled_ = false;
    duration_ = 0;
    voice_ = new VoiceCapture(path.local8Bit().data(), seconds, voiceBitrate_);
    if (!voice_->start()) {
        delete voice_;
        voice_ = 0;
        unlink(path.local8Bit().data());
        destination_ = QString::null;
        emit error(QString::fromUtf8("Не удалось начать запись"));
        return;
    }
    busy_ = true;
    timer_.start(100);
}
void CaptureController::stop() {
    if (voice_) {
        std::fprintf(stderr, "Voice recording: stop requested at %u AMR frames\n",
                     voice_->frames());
        voice_->stop();
    } else if (dialog_)
        cancel();
}
void CaptureController::cancel() {
    if (!busy_)
        return;
    if (dialog_ && dialog_->result() == QDialog::Accepted)
        return; // A late AM/background notification cannot discard a saved shot.
    cancelled_ = true;
    if (voice_)
        voice_->stop();
    if (dialog_) {
        fn<void (*)(void *)>(dlsym(cameraLibrary_, "_ZN10CAM_UI_Dlg6cancelEv"))(dialog_);
    }
}
void CaptureController::poll() {
    if (voice_ && voice_->done()) {
        timer_.stop();
        unsigned code = voice_->error(), frames = voice_->frames();
        std::fprintf(stderr, "Voice recording: completed, %u AMR frames, error %u, cancelled %d\n",
                     frames, code, cancelled_ ? 1 : 0);
        delete voice_;
        voice_ = 0;
        busy_ = false;
        QString path = destination_;
        destination_ = QString::null;
        if (cancelled_ || code || !frames) {
            unlink(path.local8Bit().data());
            if (cancelled_)
                emit cancelled();
            else
                emit error(QString::fromUtf8("Ошибка записи звука: ") + QString::number(code));
        } else {
            duration_ = (frames + 49) / 50;
            emit ready(path, "audio/amr");
        }
        return;
    }
    if (dialog_ && videoSeconds_) {
        // SAedition camera manager is a second base at +208. Its model owns the
        // stock CAM_3GPRecorder at +416 (same path used by the native Record key).
        void *model =
            fn<void *(*)(void *)>(dlsym(cameraLibrary_, "_ZN14CAM_UI_Manager11globalModelEv"))(
                reinterpret_cast<char *>(dialog_) + 208);
        if (!model)
            return;
        void *recorder = 0;
        std::memcpy(&recorder, static_cast<char *>(model) + 416, 4);
        if (!recorder)
            return;
        void **table = 0;
        std::memcpy(&table, recorder, 4);
        void *expected = dlsym(cameraEngineLibrary_, "_ZTV15CAM_3GPRecorder");
        if (table != static_cast<void **>(expected) + 2)
            return;
        int current = 0;
        std::memcpy(&current, static_cast<char *>(recorder) + 24, 4);
        if (current != videoSeconds_)
            fn<int (*)(void *, int)>(
                dlsym(cameraEngineLibrary_, "_ZN15CAM_3GPRecorder18setVideoLengthSecsEi"))(
                recorder, videoSeconds_);
    }
}
void CaptureController::camera(const QString &path, bool video, int seconds) {
    if (busy_) {
        emit error(QString::fromUtf8("Камера уже открыта"));
        return;
    }
    if (!cameraLibrary_)
        cameraLibrary_ = dlopen("libezxcamera.so.1", RTLD_NOW | RTLD_GLOBAL);
    if (!cameraEngineLibrary_)
        cameraEngineLibrary_ = dlopen("libezxcameraengine.so.1", RTLD_NOW | RTLD_GLOBAL);
    const char *symbols[] = {"CreateCameraDlg",
                             "DestroyCameraDlg",
                             "SetCameraFileName",
                             "GetCameraFileName",
                             "SetCameraPhotoMaxLimitation",
                             "SetCameraVideoMaxLimitation",
                             "_ZN10CAM_UI_Dlg6cancelEv",
                             "_ZN14CAM_UI_Manager11globalModelEv"};
    bool valid = cameraLibrary_ && cameraEngineLibrary_ && sizeof(void *) == 4;
    for (unsigned i = 0; valid && i < sizeof(symbols) / sizeof(symbols[0]); ++i)
        valid = dlsym(cameraLibrary_, symbols[i]) != 0;
    if (valid) {
        void *create = dlsym(cameraLibrary_, "CreateCameraDlg"),
             *cancel = dlsym(cameraLibrary_, "_ZN10CAM_UI_Dlg6cancelEv");
        valid = reinterpret_cast<unsigned long>(create) - reinterpret_cast<unsigned long>(cancel) ==
                0x42e52c18UL - 0x42e51d0cUL;
    }
    if (video)
        valid = valid && dlsym(cameraEngineLibrary_, "_ZTV15CAM_3GPRecorder") &&
                dlsym(cameraEngineLibrary_, "_ZN15CAM_3GPRecorder18setVideoLengthSecsEi");
    if (!valid) {
        emit error(QString::fromUtf8("Недоступна камера этой прошивки V8"));
        return;
    }
    if (!reserve(path)) {
        emit error(QString::fromUtf8("Не удалось создать файл камеры"));
        return;
    }
    busy_ = true;
    cancelled_ = false;
    destination_ = path;
    duration_ = 0;
    videoSeconds_ = video ? (seconds < 1 ? 1 : seconds > 30 ? 30 : seconds) : 0;
    typedef QDialog *(*Create)(int, int, QWidget *, const char *, bool, bool, const char *);
    dialog_ = fn<Create>(dlsym(cameraLibrary_, "CreateCameraDlg"))(
        video ? 2 : 1, 4 * 1024 * 1024, window_, "telemotomax-camera", true, false, 0);
    if (!dialog_) {
        busy_ = false;
        unlink(path.local8Bit().data());
        destination_ = QString::null;
        emit error(QString::fromUtf8("Не удалось открыть камеру"));
        return;
    }
    fn<void (*)(void *, const char *)>(dlsym(cameraLibrary_, "SetCameraFileName"))(
        dialog_, path.local8Bit().data());
    int x = size_.find('x'), width = size_.left(x).toInt(), height = size_.mid(x + 1).toInt();
    fn<void (*)(void *, int, int)>(dlsym(cameraLibrary_, video ? "SetCameraVideoMaxLimitation"
                                                               : "SetCameraPhotoMaxLimitation"))(
        dialog_, video ? 320 : width, video ? 240 : height);
    if (video)
        timer_.start(100);
    CameraUiV8 cameraUi(dialog_, cameraLibrary_, video);
    if (!cameraUi.valid()) {
        timer_.stop();
        fn<void (*)(void *)>(dlsym(cameraLibrary_, "DestroyCameraDlg"))(dialog_);
        dialog_ = 0;
        busy_ = false;
        videoSeconds_ = 0;
        destination_ = QString::null;
        unlink(path.local8Bit().data());
        emit error(QString::fromUtf8("Несовместимый интерфейс камеры V8"));
        return;
    }
    int result = dialog_->exec();
    cameraUi.detach();
    timer_.stop();
    QString recorded = cameraFileName(dialog_);
    // A service dialog owns its temporary result. Preserve it before the
    // native destructor removes temporary camera files.
    const QString staged = path + ".captured";
    bool ownsStaged =
        result == QDialog::Accepted && !cancelled_ && !recorded.isEmpty() && reserve(staged);
    bool ok = ownsStaged && copyFile(recorded, staged);
    std::fprintf(stderr, "Camera %s: result %d, cancelled %d, result path %s, copied %d\n",
                 video ? "video" : "photo", result, cancelled_ ? 1 : 0,
                 recorded.isEmpty() ? "empty" : "present", ok ? 1 : 0);
    fn<void (*)(void *)>(dlsym(cameraLibrary_, "DestroyCameraDlg"))(dialog_);
    dialog_ = 0;
    videoSeconds_ = 0;
    if (ok)
        ok = ::rename(staged.local8Bit().data(), path.local8Bit().data()) == 0;
    if (ownsStaged)
        unlink(staged.local8Bit().data());
    if (ok && !video) {
        QImage image(path);
        ok = !image.isNull();
        if (ok) {
            // Native camera can return a smaller or differently oriented frame.
            // Treat the selected size as bounds, preserving its proportions.
            int fittedWidth = image.width(), fittedHeight = image.height();
            fitPhotoSize(fittedWidth, fittedHeight, width, height);
            if (image.width() != fittedWidth || image.height() != fittedHeight) {
                image = image.smoothScale(fittedWidth, fittedHeight);
                ok = !image.isNull() && image.save(path, "JPEG", 85);
            }
        }
    }
    busy_ = false;
    destination_ = QString::null;
    if (!ok) {
        unlink(path.local8Bit().data());
        if (!cancelled_ && result == QDialog::Accepted)
            emit error(QString::fromUtf8("Камера не сохранила файл"));
        else
            emit cancelled();
    } else {
        chmod(path.local8Bit().data(), 0600);
        duration_ = video ? captureDuration(path.local8Bit().data()) : 0;
        emit ready(path, video ? "video/3gpp" : "image/jpeg");
    }
}
QString CaptureController::cameraFileName(QDialog *dialog) const {
    // V8 GetCameraFileName returns the model's QString by reference, not a
    // char buffer: its export returns model+584, which CAM_UI_Dlg::done passes
    // directly to QString's copy constructor. Copy while the dialog still owns
    // the model; interpreting these object bytes as UTF-8 corrupts the path.
    const QString *actual =
        fn<const QString *(*)(void *)>(dlsym(cameraLibrary_, "GetCameraFileName"))(dialog);
    return actual ? *actual : QString::null;
}
} // namespace tmm
