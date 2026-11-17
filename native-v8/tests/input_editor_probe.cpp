// Run only in tests/run_qws.py's isolated firmware fixture. No direct calls to
// KbStatusControl or synthetic indicator events: keys enter through QWS itself.
#define FEAT_KEYPAD_SUPPORT
#include "application.h"
#include "window.h"
#include "input_indicator.h"
#include "oscar.h"
#include "crypto.h"
#include <ZMultiLineEdit.h>
#include <ZKbInputField.h>
#include <ZKeyDef.h>
#include <qwindowsystem_qws.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern "C" void UTIL_SetPowerOnHandleStatus(int);
extern "C" void UTIL_SetFlipStatus(int);
extern "C" void UTIL_SetKeypadLockStatus(bool);

namespace tmm {
class UiProbe : public QObject {
    Window &w_;
    bool text_;
    unsigned tick_, events_, checks_;
    QString state_[4];
    void require(bool ok, const char *name) {
        if (!ok) {
            fprintf(stderr, "KEYS FAIL: %s\n", name);
            exit(2);
        }
        ++checks_;
        fprintf(stderr, "KEYS PASS: %s\n", name);
    }
    void press(unsigned at, int key) {
        if (tick_ == at || tick_ == at + 1)
            QWSServer::processKeyEvent(0, key, 0, tick_ == at, false);
    }
    void done() {
        fprintf(stderr, "KEYS PASS: %u checks, %u actual engine events\n", checks_, events_);
        qApp->quit();
    }
    void password() {
        if (tick_ == 1) {
            w_.showSettings("account");
            w_.chooseSetting("password");
        }
        if (tick_ == 3)
            require(events_ >= 4 && !state_[0].isEmpty(), "input mode visible before first key");
        press(4, KEYCODE_2);
        if (tick_ == 7) {
            require(w_.editor_->text() == "a", "first password letter is lowercase");
            require(!state_[0].isEmpty(), "typed password has a native mode indicator");
        }
        press(8, KEYCODE_POUND);
        if (tick_ == 11)
            require(state_[0].contains("numeric") && state_[2].isEmpty(),
                    "password # changes to numeric and clears language");
        press(12, KEYCODE_2);
        press(16, KEYCODE_STAR);
        press(20, KEYCODE_3);
        if (tick_ == 23) {
            require(w_.editor_->text() == "a2*3", "raw password keys produce exact expected text");
            w_.editorMenu();
            bool reveal = false;
            for (size_t i = 0; i < w_.view().rows.size(); ++i)
                if (w_.view().rows[i].action == "editor-secret") {
                    w_.activate(w_.view().rows[i]);
                    reveal = true;
                    break;
                }
            require(reveal && w_.editor_->isVisible() &&
                        w_.editor_->echoMode() == ZMultiLineEdit::Normal &&
                        w_.editor_->getInputField()->getType() ==
                            ZKbInputField::FIELD_TYPE_PASSWORD &&
                        w_.editor_->text() == "a2*3",
                    "password reveal after real typing preserves text");
        }
        if (tick_ == 25) {
            w_.finishEdit(true);
            require(w_.settingsDraft_.get("password") == "a2*3" &&
                        w_.settings_.get("password") != "a2*3",
                    "real typed password stays in account draft before Save");
            w_.finishSettings(true);
            Settings saved;
            std::string error;
            require(saved.load(w_.settings_.path(), error) && saved.get("password") == "a2*3",
                    "real typed password survives settings save and reload");
            require(wire::passwordBytes(saved.get("password")) == "a2*3",
                    "authentication receives the exact typed password bytes");
            done();
        }
    }
    void text() {
        if (tick_ == 1)
            w_.edit(QString::fromUtf8("Сообщение"), "search", "");
        if (tick_ == 3)
            require(events_ >= 4 && state_[2] == QString::fromUtf8("Русский"),
                    "Input Cycle Russian visible before typing");
        press(4, KEYCODE_2);
        if (tick_ == 7)
            require(w_.editor_->text().lower() == QString::fromUtf8("а"),
                    "Russian indicator matches actual Cyrillic text");
        press(8, KEYCODE_POUND);
        if (tick_ == 11)
            require(!state_[2].isEmpty() && state_[2] != QString::fromUtf8("Русский"),
                    "short # switches actual language indicator to English");
        press(12, KEYCODE_2);
        if (tick_ == 15)
            require(w_.editor_->text().lower() == QString::fromUtf8("аa"),
                    "English indicator matches actual Latin text");
        press(16, KEYCODE_POUND);
        if (tick_ == 19)
            require(state_[0].contains("numeric") && state_[2].isEmpty(),
                    "short # selects digits and clears language");
        press(20, KEYCODE_3);
        if (tick_ == 23)
            require(w_.editor_->text().lower() == QString::fromUtf8("аa3"),
                    "numeric indicator matches actual digit");
        press(24, KEYCODE_POUND);
        if (tick_ == 27)
            require(!state_[0].isEmpty() && !state_[0].contains("numeric") && state_[2].isEmpty(),
                    "short # selects native symbols indicator");
        press(28, KEYCODE_POUND);
        if (tick_ == 31) {
            require(state_[2] == QString::fromUtf8("Русский"), "# completes the language cycle");
            done();
        }
    }

  protected:
    bool eventFilter(QObject *, QEvent *e) {
        if (int(e->type()) == ZKbGlobal::ZIMIndicatorChangeEvent::EventType) {
            const ZKbGlobal::ZIMIndicatorChangeEvent *s =
                static_cast<const ZKbGlobal::ZIMIndicatorChangeEvent *>(e);
            require(s->indicator >= 0 && s->indicator < 4, "native event range");
            state_[s->indicator] = s->remove ? QString::null : s->value;
            ++events_;
            fprintf(stderr, "KEYS state[%d]=%s\n", s->indicator,
                    state_[s->indicator].utf8().data());
        }
        return false;
    }
    void timerEvent(QTimerEvent *) {
        ++tick_;
        if (text_)
            text();
        else
            password();
    }

  public:
    UiProbe(Window &window, bool text) : w_(window), text_(text), tick_(0), events_(0), checks_(0) {
        w_.timer_.stop();
        w_.settings_.setInt("initial_caps", 0);
        w_.inputIndicator_->installEventFilter(this);
        startTimer(200);
    }
};
} // namespace tmm

int main(int argc, char **argv) {
    if (!getenv("V8_QWS_LOCAL_ONLY"))
        return 3; // Never write test configuration outside the isolated QWS runner.
    const bool text = strstr(argv[0], "text") != 0;
    std::string error;
    if (text && (!tmm::ensureDirectory("/ezxlocal/download/mystuff/InputCycle", error) ||
                 !tmm::atomicWrite("/ezxlocal/download/mystuff/InputCycle/langs.dat",
                                   std::string("YIC1\x1d\0\0\0\0\0\0\0", 12), error)))
        return 4;
    tmm::Application app(argc, argv, QApplication::GuiServer);
    UTIL_SetPowerOnHandleStatus(10);
    UTIL_SetFlipStatus(SYSTEM_FLIP_OPEN);
    UTIL_SetKeypadLockStatus(false);
    tmm::Window w("/state/input-data");
    app.setMainWidget(&w);
    w.resize(240, 320);
    w.show();
    tmm::UiProbe probe(w, text);
    return app.exec();
}
