#include "system_chrome.h"
#include <ZSoftKey.h>
#include <RES_ICON_Reader.h>
#include <qapplication.h>
#include <stddef.h>
#include <algorithm>

// These public SDK layouts match this firmware's ZSkinBase constructor and
// ZSoftKey::initFont/updateFont. Keep the native objects' vtables intact.
typedef char TmmSkinBaseSize[(sizeof(ZSkinBase) == 64) ? 1 : -1];
typedef char TmmSkinFontSize[(sizeof(FONT_INFO_T) == 28) ? 1 : -1];
typedef char TmmHeaderFontOffset[(offsetof(ZWidgetSkinProps, fntHeaderAStd) == 14364) ? 1 : -1];
typedef char TmmSoftkeyFontOffset[(offsetof(ZWidgetSkinProps, fntSoftkeyStd) == 14448) ? 1 : -1];

// Both V8 functions read the firmware's shared device-state segment.
extern "C" int UTIL_GetSignalQuality();
extern "C" int UTIL_GetBatteryLevel();

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
    : window_(window), header_(window, ZSkinService::clsZHeader1, false), signal_(-2),
      battery_(-2) {
    refresh();
}
void SystemChrome::refresh() {
    header_.updateSkin();
    signal_ = battery_ = -2;
    refreshIndicators();
    footerBackground_ = QPixmap();
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
static QPixmap headerIcon(RES_ICON_Reader &reader, const QString &name, int width) {
    QPixmap icon = reader.getIcon(name.latin1(), false);
    if (!icon.isNull() && (icon.width() > width || icon.height() > 16)) {
        double scale = std::min(double(width) / icon.width(), 16.0 / icon.height());
        QWMatrix m;
        m.scale(scale, scale);
        return icon.xForm(m);
    }
    return icon;
}

bool SystemChrome::refreshIndicators() {
    int signal = UTIL_GetSignalQuality(), battery = UTIL_GetBatteryLevel();
    if (signal < 0 || signal > 5)
        signal = -1;
    // The V8 Phone app maps its six battery readings to four header images:
    // readings 0, 1 and 2 use the empty image; 3, 4 and 5 use levels 1..3.
    battery = battery >= 0 && battery <= 5 ? std::max(0, battery - 2) : -1;
    if (signal == signal_ && battery == battery_)
        return false;
    RES_ICON_Reader reader;
    if (signal != signal_) {
        signal_ = signal;
        signalIcon_ =
            signal < 0 ? QPixmap()
                       : headerIcon(reader, "signal_" + QString::number(signal) + "_idle1.g", 22);
    }
    if (battery != battery_) {
        battery_ = battery;
        batteryIcon_ =
            battery < 0
                ? QPixmap()
                : headerIcon(reader, "batt_level_" + QString::number(battery) + "_hed2.gif", 21);
    }
    return true;
}

static bool drawIndicator(QPainter &p, const QRect &box, const QPixmap &icon) {
    if (icon.isNull())
        return false;
    p.drawPixmap(box.x() + (box.width() - icon.width()) / 2,
                 box.y() + (box.height() - icon.height()) / 2, icon);
    return true;
}

void SystemChrome::drawHeader(QPainter &p, const QRect &rect, const QString &title, int offset) {
    if (rect.isEmpty())
        return;
    p.save();
    p.fillRect(rect, window_.palette().active().background());
    header_.drawBackground(p, &rect, false);
    header_.drawBorder(p, &rect);
    p.setFont(headerFont_);
    p.setPen(headerInk_);
    const int middle = rect.y() + rect.height() / 2;
    const QRect cell(rect.right() - 47, middle - 8, 22, 16);
    const QRect power(rect.right() - 23, middle - 8, 21, 16);
    if (!drawIndicator(p, cell, signalIcon_)) {
        for (int i = 0; i < 5; ++i) {
            int h = 3 + i * 2;
            int x = cell.x() + 2 + i * 4;
            if (i < signal_)
                p.fillRect(x, middle + 5 - h, 3, h, headerInk_);
            else
                p.drawPoint(x + 1, middle + 4);
        }
    }
    if (!drawIndicator(p, power, batteryIcon_)) {
        p.drawRect(power.x(), middle - 5, 18, 10);
        p.fillRect(power.x() + 18, middle - 2, 2, 4, headerInk_);
        if (battery_ > 0)
            p.fillRect(power.x() + 2, middle - 3, battery_ * 5, 6, headerInk_);
    }
    const int indent = std::max(0, 5 + offset);
    const int space = cell.x() - 2 - rect.x() - indent;
    if (space > 0)
        p.drawText(rect.x() + indent, rect.y(), space, rect.height(),
                   Qt::AlignLeft | Qt::AlignVCenter | Qt::SingleLine, title);
    p.restore();
}
void SystemChrome::drawFooter(QPainter &p, const QRect &rect, const QString &left,
                              const QString &right) {
    if (rect.isEmpty())
        return;
    p.save();
    if (footerBackground_.size() != rect.size()) {
        // The QWidget ZSkinBase overload does not blend like ZSoftButton's
        // ZWidget overload. Render the real control without showing it or
        // processing application events. Its solid themed parent prevents
        // chat/photo pixels from showing through the bar's translucent skin.
        QWidget surface(&window_);
        surface.resize(rect.size());
        surface.setPalette(window_.palette());
        surface.setBackgroundColor(window_.palette().active().background());
        ZSoftKey keys("CST_2", &surface);
        keys.setGeometry(0, 0, rect.width(), rect.height());
        keys.setText(ZSoftKey::LEFT, QString::null);
        keys.setText(ZSoftKey::RIGHT, QString::null);
        keys.hide();
        footerBackground_ = QPixmap::grabWidget(&keys);
    }
    p.fillRect(rect, window_.palette().active().background());
    if (!footerBackground_.isNull())
        p.drawPixmap(rect.x(), rect.y(), footerBackground_);
    const QRect leftRect(rect.x(), rect.y(), rect.width() / 2, rect.height());
    const QRect rightRect(leftRect.right() + 1, rect.y(), rect.width() - leftRect.width(),
                          rect.height());
    p.setFont(softkeyFont_);
    p.setPen(softkeyInk_);
    p.drawText(leftRect.x() + 4, leftRect.y(), std::max(1, leftRect.width() - 8), leftRect.height(),
               Qt::AlignLeft | Qt::AlignVCenter | Qt::SingleLine, left);
    p.drawText(rightRect.x() + 4, rightRect.y(), std::max(1, rightRect.width() - 8),
               rightRect.height(), Qt::AlignRight | Qt::AlignVCenter | Qt::SingleLine, right);
    p.restore();
}
} // namespace tmm
