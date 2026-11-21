// Real firmware controls are the reference; run only inside isolated Qt/QWS.
#include "zapplication_v8.h"
#include "system_chrome.h"
#include <ZSoftKey.h>
#include <RES_ICON_Reader.h>
#include <qdatetime.h>
#include <qimage.h>
#include <stdio.h>
#include <stdlib.h>
#include <assert.h>
static unsigned constructed;
extern "C" void realSoftkey(ZSoftKey *, const QString &, QWidget *,
                            QWidget *) asm("__real__ZN8ZSoftKeyC1ERK7QStringP7QWidgetS4_");
extern "C" void wrapSoftkey(ZSoftKey *, const QString &, QWidget *,
                            QWidget *) asm("__wrap__ZN8ZSoftKeyC1ERK7QStringP7QWidgetS4_");
extern "C" void wrapSoftkey(ZSoftKey *key, const QString &kind, QWidget *parent, QWidget *watcher) {
    ++constructed;
    realSoftkey(key, kind, parent, watcher);
}
static void same(const QPixmap &left, const QPixmap &right) {
    assert(left.size() == right.size());
    QImage a = left.convertToImage(), b = right.convertToImage();
    for (int y = 0; y < a.height(); ++y)
        for (int x = 0; x < a.width(); ++x)
            if (a.pixel(x, y) != b.pixel(x, y)) {
                fprintf(stderr, "FOOTER mismatch at %d,%d: %x vs native %x\n", x, y,
                        unsigned(a.pixel(x, y)), unsigned(b.pixel(x, y)));
                exit(2);
            }
}
static QPixmap draw(tmm::SystemChrome &chrome, const QSize &size, const QColor &underlay,
                    bool offset) {
    QPixmap canvas(size.width() + 8, size.height() + 40);
    canvas.fill(underlay);
    QPainter p(&canvas);
    chrome.drawFooter(p, QRect(offset ? QPoint(4, 37) : QPoint(0, 0), size), "", "");
    p.end();
    QPixmap result;
    result.convertFromImage(
        canvas.convertToImage().copy(offset ? 4 : 0, offset ? 37 : 0, size.width(), size.height()));
    return result;
}
static int signalLevel = 0, batteryLevel = 0;
static unsigned clockMinute = 41;
extern "C" time_t __wrap_time(time_t *out) {
    const time_t stamp = (15 * 60 + clockMinute) * 60;
    if (out)
        *out = stamp;
    return stamp;
}
extern "C" QTime testTime() asm("__wrap__ZN5QTime11currentTimeEv");
QTime testTime() {
    return QTime(15, clockMinute);
}
extern "C" int __wrap_UTIL_GetSignalQuality() {
    return signalLevel;
}
extern "C" int __wrap_UTIL_GetBatteryLevel() {
    return batteryLevel;
}

static QImage header(tmm::SystemChrome &chrome, const QColor &underlay, const QString &title) {
    QPixmap image(240, 29);
    image.fill(underlay);
    QPainter p(&image);
    chrome.drawHeader(p, QRect(0, 0, 240, 29), title);
    p.end();
    return image.convertToImage();
}

int main(int argc, char **argv) {
    if (!getenv("V8_QWS_LOCAL_ONLY"))
        return 3;
    ZApplication app(argc, argv, QApplication::GuiServer);
    QWidget window;
    window.resize(240, 320);
    window.show();
    tmm::SystemChrome chrome(window);
    const QString longTitle = QString::fromUtf8("Очень длинное название контакта или группы");
    QImage low = header(chrome, Qt::red, longTitle);
    assert(low == header(chrome, Qt::blue, longTitle));
    assert(!chrome.refreshIndicators());
    batteryLevel = 2;
    assert(!chrome.refreshIndicators());
    signalLevel = 5;
    batteryLevel = 5;
    assert(chrome.refreshIndicators());
    QImage full = header(chrome, Qt::red, longTitle);
    const QRect radio(0, 0, 25, 29), battery(215, 0, 25, 29);
    assert(low.copy(radio) != full.copy(radio));
    assert(low.copy(battery) != full.copy(battery));
    RES_ICON_Reader reader;
    QPixmap background = reader.getIcon("header_bg_std", false);
    QPixmap signal = reader.getIcon("signal_5_hed1", false);
    QPixmap power = reader.getIcon("batt_level_3_hed2", false);
    assert(!background.isNull() && signal.size() == radio.size() && power.size() == battery.size());
    QPixmap reference(240, 29);
    reference.fill(window.palette().active().background());
    QPainter p(&reference);
    p.drawPixmap(0, 0, background, 0, 0, reference.width(), reference.height());
    p.drawPixmap(radio.topLeft(), signal);
    p.drawPixmap(battery.topLeft(), power);
    p.end();
    const QImage native = reference.convertToImage();
    assert(native.copy(radio) == full.copy(radio) && native.copy(battery) == full.copy(battery));
    QImage empty = header(chrome, Qt::blue, "");
    assert(empty.copy(26, 0, 80, 29) == native.copy(26, 0, 80, 29));
    assert(full.copy(27, 0, 70, 29) != empty.copy(27, 0, 70, 29));
    assert(!chrome.refreshClock());
    ++clockMinute;
    assert(chrome.refreshClock());
    QImage later = header(chrome, Qt::red, "");
    bool sawClock = false;
    for (int x = 0; x < 240; ++x) {
        for (int y = 0; y < 29; ++y) {
            if (empty.pixel(x, y) != native.pixel(x, y)) {
                assert(x >= 130 && x < battery.x() && empty.pixel(x, y) == full.pixel(x, y));
                sawClock = true;
            }
        }
    }
    assert(sawClock && empty != later && !chrome.refreshClock());
    puts("HEADER PASS: native background and unscaled left signal/right battery, unclipped "
         "firmware clock updates by minute, title cannot cross indicators");
    const QSize sizes[] = {QSize(240, 26), QSize(239, 32)};
    for (unsigned i = 0; i < 2; ++i) {
        ZSoftKey reference("CST_2", &window);
        reference.setGeometry(0, 0, sizes[i].width(), sizes[i].height());
        reference.setText(ZSoftKey::LEFT, "");
        reference.setText(ZSoftKey::RIGHT, "");
        reference.show();
        app.processEvents();
        QPixmap native = QPixmap::grabWidget(&reference);
        const unsigned before = constructed;
        QPixmap red = draw(chrome, sizes[i], QColor(255, 0, 0), true);
        same(red, native);
        same(red, draw(chrome, sizes[i], QColor(0, 0, 255), false));
        for (unsigned repeat = 0; repeat < 12; ++repeat)
            same(red, draw(chrome, sizes[i], QColor(0, 255, 0), true));
        assert(constructed == before + 1); // One snapshot, not a widget per repaint.
        if (!i) {
            assert(red.save("/state/client-footer.png", "PNG"));
            assert(native.save("/state/native-footer.png", "PNG"));
        }
    }
    unsigned before = constructed;
    chrome.refresh();
    draw(chrome, sizes[1], QColor(0, 0, 0), false);
    assert(constructed == before + 1);
    puts("FOOTER PASS: native pixels, opaque over chat/photo colors, coordinates, size, cache and "
         "theme refresh");
    return 0;
}
