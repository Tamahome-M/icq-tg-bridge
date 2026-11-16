#ifndef TMM_INPUT_CONTROLLER_V8_H
#define TMM_INPUT_CONTROLLER_V8_H
#include <qobject.h>
class QWidget;
class ZSoftKey;
class ZAppInfoArea;
class ZInputFieldAdapter;

// Native-only ABI declarations omitted from the public V8 SDK. Objects are
// constructed by libezxappbase, never subclassed here: its native vtables must
// remain intact. Verified against ZKbMainWidget::slotKbStateChanged and the
// firmware constructor (QObject, interface vptr, seven pointer-sized members).
class KbUIControlInterface {
  public:
    virtual ~KbUIControlInterface();
};
class KbUIController : public QObject, public KbUIControlInterface {
    unsigned int nativeData_[7];

  public:
    explicit KbUIController(ZInputFieldAdapter *);
    virtual ~KbUIController();
    void activateInputUI(QWidget *, ZSoftKey *, ZAppInfoArea *, bool);

  private:
    KbUIController(const KbUIController &);
    KbUIController &operator=(const KbUIController &);
};
typedef char TmmInputControllerSize[(sizeof(KbUIController) == 68) ? 1 : -1];
#endif
