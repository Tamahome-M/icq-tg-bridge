#ifndef TMM_NATIVE_MEDIA_H
#define TMM_NATIVE_MEDIA_H
#include <qobject.h>
#include <qstring.h>
#include <qtimer.h>
class QWidget;
class AM_NORMAL_DEV_INTERFACE;
namespace tmm {
class MediaController : public QObject {
    Q_OBJECT
  public:
    explicit MediaController(QObject *parent = 0);
    ~MediaController();
    bool play(const QString &path, int volume = 70, bool audioOnly = false);
    void stop();
    void setVolume(int volume);
    bool pause(bool paused);
    bool seek(unsigned int milliseconds);
    QWidget *videoWidget();
    bool active() const;
  signals:
    void finished();
    void error(const QString &reason);
    void positionChanged(unsigned int elapsed, unsigned int duration);
  private slots:
    void ended();
    void playbackError();
    void unavailable();
    void position(unsigned int elapsed, unsigned int duration);
    void startupTimeout();
    void dispatch();
    void videoDestroyed();

  private:
    bool load();
    QWidget *ensureVideoWidget();
    void release();
    void *library_, *videoLibrary_;
    QObject *engine_;
    QWidget *video_;
    AM_NORMAL_DEV_INTERFACE *device_;
    void **table_;
    QTimer startup_, completion_;
    QString pendingError_;
    unsigned elapsed_, duration_;
    int pending_;
    bool active_, failed_, videoActive_;
    int volume_;
};
} // namespace tmm
#endif
