#ifndef TMM_NATIVE_STATUS_ICON_V8_H
#define TMM_NATIVE_STATUS_ICON_V8_H
namespace tmm {
// Native Motorola header registration, independent of connection/foreground.
class StatusIconV8 {
  public:
    StatusIconV8();
    ~StatusIconV8();
    bool show(unsigned mode = 1); // 0=off, 1=header (IM), 2=idle screen (ICQ)
    static void configureApplication(unsigned mode);
    void hide();

  private:
    StatusIconV8(const StatusIconV8 &);
    StatusIconV8 &operator=(const StatusIconV8 &);
    bool registered_;
    unsigned mode_, slot_;
};
} // namespace tmm
#endif
