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
#include <qarray.h>
#include <dlfcn.h>
#include <new>
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>

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
    assert(sizeof(QByteArray) == 8);
    QByteArray *nativeData = new (dialog.bytes + 384) QByteArray;
    char directory[] = "/tmp/tmm-camera-result-XXXXXX";
    assert(mkdtemp(directory));
    QString staged = QString(directory) + "/saved.jpg";
    // Mode 1 has no filename: GetCameraData returns its QByteArray by reference.
    const char sample[] = {'\xff', '\xd8', 0, 1, 'J', 'P', 'E', 'G', '\xff', '\xd9'};
    nativeData->duplicate(sample, sizeof(sample));
    assert(native->isEmpty() &&
           capture.saveCameraResult(reinterpret_cast<QDialog *>(dialog.bytes), staged));
    nativeData->resize(0); // The persisted result survives native result cleanup.
    FILE *saved = fopen(staged.local8Bit().data(), "rb");
    char readback[sizeof(sample) + 1];
    assert(saved && fread(readback, 1, sizeof(readback), saved) == sizeof(sample));
    fclose(saved);
    assert(!memcmp(readback, sample, sizeof(sample)));
    // The filename path still works for native camera modes returning a file.
    *native = staged;
    QString copiedPath = QString(directory) + "/copied.3gp";
    assert(capture.saveCameraResult(reinterpret_cast<QDialog *>(dialog.bytes), copiedPath));
    *native = QString::null;
    assert(!capture.saveCameraResult(reinterpret_cast<QDialog *>(dialog.bytes), copiedPath));
    nativeData->duplicate(sample, sizeof(sample));
    assert(!capture.saveCameraResult(reinterpret_cast<QDialog *>(dialog.bytes),
                                     QString(directory) + "/missing/result.jpg"));
    nativeData->~QArray();
    memset(dialog.bytes + 384, 0xa5, sizeof(QByteArray));
    unlink(staged.local8Bit().data());
    unlink(copiedPath.local8Bit().data());
    rmdir(directory);
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
    puts("V8 camera result: real QByteArray/QString reference exports, buffer without filename, "
         "persist before teardown, file fallback, write failure and guards PASS");
}
