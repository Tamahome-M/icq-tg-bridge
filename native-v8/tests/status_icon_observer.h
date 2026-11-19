#ifndef TMM_NATIVE_STATUS_ICON_OBSERVER_H
#define TMM_NATIVE_STATUS_ICON_OBSERVER_H
#include <qobject.h>
#include <qcstring.h>
#include <qarray.h>
#include <vector>
class StatusIconObserver : public QObject {
    Q_OBJECT
  public:
    std::vector<QCString> messages;
    std::vector<QByteArray> payloads;
  public slots:
    void receive(const QCString &message, const QByteArray &data) {
        messages.push_back(message);
        payloads.push_back(data);
    }
};
#endif
