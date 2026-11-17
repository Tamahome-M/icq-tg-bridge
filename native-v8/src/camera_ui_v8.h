#ifndef TMM_NATIVE_CAMERA_UI_V8_H
#define TMM_NATIVE_CAMERA_UI_V8_H
#include <qobject.h>
#include <qguardedptr.h>
class QDialog;
class QWidget;
namespace tmm {
// Keeps Motorola's viewfinder, while using the same shoot/start/stop/cancel
// actions as the Java client. Scope this object around CAM_UI_Dlg::exec().
class CameraUiV8 : public QObject {
  public:
    CameraUiV8(QDialog *dialog, void *cameraLibrary, bool video);
    ~CameraUiV8();
    void detach();
    bool valid() const;

  protected:
    bool eventFilter(QObject *, QEvent *);
    void timerEvent(QTimerEvent *);

  private:
    bool owns(QObject *) const;
    QWidget *viewfinder(QObject *) const;
    bool recording() const;
    static bool invoke(QObject *, const char *);
    void queueInsert(QWidget *);
    QGuardedPtr<QDialog> dialog_;
    QGuardedPtr<QWidget> pendingInsert_;
    bool video_, valid_, sendingKey_, finishing_;
    int timer_, heldKey_;
    void (*done_)(void *);
    void (*cancel_)(void *);
    void *(*model_)(void *);
    void **modelVtable_;
};
} // namespace tmm
#endif
