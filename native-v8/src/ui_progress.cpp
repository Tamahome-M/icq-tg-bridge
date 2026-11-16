#include "window.h"
#include "ui_language.h"
#include "ui_settings.h"
#include <qpainter.h>
#include <qfontmetrics.h>
#include <algorithm>
#include <stdio.h>

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
} // namespace

void Window::drawProgress(QPainter &p, const QString &details, const QString &status,
                          uint64_t bytes, uint64_t total) {
    p.save();
    const bool dark = settingValue(settings_, "theme") == "dark";
    const QColor ink = dark ? QColor(Qt::white) : QColor(Qt::black);
    const QColor track = dark ? QColor(64, 68, 72) : QColor(210, 216, 222);
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
            p.fillRect(left + 1, top + 1, fill, barHeight - 2, QColor(75, 123, 159));
        p.setPen(ink);
        p.drawRect(left, top, textWidth, barHeight);
        top += barHeight + 6;
        drawLines(p, captionLines, left, top, textWidth, lineHeight, Qt::AlignHCenter);
    } else if (!captionLines.empty())
        drawLines(p, captionLines, left, top, textWidth, lineHeight, Qt::AlignHCenter);
    p.restore();
}

void Window::drawAttachmentDetails(QPainter &p) {
    p.save();
    p.setClipRect(8, 33, std::max(1, width() - 16), 104);
    p.setFont(QFont("Helvetica", 14));
    p.setPen(palette().active().foreground());
    QFontMetrics metrics(p.font());
    const int lineHeight = std::max(18, metrics.height() + 2);
    const unsigned count = std::max(1, 104 / lineHeight);
    drawLines(p, wrapped(view().details, metrics, std::max(1, width() - 16), count), 8, 33,
              std::max(1, width() - 16), lineHeight);
    p.restore();
}
} // namespace tmm
