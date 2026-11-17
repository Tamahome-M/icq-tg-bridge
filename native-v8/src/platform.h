#ifndef TMM_NATIVE_PLATFORM_H
#define TMM_NATIVE_PLATFORM_H
#include <qobject.h>
#include <qstring.h>
#include <qtimer.h>
class QWidget;
namespace tmm {
class MediaController;
class ExternalDisplay;
class Platform : public QObject {
    Q_OBJECT
  public:
    explicit Platform(QObject *parent = 0);
    ~Platform();
    void setWindow(QWidget *window);
    bool flipClosed() const;
    void minimize();
    void requestForeground();
    void setBacklight(bool on);
    bool openUrl(const QString &url);
    bool openFile(const QString &path);
    void vibrate(int milliseconds);
    void notifyMessage(const QString &audioFile, int volume, int vibrationMs);
    void notifyDisconnected(int volume);
    void stopNotificationSound();
    void clearExternalText();
    void externalText(const QString &title, const QString &text, int durationSeconds = 10);
  signals:
    void flipChanged(bool closed);
    void error(const QString &reason);
  private slots:
    void lidChanged(int state);
    void endVibration();

  private:
    QWidget *window_;
    MediaController *sound_;
    ExternalDisplay *external_;
    QTimer vibration_;
    void *soundLibrary_;
    int vibrationHandle_, backlightHandle_;
    bool closed_;
    QString tonePath_;
};
} // namespace tmm
#endif
