// Production adapter on V8 Qt. No audio hardware is opened.
#include <qobject.h>
#include <qstring.h>
#include <qtimer.h>
#define private public
#include "media.h"
#undef private
#include <qapplication.h>
#include <qmetaobject.h>
#include <dlfcn.h>
#include <cassert>
#include <cstring>
#include <cstdio>
class EngineEvents : public QObject {
  public:
    explicit EngineEvents(QMetaObject *m) : meta_(m) {}
    QMetaObject *metaObject() const {
        return meta_;
    }
    const char *className() const {
        return "MP_PlayerEngine";
    }

  private:
    QMetaObject *meta_;
};
template <class T> T fn(void *p) {
    assert(p);
    T f;
    std::memcpy(&f, &p, sizeof(f));
    return f;
}
int main(int argc, char **argv) {
    QApplication app(argc, argv, false);
    tmm::MediaController media;
    assert(media.load());
    void *library = dlopen("libezx_mp_playerengine.so.1", RTLD_NOW | RTLD_GLOBAL);
    assert(library);
    QMetaObject *meta =
        fn<QMetaObject *(*)()>(dlsym(library, "_ZN15MP_PlayerEngine16staticMetaObjectEv"))();
    assert(meta);
    EngineEvents events(meta);
    assert(QObject::connect(&events, SIGNAL(playFinished()), &media, SLOT(ended())));
    assert(
        QObject::connect(&events, SIGNAL(audioDeviceUnavailable()), &media, SLOT(unavailable())));
    assert(QObject::connect(&events, SIGNAL(positionChanged(unsigned int, unsigned int)), &media,
                            SLOT(position(unsigned int, unsigned int))));
    assert(!media.play("/not-a-telemotomax-file.amr", 50));
    media.active_ = true;
    fn<void (*)(QObject *, unsigned, unsigned)>(
        dlsym(library, "_ZN15MP_PlayerEngine15positionChangedEjj"))(&events, 100, 1000);
    assert(media.pending_ == 1 && media.elapsed_ == 100);
    media.dispatch();
    assert(media.pending_ == 0 && media.active());
    fn<void (*)(QObject *)>(dlsym(library, "_ZN15MP_PlayerEngine12playFinishedEv"))(&events);
    assert(media.active() && media.pending_ == 2); // No teardown in the native callback.
    media.dispatch();
    assert(!media.active() && media.pending_ == 0);
    media.active_ = true;
    fn<void (*)(QObject *)>(dlsym(library, "_ZN15MP_PlayerEngine22audioDeviceUnavailableEv"))(
        &events);
    assert(media.active() && media.pending_ == 3);
    media.stop();
    media.dispatch();
    assert(!media.active() && media.pending_ == 0);
    fn<void (*)(QObject *)>(dlsym(library, "_ZN15MP_PlayerEngine12playFinishedEv"))(&events);
    assert(!media.pending_);
    fn<void (*)(QObject *)>(dlsym(library, "_ZN15MP_PlayerEngine22audioDeviceUnavailableEv"))(
        &events);
    assert(!media.pending_);
    assert(media.videoWidget() == 0);
    tmm::MediaController alert(0, true);
    assert(alert.load() && alert.notification_);
    // Coalescing preserves the running engine; no path/hardware operation.
    alert.active_ = true;
    assert(alert.play("/not-a-file.mp3", 50, true) && alert.active());
    alert.unavailable();
    assert(alert.pending_ == 3);
    alert.dispatch();
    assert(!alert.active() && !alert.pending_);
    // An unavailable device is released, not permanently disabled.
    assert(!alert.play("/not-a-file.mp3", 50, true) && !alert.active());
    alert.active_ = true;
    alert.ended();
    alert.dispatch();
    assert(!alert.active() && !alert.pending_);
    std::puts("V8 media: native metadata, events deferred, finish teardown, stop discards queued "
              "callback PASS");
    return 0;
}
