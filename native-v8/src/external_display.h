#ifndef TMM_NATIVE_EXTERNAL_DISPLAY_H
#define TMM_NATIVE_EXTERNAL_DISPLAY_H
#include <qobject.h>
#include <qstring.h>
#include <qtimer.h>
namespace tmm {
class ExternalDisplay : public QObject {
    Q_OBJECT
  public:
    explicit ExternalDisplay(QObject *parent = 0);
    ~ExternalDisplay();
    bool showText(const QString &title, const QString &text, int seconds);
    void clear();
  signals:
    void error(const QString &reason);
  private slots:
    void sessionReady();
    void publish();
    void expired();
    void displayClosed();

  private:
    bool load();
    void *library_;
    QObject *client_;
    QString title_, text_;
    QTimer lifetime_, retry_;
    int attempts_;
    bool ready_;
};
} // namespace tmm
#endif
