#ifndef TMM_CAPTURE_TEST_OBSERVER_H
#define TMM_CAPTURE_TEST_OBSERVER_H
#include <qobject.h>
#include <qstring.h>
namespace tmm {
class CaptureController;
}
class CaptureTestObserver : public QObject {
    Q_OBJECT
  public:
    explicit CaptureTestObserver(tmm::CaptureController &capture);
    unsigned readyCount, errorCount, cancelledCount;
    bool terminalWhileBusy;
    QString path, mime;
  public slots:
    void ready(const QString &, const QString &);
    void error(const QString &);
    void cancelled();

  private:
    tmm::CaptureController &capture_;
};
#endif
