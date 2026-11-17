#include "application.h"
#include "window.h"
#include "instance.h"
#include "storage.h"
#include "status_icon_v8.h"
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
        tmm::Application app(argc, argv);
        tmm::StatusIconV8 statusIcon;
        tmm::Window window(data);
        app.setMainWidget(&window);
        window.showFullScreen();
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
