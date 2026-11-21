#include "system_chrome.h"
#include <ZSoftKey.h>
#include <ZSkinBase.h>
#include <qdatetime.h>
#include <RES_ICON_Reader.h>
#include <qapplication.h>
#include <stddef.h>
#include <algorithm>

// Same time formatter and minute precision as ZHeader::setTimeString on V8.
class UTIL_DateTime {
  public:
    enum TimeAccuracy { Minutes };
    static QString timeToString(const QTime &, TimeAccuracy);
};

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
    : window_(window), signal_(-2), battery_(-2), minute_(-1) {
    refresh();
}
void SystemChrome::refresh() {
    RES_ICON_Reader reader;
    const QPixmap artwork = reader.getIcon("header_bg_std", false);
    headerBackground_ = QPixmap();
    if (!artwork.isNull()) {
        headerBackground_.resize(artwork.size());
        headerBackground_.fill(window_.palette().active().background());
        QPainter background(&headerBackground_);
        background.drawPixmap(0, 0, artwork);
    }
    minute_ = -1;
    refreshClock();
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
bool SystemChrome::refreshClock() {
    const time_t minute = time(0) / 60;
    if (minute == minute_)
        return false;
    minute_ = minute;
    clock_ = UTIL_DateTime::timeToString(QTime::currentTime(), UTIL_DateTime::Minutes);
    return true;
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
            signal < 0
                ? QPixmap()
                : reader.getIcon(("signal_" + QString::number(signal) + "_hed1").latin1(), false);
    }
    if (battery != battery_) {
        battery_ = battery;
        batteryIcon_ =
            battery < 0 ? QPixmap()
                        : reader.getIcon(
                              ("batt_level_" + QString::number(battery) + "_hed2").latin1(), false);
    }
    return true;
}

int SystemChrome::titleLeft() const {
    // Keep the application icon and title aligned even while radio state is unknown.
    return std::max(25, signalIcon_.width()) + 2;
}
void SystemChrome::drawHeader(QPainter &p, const QRect &rect, const QString &title, int offset) {
    if (rect.isEmpty())
        return;
    p.save();
    p.setClipRect(rect);
    // Paint the application's header artwork on a solid surface. The generic
    // ZSkinBase background can include the handset wallpaper.
    p.fillRect(rect, window_.palette().active().background());
    if (!headerBackground_.isNull()) {
        // V8 Qt's 24-bit tiled blit can run past a pixmap in the window framebuffer.
        const int w = std::min(rect.width(), headerBackground_.width());
        const int h = std::min(rect.height(), headerBackground_.height());
        p.drawPixmap(rect.x(), rect.y(), headerBackground_, 0, 0, w, h);
    }
    if (!signalIcon_.isNull())
        p.drawPixmap(rect.x(), rect.y() + (rect.height() - signalIcon_.height()) / 2, signalIcon_);
    const int batteryLeft = rect.right() + 1 - std::max(25, batteryIcon_.width());
    if (!batteryIcon_.isNull())
        p.drawPixmap(rect.right() + 1 - batteryIcon_.width(),
                     rect.y() + (rect.height() - batteryIcon_.height()) / 2, batteryIcon_);
    p.setFont(headerFont_);
    p.setPen(headerInk_);
    const int clockWidth = p.fontMetrics().width(clock_);
    const int clockLeft = batteryLeft - 2 - clockWidth;
    p.drawText(clockLeft, rect.y(), clockWidth, rect.height(),
               Qt::AlignRight | Qt::AlignVCenter | Qt::SingleLine, clock_);
    const int titleX = rect.x() + titleLeft() + std::max(0, offset);
    if (clockLeft > titleX + 3)
        p.drawText(titleX, rect.y(), clockLeft - titleX - 3, rect.height(),
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
