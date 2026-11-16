// Real client/server transport regression. The server injects raw keyboard
// events; a separate GuiClient opens the production editor and observes its
// actual native indicator events. No indicator or input-engine hooks.
#define FEAT_KEYPAD_SUPPORT
#include "application.h"
#include "window.h"
#include "input_indicator.h"
#include <ZMultiLineEdit.h>
#include <ZKeyDef.h>
#include <qwindowsystem_qws.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/wait.h>
#include <signal.h>
#include <string.h>

extern "C" void UTIL_SetPowerOnHandleStatus(int);
extern "C" void UTIL_SetFlipStatus(int);
extern "C" void UTIL_SetKeypadLockStatus(bool);
static const char *ready = "/state/input-client.ready";
static void require(bool ok, const char *message) {
    if (!ok) {
        fprintf(stderr, "CLIENT INPUT FAIL: %s\n", message);
        exit(2);
    }
}
namespace tmm {
class UiProbe : public QObject {
    Window &window_;
    unsigned tick_, received_;
    QString state_[4];
    bool eventFilter(QObject *, QEvent *event) {
        if (int(event->type()) == ZKbGlobal::ZIMIndicatorChangeEvent::EventType) {
            const ZKbGlobal::ZIMIndicatorChangeEvent *s =
                static_cast<const ZKbGlobal::ZIMIndicatorChangeEvent *>(event);
            require(s->indicator >= 0 && s->indicator < 4, "indicator event range");
            state_[s->indicator] = s->remove ? QString::null : s->value;
            ++received_;
        }
        return false;
    }
    void timerEvent(QTimerEvent *) {
        ++tick_;
        if (tick_ == 1) {
            window_.showSettings("account");
            window_.chooseSetting("password");
        }
        if (tick_ == 3) {
            require(qApp->type() == QApplication::GuiClient, "separate real GuiClient mode");
            require(received_ >= 4 && !state_[0].isEmpty(), "native mode before first key");
            require(window_.editor_->hasFocus(), "production editor focus");
            FILE *file = fopen(ready, "wb");
            require(file != 0, "keyboard synchronization file");
            fclose(file);
        }
        if (tick_ == 20) {
            require(window_.editor_->text() == "a3", "raw QWS keys reach the native editor");
            require(received_ >= 8 && state_[0].contains("numeric") && state_[2].isEmpty(),
                    "# updates native mode and clears language through real client transport");
            fprintf(stderr, "CLIENT INPUT PASS: GuiClient, native mode/case/language events, "
                            "raw server keys and numeric switch\n");
            qApp->quit();
        }
    }

  public:
    explicit UiProbe(Window &window) : window_(window), tick_(0), received_(0) {
        window_.inputIndicator_->installEventFilter(this);
        startTimer(250);
    }
};
} // namespace tmm
class InputServer : public QObject {
    unsigned tick_, phase_;
    pid_t child_;
    void timerEvent(QTimerEvent *) {
        ++tick_;
        if (tick_ == 2) {
            child_ = fork();
            require(child_ >= 0, "fork isolated client");
            if (child_ == 0) {
                // Never pass -qws to the client: it would silently turn this
                // into another server and invalidate the regression.
                execl("/qemu", "/qemu", "-strace", "-cpu", "arm1136", "/work/input-client-probe",
                      "--client", (char *)0);
                _exit(7);
            }
        }
        if (phase_ || access(ready, F_OK) == 0)
            ++phase_;
        int key = 0;
        if (phase_ == 2 || phase_ == 3)
            key = KEYCODE_2;
        if (phase_ == 6 || phase_ == 7)
            key = KEYCODE_POUND;
        if (phase_ == 10 || phase_ == 11)
            key = KEYCODE_3;
        if (key)
            QWSServer::processKeyEvent(getenv("TMM_CLIENT_KEY_UNICODE") ? key : 0, key, 0,
                                       phase_ % 2 == 0, false);
        int status = 0;
        if (child_ > 0 && waitpid(child_, &status, WNOHANG) == child_) {
            child_ = -1;
            require(WIFEXITED(status) && WEXITSTATUS(status) == 0, "native client exited cleanly");
            fprintf(stderr, "CLIENT INPUT SERVER PASS: separate process, real Unix socket QWS\n");
            qApp->quit();
        }
        if (tick_ == 32) {
            if (child_ > 0)
                kill(child_, SIGTERM);
            require(false, "native client deadline");
        }
    }

  public:
    InputServer() : tick_(0), phase_(0), child_(-1) {
        unlink(ready);
        startTimer(250);
    }
};
int main(int argc, char **argv) {
    if (!getenv("V8_QWS_LOCAL_ONLY"))
        return 3;
    const bool client = argc > 1 && !strcmp(argv[1], "--client");
    tmm::Application app(argc, argv, client ? QApplication::GuiClient : QApplication::GuiServer);
    UTIL_SetPowerOnHandleStatus(10);
    UTIL_SetFlipStatus(SYSTEM_FLIP_OPEN);
    UTIL_SetKeypadLockStatus(false);
    if (client) {
        tmm::Window window("/state/gui-client-data");
        app.setMainWidget(&window);
        window.resize(240, 320);
        window.showFullScreen();
        tmm::UiProbe probe(window);
        return app.exec();
    }
    QWidget window;
    app.setMainWidget(&window);
    window.resize(240, 320);
    window.show();
    InputServer probe;
    return app.exec();
}
