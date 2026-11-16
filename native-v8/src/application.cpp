#include "application.h"
#include "window.h"
namespace tmm {
void Application::slotQuickQuit() {
    if (mainWidget()) {
        static_cast<Window *>(mainWidget())->suspend();
        mainWidget()->hide();
    }
}
int Application::slotUsbStorageInOut(bool connected) {
    if (connected)
        quit();
    return 0;
}
void Application::slotShutdown() {
    if (mainWidget())
        static_cast<Window *>(mainWidget())->saveState();
    ZApplication::slotShutdown();
}
int Application::slotKillactionByMassstorage() {
    quit();
    return 0;
}
} // namespace tmm
