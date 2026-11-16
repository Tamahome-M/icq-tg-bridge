#include "platform.h"
#include "media.h"
#include "external_display.h"
#include "zapplication_v8.h"
#include <ZKeyDef.h>
#include <qwidget.h>
#include <qfileinfo.h>
#include <dlfcn.h>
#include <unistd.h>
#include <sys/stat.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
extern "C" int UTIL_GetFlipStatus();
namespace tmm {
namespace {
template <class T> T fn(void *p) {
    T f;
    std::memcpy(&f, &p, sizeof(f));
    return f;
}
typedef int (*OpenDevice)(const char *);
typedef int (*Device)(int);
void put16(FILE *f, unsigned v) {
    std::fputc(v & 255, f);
    std::fputc((v >> 8) & 255, f);
}
void put32(FILE *f, unsigned v) {
    put16(f, v);
    put16(f, v >> 16);
}
QString makeTone() {
    char folder[] = "/tmp/tmm-native-tone-XXXXXX";
    if (!mkdtemp(folder))
        return QString("");
    QString path = QString::fromLatin1(folder) + "/disconnect.wav";
    FILE *f = std::fopen(path.local8Bit().data(), "wb");
    if (!f) {
        rmdir(folder);
        return QString("");
    }
    const unsigned rate = 8000, note = 640, gap = 240, count = note * 3 + gap * 2;
    std::fwrite("RIFF", 1, 4, f);
    put32(f, 36 + count * 2);
    std::fwrite("WAVEfmt ", 1, 8, f);
    put32(f, 16);
    put16(f, 1);
    put16(f, 1);
    put32(f, rate);
    put32(f, rate * 2);
    put16(f, 2);
    put16(f, 16);
    std::fwrite("data", 1, 4, f);
    put32(f, count * 2);
    const int frequencies[] = {880, 660, 440};
    for (unsigned n = 0; n < 3; ++n) {
        for (unsigned i = 0; i < note; ++i) {
            double envelope = i < 80 ? i / 80.0 : (i > note - 80 ? (note - i) / 80.0 : 1.0);
            short value = static_cast<short>(
                4000 * envelope * std::sin(6.283185307179586 * frequencies[n] * i / rate));
            put16(f, static_cast<unsigned short>(value));
        }
        if (n < 2)
            for (unsigned i = 0; i < gap; ++i)
                put16(f, 0);
    }
    bool ok = !std::ferror(f);
    if (std::fclose(f))
        ok = false;
    if (!ok) {
        unlink(path.local8Bit().data());
        rmdir(folder);
        return QString("");
    }
    chmod(path.local8Bit().data(), 0600);
    return path;
}
bool launch(const QString &document) {
    static void *library = dlopen("libezxappbase.so.1", RTLD_NOW | RTLD_LOCAL);
    if (!library)
        return false;
    void *ctor = dlsym(library, "_ZN20AM_LauncherInterfaceC1EP7QObjectPKc"),
         *dtor = dlsym(library, "_ZN20AM_LauncherInterfaceD1Ev"),
         *open = dlsym(library, "_ZN20AM_LauncherInterface8autoOpenERK7QStringb");
    if (!ctor || !dtor || !open)
        return false;
    // Exact V8 constructor initializes QObject and vptr only; no derived fields.
    void *p = std::malloc(sizeof(QObject));
    if (!p)
        return false;
    fn<void (*)(void *, QObject *, const char *)>(ctor)(p, 0, "telemotomax-launcher");
    fn<void (*)(void *, const QString &, bool)>(open)(p, document, true);
    fn<void (*)(void *)>(dtor)(p);
    std::free(p);
    return true;
}
} // namespace
Platform::Platform(QObject *p)
    : QObject(p), window_(0), sound_(new MediaController(this)),
      external_(new ExternalDisplay(this)),
      soundLibrary_(dlopen("libezxsound.so", RTLD_NOW | RTLD_LOCAL)), vibrationHandle_(0),
      backlightHandle_(0), closed_(UTIL_GetFlipStatus() == SYSTEM_FLIP_CLOSE) {
    connect(qApp, SIGNAL(flipStatusChanged(int)), this, SLOT(lidChanged(int)));
    connect(&vibration_, SIGNAL(timeout()), this, SLOT(endVibration()));
    connect(sound_, SIGNAL(error(const QString &)), this, SIGNAL(error(const QString &)));
    connect(external_, SIGNAL(error(const QString &)), this, SIGNAL(error(const QString &)));
}
Platform::~Platform() {
    endVibration();
    setBacklight(false);
    delete external_;
    delete sound_;
    if (!tonePath_.isEmpty()) {
        unlink(tonePath_.local8Bit().data());
        QString folder = QFileInfo(tonePath_).dirPath();
        rmdir(folder.local8Bit().data());
    }
}
void Platform::setWindow(QWidget *w) {
    window_ = w;
}
bool Platform::flipClosed() const {
    return closed_;
}
void Platform::lidChanged(int state) {
    bool value = state == SYSTEM_FLIP_CLOSE;
    if (value == closed_)
        return;
    closed_ = value;
    if (value)
        setBacklight(false);
    else
        external_->clear();
    emit flipChanged(value);
}
void Platform::minimize() {
    if (window_)
        window_->hide();
}
void Platform::requestForeground() {
    if (window_ && !closed_) {
        window_->showFullScreen();
        window_->raise();
        window_->setActiveWindow();
        static_cast<ZApplication *>(qApp)->raiseAppWindows();
    }
}
void Platform::setBacklight(bool on) {
    if (!soundLibrary_)
        return;
    OpenDevice open = fn<OpenDevice>(dlsym(soundLibrary_, "SOUNDM_VBBLM_BackLightOpenDev"));
    Device enable = fn<Device>(dlsym(soundLibrary_, "SOUNDM_VBBLM_BackLightDevON")),
           disable = fn<Device>(dlsym(soundLibrary_, "SOUNDM_VBBLM_BackLightDevOFF")),
           close = fn<Device>(dlsym(soundLibrary_, "SOUNDM_VBBLM_BackLightCloseDev"));
    if (!open || !enable || !disable || !close)
        return;
    if (on && !closed_) {
        if (backlightHandle_ <= 0)
            backlightHandle_ = open("TeleMotoMax");
        if (backlightHandle_ > 0)
            enable(backlightHandle_);
    } else if (backlightHandle_ > 0) {
        disable(backlightHandle_);
        close(backlightHandle_);
        backlightHandle_ = 0;
    }
}
void Platform::vibrate(int ms) {
    endVibration();
    if (ms <= 0)
        return;
    if (ms > 2000)
        ms = 2000;
    if (!soundLibrary_) {
        emit error(QString::fromUtf8("Недоступна вибрация"));
        return;
    }
    OpenDevice open = fn<OpenDevice>(dlsym(soundLibrary_, "SOUNDM_VBBLM_VibeOpenDev"));
    Device on = fn<Device>(dlsym(soundLibrary_, "SOUNDM_VBBLM_VibeDevON"));
    if (!open || !on) {
        emit error(QString::fromUtf8("Нет API вибрации"));
        return;
    }
    vibrationHandle_ = open("TeleMotoMax");
    if (vibrationHandle_ <= 0) {
        vibrationHandle_ = 0;
        emit error(QString::fromUtf8("Вибрация занята"));
        return;
    }
    on(vibrationHandle_);
    vibration_.start(ms, true);
}
void Platform::endVibration() {
    vibration_.stop();
    if (vibrationHandle_ > 0) {
        Device off = fn<Device>(dlsym(soundLibrary_, "SOUNDM_VBBLM_VibeDevOFF")),
               close = fn<Device>(dlsym(soundLibrary_, "SOUNDM_VBBLM_VibeCloseDev"));
        if (off)
            off(vibrationHandle_);
        if (close)
            close(vibrationHandle_);
        vibrationHandle_ = 0;
    }
}
void Platform::notifyMessage(const QString &file, int volume, int ms) {
    vibrate(ms);
    if (volume <= 0 || file.isEmpty())
        return;
    if (file == "tone")
        notifyDisconnected(volume);
    else
        sound_->play(file, volume);
}
void Platform::notifyDisconnected(int volume) {
    if (volume <= 0)
        return;
    if (tonePath_.isEmpty())
        tonePath_ = makeTone();
    if (tonePath_.isEmpty()) {
        emit error(QString::fromUtf8("Не удалось создать сигнал"));
        return;
    }
    sound_->play(tonePath_, volume);
}
void Platform::clearExternalText() {
    external_->clear();
}
void Platform::externalText(const QString &title, const QString &text, int seconds) {
    if (closed_)
        external_->showText(title, text, seconds);
}
bool Platform::openUrl(const QString &url) {
    if (!(url.startsWith("http://") || url.startsWith("https://")) || url.find('\n') >= 0 ||
        url.find('\r') >= 0) {
        emit error(QString::fromUtf8("Неверный адрес"));
        return false;
    }
    bool ok = launch(url);
    if (!ok)
        emit error(QString::fromUtf8("Недоступен запуск браузера"));
    return ok;
}
bool Platform::openFile(const QString &path) {
    QFileInfo info(path);
    if (!info.isFile())
        return false;
    bool ok = launch(info.absFilePath());
    if (!ok)
        emit error(QString::fromUtf8("Недоступно открытие файла"));
    return ok;
}
} // namespace tmm
