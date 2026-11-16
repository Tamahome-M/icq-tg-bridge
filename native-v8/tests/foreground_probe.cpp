// The actual Platform/Qt/native raise path; only physical backlight I/O is
// recorded at dlsym. Link the QWS probe with --wrap=dlsym, never the application.
#include "platform.h"
#include "zapplication_v8.h"
#include <qwidget.h>
#include <qapplication.h>
#include <ZKeyDef.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>
extern "C" void UTIL_SetFlipStatus(int);
extern "C" void *__real_dlsym(void *, const char *);

static unsigned opened, enabled, disabled, closed;
static int lightOpen(const char *name) {
    assert(strcmp(name, "TeleMotoMax") == 0);
    ++opened;
    return 17;
}
static int lightOn(int handle) {
    assert(handle == 17);
    ++enabled;
    return 0;
}
static int lightOff(int handle) {
    assert(handle == 17);
    ++disabled;
    return 0;
}
static int lightClose(int handle) {
    assert(handle == 17);
    ++closed;
    return 0;
}
template <class Function> static void *pointer(Function function) {
    void *result;
    assert(sizeof(result) == sizeof(function));
    memcpy(&result, &function, sizeof(result));
    return result;
}
extern "C" void *__wrap_dlsym(void *library, const char *name) {
    if (!strcmp(name, "SOUNDM_VBBLM_BackLightOpenDev"))
        return pointer(lightOpen);
    if (!strcmp(name, "SOUNDM_VBBLM_BackLightDevON"))
        return pointer(lightOn);
    if (!strcmp(name, "SOUNDM_VBBLM_BackLightDevOFF"))
        return pointer(lightOff);
    if (!strcmp(name, "SOUNDM_VBBLM_BackLightCloseDev"))
        return pointer(lightClose);
    return __real_dlsym(library, name);
}
void checkForeground(tmm::Platform &platform, QWidget &window) {
    platform.setBacklight(false);
    opened = enabled = disabled = closed = 0;
    window.hide();
    platform.requestForeground();
    assert(window.isVisible());
    assert(opened == 1 && enabled == 1 && !disabled && !closed);
    platform.requestForeground();
    assert(window.isVisible());
    assert(opened == 1 && enabled == 2); // Reuse the existing hardware handle.
    platform.setBacklight(false);
    assert(disabled == 1 && closed == 1);

    // A restore after an unobserved physical lid transition must query the
    // actual state, rather than refusing forever because its cache said closed.
    UTIL_SetFlipStatus(SYSTEM_FLIP_CLOSE);
    window.hide();
    platform.requestForeground();
    assert(!window.isVisible() && platform.flipClosed());
    UTIL_SetFlipStatus(SYSTEM_FLIP_OPEN);
    platform.requestForeground();
    assert(window.isVisible() && !platform.flipClosed());
    assert(opened == 2 && enabled == 3);
    fprintf(stderr, "FOREGROUND PASS: native showMainWidget, physical light wake, handle reuse, "
                    "missed lid callback recovery\n");
}
