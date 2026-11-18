// Production play()/Qt callbacks on the V8 firmware. Only the device and
// native engine calls are fixtures; no speaker, decoder or worker is started.
#include <qobject.h>
#include <qstring.h>
#include <qtimer.h>
#define private public
#include "media.h"
#undef private
#include "media_test_observer.h"
#include <qapplication.h>
#include <qmetaobject.h>
#include <ezxsound.h>
#include <dlfcn.h>
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <unistd.h>
MediaTestObserver::MediaTestObserver(tmm::MediaController &media)
    : finishedCount(0), errorCount(0), reportedWhileActive(false), media_(media) {
    assert(connect(&media, SIGNAL(finished()), this, SLOT(finished())));
    assert(connect(&media, SIGNAL(error(const QString &)), this, SLOT(error(const QString &))));
}
void MediaTestObserver::finished() {
    ++finishedCount;
    reportedWhileActive = reportedWhileActive || media_.active();
}
void MediaTestObserver::error(const QString &reason) {
    ++errorCount;
    lastError = reason;
    reportedWhileActive = reportedWhileActive || media_.active();
}
template <class T> T fn(void *p) {
    assert(p);
    T result;
    std::memcpy(&result, &p, sizeof(result));
    return result;
}
template <class T> void *symbol(T function) {
    void *result;
    assert(sizeof(result) == sizeof(function));
    std::memcpy(&result, &function, sizeof(result));
    return result;
}
class EngineEvents : public QObject {
  public:
    QMetaObject *metaObject() const {
        return meta;
    }
    const char *className() const {
        return "MP_PlayerEngine";
    }
    static QMetaObject *meta;
};
QMetaObject *EngineEvents::meta;
static void **qtTable;
static void *engineTable[0xc0 / 4];
static QObject *engine;
static tmm::MediaController *controller;
static std::string calls;
static void (*sendFinished)(QObject *);
static void (*sendError)(QObject *, unsigned short);
static void (*sendPosition)(QObject *, unsigned, unsigned);
static void (*sendUnavailable)(QObject *);
static bool inCallback;
static unsigned short storedError;
static unsigned codeReads;
enum Behavior { Normal, FinishThenError, ErrorThenFinish, OpenFailure, VolumeFailure, PlayFailure };
static Behavior behavior;
AM_NORMAL_DEV_INTERFACE::AM_NORMAL_DEV_INTERFACE() {
    calls += 'D';
}
AM_NORMAL_DEV_INTERFACE::~AM_NORMAL_DEV_INTERFACE() {
    calls += 'd';
}
void AM_NORMAL_DEV_INTERFACE::flush() {
    calls += 'F';
}
void AM_NORMAL_DEV_INTERFACE::close() {
    calls += 'C';
}
static QObject *createEngine(void *device, bool ringtone) {
    assert(controller && device == controller->device_ && !engine);
    assert(controller->notification_ == ringtone);
    calls += ringtone ? 'R' : 'M';
    engine = new EngineEvents;
    void **table = engineTable;
    std::memcpy(engine, &table, sizeof(table));
    return engine;
}
static QObject *createRingtone(void *device) {
    return createEngine(device, true);
}
static QObject *createMediaPlayer(void *device, void *video) {
    assert(!video);
    return createEngine(device, false);
}
static void deleteEngine(QObject *value) {
    assert(value == engine && !inCallback && !controller->active() && !controller->engine_);
    calls += 'X';
    std::memcpy(value, &qtTable, sizeof(qtTable));
    engine = 0;
    delete value;
}
extern "C" void *__real_dlsym(void *, const char *);
extern "C" void *__wrap_dlsym(void *library, const char *name) {
    if (!std::strcmp(name, "MP_CreateRingtone"))
        return symbol(&createRingtone);
    if (!std::strcmp(name, "MP_CreateMediaPlayer"))
        return symbol(&createMediaPlayer);
    if (!std::strcmp(name, "MP_DeleteRingtone") || !std::strcmp(name, "MP_DeleteMediaPlayer"))
        return symbol(&deleteEngine);
    return __real_dlsym(library, name);
}
static void finishThenLateEvents() {
    inCallback = true;
    sendFinished(engine);
    sendPosition(engine, 1000, 1000);
    sendError(engine, 2);
    sendUnavailable(engine);
    inCallback = false;
}
static bool openEngine(QObject *value, const char *path, int mode) {
    assert(value == engine && path && access(path, F_OK) == 0 && mode == 0);
    calls += 'O';
    return behavior != OpenFailure;
}
static unsigned volumeEngine(QObject *value, unsigned level) {
    assert(value == engine && level == 2); // 30% maps to V8's 0..7 scale.
    calls += 'V';
    if (behavior == VolumeFailure) {
        inCallback = true;
        sendError(engine, 2);
        inCallback = false;
    }
    return 7;
}
static bool muteEngine(QObject *, bool) {
    calls += 'U';
    return false;
}
static bool playEngine(QObject *value, int mode) {
    assert(value == engine && mode == 1);
    calls += 'P';
    if (behavior == FinishThenError)
        finishThenLateEvents();
    else if (behavior == ErrorThenFinish) {
        inCallback = true;
        sendError(engine, 2);
        sendFinished(engine);
        inCallback = false;
    }
    return behavior != PlayFailure;
}
static unsigned short getError(QObject *value) {
    assert(value == engine);
    ++codeReads;
    return storedError;
}
static void prepare(tmm::MediaController &media, Behavior next) {
    assert(!engine && !media.active());
    controller = &media;
    media.table_ = engineTable;
    behavior = next;
    calls.clear();
    codeReads = 0;
    storedError = 7; // Deliberately differs from errorOccurred(2).
}
static void dispatch(QApplication &app, tmm::MediaController &media) {
    for (unsigned i = 0; i < 10 && media.pending_; ++i)
        app.processEvents();
    assert(!media.pending_ && !media.active() && !engine);
}
int main(int argc, char **argv) {
    QApplication app(argc, argv, false);
    tmm::MediaController media, alert(0, true);
    // Production load() verifies the firmware factory and vtable addresses.
    assert(media.load() && alert.load());
    void *library = dlopen("libezx_mp_playerengine.so.1", RTLD_NOW | RTLD_GLOBAL);
    EngineEvents::meta =
        fn<QMetaObject *(*)()>(dlsym(library, "_ZN15MP_PlayerEngine16staticMetaObjectEv"))();
    EngineEvents prototype;
    std::memcpy(&qtTable, &prototype, sizeof(qtTable));
    // Retain this QObject's actual Qt virtuals, then replace only media calls.
    std::memcpy(engineTable, media.table_, sizeof(engineTable));
    std::memcpy(engineTable, qtTable, 0x40);
    engineTable[0x54 / 4] = symbol(&openEngine);
    engineTable[0x6c / 4] = symbol(&playEngine);
    engineTable[0x84 / 4] = symbol(&volumeEngine);
    engineTable[0x8c / 4] = symbol(&muteEngine);
    engineTable[0xbc / 4] = symbol(&getError);
    sendFinished = fn<void (*)(QObject *)>(dlsym(library, "_ZN15MP_PlayerEngine12playFinishedEv"));
    sendError = fn<void (*)(QObject *, unsigned short)>(
        dlsym(library, "_ZN15MP_PlayerEngine13errorOccurredEt"));
    sendPosition = fn<void (*)(QObject *, unsigned, unsigned)>(
        dlsym(library, "_ZN15MP_PlayerEngine15positionChangedEjj"));
    sendUnavailable =
        fn<void (*)(QObject *)>(dlsym(library, "_ZN15MP_PlayerEngine22audioDeviceUnavailableEv"));
    MediaTestObserver observer(alert), normalObserver(media);
    char path[] = "/tmp/tmm-player-start-XXXXXX";
    int file = mkstemp(path);
    assert(file >= 0);
    close(file);
    prepare(alert, Normal);
    assert(alert.play(path, 30, true) && calls == "DROVP" && alert.startup_.isActive());
    assert(alert.play("/missing-file.mp3", 90, true) && calls == "DROVP");
    finishThenLateEvents();
    alert.startupTimeout(); // A ready timeout cannot override completion either.
    assert(alert.pending_ == 2 && !alert.failed_ && !alert.startup_.isActive());
    assert(!observer.finishedCount && !observer.errorCount && codeReads == 0);
    assert(calls == "DROVP"); // No deletion inside a native callback.
    dispatch(app, alert);
    assert(observer.finishedCount == 1 && !observer.errorCount && calls == "DROVPXd");
    prepare(alert, FinishThenError);
    assert(alert.play(path, 30, true) && alert.pending_ == 2 && !alert.startup_.isActive());
    dispatch(app, alert);
    assert(observer.finishedCount == 2 && !observer.errorCount);
    prepare(alert, ErrorThenFinish);
    assert(!alert.play(path, 30, true) && alert.pending_ == 3);
    dispatch(app, alert);
    assert(observer.finishedCount == 2 && observer.errorCount == 1 && codeReads == 0);
    assert(observer.lastError == QString::fromUtf8("Ошибка плеера Motorola: 2"));
    prepare(alert, OpenFailure);
    storedError = 2;
    assert(!alert.play(path, 30, true) && calls == "DROXd" && codeReads == 1);
    dispatch(app, alert);
    assert(observer.errorCount == 2 &&
           observer.lastError == QString::fromUtf8("Ошибка плеера Motorola: 2"));
    prepare(alert, VolumeFailure);
    assert(!alert.play(path, 30, true) && calls == "DROVXd" && codeReads == 0);
    dispatch(app, alert);
    assert(observer.errorCount == 3);
    prepare(alert, PlayFailure);
    assert(!alert.play(path, 30, true) && codeReads == 1);
    dispatch(app, alert);
    assert(observer.errorCount == 4 && observer.lastError.contains("Motorola: 7"));
    prepare(alert, Normal);
    assert(alert.play(path, 30, true));
    sendPosition(engine, 100, 1000);
    assert(!alert.startup_.isActive());
    sendError(engine, 2);
    alert.stop();
    app.processEvents();
    assert(!alert.pending_ && observer.errorCount == 4);
    prepare(alert, Normal);
    assert(alert.play(path, 30, true));
    alert.startupTimeout();
    sendFinished(engine);
    dispatch(app, alert);
    assert(observer.errorCount == 5 &&
           observer.lastError == QString::fromUtf8("Плеер не подтвердил запуск"));
    prepare(media, Normal);
    assert(media.play(path, 30, true) && calls == "DMOVP");
    finishThenLateEvents();
    dispatch(app, media);
    assert(normalObserver.finishedCount == 1 && !normalObserver.errorCount);
    assert(!observer.reportedWhileActive && !normalObserver.reportedWhileActive);
    unlink(path);
    std::puts("V8 player: stock start order, no flush/close/unmute, deferred first terminal "
              "event, exact native error argument, real errors/retry/stop PASS");
    return 0;
}
