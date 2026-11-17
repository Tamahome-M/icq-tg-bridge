// Native header API, real resource/layout tables and Qt/QCop loopback.
// The phone's header daemon is an observing endpoint; no physical state changes.
#include "zapplication_v8.h"
#include "status_icon_v8.h"
#include "status_icon_observer.h"
#include <ZHeader.h>
#include <RES_ICON_Reader.h>
#include <qcopchannel_qws.h>
#include <qdatastream.h>
#include <qwidget.h>
#include <qtimer.h>
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <dlfcn.h>
#include <string.h>
static const char *resources[] = {"im_icq_cli4", "im_icq_idle5"};
static void drain() {
    for (unsigned i = 0; i < 20; ++i) {
        qApp->processEvents();
        usleep(1000);
    }
}
static void changed(StatusIconObserver &observer, unsigned at, int slot, int value) {
    assert(observer.messages[at] == "appStatusChanged(int)");
    QDataStream stream(observer.payloads[at], IO_ReadOnly);
    Q_INT32 status, state;
    stream >> status >> state;
    assert(status == slot && state == value && stream.atEnd());
}
static void removed(StatusIconObserver &observer, unsigned at, int slot) {
    assert(observer.messages[at] == "unregister()");
    QDataStream stream(observer.payloads[at], IO_ReadOnly);
    Q_INT32 status;
    stream >> status;
    assert(status == slot && stream.atEnd());
}
static void registered(StatusIconObserver &observer, unsigned at, int slot) {
    assert(observer.messages[at] == "register()");
    QDataStream stream(observer.payloads[at], IO_ReadOnly);
    Q_INT8 kind, state;
    Q_INT32 count, priority;
    stream >> kind >> count >> priority >> state;
    assert(kind == slot && count == 1 && priority == 3 && state == 0);
    for (unsigned i = 0; i < 4; ++i) {
        QString resource;
        stream >> resource;
        assert(resource == resources[i / 2]);
    }
    assert(stream.atEnd());
}
static void nativeAreas(void *library) {
    typedef int (*FindLocation)(void *, void *, int, int);
    void *method =
        dlsym(library,
              "_ZN16ZHeaderShareInfo12findLocationEP16StatusListData_tiN7ZHeader13HEADER_STATUSE");
    assert(method);
    FindLocation findLocation;
    memcpy(&findLocation, &method, sizeof(findLocation));
    const char *areas[] = {"MAINDISPLAY_HEADER_AREA", "CLI_HEADER_AREA", "MAINDISPLAY_IDL_AREA",
                           "CLI_IDL_AREA"};
    const int counts[] = {6, 4, 10, 7}; // Native AreaList ctor: 8-byte entries.
    for (unsigned a = 0; a < 4; ++a) {
        void **area = static_cast<void **>(dlsym(library, areas[a]));
        assert(area && *area);
        int im = findLocation(0, *area, counts[a], ZHeader::IM),
            icq = findLocation(0, *area, counts[a], ZHeader::ICQ),
            bt = findLocation(0, *area, counts[a], ZHeader::BT),
            usb = findLocation(0, *area, counts[a], ZHeader::USB);
        fprintf(stderr, "STATUS ICON area %s: IM=%d ICQ=%d BT=%d USB=%d\n", areas[a], im, icq, bt,
                usb);
        if (!a)
            assert(im >= 0 && icq < 0 && im == bt && im == usb);
        else if (a == 1)
            assert(im >= 0 && icq < 0);
        else
            assert(icq >= 0 && icq != bt && icq != usb);
    }
}
int main(int argc, char **argv) {
    if (!getenv("V8_QWS_LOCAL_ONLY"))
        return 3;
    ZApplication app(argc, argv, QApplication::GuiServer);
    void *library = dlopen("libezxappbase.so.1", RTLD_NOW | RTLD_GLOBAL);
    assert(library);
    nativeAreas(library);
    RES_ICON_Reader reader;
    for (unsigned i = 0; i < 2; ++i) {
        QPixmap icon = reader.getIcon(resources[i], false);
        fprintf(stderr, "STATUS ICON native resource %s: %dx%d\n", resources[i], icon.width(),
                icon.height());
        assert(!icon.isNull() && icon.width() <= 64 && icon.height() <= 32);
        char path[64];
        snprintf(path, sizeof(path), "/state/status-icon-%u.png", i);
        assert(icon.save(path, "PNG"));
    }
    StatusIconObserver observer;
    {
        tmm::StatusIconV8 unavailable;
        assert(!unavailable.show());
        unavailable.hide();
    }
    assert(observer.messages.empty());
    QCopChannel endpoint("headerregister");
    assert(QObject::connect(&endpoint, SIGNAL(received(const QCString &, const QByteArray &)),
                            &observer, SLOT(receive(const QCString &, const QByteArray &))));
    drain();
    assert(QCopChannel::isRegistered("headerregister"));
    {
        tmm::StatusIconV8 icon;
        assert(icon.show());
        drain();
        assert(observer.messages.size() == 2);
        registered(observer, 0, ZHeader::IM);
        changed(observer, 1, ZHeader::IM, 0);
        assert(icon.show());
        QWidget foreground;
        foreground.show();
        drain();
        foreground.hide();
        drain();
        foreground.show();
        drain();
        assert(observer.messages.size() == 2); // Backgrounding retains the icon.
        tmm::StatusIconV8::configureApplication(2);
        drain();
        assert(observer.messages.size() == 6);
        changed(observer, 2, ZHeader::IM, ZHeader::EMPTY_STATUS);
        removed(observer, 3, ZHeader::IM);
        registered(observer, 4, ZHeader::ICQ);
        changed(observer, 5, ZHeader::ICQ, 0);
        tmm::StatusIconV8::configureApplication(2);
        drain();
        assert(observer.messages.size() == 6); // Unrelated settings saves do no IPC.
        tmm::StatusIconV8::configureApplication(0);
        drain();
        assert(observer.messages.size() == 8);
        changed(observer, 6, ZHeader::ICQ, ZHeader::EMPTY_STATUS);
        removed(observer, 7, ZHeader::ICQ);
        icon.hide();
        drain();
        assert(observer.messages.size() == 8);
    }
    drain();
    assert(observer.messages.size() == 8);
    {
        tmm::StatusIconV8 icon;
        tmm::StatusIconV8::configureApplication(1);
        drain();
        assert(observer.messages.size() == 10);
        registered(observer, 8, ZHeader::IM);
        changed(observer, 9, ZHeader::IM, 0);
        // Production destroys its registration after the main event loop exits.
        QTimer::singleShot(0, &app, SLOT(quit()));
        assert(app.QApplication::exec() == 0);
    }
    // This fixture hosts both sides of QCop in the same process. Restart
    // only the server event loop to observe packets sent after the client
    // loop ended; the physical phone's server stays in its own process.
    QTimer::singleShot(50, &app, SLOT(quit()));
    assert(app.QApplication::exec() == 0);
    drain();
    fprintf(stderr, "STATUS ICON after stopped-loop cleanup packets=%u\n",
            observer.messages.size());
    assert(observer.messages.size() == 12);
    changed(observer, 10, ZHeader::IM, ZHeader::EMPTY_STATUS);
    removed(observer, 11, ZHeader::IM);
    tmm::StatusIconV8::configureApplication(1); // No owner after destruction.
    drain();
    assert(observer.messages.size() == 12);
    puts("V8 status icon: real layout/resource tables and QCop packets, header/idle/off modes, "
         "foreground independence, idempotence, exit cleanup and absent-service handling PASS");
    return 0;
}
