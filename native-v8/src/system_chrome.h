#ifndef TMM_SYSTEM_CHROME_H
#define TMM_SYSTEM_CHROME_H
#include <ZSkinBase.h>

namespace tmm {
// Draw native chrome into the completed frame. The footer background is
// captured once from a hidden native ZSoftKey, including its theme blending.
class SystemChrome {
  public:
    explicit SystemChrome(QWidget &);
    void refresh();
    bool refreshIndicators();
    void drawHeader(QPainter &, const QRect &, const QString &, int offset = 0);
    void drawFooter(QPainter &, const QRect &, const QString &, const QString &);

  private:
    QWidget &window_;
    ZSkinBase header_;
    QPixmap footerBackground_, signalIcon_, batteryIcon_;
    int signal_, battery_;
    QFont headerFont_, softkeyFont_;
    QColor headerInk_, softkeyInk_;
    SystemChrome(const SystemChrome &);
    SystemChrome &operator=(const SystemChrome &);
};
} // namespace tmm
#endif
