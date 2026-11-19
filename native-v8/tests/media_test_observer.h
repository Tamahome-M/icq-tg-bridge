#ifndef TMM_MEDIA_TEST_OBSERVER_H
#define TMM_MEDIA_TEST_OBSERVER_H
#include <qobject.h>
#include <qstring.h>
namespace tmm {
class MediaController;
}
class MediaTestObserver : public QObject {
    Q_OBJECT
  public:
    explicit MediaTestObserver(tmm::MediaController &media);
    unsigned finishedCount, errorCount;
    bool reportedWhileActive;
    QString lastError;
  public slots:
    void finished();
    void error(const QString &reason);

  private:
    tmm::MediaController &media_;
};
#endif
