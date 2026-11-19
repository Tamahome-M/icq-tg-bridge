// Real firmware controls are the reference; run only inside isolated Qt/QWS.
#include "zapplication_v8.h"
#include "system_chrome.h"
#include <ZSoftKey.h>
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
int main(int argc, char **argv) {
    if (!getenv("V8_QWS_LOCAL_ONLY"))
        return 3;
    ZApplication app(argc, argv, QApplication::GuiServer);
    QWidget window;
    window.resize(240, 320);
    window.show();
    tmm::SystemChrome chrome(window);
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
