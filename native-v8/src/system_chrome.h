#ifndef TMM_SYSTEM_CHROME_H
#define TMM_SYSTEM_CHROME_H
#include <qpainter.h>
#include <qpixmap.h>
#include <time.h>

namespace tmm {
// Draw native chrome into the completed frame. The footer background is
// captured once from a hidden native ZSoftKey, including its theme blending.
class SystemChrome {
  public:
    explicit SystemChrome(QWidget &);
    void refresh();
    bool refreshIndicators();
    bool refreshClock();
    int titleLeft() const;
    void drawHeader(QPainter &, const QRect &, const QString &, int offset = 0);
    void drawFooter(QPainter &, const QRect &, const QString &, const QString &);

  private:
    QWidget &window_;
    QPixmap headerBackground_, footerBackground_, signalIcon_, batteryIcon_;
    int signal_, battery_;
    time_t minute_;
    QString clock_;
    QFont headerFont_, softkeyFont_;
    QColor headerInk_, softkeyInk_;
    SystemChrome(const SystemChrome &);
    SystemChrome &operator=(const SystemChrome &);
};
} // namespace tmm
#endif
