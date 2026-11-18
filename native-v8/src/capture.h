#ifndef TMM_NATIVE_CAPTURE_H
#define TMM_NATIVE_CAPTURE_H
#include <qobject.h>
#include <qstring.h>
#include <qstringlist.h>
#include <qtimer.h>
class QWidget;
class QDialog;
namespace tmm {
class VoiceCapture;
class CaptureController : public QObject {
    Q_OBJECT
  public:
    explicit CaptureController(QObject *parent = 0);
    ~CaptureController();
    void setWindow(QWidget *window);
    void setProfile(const QString &size, const QString &encoding);
    void setVoiceBitrate(unsigned bitrate);
    static QStringList supportedSizes();
    static QStringList supportedEncodings();
    void capturePhoto(const QString &destination);
    void recordVoice(const QString &destination, int seconds);
    void recordVideo(const QString &destination, int seconds = 30);
    void stop();
    void cancel();
    bool busy() const;
    unsigned durationSeconds() const;
  signals:
    void ready(const QString &path, const QString &mime);
    void error(const QString &reason);
    void cancelled();
  private slots:
    void poll();

  private:
    void camera(const QString &destination, bool video, int seconds);
    QString cameraFileName(QDialog *) const;
    bool saveCameraResult(QDialog *, const QString &destination) const;
    static void fitPhotoSize(int &width, int &height, int maximumWidth, int maximumHeight);
    QWidget *window_;
    QDialog *dialog_;
    bool busy_, cancelled_;
    void *cameraLibrary_, *cameraEngineLibrary_;
    VoiceCapture *voice_;
    QTimer timer_;
    QString destination_, size_, encoding_;
    unsigned voiceBitrate_, duration_;
    int videoSeconds_;
};
} // namespace tmm
#endif
