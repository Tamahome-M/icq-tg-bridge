// Real Window/settings save path. Run only in the isolated V8 Qt/QWS server.
#include "application.h"
#include "window.h"
#include "storage.h"
#include "ui_settings.h"
#include <ZKeyDef.h>
#include <qapplication.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
extern "C" void UTIL_SetPowerOnHandleStatus(int);
extern "C" void UTIL_SetFlipStatus(int);
extern "C" void UTIL_SetKeypadLockStatus(bool);
namespace tmm {
class UiProbe {
    static void require(bool condition, const char *message) {
        if (!condition) {
            fprintf(stderr, "WINDOW GEOMETRY FAIL: %s\n", message);
            exit(2);
        }
        fprintf(stderr, "WINDOW GEOMETRY PASS: %s\n", message);
    }

  public:
    static void run(Window &window) {
        window.timer_.stop();
        const QRect screen = QApplication::desktop()->geometry();
        window.setGeometry(screen.x(), screen.y(), screen.width() / 2, screen.height() / 2);
        window.showFullScreen();
        qApp->processEvents();
        require(window.size() == screen.size(), "starts at full display size");
        window.settings_.setBool("fullscreen", false);
        window.showSettings("media");
        window.commitSetting("photo_kb", "20");
        window.finishSettings(true);
        qApp->processEvents();
        fprintf(stderr, "WINDOW GEOMETRY after Save: %dx%d, screen %dx%d\n", window.width(),
                window.height(), screen.width(), screen.height());
        require(window.settings_.getInt("photo_kb") == 20 && !window.settingsEditing_,
                "media settings were actually saved");
        require(window.size() == screen.size(),
                "settings Save cannot restore quarter-size geometry");
        require(window.isMaximized(), "non-fullscreen mode is maximized");
        // Startup must apply the same policy, not rely on a later settings save.
        window.hide();
        qApp->processEvents();
        window.showNormal();
        window.setGeometry(screen.x(), screen.y(), screen.width() / 2, screen.height() / 2);
        window.showConfigured();
        qApp->processEvents();
        require(window.isVisible() && window.size() == screen.size() && window.isMaximized(),
                "configured non-fullscreen startup fills the display");
        window.showSettings("interface");
        window.commitSetting("fullscreen", "1");
        window.finishSettings(false);
        require(!settingFlag(window.settings_, "fullscreen") && window.size() == screen.size(),
                "Back cancels a staged fullscreen change without resizing");
        window.showSettings("interface");
        window.commitSetting("fullscreen", "1");
        window.finishSettings(true);
        require(settingFlag(window.settings_, "fullscreen") && window.size() == screen.size(),
                "saving fullscreen mode fills the display");
        window.showSettings("media");
        window.commitSetting("photo_kb", "40");
        window.finishSettings(true);
        require(window.settings_.getInt("photo_kb") == 40 && window.size() == screen.size(),
                "unrelated Save preserves fullscreen geometry");
        window.showSettings("interface");
        window.commitSetting("fullscreen", "0");
        window.finishSettings(true);
        for (unsigned i = 0; i < 3; ++i) {
            window.showSettings("notifications");
            window.finishSettings(true);
            require(window.size() == screen.size(), "repeated Save keeps the full display");
        }
        window.platform_.minimize();
        // Let the QWS hide notification settle before simulating a later raise.
        qApp->processEvents();
        require(!window.isVisible(), "minimize hides the application");
        window.applySettings();
        require(!window.isVisible(), "applying settings in background does not raise it");
        window.resume();
        qApp->processEvents();
        fprintf(stderr, "WINDOW GEOMETRY after Resume: %dx%d, visible=%d maximized=%d\n",
                window.width(), window.height(), window.isVisible(), window.isMaximized());
        require(window.isVisible() && window.size() == screen.size() && window.isMaximized(),
                "native foreground restore keeps maximized mode and size");
        UTIL_SetFlipStatus(SYSTEM_FLIP_CLOSE);
        window.platform_.minimize();
        qApp->processEvents();
        window.resume();
        require(!window.isVisible(), "closed flip still prevents raising the application");
        UTIL_SetFlipStatus(SYSTEM_FLIP_OPEN);
        window.resume();
        qApp->processEvents();
        require(window.isVisible() && window.size() == screen.size(),
                "missed flip callback recovery also preserves the display size");
    }
};
} // namespace tmm
int main(int argc, char **argv) {
    if (!getenv("V8_QWS_LOCAL_ONLY"))
        return 3;
    tmm::Application app(argc, argv, QApplication::GuiServer);
    chdir("/work");
    UTIL_SetPowerOnHandleStatus(10);
    UTIL_SetFlipStatus(SYSTEM_FLIP_OPEN);
    UTIL_SetKeypadLockStatus(false);
    const std::string directory = "/state/window-geometry-data";
    std::string error;
    if (!tmm::ensureDirectory(directory, error))
        return 4;
    tmm::Settings settings;
    settings.load(directory + "/settings", error);
    settings.set("host", "bridge.example.test");
    settings.set("uin", "123456");
    settings.set("password", "dummy");
    settings.set("network", "system");
    settings.setBool("auto_connect", false);
    settings.setBool("auto_reconnect", false);
    settings.setBool("startup_dns", false);
    settings.setBool("fullscreen", false);
    if (!settings.save(error))
        return 5;
    tmm::Window window(directory);
    app.setMainWidget(&window);
    tmm::UiProbe::run(window);
    puts("WINDOW GEOMETRY COMPLETE");
    return 0;
}
