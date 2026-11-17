// Real V8 Qt/metaobjects; camera widgets and completed shots are fixtures.
// This verifies key routing/result ownership, not physical camera operation.
#include <qapplication.h>
#include <qdialog.h>
#include <qevent.h>
#include <qmetaobject.h>
#include <qguardedptr.h>
#define private public
#include "camera_ui_v8.h"
#undef private
#include <ZKeyDef.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <assert.h>
namespace {
template <class T> T fn(void *value) {
    T result;
    memcpy(&result, &value, sizeof(result));
    return result;
}
union ModelStorage {
    void *alignment;
    unsigned char bytes[640];
} model;
unsigned accepted, cancelled;
class FixtureDialog : public QDialog {
    // Space for the native current-frame field in the detached-view test.
    char nativeLayout_[400];

  public:
    void finish(bool acceptResult) {
        if (acceptResult)
            accept();
        else
            reject();
    }
};
void *fixtureModel(void *) {
    return model.bytes;
}
void setState(int value) {
    memcpy(model.bytes + 564, &value, sizeof(value));
}
void acceptDialog(void *value) {
    ++accepted;
    static_cast<FixtureDialog *>(value)->finish(true);
}
void cancelDialog(void *value) {
    ++cancelled;
    static_cast<FixtureDialog *>(value)->finish(false);
}
class PhotoView : public QWidget {
  public:
    unsigned presses, releases;
    explicit PhotoView(QWidget *parent) : QWidget(parent), presses(0), releases(0) {}
    const char *className() const {
        return "CAM_UI_PhotoViewfinderView";
    }

  protected:
    void keyPressEvent(QKeyEvent *event) {
        if (event->key() == KEYCODE_CENTER_SELECT)
            ++presses;
    }
    void keyReleaseEvent(QKeyEvent *event) {
        if (event->key() == KEYCODE_CENTER_SELECT)
            ++releases;
    }
};
class VideoView : public PhotoView {
  public:
    unsigned stops;
    explicit VideoView(QWidget *parent) : PhotoView(parent), stops(0) {}
    const char *className() const {
        return "CAM_UI_VideoViewfinderView";
    }
    QMetaObject *metaObject() const {
        static QMetaObject *meta = 0;
        if (!meta) {
            QWidget::staticMetaObject();
            QMetaData *method = QMetaObject::new_metadata(1);
            method[0].name = "capturePauseLimitedTimeSlot()";
            method[0].ptr = static_cast<QMember>(&VideoView::stop);
            meta = QMetaObject::new_metaobject("CameraVideoFixture", "QWidget", method, 1, 0, 0);
        }
        return meta;
    }
    void stop() {
        ++stops;
        setState(0);
    }

  protected:
    void keyPressEvent(QKeyEvent *event) {
        PhotoView::keyPressEvent(event);
        if (event->key() == KEYCODE_CENTER_SELECT)
            setState(2);
    }
};
class InsertView : public QWidget {
    bool video_;

  public:
    InsertView(QWidget *parent, bool video) : QWidget(parent), video_(video) {}
    const char *className() const {
        return video_ ? "CAM_UI_VideoInsertView" : "CAM_UI_PhotoInsertView";
    }
};
class VideoPreview : public QWidget {
  public:
    explicit VideoPreview(QWidget *parent) : QWidget(parent) {}
    const char *className() const {
        return "CAM_UI_VideoPreviewView";
    }
};
void key(QWidget &widget, int code, bool pressed, bool repeat = false) {
    QKeyEvent event(pressed ? QEvent::KeyPress : QEvent::KeyRelease, code, 0, 0, QString::null,
                    repeat);
    QApplication::sendEvent(&widget, &event);
}
void drain() {
    for (unsigned i = 0; i < 10; ++i) {
        qApp->processEvents();
        usleep(1000);
    }
}
void enableFixture(tmm::CameraUiV8 &ui, void **nativeModelTable) {
    assert(!ui.valid()); // A generic test QDialog must fail the real ABI guard.
    ui.valid_ = true;
    ui.done_ = acceptDialog;
    ui.cancel_ = cancelDialog;
    ui.model_ = fixtureModel;
    ui.modelVtable_ = nativeModelTable;
    qApp->installEventFilter(&ui);
}
QMetaObject *nativeMeta(void *library, const char *tableName) {
    void **table = static_cast<void **>(dlsym(library, tableName));
    assert(table);
    // V8 vtable getter is a static metadata thunk and does not dereference this.
    // No camera/widget constructor or hardware operation is called here.
    return fn<QMetaObject *(*)(void *)>(table[6])(0);
}
} // namespace
int main(int argc, char **argv) {
    if (!getenv("V8_QWS_LOCAL_ONLY"))
        return 3;
    QApplication app(argc, argv, QApplication::GuiServer);
    void *library = dlopen("libezxcamera.so.1", RTLD_NOW | RTLD_GLOBAL);
    assert(library && sizeof(void *) == 4);
    QMetaObject *videoMeta = nativeMeta(library, "_ZTV26CAM_UI_VideoViewfinderView");
    assert(!strcmp(videoMeta->className(), "CAM_UI_VideoViewfinderView"));
    QMetaData *stop = videoMeta->slot("capturePauseLimitedTimeSlot()", true);
    assert(stop);
    unsigned code[2];
    memcpy(code, &stop->ptr, sizeof(code));
    unsigned long create = reinterpret_cast<unsigned long>(dlsym(library, "CreateCameraDlg"));
    assert(code[0] - create == 0x42e3258cUL - 0x42e52c18UL && code[1] == 0);
    assert(nativeMeta(library, "_ZTV22CAM_UI_PhotoInsertView")->slot("insertSlot()", true));
    assert(!strcmp(nativeMeta(library, "_ZTV22CAM_UI_VideoInsertView")->className(),
                   "CAM_UI_VideoInsertView"));
    assert(!strcmp(nativeMeta(library, "_ZTV23CAM_UI_VideoPreviewView")->className(),
                   "CAM_UI_VideoPreviewView"));
    void **modelTable = static_cast<void **>(dlsym(library, "_ZTV18CAM_UI_GlobalModel"));
    assert(modelTable);
    memset(model.bytes, 0xa5, sizeof(model.bytes));
    void **modelHead = modelTable + 2;
    memcpy(model.bytes, &modelHead, sizeof(modelHead));
    setState(0);
    {
        FixtureDialog dialog;
        PhotoView view(&dialog);
        dialog.resize(240, 320);
        dialog.show();
        view.show();
        tmm::CameraUiV8 ui(&dialog, library, false);
        enableFixture(ui, modelTable);
        key(view, KEYCODE_5, true);
        key(view, KEYCODE_5, true, true);
        key(view, KEYCODE_5, false);
        assert(view.presses == 1 && view.releases == 1);
        key(view, KEYCODE_CENTER_SELECT, true);
        key(view, KEYCODE_CENTER_SELECT, false);
        assert(view.presses == 2 && view.releases == 2);
        QWidget unrelated;
        InsertView outside(&unrelated, false);
        unrelated.show();
        outside.show();
        drain();
        assert(!accepted);
        InsertView *discarded = new InsertView(&dialog, false);
        discarded->show();
        delete discarded;
        drain();
        assert(!accepted);
        InsertView hidden(&dialog, false);
        hidden.show();
        hidden.hide();
        drain();
        assert(!accepted);
        InsertView saved(&dialog, false);
        saved.show();
        assert(!accepted); // Must leave the native show/capture stack first.
        drain();
        assert(accepted == 1 && !dialog.isVisible());
        ui.detach();
        key(view, KEYCODE_5, true);
        key(view, KEYCODE_5, false);
        assert(view.presses == 2); // No global key rewriting after detach.
    }
    {
        FixtureDialog dialog;
        VideoView view(&dialog);
        dialog.show();
        view.show();
        tmm::CameraUiV8 ui(&dialog, library, true);
        enableFixture(ui, modelTable);
        assert(!ui.recording());
        key(view, KEYCODE_5, true);
        key(view, KEYCODE_5, false);
        assert(view.presses == 1 && ui.recording());
        unsigned char before[640];
        memcpy(before, model.bytes, sizeof(before));
        assert(ui.recording());
        assert(!memcmp(before, model.bytes, sizeof(before))); // Native state is read-only.
        key(view, KEYCODE_CENTER_SELECT, true);
        key(view, KEYCODE_CENTER_SELECT, false);
        assert(view.stops == 1 && view.presses == 1 && !ui.recording());
        InsertView saved(&dialog, true);
        saved.show();
        drain();
        assert(accepted == 2);
    }
    {
        FixtureDialog dialog;
        PhotoView view(&dialog);
        dialog.show();
        view.show();
        tmm::CameraUiV8 ui(&dialog, library, false);
        enableFixture(ui, modelTable);
        key(view, KEYCODE_RSK, true);
        key(view, KEYCODE_RSK, false);
        assert(cancelled == 1 && !dialog.isVisible());
        InsertView late(&dialog, false);
        late.show();
        drain();
        assert(accepted == 2); // A cancelled capture cannot become an upload.
    }
    {
        FixtureDialog dialog;
        VideoView view(&dialog);
        dialog.show();
        view.show();
        tmm::CameraUiV8 ui(&dialog, library, true);
        enableFixture(ui, modelTable);
        key(view, KEYCODE_5, true);
        key(view, KEYCODE_5, false);
        assert(ui.recording());
        key(view, KEYCODE_5, true);
        key(view, KEYCODE_5, false);
        assert(view.stops == 1 && !ui.recording());
        // This is the actual video-only frame used by CAM_UI_Dlg mode 2.
        VideoPreview saved(&dialog);
        saved.show();
        assert(accepted == 2 && cancelled == 1);
        drain();
        assert(accepted == 3 && cancelled == 1 && dialog.result() == QDialog::Accepted);
    }
    {
        FixtureDialog dialog;
        PhotoView view(&dialog);
        dialog.show();
        view.show();
        tmm::CameraUiV8 ui(&dialog, library, false);
        enableFixture(ui, modelTable);
        VideoPreview unrelated(&dialog);
        unrelated.show();
        drain();
        assert(accepted == 3 && dialog.isVisible());
        key(view, KEYCODE_CLEAR, true);
        key(view, KEYCODE_CLEAR, false);
        assert(cancelled == 2);
    }
    {
        FixtureDialog dialog;
        VideoView view(&dialog);
        dialog.show();
        view.show();
        tmm::CameraUiV8 ui(&dialog, library, true);
        enableFixture(ui, modelTable);
        key(view, KEYCODE_5, true);
        key(view, KEYCODE_5, false);
        assert(ui.recording());
        key(view, KEYCODE_RSK, true);
        key(view, KEYCODE_RSK, true, true);
        key(view, KEYCODE_RSK, false);
        assert(view.stops == 1 && !ui.recording() && !ui.heldKey_ && cancelled == 2);
        VideoPreview saved(&dialog);
        saved.show();
        drain();
        assert(accepted == 4 && cancelled == 2 && dialog.result() == QDialog::Accepted);
    }
    {
        FixtureDialog dialog;
        VideoView view(&dialog);
        dialog.show();
        view.show();
        tmm::CameraUiV8 ui(&dialog, library, true);
        enableFixture(ui, modelTable);
        key(view, KEYCODE_RSK, true);
        key(view, KEYCODE_RSK, false);
        assert(cancelled == 3 && !dialog.isVisible());
    }
    {
        FixtureDialog dialog;
        VideoView detached(0);
        dialog.show();
        detached.show();
        tmm::CameraUiV8 ui(&dialog, library, true);
        enableFixture(ui, modelTable);
        assert(sizeof(QDialog) <= 264 && sizeof(dialog) > 268);
        void **actual = 0;
        memcpy(&actual, &dialog, sizeof(actual));
        ui.dialogVtable_ = actual;
        void *frame[2] = {0, &detached};
        void *framePointer = frame;
        memcpy(reinterpret_cast<char *>(&dialog) + 264, &framePointer, 4);
        assert(ui.activeView() == &detached && ui.owns(&detached));
        key(detached, KEYCODE_5, true);
        key(detached, KEYCODE_5, false);
        key(detached, KEYCODE_RSK, true);
        key(detached, KEYCODE_RSK, false);
        assert(detached.stops == 1 && !ui.recording() && cancelled == 3);
        VideoPreview preview(0);
        preview.show();
        // Native showFrame publishes the active view after Show is delivered.
        frame[1] = &preview;
        drain();
        assert(accepted == 5 && dialog.result() == QDialog::Accepted);
        ui.detach();
        framePointer = 0;
        memcpy(reinterpret_cast<char *>(&dialog) + 264, &framePointer, 4);
    }
    fprintf(stderr,
            "CAMERA UI PASS: real native stop metadata, scoped Fire/5 start and Fire/5/RSK stop, "
            "repeat "
            "suppression, detached native frame ownership, preview/insert accept, "
            "hide/delete/cancel guards\n");
    return 0;
}
