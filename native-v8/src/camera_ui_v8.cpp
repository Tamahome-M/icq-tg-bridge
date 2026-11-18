#include "camera_ui_v8.h"
#include <qapplication.h>
#include <qdialog.h>
#include <qevent.h>
#include <qmetaobject.h>
#include <qobjectlist.h>
#include <qwidget.h>
#include <ZKeyDef.h>
#include <dlfcn.h>
#include <cstring>
#include <cstdio>
namespace tmm {
namespace {
template <class T> T fn(void *value) {
    T result;
    std::memcpy(&result, &value, sizeof(result));
    return result;
}
bool named(QObject *object, const char *name) {
    return object && std::strcmp(object->className(), name) == 0;
}
bool resultView(QObject *object, bool video) {
    // Video-only service dialogs finish through frame 4 / VideoPreviewView.
    // The MMS-style VideoInsertView (frame 10) is another native path.
    // Photo mode 1 can return a byte buffer without any saved filename.
    return named(object, "CAM_UI_PhotoInsertView") || named(object, "CAM_UI_VideoInsertView") ||
           (video && named(object, "CAM_UI_VideoPreviewView"));
}
bool fire(int key) {
    return key == KEYCODE_CENTER_SELECT || key == KEYCODE_5;
}
} // namespace
CameraUiV8::CameraUiV8(QDialog *dialog, void *library, bool video)
    : QObject(0), dialog_(dialog), video_(video), valid_(false), sendingKey_(false),
      finishing_(false), timer_(0), heldKey_(0), done_(0), cancel_(0), model_(0), modelVtable_(0),
      dialogVtable_(0) {
    if (!dialog || !library || sizeof(void *) != 4)
        return;
    void *create = dlsym(library, "CreateCameraDlg"),
         *cancel = dlsym(library, "_ZN10CAM_UI_Dlg6cancelEv"),
         *done = dlsym(library, "_ZN10CAM_UI_Dlg4doneEv"),
         *model = dlsym(library, "_ZN14CAM_UI_Manager11globalModelEv");
    void **table = static_cast<void **>(dlsym(library, "_ZTV10CAM_UI_Dlg"));
    modelVtable_ = static_cast<void **>(dlsym(library, "_ZTV18CAM_UI_GlobalModel"));
    void **actual = 0;
    std::memcpy(&actual, dialog, sizeof(actual));
    // The model state below is the exact field checked by this firmware's
    // VideoViewfinder::keyPressEvent. Refuse other layouts instead of guessing.
    if (!create || !cancel || !done || !model || !table || !modelVtable_ || actual != table + 2 ||
        reinterpret_cast<unsigned long>(create) - reinterpret_cast<unsigned long>(cancel) !=
            0x42e52c18UL - 0x42e51d0cUL ||
        reinterpret_cast<unsigned long>(done) - reinterpret_cast<unsigned long>(cancel) !=
            0x42e52954UL - 0x42e51d0cUL ||
        reinterpret_cast<unsigned long>(model) - reinterpret_cast<unsigned long>(cancel) !=
            0x42e532a8UL - 0x42e51d0cUL)
        return;
    done_ = fn<void (*)(void *)>(done);
    cancel_ = fn<void (*)(void *)>(cancel);
    model_ = fn<void *(*)(void *)>(model);
    dialogVtable_ = table + 2;
    valid_ = true;
    qApp->installEventFilter(this);
}
CameraUiV8::~CameraUiV8() {
    detach();
}
void CameraUiV8::detach() {
    if (qApp)
        qApp->removeEventFilter(this);
    if (timer_)
        killTimer(timer_);
    timer_ = heldKey_ = 0;
    pendingInsert_ = 0;
    valid_ = false;
}
bool CameraUiV8::valid() const {
    return valid_;
}
bool CameraUiV8::owns(QObject *object) const {
    QWidget *active = activeView();
    for (QObject *current = object; current; current = current->parent())
        if (current == dialog_ || current == active)
            return true;
    return false;
}
QWidget *CameraUiV8::activeView() const {
    if (!dialog_ || !dialogVtable_)
        return 0;
    void **actual = 0;
    std::memcpy(&actual, static_cast<QDialog *>(dialog_), sizeof(actual));
    if (actual != dialogVtable_)
        return 0;
    // CAM_UI_Dlg::done reads the current CAM_UI_Frame at +264, and its
    // CAM_UI_View pointer at +4. Native frames need not parent views to Dlg.
    void *frame = 0;
    std::memcpy(&frame, reinterpret_cast<char *>(static_cast<QDialog *>(dialog_)) + 264, 4);
    QWidget *view = 0;
    if (frame)
        std::memcpy(&view, static_cast<char *>(frame) + 4, 4);
    return view;
}
QWidget *CameraUiV8::viewfinder(QObject *object) const {
    const char *name = video_ ? "CAM_UI_VideoViewfinderView" : "CAM_UI_PhotoViewfinderView";
    for (QObject *current = object; current && current != dialog_; current = current->parent())
        if (named(current, name))
            return static_cast<QWidget *>(current);
    QWidget *active = activeView();
    if (named(active, name))
        return active;
    if (!dialog_)
        return 0;
    QObjectList *matches = dialog_->queryList(name);
    QWidget *result = 0;
    QObjectListIt item(*matches);
    for (QObject *current; (current = item.current()) != 0; ++item)
        if (static_cast<QWidget *>(current)->isVisible()) {
            result = static_cast<QWidget *>(current);
            break;
        }
    delete matches;
    return result;
}
bool CameraUiV8::recording() const {
    if (!dialog_ || !model_ || !modelVtable_)
        return false;
    void *model = model_(reinterpret_cast<char *>(static_cast<QDialog *>(dialog_)) + 208);
    if (!model)
        return false;
    void **table = 0;
    std::memcpy(&table, model, sizeof(table));
    if (table != modelVtable_ + 2)
        return false;
    int state = 0;
    std::memcpy(&state, static_cast<char *>(model) + 564, sizeof(state));
    return state == 2;
}
bool CameraUiV8::invoke(QObject *receiver, const char *name) {
    if (!receiver)
        return false;
    QMetaData *method = receiver->metaObject()->slot(name, true);
    if (!method)
        return false;
    (receiver->*(method->ptr))();
    return true;
}
void CameraUiV8::queueInsert(QWidget *widget) {
    pendingInsert_ = widget;
    if (!timer_)
        timer_ = startTimer(0);
}
void CameraUiV8::timerEvent(QTimerEvent *event) {
    if (event->timerId() != timer_)
        return;
    killTimer(timer_);
    timer_ = 0;
    QWidget *widget = pendingInsert_;
    pendingInsert_ = 0;
    if (!valid_ || !dialog_ || !widget || !widget->isVisible() || !resultView(widget, video_) ||
        !owns(widget) || finishing_)
        return;
    // Leave the native Show transition before accepting its result view;
    // never infer capture completion from a growing/partially written file.
    finishing_ = true;
    std::fprintf(stderr, "Camera UI: accepting completed %s\n", widget->className());
    if (named(widget, "CAM_UI_PhotoInsertView")) {
        // Follow the native Insert action, including the size check and the
        // view's completion signal, before the manager accepts the dialog.
        if (!invoke(widget, "insertSlot()"))
            std::fprintf(stderr, "Camera UI: photo insert slot unavailable\n");
        if (dialog_ && dialog_->isVisible())
            finishing_ = false; // Native size checks can leave a retryable view.
    } else
        done_(static_cast<QDialog *>(dialog_));
}
bool CameraUiV8::eventFilter(QObject *object, QEvent *event) {
    if (!valid_ || !dialog_ || sendingKey_ || finishing_)
        return false;
    if (event->type() == QEvent::Show && resultView(object, video_)) {
        // showFrame may publish its current-frame pointer after Show. Resolve
        // ownership in the queued callback, once the native transition ends.
        queueInsert(static_cast<QWidget *>(object));
        return false;
    }
    if (event->type() != QEvent::KeyPress && event->type() != QEvent::KeyRelease)
        return false;
    // During native transitions/deletion the current-frame pointer can be
    // changing. Only key routing needs to inspect it, not arbitrary Qt events.
    if (!owns(object))
        return false;
    QKeyEvent *key = static_cast<QKeyEvent *>(event);
    const int code = key->key();
    if (code == KEYCODE_LSK && named(object, "CAM_UI_PhotoInsertView")) {
        if (event->type() == QEvent::KeyPress && !key->isAutoRepeat())
            queueInsert(static_cast<QWidget *>(object));
        return true;
    }
    // The stock right softkey is Stop while recording, not Cancel. Keep
    // owning its release after stop changes the native recording state.
    bool stopKey = video_ && code == KEYCODE_RSK && (heldKey_ == code || recording());
    if ((!stopKey && code == KEYCODE_RSK) || code == KEYCODE_CLEAR || code == KEYCODE_END) {
        if (event->type() == QEvent::KeyPress && !key->isAutoRepeat() && !finishing_) {
            finishing_ = true;
            cancel_(static_cast<QDialog *>(dialog_));
        }
        return true;
    }
    if (!fire(code) && !stopKey)
        return false;
    if (event->type() == QEvent::KeyRelease) {
        if (heldKey_ == code)
            heldKey_ = 0;
        return true;
    }
    if (key->isAutoRepeat() || heldKey_ || finishing_)
        return true;
    QWidget *target = viewfinder(object);
    if (!target)
        return false;
    heldKey_ = code;
    if (video_ && recording()) {
        // The stock center key pauses. This native slot instead stops and
        // finalizes the clip, exactly like Java's second Fire/5 action.
        invoke(target, "capturePauseLimitedTimeSlot()");
    } else {
        sendingKey_ = true;
        QKeyEvent press(QEvent::KeyPress, KEYCODE_CENTER_SELECT, 0, 0);
        QKeyEvent release(QEvent::KeyRelease, KEYCODE_CENTER_SELECT, 0, 0);
        QApplication::sendEvent(target, &press);
        QApplication::sendEvent(target, &release);
        sendingKey_ = false;
    }
    return true;
}
} // namespace tmm
