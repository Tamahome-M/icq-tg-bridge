#include "window.h"
#include "ui_language.h"
#include "ui_settings.h"
#include <qpainter.h>
#include <qfontmetrics.h>
#include <algorithm>
#include <stdio.h>
#include <sys/stat.h>

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
} // namespace

void Window::drawProgress(QPainter &p, const QString &details, const QString &status,
                          uint64_t bytes, uint64_t total) {
    p.save();
    const QColor ink(interfaceColor(settings_, 2));
    const QColor track(interfaceColor(settings_, 4));
    const QColor accent(interfaceColor(settings_, 3));
    const QColor border(interfaceColor(settings_, 8));
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
    p.fillRect(body, QColor(interfaceColor(settings_, 1)));
    const int left = 10, textWidth = std::max(1, width() - 2 * left);
    const QColor ink(interfaceColor(settings_, 2));
    const QColor accent(interfaceColor(settings_, 3));
    const QColor track(interfaceColor(settings_, 4));
    const QColor border(interfaceColor(settings_, 8));
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
    p.setPen(QColor(interfaceColor(settings_, 2)));
    QFontMetrics metrics(p.font());
    const int lineHeight = std::max(18, metrics.height() + 2);
    const unsigned count = std::max(1, 104 / lineHeight);
    drawLines(p, wrapped(view().details, metrics, std::max(1, width() - 16), count), 8, 33,
              std::max(1, width() - 16), lineHeight);
    p.restore();
}
} // namespace tmm
