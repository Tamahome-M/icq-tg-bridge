#include "system_menu.h"
#include "window.h"
#include "ui_settings.h"
#include "ui_language.h"
#include "status_icon.h"
#include <ZListBox.h>
#include <qapplication.h>
#include <qimage.h>
#include <algorithm>
// The archived header adds a ShowPriority argument to setSubItem, but both
// SDK and V8 export this six-argument setter. Priority stays as set at append.
extern "C" bool
setV8SubItem(ZListBoxItem *, int, int, QString, QString, const QPixmap *,
             unsigned) asm("_ZN12ZListBoxItem10setSubItemEii7QStringS0_PK7QPixmapj");
namespace tmm {
static QString rosterText(const Row &row) {
    if (row.action.compare(0, 13, "group-toggle:") != 0)
        return row.text;
    int spaces = 0;
    while (spaces < int(row.text.length()) && row.text[spaces] == QChar(' '))
        ++spaces;
    QString branch;
    for (int depth = 0; depth < spaces / 2; ++depth)
        branch += "| ";
    // ZWrapLine trims leading spaces; an ASCII branch preserves tree depth.
    return branch + row.text.mid(spaces);
}
SystemMenu::SystemMenu(QWidget *parent, const std::vector<ContactRecord> &contacts,
                       const QPixmap &statuses, const QPixmap &messages)
    : parent_(parent), list_(new ZListBox(QString("%M"), parent)), contacts_(contacts),
      statusAtlas_(statuses), messageAtlas_(messages), first_(-1), settings_(false), roster_(false),
      revision_(0) {
    list_->setFocusPolicy(QWidget::StrongFocus);
    list_->showAllSubItem(true);
    list_->setShowSubItemIcon(true);
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
int SystemMenu::rosterIconKey(const Row &row) const {
    if (row.value)
        return 14; // Unread envelope also decorates a collapsed group.
    if (row.uin)
        for (size_t i = 0; i < contacts_.size(); ++i)
            if (contacts_[i].type == 0 && contacts_[i].uin == row.uin)
                return statusIcon(contacts_[i].status);
    return -1;
}
const QPixmap &SystemMenu::rosterIcon(int key) {
    QPixmap &icon = rosterIcons_[key];
    if (icon.isNull()) {
        const QPixmap &atlas = key == 14 ? messageAtlas_ : statusAtlas_;
        const int x = key == 14 ? 0 : key * 16;
        if (atlas.width() >= x + 16 && atlas.height() >= 16)
            icon.convertFromImage(atlas.convertToImage().copy(x, 0, 16, 16));
    }
    return icon;
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
    const bool privacy = v.context == "privacy-editor";
    const bool settings = v.kind == View::SettingsPage || privacy;
    const bool roster = v.kind == View::Roster;
    // QWidget font inheritance can already match while ZListBox's separately
    // cached region fonts still have the previous size.
    const ZListBox::ListItemRegion firstRegion = static_cast<ZListBox::ListItemRegion>(0);
    const bool fontChanged = list_->getItemFont(firstRegion, false) != parent_->font() ||
                             list_->getItemFont(firstRegion, true) != parent_->font();
    if (fontChanged) {
        QFont body = parent_->font();
        list_->setFont(body);
        for (int region = 0; region < 3; ++region) {
            list_->setItemFont(static_cast<ZListBox::ListItemRegion>(region), body, false);
            list_->setItemFont(static_cast<ZListBox::ListItemRegion>(region), body, true);
        }
    }
    std::vector<QString> signatures;
    int iconKeys[pageSize];
    for (int i = 0; i < count; ++i) {
        const Row &row = v.rows[first + i];
        QString signature = row.text;
        if (v.context == "phonebook" && row.action.compare(0, 6, "phone:") == 0)
            signature += "  " + QString::fromLatin1(row.action.c_str() + 6);
        if (privacy)
            signature += ":" + QString::number(row.value) + ":" + QString::number(v.offset);
        iconKeys[i] = -1;
        if (roster)
            iconKeys[i] = rosterIconKey(row);
        else if (row.action == "status-set" || row.action == "status")
            iconKeys[i] = int(statusIcon(row.value));
        if (roster || iconKeys[i] >= 0)
            signature += ":icon:" + QString::number(iconKeys[i]);
        signatures.push_back(signature);
    }
    const bool rebuild = fontChanged || first_ != first || settings_ != settings ||
                         roster_ != roster || int(labels_.size()) != count;
    bool changed = rebuild;
    for (int i = 0; !changed && i < count; ++i)
        changed = labels_[i] != signatures[i];
    if (changed) {
        list_->setUpdatesEnabled(false);
        if (list_->viewport())
            list_->viewport()->setUpdatesEnabled(false);
        // Presence/unread updates reuse the bounded native roster items.
        // Rebuilding a whole page per status would stall the login burst.
        if (roster && !rebuild) {
            for (int i = 0; i < count; ++i) {
                if (labels_[i] == signatures[i])
                    continue;
                ZListBoxItem *item = static_cast<ZListBoxItem *>(list_->item(i));
                const QPixmap *icon = iconKeys[i] < 0 ? 0 : &rosterIcon(iconKeys[i]);
                setV8SubItem(item, 0, 0, rosterText(v.rows[first + i]), QString::null, icon, 100);
                item->setSelectable(!v.rows[first + i].action.empty());
                labels_[i] = signatures[i];
            }
        } else {
            list_->clear();
            list_->setListItemType(settings ? ZListItem::SETTINGITEM : ZListItem::LISTBOXITEM);
            first_ = first;
            settings_ = settings;
            roster_ = roster;
            labels_.clear();
            QImage smileys;
            if (v.context == "smileys")
                smileys.load("smiles.png");
            for (int i = 0; i < count; ++i) {
                const QString text = roster                     ? rosterText(v.rows[first + i])
                                     : v.context == "phonebook" ? signatures[i]
                                                                : v.rows[first + i].text;
                labels_.push_back(signatures[i]);
                if (settings) {
                    ZSettingItem *item = new ZSettingItem(list_, QString("%M"));
                    const std::string &action = v.rows[first + i].action;
                    const SettingField *field =
                        action.compare(0, 6, "field:") == 0 ? settingField(action.substr(6)) : 0;
                    // A label or its value may contain ': ' (media labels, paths).
                    // Separate at the known label boundary, never at a delimiter.
                    QString label = field ? uiText(field->label) : text;
                    if (field && (std::string(field->key) == "uin" ||
                                  std::string(field->key) == "password")) {
                        int delimiter = text.find(": ");
                        if (delimiter >= 0)
                            label = text.left(delimiter);
                    }
                    item->appendSubItem(0, label, false, SETTINGITEM_REGION_A);
                    if (privacy) {
                        QString cells;
                        const char *names[] = {"D", "I", "V"};
                        for (unsigned col = 0; col < 3; ++col) {
                            if (col)
                                cells += " ";
                            if (col == v.offset)
                                cells += "<";
                            cells += names[col];
                            cells += (v.rows[first + i].value & (4U >> col)) ? "[x]" : "[ ]";
                            if (col == v.offset)
                                cells += ">";
                        }
                        item->appendSubItem(0, cells, false, SETTINGITEM_REGION_B);
                    } else if (field)
                        item->appendSubItem(0, text.mid(label.length() + 2), false,
                                            SETTINGITEM_REGION_B);
                    item->setSelectable(!action.empty() && action != "settings-heading");
                    list_->insertItem(item, -1, false);
                } else {
                    ZListBoxItem *item = new ZListBoxItem(list_, QString("%M"));
                    // The paired full-width region is also used by SMS Threads.
                    // The single wrapped-text variant clips the last glyph of
                    // short numbers on this firmware (e.g. 128 in video choices).
                    QPixmap icon;
                    if (iconKeys[i] >= 0)
                        icon = rosterIcon(iconKeys[i]);
                    if (!smileys.isNull() && v.offset && v.offset <= 64 &&
                        smileys.width() >= int(v.offset)) {
                        const unsigned columns = smileys.width() / v.offset;
                        const unsigned index = v.rows[first + i].value;
                        if ((index / columns + 1) * v.offset <= unsigned(smileys.height())) {
                            icon.convertFromImage(smileys.copy((index % columns) * v.offset,
                                                               (index / columns) * v.offset,
                                                               v.offset, v.offset));
                        }
                    }
                    item->appendSubItem(0, text, QString::null, icon.isNull() ? 0 : &icon, 100,
                                        ZListBoxItem::FirstPriority);
                    item->setSelectable(!v.rows[first + i].action.empty());
                    list_->insertItem(item, -1, false);
                }
            }
        }
        ++revision_;
    }
    if (v.kind == View::Popup) {
        int wanted = 4;
        for (int i = 0; i < count; ++i)
            wanted += std::max(1, list_->itemHeight(i));
        top = std::max(top, bottom - wanted);
    }
    const QRect geometry(0, top, parent_->width(), std::max(1, bottom - top));
    if (list_->geometry() != geometry)
        list_->setGeometry(geometry);
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
