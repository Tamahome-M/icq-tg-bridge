#ifndef TMM_INPUT_INDICATOR_H
#define TMM_INPUT_INDICATOR_H
#include <qwidget.h>
#include <qevent.h>
class ZAppInfoArea;
class ZInputFieldAdapter;
class KbUIController;

// Motorola V8's observer event is absent from the public SDK headers.
// Layout verified against KbStatusControl::setInputState in the V8 firmware
// and exercised with the actual native producer by tests/input_indicator_test.
// It carries resource IDs / language text, never the edited text.
namespace ZKbGlobal {
class ZIMIndicatorChangeEvent : public QCustomEvent {
  public:
    enum { EventType = 1239 };
    int indicator;
    QString value;
    int remove;

  private:
    ZIMIndicatorChangeEvent(); // Events are constructed and owned by the native engine.
};
} // namespace ZKbGlobal
namespace tmm {
class InputIndicator : public QWidget {
  public:
    explicit InputIndicator(QWidget *parent);
    QSize sizeHint() const;
    QObject *stateSource() const;
    void activate(int windowId, bool active);

  protected:
    bool eventFilter(QObject *, QEvent *);
    void resizeEvent(QResizeEvent *);

  private:
    ZAppInfoArea *area_;
    ZInputFieldAdapter *adapter_;
    KbUIController *controller_;
    QString values_[4];
};
} // namespace tmm
#endif
