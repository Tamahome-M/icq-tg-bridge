// Native header API, real resource/layout tables and Qt/QCop loopback.
// The phone's header daemon is an observing endpoint; no physical state changes.
#include "zapplication_v8.h"
#include "status_icon_v8.h"
#include "status_icon_observer.h"
#include "theme_patch.h"
#include <ZHeader.h>
#include <ZMessageDlg.h>
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
#include <sys/stat.h>
static bool patched;
static const char *resources[][2] = {{"im_offline_cli4", "im_offline_idle4"},
                                     {"im_icq_cli4", "im_icq_idle5"},
                                     {"im_icq_away_cli4", "im_icq_away_idle5"},
                                     {"im_busy_cli4", "im_busy_idle4"},
                                     {"im_icq_invisible_cli4", "im_icq_invisible_idle5"}};
static const char *customResources[][2] = {{"tmm_offline_cli", "tmm_offline_main"},
                                           {"im_icq_cli4", "im_icq_idle5"},
                                           {"im_icq_away_cli4", "im_icq_away_idle5"},
                                           {"im_busy_cli4", "im_busy_idle4"},
                                           {"im_icq_invisible_cli4", "im_icq_invisible_idle5"},
                                           {"tmm_msg_offline_cli", "tmm_msg_offline_main"},
                                           {"tmm_msg_online_cli", "tmm_msg_online_main"},
                                           {"tmm_msg_away_cli", "tmm_msg_away_main"},
                                           {"tmm_msg_busy_cli", "tmm_msg_busy_main"},
                                           {"tmm_msg_invisible_cli", "tmm_msg_invisible_main"}};
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
    stream >> kind >> count >> priority;
    assert(kind == slot && count == (patched ? 10 : 5) && priority == 3);
    for (unsigned value = 0; value < unsigned(count); ++value) {
        stream >> state;
        assert(unsigned(state) == value);
        for (unsigned i = 0; i < 4; ++i) {
            QString resource;
            stream >> resource;
            assert(resource == (patched ? customResources[value][i / 2] : resources[value][i / 2]));
            assert(resource.length() <= 60); // Native shared-memory resource limit.
        }
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
    // Exercise installation in the sandbox's real /ezxlocal before Qt loads
    // its skin. No physical phone or read-only firmware files are touched.
    const bool install = getenv("TMM_TEST_INSTALL_ICONS");
    const std::string themeConfig = "/ezxlocal/download/appwrite/setup/ezx_theme.cfg";
    const std::string patchDir = "/ezxlocal/download/appwrite/TeleMotoMaxStatusIcons";
    if (install) {
        assert(mkdir(patchDir.c_str(), 0700) == 0);
        std::string error;
        if (!tmm::patchStatusTheme(themeConfig, patchDir, "/work/status-icons.ezx", false, error)) {
            fprintf(stderr, "THEME INSTALL FAILED: %s\n", error.c_str());
            return 4;
        }
    }
    ZApplication app(argc, argv, QApplication::GuiServer);
    void *library = dlopen("libezxappbase.so.1", RTLD_NOW | RTLD_GLOBAL);
    assert(library);
    nativeAreas(library);
    RES_ICON_Reader reader;
    patched = !reader.getIcon("tmm_status_v1", false).isNull();
    assert(patched == bool(getenv("TMM_TEST_PATCHED_ICONS")));
    for (unsigned state = 0; state < (patched ? 10U : 5U); ++state)
        for (unsigned display = 0; display < 2; ++display) {
            QPixmap icon = reader.getIcon(
                (patched ? customResources[state][display] : resources[state][display]), false);
            assert(!icon.isNull() && icon.width() <= 64 && icon.height() <= 32);
            if (patched) {
                char file[100];
                snprintf(file, sizeof file, "/state/status-%u-%u.png", state, display);
                assert(icon.save(file, "PNG"));
            }
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
        assert(icon.show()); // Starts grey/disconnected.
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
        assert(observer.messages.size() == 2);
        const uint32_t raw[] = {0,   32,     1,      4,      16,     2,      256,
                                512, 0x3000, 0x4000, 0x5000, 0x6000, 0x2001, 0xffffffffU};
        const unsigned mapped[] = {1, 1, 2, 2, 3, 3, 4, 4, 3, 2, 1, 1, 2, 0};
        unsigned previous = 0;
        for (unsigned i = 0; i < sizeof(raw) / sizeof(raw[0]); ++i) {
            unsigned at = observer.messages.size();
            tmm::StatusIconV8::configureApplication(1, raw[i]);
            drain();
            assert(observer.messages.size() == at + (mapped[i] != previous));
            if (mapped[i] != previous)
                changed(observer, at, ZHeader::IM, mapped[i]);
            previous = mapped[i];
        }
        unsigned at = observer.messages.size();
        tmm::StatusIconV8::configureApplication(2, 0);
        drain();
        assert(observer.messages.size() == at + 4);
        changed(observer, at, ZHeader::IM, ZHeader::EMPTY_STATUS);
        removed(observer, at + 1, ZHeader::IM);
        registered(observer, at + 2, ZHeader::ICQ);
        changed(observer, at + 3, ZHeader::ICQ, 1);
        at = observer.messages.size();
        tmm::StatusIconV8::configureApplication(2, 32);
        drain();
        assert(observer.messages.size() == at); // Equivalent state needs no IPC.
        tmm::StatusIconV8::configureApplication(2, 0xffffffffU);
        drain();
        assert(observer.messages.size() == at + 1);
        changed(observer, at, ZHeader::ICQ, 0);
        // Unread follows every presence, remains while offline, and changes
        // only when the boolean changes; another unread needs no IPC.
        for (unsigned i = 0; i < 5; ++i) {
            const uint32_t raw[] = {0xffffffffU, 0, 1, 16, 256};
            tmm::StatusIconV8::configureApplication(2, raw[i], false);
            drain();
            at = observer.messages.size();
            tmm::StatusIconV8::configureApplication(2, raw[i], true);
            drain();
            assert(observer.messages.size() == at + unsigned(patched));
            if (patched)
                changed(observer, at, ZHeader::ICQ, i + 5);
            tmm::StatusIconV8::configureApplication(2, raw[i], true);
            drain();
            assert(observer.messages.size() == at + unsigned(patched));
            tmm::StatusIconV8::configureApplication(2, raw[i], false);
            drain();
            assert(observer.messages.size() == at + unsigned(patched) * 2);
            if (patched)
                changed(observer, at + 1, ZHeader::ICQ, i);
        }
        at = observer.messages.size();
        tmm::StatusIconV8::configureApplication(0, 0);
        drain();
        assert(observer.messages.size() == at + 2);
        changed(observer, at, ZHeader::ICQ, ZHeader::EMPTY_STATUS);
        removed(observer, at + 1, ZHeader::ICQ);
        icon.hide();
        drain();
        assert(observer.messages.size() == at + 2);
    }
    unsigned at = observer.messages.size();
    {
        tmm::StatusIconV8 icon;
        tmm::StatusIconV8::configureApplication(1, 0);
        drain();
        assert(observer.messages.size() == at + 2);
        registered(observer, at, ZHeader::IM);
        changed(observer, at + 1, ZHeader::IM, 1);
        QTimer::singleShot(0, &app, SLOT(quit()));
        assert(app.QApplication::exec() == 0);
    }
    // The test hosts the QCop server too; restart it to drain normal-exit IPC.
    QTimer::singleShot(50, &app, SLOT(quit()));
    assert(app.QApplication::exec() == 0);
    drain();
    assert(observer.messages.size() == at + 4);
    if (install) {
        // Same native result dialog as the phone installer. No Window-specific
        // foreground handlers are attached to this standalone application.
        ZMessageDlg result(QString::fromUtf8("TeleMotoMax"),
                           QString::fromUtf8("Значки установлены. Перезагрузите телефон."),
                           ZMessageDlg::just_ok);
        QTimer::singleShot(200, &result, SLOT(accept()));
        result.exec();
        std::string error;
        assert(tmm::patchStatusTheme(themeConfig, patchDir, "/work/status-icons.ezx", true, error));
    }
    changed(observer, at + 2, ZHeader::IM, ZHeader::EMPTY_STATUS);
    removed(observer, at + 3, ZHeader::IM);
    tmm::StatusIconV8::configureApplication(1, 0); // No owner after destruction.
    drain();
    assert(observer.messages.size() == at + 4);
    puts("V8 status icon: native resources and QCop, grey offline, all presence mappings, "
         "header/idle/off, background independence, idempotence and exit cleanup PASS");
    return 0;
}
