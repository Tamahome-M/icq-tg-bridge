// Real video surface construction, without opening a player or decoder.
#include <qobject.h>
#include <qstring.h>
#include <qtimer.h>
#include <qwidget.h>
#define private public
#include "media.h"
#undef private
#include <assert.h>
#include <stdio.h>
void checkVideoParent(QWidget &window) {
    tmm::MediaController media(&window);
    QWidget *video = media.ensureVideoWidget();
    assert(video && video->parentWidget() == &window && !video->isTopLevel());
    assert(video->isHidden());
    video->setGeometry(0, 30, 240, 232);
    video->show();
    assert(video->isVisible());
    window.hide();
    assert(!video->isVisible());
    window.show();
    assert(video->isVisible() && video->topLevelWidget() == &window);
    fprintf(stderr, "VIDEO PARENT PASS: native surface starts as a child, follows main window, "
                    "never creates a separate player window\n");
}
