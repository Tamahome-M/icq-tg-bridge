#ifndef TMM_NATIVE_STATUS_ICON_V8_H
#define TMM_NATIVE_STATUS_ICON_V8_H
#include <stdint.h>
namespace tmm {
// Native Motorola header registration, retained independently of foreground.
class StatusIconV8 {
  public:
    StatusIconV8();
    ~StatusIconV8();
    bool show(unsigned mode = 1, uint32_t status = 0xffffffffU, bool unread = false);
    static void configureApplication(unsigned mode, uint32_t status, bool unread = false);
    static void themeChanged();
    void hide();

  private:
    StatusIconV8(const StatusIconV8 &);
    StatusIconV8 &operator=(const StatusIconV8 &);
    bool registered_;
    bool resourcesChecked_, patched_;
    unsigned mode_, slot_, state_;
};
} // namespace tmm
#endif
