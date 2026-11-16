// Isolated QWS only. Executes native widget ABI; never opens a camera/player.
#include "zapplication_v8.h"
#include <ZKeyDef.h>
#include <qtimer.h>
#include <qwidget.h>
#include <dlfcn.h>
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <cstdio>
extern "C" void UTIL_SetPowerOnHandleStatus(int);
extern "C" void UTIL_SetFlipStatus(int);
extern "C" void UTIL_SetKeypadLockStatus(bool);
template <class T> T fn(void *p) {
    assert(p);
    T f;
    std::memcpy(&f, &p, sizeof(f));
    return f;
}
int main(int argc, char **argv) {
    ZApplication app(argc, argv, QApplication::GuiServer);
    UTIL_SetPowerOnHandleStatus(10);
    UTIL_SetFlipStatus(SYSTEM_FLIP_OPEN);
    UTIL_SetKeypadLockStatus(false);
    QWidget window;
    window.resize(240, 320);
    app.setMainWidget(&window);
    window.show();
    void *library = dlopen("libezx_mp_utility.so.1", RTLD_NOW | RTLD_GLOBAL);
    assert(library);
    unsigned long *block = static_cast<unsigned long *>(std::calloc(1, 256));
    assert(block);
    block[0] = 0x12345678;
    block[63] = 0x87654321;
    void *widget = block + 1;
    fn<void (*)(void *, QWidget *, const char *, unsigned)>(dlsym(
        library, "_ZN14MP_VideoWidgetC1EP7QWidgetPKcj"))(widget, &window, "tmm-video-test", 0);
    assert(block[0] == 0x12345678 && block[63] == 0x87654321);
    QWidget *w = static_cast<QWidget *>(widget);
    w->setGeometry(0, 40, 240, 180);
    w->show();
    // Ezx_VideoDevice has a secondary vtable at native QWidget base +196.
    void **interface = 0;
    std::memcpy(&interface, static_cast<char *>(widget) + 196, 4);
    assert(interface);
    assert(fn<int (*)(void *)>(dlsym(library, "_ZThn196_N14MP_VideoWidget8getWidthEv"))(
               static_cast<char *>(widget) + 196) == 240);
    assert(fn<int (*)(void *)>(dlsym(library, "_ZThn196_N14MP_VideoWidget9getHeightEv"))(
               static_cast<char *>(widget) + 196) == 180);
    QTimer::singleShot(1000, &app, SLOT(quit()));
    int result = app.QApplication::exec();
    fn<void (*)(void *)>(dlsym(library, "_ZN14MP_VideoWidgetD1Ev"))(widget);
    assert(block[0] == 0x12345678 && block[63] == 0x87654321);
    std::free(block);
    std::puts("native MP_VideoWidget: 248-byte constructor/destructor guards, interface+196, "
              "geometry PASS");
    return result;
}
