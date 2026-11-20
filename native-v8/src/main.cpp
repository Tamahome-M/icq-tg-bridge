#include "application.h"
#include "window.h"
#include "instance.h"
#include "storage.h"
#include "status_icon_v8.h"
#include "theme_patch.h"
#include <ZMessageDlg.h>
#include <exception>
#include <sys/stat.h>
#include <sys/file.h>
#include <fcntl.h>
#include <unistd.h>
#include <cstdlib>
#include <cstdio>
#include <cstring>
int main(int argc, char **argv) {
    umask(0077);
    if (argc == 2 && std::strcmp(argv[1], "--version") == 0) {
        std::puts("TeleMotoMax Native " TMM_NATIVE_VERSION " / Motorola V8");
        return 0;
    }
    const char *configured = std::getenv("TMM_NATIVE_DATA");
    std::string data = configured ? configured : "data";
    std::string error;
    if (!tmm::ensureDirectory(data, error)) {
        std::fprintf(stderr, "%s\n", error.c_str());
        return 1;
    }
    tmm::Instance instance;
    int state = instance.acquire(data, error);
    if (state <= 0) {
        if (state < 0)
            std::fprintf(stderr, "%s\n", error.c_str());
        return state < 0 ? 1 : 0;
    }
    if (!tmm::cleanupCachedMedia(data, error))
        std::fprintf(stderr, "%s\n", error.c_str());
    try {
        if (argc == 2 && (std::strcmp(argv[1], "--install-status-icons") == 0 ||
                          std::strcmp(argv[1], "--restore-status-icons") == 0)) {
            ZApplication app(argc, argv);
            const bool restore = std::strcmp(argv[1], "--restore-status-icons") == 0;
            const std::string iconDirectory = "/ezxlocal/download/appwrite/TeleMotoMaxStatusIcons";
            bool ok = tmm::ensureDirectory(iconDirectory, error) &&
                      tmm::patchStatusTheme("/ezxlocal/download/appwrite/setup/ezx_theme.cfg",
                                            iconDirectory, "status-icons.ezx", restore, error);
            const char *message =
                ok ? (restore ? "Исходная тема восстановлена. Перезагрузите телефон."
                              : "Значки установлены. Перезагрузите телефон.")
                   : "Не удалось изменить тему. Подробности в журнале приложения.";
            if (!ok)
                std::fprintf(stderr, "Status icons: %s\n", error.c_str());
            ZMessageDlg result(QString::fromUtf8("TeleMotoMax"), QString::fromUtf8(message),
                               ZMessageDlg::just_ok);
            result.exec();
            return ok ? 0 : 1;
        }
        tmm::Application app(argc, argv);
        tmm::StatusIconV8 statusIcon;
        tmm::Window window(data);
        app.setMainWidget(&window);
        window.showConfigured();
        int result = app.exec();
        window.saveState();
        return result;
    } catch (const std::exception &e) {
        std::fprintf(stderr, "Cannot start TeleMotoMax: %s\n", e.what());
    } catch (...) {
        std::fprintf(stderr, "Cannot start TeleMotoMax\n");
    }
    return 1;
}
