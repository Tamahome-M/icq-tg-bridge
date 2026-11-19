#ifndef TMM_SYSTEM_MENU_H
#define TMM_SYSTEM_MENU_H
#include <qstring.h>
#include <qpixmap.h>
#include <vector>
class QWidget;
class QObject;
class ZListBox;
namespace tmm {
struct View;
struct Row;
struct ContactRecord;
// Owns native Motorola lists, never subclasses a widget with an incomplete SDK
// vtable. The existing View remains the sole source of actions and selection.
class SystemMenu {
  public:
    SystemMenu(QWidget *parent, const std::vector<ContactRecord> &, const QPixmap &statuses,
               const QPixmap &messages);
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
    int rosterIconKey(const Row &) const;
    const QPixmap &rosterIcon(int);
    QWidget *parent_;
    ZListBox *list_;
    const std::vector<ContactRecord> &contacts_;
    const QPixmap &statusAtlas_, &messageAtlas_;
    QPixmap rosterIcons_[15];
    std::vector<QString> labels_;
    int first_;
    bool settings_, roster_;
    unsigned revision_;
};
} // namespace tmm
#endif
