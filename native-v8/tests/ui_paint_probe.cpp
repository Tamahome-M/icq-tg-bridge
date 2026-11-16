#include <qpainter.h>
#include <qwidget.h>
#include <stdio.h>
#include <stdlib.h>

// Observe the real ARM Qt painter. No alternate renderer or artificial delay.
static const QPaintDevice *screen;
static unsigned fills, copies;
extern "C" void realFill(QPainter *, int, int, int, int,
                         const QBrush &) asm("__real__ZN8QPainter8fillRectEiiiiRK6QBrush");
extern "C" void wrapFill(QPainter *, int, int, int, int,
                         const QBrush &) asm("__wrap__ZN8QPainter8fillRectEiiiiRK6QBrush");
extern "C" void wrapFill(QPainter *p, int x, int y, int w, int h, const QBrush &b) {
    if (p->device() == screen)
        ++fills;
    realFill(p, x, y, w, h, b);
}
extern "C" void realCopy(QPainter *, int, int, const QPixmap &, int, int, int,
                         int) asm("__real__ZN8QPainter10drawPixmapEiiRK7QPixmapiiii");
extern "C" void wrapCopy(QPainter *, int, int, const QPixmap &, int, int, int,
                         int) asm("__wrap__ZN8QPainter10drawPixmapEiiRK7QPixmapiiii");
extern "C" void wrapCopy(QPainter *p, int x, int y, const QPixmap &image, int sx, int sy, int w,
                         int h) {
    if (p->device() == screen)
        ++copies;
    realCopy(p, x, y, image, sx, sy, w, h);
}
void checkPaint(QWidget &window, const char *scene) {
    screen = static_cast<QPaintDevice *>(&window);
    fills = copies = 0;
    window.repaint(false);
    screen = 0;
    fprintf(stderr, "PAINT %s: visible fills=%u, completed frame copies=%u\n", scene, fills,
            copies);
    if (fills || copies != 1) {
        fprintf(stderr, "UI FAIL: repaint exposes intermediate drawing\n");
        exit(2);
    }
}
