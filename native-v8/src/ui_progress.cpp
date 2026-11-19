#include "window.h"
#include "ui_language.h"
#include "ui_settings.h"
#include "status_icon.h"
#include <qpainter.h>
#include <qfontmetrics.h>
#include <algorithm>
#include <stdio.h>
#include <sys/stat.h>
#include <time.h>

namespace tmm {
namespace {
// Qt 2 WordBreak leaves a long filename/hostname on one clipped line. Split
// those tokens too, using the same font metrics as the real phone painter.
std::vector<QString> wrapped(const QString &text, const QFontMetrics &metrics, int width,
                             unsigned maximum) {
    std::vector<QString> lines;
    QString line;
    const QString source = text.left(1024);
    for (unsigned i = 0; i < source.length(); ++i) {
        QChar character = source[i];
        if (character == '\n') {
            lines.push_back(line);
            line = QString::null;
            continue;
        }
        line += character == '\t' ? QChar(' ') : character;
        while (line.length() > 1 && metrics.width(line) > width) {
            int cut = line.findRev(' ', int(line.length()) - 2);
            if (cut <= 0)
                cut = line.length() - 1;
            lines.push_back(line.left(cut));
            line = line.mid(cut);
            while (!line.isEmpty() && line[0] == ' ')
                line = line.mid(1);
        }
    }
    if (!line.isEmpty())
        lines.push_back(line);
    if (lines.size() > maximum) {
        lines.resize(maximum);
        QString &last = lines.back();
        while (!last.isEmpty() && metrics.width(last + "...") > width)
            last.truncate(last.length() - 1);
        last += "...";
    }
    return lines;
}
void drawLines(QPainter &painter, const std::vector<QString> &lines, int left, int top, int width,
               int lineHeight, int alignment = Qt::AlignLeft) {
    for (size_t i = 0; i < lines.size(); ++i)
        painter.drawText(left, top + i * lineHeight, width, lineHeight,
                         alignment | Qt::AlignVCenter | Qt::SingleLine, lines[i]);
}
QString byteCount(uint64_t bytes) {
    char value[48];
    snprintf(value, sizeof(value), "%llu", (unsigned long long)bytes);
    return QString::fromLatin1(value);
}
QString mediaTime(unsigned milliseconds) {
    const unsigned seconds = milliseconds / 1000;
    char clock[32];
    snprintf(clock, sizeof(clock), "%u:%02u", seconds / 60, seconds % 60);
    return QString::fromLatin1(clock);
}
QString connectionCaption(const QString &stage) {
    static const char *labels[][2] = {
        {"Подготовка сети", "Подготовка сети"},
        {"Открытие доступа в сеть", "Доступ в сеть"},
        {"Определение адреса сервера", "Поиск сервера"},
        {"Соединение с сервером", "Соединение"},
        {"Соединение и защита TMME", "Соединение TMME"},
        {"Авторизация", "Авторизация"},
        {"Подключение к сеансу", "Начало сеанса"},
        {"Согласование протокола", "Протокол"},
        {"Получение контактов", "Контакты"},
        {"Подготовка контакт-листа", "Список контактов"},
        {"Повторное подключение…", "Переподключение"},
        {"Ожидание перед повторным подключением", "Ожидание повтора"},
        {"Переподключение", "Переподключение"},
        {"Подключено", "Подключено"},
    };
    for (unsigned i = 0; i < sizeof(labels) / sizeof(labels[0]); ++i)
        if (stage == QString::fromUtf8(labels[i][0]) || stage == uiText(labels[i][0]))
            return uiText(labels[i][1]);
    return stage;
}
QString singleLine(QString text, const QFontMetrics &metrics, int width) {
    text = text.left(128);
    for (unsigned i = 0; i < text.length(); ++i)
        if (text[i] == '\n' || text[i] == '\r')
            text[i] = QChar(' ');
    if (metrics.width(text) <= width)
        return text;
    while (!text.isEmpty() && metrics.width(text + "...") > width)
        text.truncate(text.length() - 1);
    return text + "...";
}
} // namespace

void Window::drawSplash(QPainter &p) {
    p.save();
    const QColor background(bodyColor(1)), ink(bodyColor(2));
    const QFontMetrics metrics(font());
    const int line = metrics.height() + 2;
    p.fillRect(rect(), background);
    p.setFont(font());
    p.setPen(ink);
    const int textWidth = std::max(1, width() - 16);
    const std::vector<QString> title =
        wrapped("TeleMotoMax " TMM_NATIVE_VERSION, metrics, textWidth, 2);
    drawLines(p, title, 8, 2, textWidth, line, Qt::AlignHCenter);
    if (settingFlag(settings_, "display_date")) {
        const time_t stamp =
            time(0) +
            (settingNumber(settings_, "timezone") + settingNumber(settings_, "daylight")) * 3600 +
            settingNumber(settings_, "time_offset_minutes") * 60;
        const struct tm *date = gmtime(&stamp);
        if (date) {
            char clock[32];
            strftime(clock, sizeof(clock), "%d.%m.%Y %H:%M", date);
            const char *days[] = {"Воскресенье", "Понедельник", "Вторник", "Среда",
                                  "Четверг",     "Пятница",     "Суббота"};
            const int top = 4 + title.size() * line;
            p.drawText(8, top, textWidth, line, Qt::AlignCenter | Qt::SingleLine, clock);
            p.drawText(8, top + line, textWidth, line, Qt::AlignCenter | Qt::SingleLine,
                       uiText(days[date->tm_wday]));
        }
    }
    if (splashLogo_.isNull())
        splashLogo_.load("logo.png");
    if (!splashLogo_.isNull())
        p.drawPixmap((width() - splashLogo_.width()) / 2, (height() - splashLogo_.height()) / 2,
                     splashLogo_);
    else
        p.drawText(8, height() / 2 - line / 2, textWidth, line, Qt::AlignCenter, "TeleMotoMax");

    // The same fullscreen bottom bar as Java; Cancel remains a key action.
    const QString stage =
        singleLine(locked_ ? uiText("Блокировка включена") : connectionCaption(connectionStage_),
                   metrics, std::max(1, width() - 28));
    const int barHeight = std::max(20, line) + 6;
    const int barTop = height() - barHeight;
    const int fill = locked_ ? width() : width() * std::min(100U, connectionProgress_) / 100;
    p.fillRect(0, barTop, width(), barHeight, palette().active().button());
    if (fill) {
        const QColor accent = palette().active().highlight();
        for (int y = 0; y < barHeight; ++y)
            p.fillRect(0, barTop + y, fill, 1,
                       accent.light(120 - 40 * y / std::max(1, barHeight - 1)));
    }
    const int sprite =
        statusIcon(connectionState_ == Event::Online ? settings_.getInt("status", 0) : 0xffffffffU);
    if (!statusIcons_.isNull())
        p.drawPixmap(4, barTop + (barHeight - 16) / 2, statusIcons_, sprite * 16, 0, 16, 16);
    p.setPen(palette().active().buttonText());
    p.drawText(24, barTop + 3, std::max(1, width() - 28), line, Qt::AlignCenter | Qt::SingleLine,
               stage);
    p.setClipRect(24, barTop, std::max(0, fill - 24), barHeight);
    p.setPen(palette().active().highlightedText());
    p.drawText(24, barTop + 3, std::max(1, width() - 28), line, Qt::AlignCenter | Qt::SingleLine,
               stage);
    p.setClipping(false);
    p.setPen(ink);
    if (locked_) {
        const bool hasPin = !settingValue(settings_, "lock_pin").empty();
        if (hasPin) {
            const int boxHeight = line * 4 + 16;
            const int top = (height() - boxHeight) / 2;
            p.fillRect(8, top, textWidth, boxHeight, background);
            p.drawRect(8, top, textWidth, boxHeight);
            QString stars;
            stars.fill('*', pin_.length());
            p.drawText(12, top + 4, width() - 24, line, Qt::AlignCenter,
                       uiText(pinWrong_ ? "Неверный PIN" : "Введите PIN"));
            p.drawText(12, top + line + 6, width() - 24, line, Qt::AlignCenter, stars);
            p.drawText(12, top + line * 2 + 8, width() - 24, line, Qt::AlignCenter,
                       uiText("*: стереть цифру"));
            p.drawText(12, top + line * 3 + 8, width() - 24, line, Qt::AlignCenter,
                       uiText("Назад: очистить"));
        } else {
            const std::vector<QString> hint =
                wrapped(uiText("Нажмите # для разблокировки"), metrics, textWidth, 2);
            drawLines(p, hint, 8, barTop - (hint.size() + 1) * line - 8, textWidth, line,
                      Qt::AlignHCenter);
        }
        if (unread()) {
            const int y = barTop - line - 3;
            if (!messageIcons_.isNull())
                p.drawPixmap(2, y + (line - 16) / 2, messageIcons_, 0, 0, 16, 16);
            p.drawText(22, y, width() - 24, line, Qt::AlignLeft | Qt::AlignVCenter,
                       "# " + QString::number(unread()));
        }
    }
    p.restore();
}

void Window::drawProgress(QPainter &p, const QString &details, const QString &status,
                          uint64_t bytes, uint64_t total) {
    p.save();
    const QColor ink(bodyColor(2));
    const QColor track(bodyColor(4));
    const QColor accent(bodyColor(3));
    const QColor border(bodyColor(8));
    const int left = 12, bodyTop = 34;
    const int banner = !notice_.isEmpty() ? 52 : !ticker_.isEmpty() ? 25 : 0;
    const int bodyBottom = height() - 32 - banner;
    const int textWidth = std::max(1, width() - 2 * left);
    p.setClipRect(0, 29, width(), std::max(1, height() - 56));
    p.setFont(QFont("Helvetica", 14));
    p.setPen(ink);
    QFontMetrics metrics(p.font());
    const int lineHeight = std::max(18, metrics.height() + 2);
    const std::vector<QString> statusLines = wrapped(status, metrics, textWidth, 2);
    const bool transfer = view().kind == View::Transfer;
    const int barHeight = 18;
    unsigned percent = 0;
    std::vector<QString> captionLines;
    if (total) {
        const uint64_t completed = std::min(bytes, total);
        percent = total <= uint64_t(-1) / 100
                      ? static_cast<unsigned>(completed * 100 / total)
                      : static_cast<unsigned>(completed / (total / 100 + (total % 100 != 0)));
        QString caption = QString::number(std::min(100U, percent)) + "%";
        if (transfer)
            caption += "  " + byteCount(bytes) + " / " + byteCount(total) + uiText(" байт");
        captionLines = wrapped(caption, metrics, textWidth, 2);
    } else if (bytes) {
        captionLines = wrapped(uiText("Получено: ") + byteCount(bytes) + uiText(" байт"), metrics,
                               textWidth, 2);
    }
    const int extra = total ? barHeight + captionLines.size() * lineHeight + 14
                            : captionLines.size() * lineHeight + 8;
    const unsigned detailLimit = std::max(
        1, std::min(6, (bodyBottom - bodyTop - int(statusLines.size()) * lineHeight - extra - 14) /
                           lineHeight));
    const std::vector<QString> detailLines = wrapped(details, metrics, textWidth, detailLimit);
    const int contentHeight = (detailLines.size() + statusLines.size()) * lineHeight + 14 + extra;
    int top = bodyTop + std::max(0, (bodyBottom - bodyTop - contentHeight) / 2);
    drawLines(p, detailLines, left, top, textWidth, lineHeight);
    top += detailLines.size() * lineHeight + 14;
    drawLines(p, statusLines, left, top, textWidth, lineHeight);
    top += statusLines.size() * lineHeight + 8;
    if (total) {
        p.fillRect(left, top, textWidth, barHeight, track);
        const int fill = static_cast<unsigned long>(textWidth - 2) * std::min(100U, percent) / 100;
        if (fill)
            p.fillRect(left + 1, top + 1, fill, barHeight - 2, accent);
        p.setPen(border);
        p.drawRect(left, top, textWidth, barHeight);
        top += barHeight + 6;
        p.setPen(ink);
        drawLines(p, captionLines, left, top, textWidth, lineHeight, Qt::AlignHCenter);
    } else if (!captionLines.empty())
        drawLines(p, captionLines, left, top, textWidth, lineHeight, Qt::AlignHCenter);
    p.restore();
}

void Window::drawPlayer(QPainter &p) {
    p.save();
    const int banner = !notice_.isEmpty() ? 52 : !ticker_.isEmpty() ? 25 : 0;
    const QRect body(0, 29, width(), std::max(1, height() - 56));
    p.setClipRect(body);
    if (view().context == "player-video") {
        // Java gives the complete Canvas to video. The Motorola video child
        // shares this body geometry; native softkeys already offer Back/Next.
        p.fillRect(body, Qt::black);
        p.restore();
        return;
    }
    // The audio Canvas owns its background, independently of chat wallpaper.
    p.fillRect(body, QColor(bodyColor(1)));
    const int left = 10, textWidth = std::max(1, width() - 2 * left);
    const QColor ink(bodyColor(2));
    const QColor accent(bodyColor(3));
    const QColor track(bodyColor(4));
    const QColor border(bodyColor(8));
    const bool finished = view().more;
    const unsigned elapsed = finished && playDuration_ ? playDuration_ : playPosition_;
    const QFont small("Helvetica", 14), clockFont("Helvetica", 18);
    const QFontMetrics smallMetrics(small), clockMetrics(clockFont);
    const int lineHeight = std::max(18, smallMetrics.height() + 2);
    const int clockHeight = std::max(22, clockMetrics.height() + 2);
    const QString status = uiText(finished ? "Проиграно" : paused_ ? "Пауза" : "Играет");
    const QString keys =
        uiText(finished ? "выбор — ещё раз, 0 — закрыть" : "выбор — пауза, 4 — сначала");
    const std::vector<QString> keyLines = wrapped(keys, smallMetrics, textWidth, 2);
    struct stat file;
    const bool hasSize = !playPath_.empty() && !stat(playPath_.c_str(), &file) &&
                         S_ISREG(file.st_mode) && file.st_size > 0;
    const int barHeight = 7;
    const int contentHeight = lineHeight + clockHeight + barHeight +
                              int(keyLines.size()) * lineHeight + (hasSize ? lineHeight : 0) + 26;
    const int bodyBottom = height() - 32 - banner;
    int top = 34 + std::max(0, (bodyBottom - 34 - contentHeight) / 2);
    p.setFont(small);
    p.setPen(ink);
    p.drawText(left, top, textWidth, lineHeight, Qt::AlignCenter | Qt::SingleLine, status);
    top += lineHeight + 4;
    p.setFont(clockFont);
    QString clock = mediaTime(elapsed);
    if (playDuration_)
        clock += " / " + mediaTime(playDuration_);
    p.drawText(left, top, textWidth, clockHeight, Qt::AlignCenter | Qt::SingleLine, clock);
    top += clockHeight + 6;
    p.fillRect(left, top, textWidth, barHeight, track);
    if (playDuration_) {
        const int fill = uint64_t(textWidth - 2) * std::min(elapsed, playDuration_) / playDuration_;
        if (fill)
            p.fillRect(left + 1, top + 1, fill, barHeight - 2, accent);
    }
    p.setPen(border);
    p.drawRect(left, top, textWidth, barHeight);
    top += barHeight + 8;
    p.setFont(small);
    p.setPen(ink);
    drawLines(p, keyLines, left, top, textWidth, lineHeight, Qt::AlignHCenter);
    top += keyLines.size() * lineHeight + 4;
    if (hasSize)
        p.drawText(left, top, textWidth, lineHeight, Qt::AlignCenter | Qt::SingleLine,
                   byteCount(file.st_size / 1024) + uiText(" КБ"));
    p.restore();
}

void Window::drawAttachmentDetails(QPainter &p) {
    p.save();
    p.setClipRect(8, 33, std::max(1, width() - 16), 104);
    p.setFont(QFont("Helvetica", 14));
    p.setPen(QColor(bodyColor(2)));
    QFontMetrics metrics(p.font());
    const int lineHeight = std::max(18, metrics.height() + 2);
    const unsigned count = std::max(1, 104 / lineHeight);
    drawLines(p, wrapped(view().details, metrics, std::max(1, width() - 16), count), 8, 33,
              std::max(1, width() - 16), lineHeight);
    p.restore();
}
} // namespace tmm
