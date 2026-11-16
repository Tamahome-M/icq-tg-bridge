#define FEAT_KEYPAD_SUPPORT
#include "input_controller_v8.h"
#include "zapplication_v8.h"
#include "input_indicator.h"
#include <ZAppInfoArea.h>
namespace tmm {
InputIndicator::InputIndicator(QWidget *parent)
    : QWidget(parent, "input-status", WRepaintNoErase | WResizeNoErase),
      area_(new ZAppInfoArea(this)),
      adapter_(static_cast<ZApplication *>(qApp)->getInputFieldAdapter()), controller_(0) {
    // A plain QWidget does not run ZKbMainWidget::slotKbStateChanged, which
    // normally installs this controller. Without it typing works, but no
    // language/case events reach FIELD_OPTION_IMSTATEOBSERVER.
    controller_ = static_cast<KbUIController *>(adapter_->getUIController());
    if (!controller_) {
        controller_ = new KbUIController(adapter_);
        adapter_->setUIController(controller_); // Owned by the native adapter.
    }
    // Do not derive from ZAppInfoArea: its SDK declaration omits native
    // virtual overrides (including sizeHint). Keep the firmware's vtable.
    setFocusPolicy(NoFocus);
    setBackgroundMode(NoBackground);
    area_->setFocusPolicy(NoFocus);
    area_->setInputArea();
    area_->show();
    installEventFilter(this);
    hide();
}
QObject *InputIndicator::stateSource() const {
    return adapter_;
}
void InputIndicator::activate(int windowId, bool active) {
    QWidget *window = topLevelWidget();
    if (window && int(window->winId()) == windowId)
        controller_->activateInputUI(window, 0, 0, active);
}
QSize InputIndicator::sizeHint() const {
    return area_->sizeHint();
}
void InputIndicator::resizeEvent(QResizeEvent *) {
    area_->setGeometry(rect());
}
bool InputIndicator::eventFilter(QObject *object, QEvent *event) {
    if (object != this || int(event->type()) != ZKbGlobal::ZIMIndicatorChangeEvent::EventType)
        return QWidget::eventFilter(object, event);
    const ZKbGlobal::ZIMIndicatorChangeEvent *change =
        static_cast<const ZKbGlobal::ZIMIndicatorChangeEvent *>(event);
    if (change->indicator < 0 || change->indicator >= 4)
        return true;
    QString value = change->remove ? QString::null : change->value;
    if (values_[change->indicator] == value)
        return true;
    // Keep the native INPUT area and its skin metrics; replace its items in
    // the firmware's mode/case/language/new-word order.
    for (int i = 0; i < 4; ++i)
        if (!values_[i].isEmpty())
            area_->removeItem(ZAppInfoArea::INPUT, QString::number(i));
    values_[change->indicator] = value;
    for (int i = 0; i < 4; ++i) {
        if (values_[i].isEmpty())
            continue;
        if (i == 2)
            area_->appendText(ZAppInfoArea::INPUT, values_[i], QString::number(i));
        else
            area_->appendIcon(ZAppInfoArea::INPUT, values_[i], QString::number(i));
    }
    area_->update();
    return true;
}
} // namespace tmm
