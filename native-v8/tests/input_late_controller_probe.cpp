// Controlled regression for an editor activated before the native controller
// was installed. The test reconstructs the indicator around an active field,
// then invokes the production edit() method on that same field.
#define FEAT_KEYPAD_SUPPORT
#include "application.h"
#include "window.h"
#include "input_indicator.h"
#include <ZMultiLineEdit.h>
#include <ZKbInputField.h>
#include <ZKeyDef.h>
#include <qwindowsystem_qws.h>
#include <stdio.h>
#include <stdlib.h>
extern "C" void UTIL_SetPowerOnHandleStatus(int);
extern "C" void UTIL_SetFlipStatus(int);
extern "C" void UTIL_SetKeypadLockStatus(bool);
namespace tmm {
class UiProbe : public QObject {
    Window &window_;
    ZInputFieldAdapter *adapter_;
    unsigned tick_, events_;
    void require(bool ok, const char *message) {
        if (!ok) {
            fprintf(stderr, "LATE INPUT FAIL: %s (events=%u)\n", message, events_);
            exit(2);
        }
    }
    bool eventFilter(QObject *, QEvent *e) {
        if (int(e->type()) == ZKbGlobal::ZIMIndicatorChangeEvent::EventType)
            ++events_;
        return false;
    }
    void timerEvent(QTimerEvent *) {
        ++tick_;
        if (tick_ == 1) {
            ZMultiLineEdit *editor = window_.editor_;
            editor->setModalEditing(false);
            editor->clearFocus();
            // Native setUIController owns/deletes the previous controller.
            // Remove its observer widget first; never save a dangling UI pointer.
            adapter_->blockSignals(true);
            delete window_.inputIndicator_;
            window_.inputIndicator_ = 0;
            editor->getInputField()->setOptions(ZKbInputField::FIELD_OPTION_IMSTATEOBSERVER, 0);
            adapter_->setUIController(0);
            editor->getInputField()->setType(ZKbInputField::FIELD_TYPE_PASSWORD);
            editor->getInputField()->setOptions(ZKbInputField::FIELD_OPTION_DISABLE_COMPLETION |
                                                ZKbInputField::FIELD_OPTION_DISABLE_UAD |
                                                ZKbInputField::FIELD_OPTION_DEFAULT_LOWER_CASE);
            editor->setEchoMode(ZMultiLineEdit::Password);
            editor->show();
            editor->setModalEditing(true);
            editor->setFocus();
        }
        if (tick_ == 3) {
            require(adapter_->currentField() != 0, "native editor active before UI attachment");
            window_.inputIndicator_ = new InputIndicator(&window_);
            window_.inputIndicator_->installEventFilter(this);
            window_.editor_->getInputField()->setOptions(
                ZKbInputField::FIELD_OPTION_IMSTATEOBSERVER,
                reinterpret_cast<long>(static_cast<QObject *>(window_.inputIndicator_)));
            window_.layoutEditor();
            window_.inputIndicator_->show();
            adapter_->blockSignals(false);
            window_.inputIndicator_->activate(window_.winId(), true);
        }
        if (tick_ == 6 || tick_ == 7)
            QWSServer::processKeyEvent(0, KEYCODE_2, 0, tick_ == 6, false);
        if (tick_ == 10) {
            require(window_.editor_->text() == "a" && events_ == 0,
                    "control reproduces working input with a blank status row");
            fprintf(stderr, "LATE INPUT CONTROL: native typing works, attached controller alone "
                            "still produces zero events\n");
        }
        if (tick_ == 12)
            window_.edit(QString::fromLatin1("Password"), "search", "", 0, true, 64);
        if (tick_ == 15)
            require(events_ >= 4, "production edit reactivates the native mode/controller link");
        if (tick_ == 16 || tick_ == 17)
            QWSServer::processKeyEvent(0, KEYCODE_3, 0, tick_ == 16, false);
        if (tick_ == 20) {
            require(window_.editor_->text() == "d" && events_ >= 4,
                    "repaired editor preserves real lowercase input");
            fprintf(stderr, "LATE INPUT PASS: production editor repairs an already-active native "
                            "mode created without a UI controller\n");
            qApp->quit();
        }
    }

  public:
    explicit UiProbe(Window &window)
        : window_(window), adapter_(static_cast<ZApplication *>(qApp)->getInputFieldAdapter()),
          tick_(0), events_(0) {
        require(adapter_->getUIController() != 0, "controller owned by native adapter");
        window_.inputIndicator_->installEventFilter(this);
        startTimer(250);
    }
};
} // namespace tmm
int main(int argc, char **argv) {
    if (!getenv("V8_QWS_LOCAL_ONLY"))
        return 3;
    tmm::Application app(argc, argv, QApplication::GuiServer);
    UTIL_SetPowerOnHandleStatus(10);
    UTIL_SetFlipStatus(SYSTEM_FLIP_OPEN);
    UTIL_SetKeypadLockStatus(false);
    tmm::Window window("/state/late-input-data");
    app.setMainWidget(&window);
    window.resize(240, 320);
    window.showFullScreen();
    tmm::UiProbe probe(window);
    return app.exec();
}
