#include "external_display.h"
#include <dlfcn.h>
#include <cstdlib>
#include <cstring>
namespace tmm {
namespace {
template <class T> T fn(void *p) {
    T f;
    std::memcpy(&f, &p, sizeof(f));
    return f;
}
typedef void (*Construct)(void *, QObject *, const char *);
typedef void (*Destroy)(void *);
typedef void (*Command)(QObject *);
typedef void (*DataConstruct)(void *, const QString &, const QString &, unsigned char,
                              const QString &, const QString &, const QString &, int);
typedef bool (*DisplayInfo)(QObject *, const void *);
} // namespace
ExternalDisplay::ExternalDisplay(QObject *p)
    : QObject(p), library_(0), client_(0), attempts_(0), ready_(false) {
    connect(&lifetime_, SIGNAL(timeout()), this, SLOT(expired()));
    connect(&retry_, SIGNAL(timeout()), this, SLOT(publish()));
}
ExternalDisplay::~ExternalDisplay() {
    clear();
}
bool ExternalDisplay::load() {
    if (!library_)
        library_ = dlopen("libezxopenwindow.so.1", RTLD_NOW | RTLD_LOCAL);
    if (!library_)
        return false;
    const char *names[] = {"_ZN3CLI10InfoClientC1EP7QObjectPKc",
                           "_ZN3CLI10InfoClientD1Ev",
                           "_ZN3CLI17BaseFeatureClient12beginSessionEv",
                           "_ZN3CLI17BaseFeatureClient10endSessionEv",
                           "_ZN3CLI8InfoDataC1ERK7QStringS3_hS3_S3_S3_NS_15CLI_INFO_DLG_IDE",
                           "_ZN3CLI8InfoDataD1Ev",
                           "_ZN3CLI10InfoClient11displayInfoERKNS_8InfoDataE",
                           "_ZTVN3CLI10InfoClientE"};
    for (unsigned i = 0; i < sizeof(names) / sizeof(names[0]); ++i)
        if (!dlsym(library_, names[i]))
            return false;
    void *ctor = dlsym(library_, "_ZN3CLI10InfoClientC1EP7QObjectPKc"),
         *table = dlsym(library_, "_ZTVN3CLI10InfoClientE");
    return sizeof(void *) == 4 &&
           reinterpret_cast<unsigned long>(ctor) - reinterpret_cast<unsigned long>(table) ==
               0x41e034c0UL - 0x41e17638UL;
}
bool ExternalDisplay::showText(const QString &title, const QString &text, int seconds) {
    if (!load()) {
        emit error(QString::fromUtf8("Недоступен внешний экран V8"));
        return false;
    }
    title_ = title.left(80);
    text_ = text.left(640);
    attempts_ = 5;
    if (!client_) {
        // Exact SAedition constructors: InfoClient 108 bytes, embedded InfoData
        // occupies [52,92). Invoke native constructors rather than inventing fields.
        void *p = std::calloc(1, 108);
        if (!p)
            return false;
        fn<Construct>(dlsym(library_, "_ZN3CLI10InfoClientC1EP7QObjectPKc"))(
            p, 0, "telemotomax-notification");
        client_ = static_cast<QObject *>(p);
        if (!connect(client_, SIGNAL(sessionBegan()), this, SLOT(sessionReady()))) {
            clear();
            emit error(QString::fromUtf8("Неизвестный интерфейс внешнего экрана"));
            return false;
        }
        connect(client_, SIGNAL(sigCloseDisplay()), this, SLOT(displayClosed()));
        fn<Command>(dlsym(library_, "_ZN3CLI17BaseFeatureClient12beginSessionEv"))(client_);
    }
    if (seconds < 1)
        seconds = 1;
    if (seconds > 60)
        seconds = 60;
    lifetime_.start(seconds * 1000, true);
    if (ready_)
        publish();
    retry_.start(1000);
    return true;
}
void ExternalDisplay::sessionReady() {
    ready_ = true;
    publish();
}
void ExternalDisplay::publish() {
    if (!client_ || !ready_ || attempts_ <= 0)
        return;
    // Native InfoData defaults dialog-id to18; zero buttons, no image. This is
    // a generic information window, never an SMS record or a media-player item.
    unsigned long data[10];
    std::memset(data, 0, sizeof(data));
    QString empty("");
    fn<DataConstruct>(
        dlsym(library_, "_ZN3CLI8InfoDataC1ERK7QStringS3_hS3_S3_S3_NS_15CLI_INFO_DLG_IDE"))(
        data, title_, text_, 0, empty, empty, empty, 18);
    bool accepted = fn<DisplayInfo>(
        dlsym(library_, "_ZN3CLI10InfoClient11displayInfoERKNS_8InfoDataE"))(client_, data);
    fn<Destroy>(dlsym(library_, "_ZN3CLI8InfoDataD1Ev"))(data);
    if (!accepted) {
        retry_.stop();
        attempts_ = 0;
        emit error(QString::fromUtf8("Внешний экран отверг уведомление"));
        return;
    }
    if (--attempts_ == 0)
        retry_.stop();
}
void ExternalDisplay::displayClosed() {
    retry_.stop();
    attempts_ = 0;
    lifetime_.start(0, true);
}
void ExternalDisplay::expired() {
    clear();
}
void ExternalDisplay::clear() {
    lifetime_.stop();
    retry_.stop();
    ready_ = false;
    attempts_ = 0;
    if (client_) {
        QObject *p = client_;
        client_ = 0;
        disconnect(p, 0, this, 0);
        fn<Command>(dlsym(library_, "_ZN3CLI17BaseFeatureClient10endSessionEv"))(p);
        fn<Destroy>(dlsym(library_, "_ZN3CLI10InfoClientD1Ev"))(p);
        std::free(p);
    }
    title_ = text_ = QString("");
}
} // namespace tmm
