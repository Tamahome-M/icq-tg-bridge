#ifndef TMM_SYSTEM_MENU_H
#define TMM_SYSTEM_MENU_H
#include <qstring.h>
#include <vector>
class QWidget;
class QObject;
class ZListBox;
namespace tmm {
struct View;
// Owns native Motorola lists, never subclasses a widget with an incomplete SDK
// vtable. The existing View remains the sole source of actions and selection.
class SystemMenu {
  public:
    explicit SystemMenu(QWidget *parent);
    void sync(View &, bool visible, int top, int bottom);
    bool owns(QObject *) const;
    void focus();
    ZListBox *list() const {
        return list_;
    }
    unsigned revision() const {
        return revision_;
    }

  private:
    QWidget *parent_;
    ZListBox *list_;
    std::vector<QString> labels_;
    int first_;
    bool settings_;
    unsigned revision_;
};
} // namespace tmm
#endif
