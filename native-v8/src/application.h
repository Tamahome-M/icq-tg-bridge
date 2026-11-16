#ifndef TMM_NATIVE_APPLICATION_H
#define TMM_NATIVE_APPLICATION_H
#include "zapplication_v8.h"
namespace tmm {
class Application : public ZApplication {
  public:
    Application(int &argc, char **argv, QApplication::Type type = QApplication::GuiClient)
        : ZApplication(argc, argv, type) {}
    virtual void slotQuickQuit();
    virtual int slotUsbStorageInOut(bool connected);
    virtual void slotShutdown();
    virtual int slotKillactionByMassstorage();
};
} // namespace tmm
#endif
