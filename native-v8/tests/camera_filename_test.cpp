// Real V8 camera export on guarded model storage. No camera constructor,
// recorder, native dialog or hardware is opened by this ABI boundary test.
#include <qobject.h>
#include <qstring.h>
#include <qstringlist.h>
#include <qtimer.h>
#define private public
#include "capture.h"
#undef private
#include <qapplication.h>
#include <dlfcn.h>
#include <new>
#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(int argc, char **argv) {
    QApplication app(argc, argv, false);
    assert(sizeof(void *) == 4 && sizeof(QString) == 4);
    tmm::CaptureController capture;
    capture.cameraLibrary_ = dlopen("libezxcamera.so.1", RTLD_NOW | RTLD_LOCAL);
    assert(capture.cameraLibrary_);
    assert(dlsym(capture.cameraLibrary_, "GetCameraFileName"));

    union Storage {
        void *alignment;
        unsigned char bytes[640];
    } dialog, model;
    memset(dialog.bytes, 0xa5, sizeof(dialog.bytes));
    memset(model.bytes, 0x5a, sizeof(model.bytes));
    // CAM_UI_Manager is the dialog's secondary base at +208. globalModel()
    // immediately returns its existing model pointer at +68 when non-null.
    void *pointer = model.bytes;
    memcpy(dialog.bytes + 208 + 68, &pointer, sizeof(pointer));
    QString *native = new (model.bytes + 584) QString;
    const char *paths[] = {"/tmp/native-camera.jpg", "/tmp/Фото 16.11.2026.jpg"};
    for (unsigned i = 0; i < sizeof(paths) / sizeof(paths[0]); ++i) {
        *native = QString::fromUtf8(paths[i]);
        QString copied = capture.cameraFileName(reinterpret_cast<QDialog *>(dialog.bytes));
        assert(copied == *native && copied.utf8() == native->utf8());
        *native = QString::null;
        assert(copied == QString::fromUtf8(paths[i]));
    }
    native->~QString();
    for (unsigned i = 0; i < sizeof(dialog.bytes); ++i)
        if (i < 276 || i >= 280)
            assert(dialog.bytes[i] == 0xa5);
    for (unsigned i = 0; i < sizeof(model.bytes); ++i)
        if (i < 584 || i >= 588)
            assert(model.bytes[i] == 0x5a);
    puts("V8 camera filename: real QString-reference export, ASCII/Cyrillic, owned copy and guards "
         "PASS");
}
