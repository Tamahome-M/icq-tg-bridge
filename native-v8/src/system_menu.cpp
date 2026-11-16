#include "system_menu.h"
#include "window.h"
#include "ui_settings.h"
#include "ui_language.h"
#include <ZListBox.h>
#include <qapplication.h>
#include <algorithm>
namespace tmm {
SystemMenu::SystemMenu(QWidget *parent)
    : parent_(parent), list_(new ZListBox(QString("%M"), parent)), first_(-1), settings_(false),
      revision_(0) {
    list_->setFocusPolicy(QWidget::StrongFocus);
    list_->showAllSubItem(true);
    list_->enableEllpsis(true);
    for (int region = 0; region < 3; ++region)
        list_->enableMarquee(static_cast<ZListBox::ListItemRegion>(region), false);
    list_->setHScrollBarMode(ZScrollPanel::AlwaysOff);
    list_->installEventFilter(parent);
    if (list_->viewport())
        list_->viewport()->installEventFilter(parent);
    if (list_->clipper())
        list_->clipper()->installEventFilter(parent);
    list_->hide();
}
bool SystemMenu::owns(QObject *object) const {
    return object == list_ || object == list_->viewport() || object == list_->clipper();
}
void SystemMenu::focus() {
    if (!list_->isHidden())
        list_->setFocus();
}
void SystemMenu::sync(View &v, bool visible, int top, int bottom) {
    if (!visible) {
        list_->hide();
        return;
    }
    // Native item lookup is linear. Large file/template lists keep only one
    // bounded page of native objects; selection and all actions stay in View.
    const int pageSize = 32;
    const int selected = std::max(0, std::min(v.selected, int(v.rows.size()) - 1));
    const int first = selected / pageSize * pageSize;
    const int count = std::min(pageSize, int(v.rows.size()) - first);
    const bool settings = v.kind == View::SettingsPage;
    bool changed = first_ != first || settings_ != settings || int(labels_.size()) != count;
    for (int i = 0; !changed && i < count; ++i)
        changed = labels_[i] != v.rows[first + i].text;
    const QRect geometry(0, top, parent_->width(), std::max(1, bottom - top));
    if (list_->geometry() != geometry)
        list_->setGeometry(geometry);
    if (changed) {
        list_->setUpdatesEnabled(false);
        if (list_->viewport())
            list_->viewport()->setUpdatesEnabled(false);
        list_->clear();
        list_->setListItemType(settings ? ZListItem::SETTINGITEM : ZListItem::LISTBOXITEM);
        first_ = first;
        settings_ = settings;
        labels_.clear();
        for (int i = 0; i < count; ++i) {
            const QString &text = v.rows[first + i].text;
            labels_.push_back(text);
            if (settings) {
                ZSettingItem *item = new ZSettingItem(list_, QString("%M"));
                const std::string &action = v.rows[first + i].action;
                const SettingField *field =
                    action.compare(0, 6, "field:") == 0 ? settingField(action.substr(6)) : 0;
                // A label or its value may contain ': ' (media labels, paths).
                // Separate at the known label boundary, never at a delimiter.
                const QString label = field ? uiText(field->label) : text;
                item->appendSubItem(0, label, false, SETTINGITEM_REGION_A);
                if (field)
                    item->appendSubItem(0, text.mid(label.length() + 2), false,
                                        SETTINGITEM_REGION_B);
                list_->insertItem(item, -1, false);
            } else {
                ZListBoxItem *item = new ZListBoxItem(list_, QString("%M"));
                // The paired full-width region is also used by SMS Threads.
                // The single wrapped-text variant clips the last glyph of
                // short numbers on this firmware (e.g. 128 in video choices).
                item->appendSubItem(0, text, QString::null, static_cast<const QPixmap *>(0), 100,
                                    ZListBoxItem::FirstPriority);
                list_->insertItem(item, -1, false);
            }
        }
        ++revision_;
    }
    if (count > 0) {
        if (list_->currentItem() != selected - first)
            list_->ZListBox::setCurrentItem(selected - first);
        if (changed)
            list_->ZListBox::setTopItem(std::max(0, std::min(v.top - first, count - 1)));
        list_->ensureCurrentVisible();
        v.top = first + list_->topItem();
    }
    if (changed) {
        if (list_->viewport())
            list_->viewport()->setUpdatesEnabled(true);
        list_->setUpdatesEnabled(true);
        list_->triggerUpdate(true);
    }
    const bool wasHidden = list_->isHidden();
    list_->show();
    if (wasHidden && parent_->isVisible() && qApp->activeWindow() == parent_->topLevelWidget())
        list_->setFocus();
}
} // namespace tmm
