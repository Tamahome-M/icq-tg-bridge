#ifndef TMM_SYSTEM_CHROME_H
#define TMM_SYSTEM_CHROME_H
#include <ZSkinBase.h>

namespace tmm {
// Draw the firmware's title/softkey skins into Window's completed frame rather
// than exposing separately painted child windows between navigation frames.
class SystemChrome {
  public:
    explicit SystemChrome(QWidget &);
    void refresh();
    void drawHeader(QPainter &, const QRect &, const QString &, int offset = 0);
    void drawFooter(QPainter &, const QRect &, const QString &, const QString &);

  private:
    QWidget &window_;
    ZSkinBase header_, left_, right_;
    QFont headerFont_, softkeyFont_;
    QColor headerInk_, softkeyInk_;
    SystemChrome(const SystemChrome &);
    SystemChrome &operator=(const SystemChrome &);
};
} // namespace tmm
#endif
