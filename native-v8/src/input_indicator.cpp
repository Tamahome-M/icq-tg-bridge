#include "input_indicator.h"
#include <ZAppInfoArea.h>
namespace tmm {
InputIndicator::InputIndicator(QWidget *parent)
    : QWidget(parent, "input-status", WRepaintNoErase | WResizeNoErase),
      area_(new ZAppInfoArea(this)) {
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
