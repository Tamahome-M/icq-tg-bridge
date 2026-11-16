#include "system_chrome.h"
#include <qapplication.h>
#include <stddef.h>
#include <algorithm>

// These public SDK layouts match this firmware's ZSkinBase constructor and
// ZSoftKey::initFont/updateFont. Keep the native objects' vtables intact.
typedef char TmmSkinBaseSize[(sizeof(ZSkinBase) == 64) ? 1 : -1];
typedef char TmmSkinFontSize[(sizeof(FONT_INFO_T) == 28) ? 1 : -1];
typedef char TmmHeaderFontOffset[(offsetof(ZWidgetSkinProps, fntHeaderAStd) == 14364) ? 1 : -1];
typedef char TmmSoftkeyFontOffset[(offsetof(ZWidgetSkinProps, fntSoftkeyStd) == 14448) ? 1 : -1];

namespace tmm {
static QFont themeFont(QWidget &window, const FONT_INFO_T &info) {
    // Match ZSoftKey::updateFont: retain the application font family, apply
    // the active skin's size and style. getSkinFont is not exported on V8.
    QFont font = QApplication::font(&window);
    if (info.size > 0)
        font.setPointSize(info.size);
    font.setWeight(info.style & fsBold ? QFont::Bold : QFont::Normal);
    font.setItalic((info.style & fsItalic) != 0);
    font.setUnderline((info.style & fsUnderline) != 0);
    font.setStrikeOut((info.style & fsStrikeOut) != 0);
    return font;
}
SystemChrome::SystemChrome(QWidget &window)
    : window_(window), header_(window, ZSkinService::clsZHeader1, false),
      left_(window, ZSkinService::clsZSoftKeyLeft, false),
      right_(window, ZSkinService::clsZSoftKeyRight, false) {
    refresh();
}
void SystemChrome::refresh() {
    header_.updateSkin();
    left_.updateSkin();
    right_.updateSkin();
    const ZWidgetSkinProps *props = ZSkinService::getAllSkinnableProps();
    if (props) {
        headerFont_ = themeFont(window_, props->fntHeaderAStd);
        softkeyFont_ = themeFont(window_, props->fntSoftkeyStd);
        headerInk_.setRgb(props->fntHeaderAStd.color);
        softkeyInk_.setRgb(props->fntSoftkeyStd.color);
    } else {
        headerFont_ = softkeyFont_ = QApplication::font(&window_);
        headerInk_ = softkeyInk_ = window_.palette().active().foreground();
    }
}
void SystemChrome::drawHeader(QPainter &p, const QRect &rect, const QString &title, int offset) {
    p.save();
    header_.drawBackground(p, &rect, false);
    header_.drawBorder(p, &rect);
    p.setFont(headerFont_);
    p.setPen(headerInk_);
    const int indent = std::max(0, std::min(rect.width() - 1, 5 + offset));
    p.drawText(rect.x() + indent, rect.y(), std::max(1, rect.width() - indent - 5), rect.height(),
               Qt::AlignLeft | Qt::AlignVCenter | Qt::SingleLine, title);
    p.restore();
}
void SystemChrome::drawFooter(QPainter &p, const QRect &rect, const QString &left,
                              const QString &right) {
    p.save();
    const QRect leftRect(rect.x(), rect.y(), rect.width() / 2, rect.height());
    const QRect rightRect(leftRect.right() + 1, rect.y(), rect.width() - leftRect.width(),
                          rect.height());
    left_.drawBackground(p, &leftRect, false);
    left_.drawBorder(p, &leftRect);
    right_.drawBackground(p, &rightRect, false);
    right_.drawBorder(p, &rightRect);
    p.setFont(softkeyFont_);
    p.setPen(softkeyInk_);
    p.drawText(leftRect.x() + 4, leftRect.y(), std::max(1, leftRect.width() - 8), leftRect.height(),
               Qt::AlignLeft | Qt::AlignVCenter | Qt::SingleLine, left);
    p.drawText(rightRect.x() + 4, rightRect.y(), std::max(1, rightRect.width() - 8),
               rightRect.height(), Qt::AlignRight | Qt::AlignVCenter | Qt::SingleLine, right);
    p.restore();
}
} // namespace tmm
