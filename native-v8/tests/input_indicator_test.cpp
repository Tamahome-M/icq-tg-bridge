#include "input_indicator.h"
#include <qapplication.h>
#include <quuid.h>
#include <dlfcn.h>
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
struct InputState {
    QUuid mode;
    int language, shift, newWord;
};
template <class T> static T native(const char *name) {
    void *symbol = dlsym(RTLD_DEFAULT, name);
    assert(symbol);
    T f;
    memcpy(&f, &symbol, sizeof(f));
    return f;
}
class IndicatorObserver : public QObject {
  public:
    QString values[4];
    unsigned received;
    IndicatorObserver() : received(0) {}
    bool eventFilter(QObject *, QEvent *e) {
        if (int(e->type()) == ZKbGlobal::ZIMIndicatorChangeEvent::EventType) {
            const ZKbGlobal::ZIMIndicatorChangeEvent *change =
                static_cast<const ZKbGlobal::ZIMIndicatorChangeEvent *>(e);
            assert(change->indicator >= 0 && change->indicator < 4);
            assert(change->remove == 0 || change->remove == 1);
            values[change->indicator] = change->remove ? QString::null : change->value;
            ++received;
        }
        return false;
    }
};
void checkInputIndicator(tmm::InputIndicator &indicator) {
    // The real input controller is active now. Drain its pending events before
    // observing the separate ABI producer exercised by this unit probe.
    QApplication::sendPostedEvents();
    // Real native constructor, producer and destructor; no synthetic Qt events.
    typedef void (*Init)(void *);
    typedef void (*Set)(void *, QObject *, const InputState &, bool);
    Init init = native<Init>("_ZN15KbStatusControlC1Ev");
    Init done = native<Init>("_ZN15KbStatusControlD1Ev");
    Set set = native<Set>("_ZN15KbStatusControl13setInputStateEP7QObjectRK14ZKB_InputStateb");
    assert(sizeof(InputState) == 28 && sizeof(ZKbGlobal::ZIMIndicatorChangeEvent) == 28);
    unsigned data[5] = {0, 0, 0, 0x12345678, 0x87654321};
    init(data);
    IndicatorObserver observed;
    indicator.installEventFilter(&observed);
    InputState s;
    s.mode = QUuid(QString("{637a8c00-1098-42ca-969a-2bf163cd3c12}"));
    s.language = 29;
    s.shift = 2;
    s.newWord = 0;
    set(data, &indicator, s, false);
    QApplication::sendPostedEvents();
    fprintf(stderr, "INPUT received=%u: [%s] [%s] [%s] [%s]\n", observed.received,
            observed.values[0].utf8().data(), observed.values[1].utf8().data(),
            observed.values[2].utf8().data(), observed.values[3].utf8().data());
    assert(observed.received == 4 && !observed.values[0].isEmpty());
    fprintf(stderr, "INPUT content: hint=%d geometry=%d,%d %dx%d\n", indicator.sizeHint().height(),
            indicator.x(), indicator.y(), indicator.width(), indicator.height());
    assert(indicator.sizeHint().height() >= 24 && indicator.height() >= 24);
    // Stock firmware hides the system language; Input Cycle deliberately shows it.
    const bool inputCycle = getenv("V8_QWS_INPUT_LIBS") && *getenv("V8_QWS_INPUT_LIBS");
    if (inputCycle)
        assert(observed.values[2] == QString::fromUtf8("Русский"));
    fprintf(stderr, "INPUT Russian: %s / %s / %s\n", observed.values[0].utf8().data(),
            observed.values[1].utf8().data(), observed.values[2].utf8().data());
    s.language = 0;
    const unsigned beforeLanguage = observed.received;
    set(data, &indicator, s, false);
    QApplication::sendPostedEvents();
    assert(observed.received > beforeLanguage && !observed.values[0].isEmpty());
    if (inputCycle)
        assert(!observed.values[2].isEmpty());
    fprintf(stderr, "INPUT English: %s / %s\n", observed.values[0].utf8().data(),
            observed.values[2].utf8().data());
    QString previous = observed.values[1];
    s.shift = 0;
    set(data, &indicator, s, false);
    QApplication::sendPostedEvents();
    assert(observed.values[1] != previous);
    for (int i = 0; i < 2; ++i) {
        s.mode = QUuid(QString(i ? "{637a8c00-1098-42ca-969a-2bf163cd3c15}"
                                 : "{637a8c00-1098-42ca-969a-2bf163cd3c14}"));
        set(data, &indicator, s, false);
        QApplication::sendPostedEvents();
        assert(!observed.values[0].isEmpty() && observed.values[2].isEmpty());
        fprintf(stderr, "INPUT %s: %s\n", i ? "symbols" : "numbers",
                observed.values[0].utf8().data());
    }
    // Leave the Russian text mode visible in the editor screenshot.
    s.mode = QUuid(QString("{637a8c00-1098-42ca-969a-2bf163cd3c12}"));
    s.language = 29;
    s.shift = 2;
    set(data, &indicator, s, false);
    QApplication::sendPostedEvents();
    indicator.removeEventFilter(&observed);
    done(data);
    assert(data[3] == 0x12345678 && data[4] == 0x87654321);
    fprintf(stderr, "INPUT PASS: actual firmware mode, case, language and clear events\n");
}
