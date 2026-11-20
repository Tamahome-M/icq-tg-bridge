#include "chat_layout.h"
#include <qfontmetrics.h>
#include <algorithm>
#include <time.h>
namespace tmm {
QString formatChatHeader(const QString &sender, uint32_t stamp, bool showSender, bool showTime,
                         bool showDate, int offsetMinutes) {
    if (!stamp)
        return QString::null; // Server history already contains its date/author.
    QString header = showSender ? sender : QString::null;
    if (showTime) {
        time_t time = int64_t(stamp) + int64_t(offsetMinutes) * 60;
        const struct tm *parts = gmtime(&time);
        if (parts) {
            char when[32];
            strftime(when, sizeof when, showDate ? "%d.%m %H:%M" : "%H:%M", parts);
            if (!header.isEmpty())
                header += " ";
            header += "(" + QString::fromLatin1(when) + ")";
        }
    }
    if (!header.isEmpty())
        header += ": ";
    return header;
}
ChatText splitChatText(const QString &formatted, const QString &generatedHeader, bool newLine,
                       bool serverHistory) {
    ChatText result;
    unsigned length = 0;
    if (!generatedHeader.isEmpty() && formatted.left(generatedHeader.length()) == generatedHeader)
        length = generatedHeader.length();
    else if (serverHistory && formatted.length() > 14 && formatted[0] == '[' &&
             formatted[3] == '.' && formatted[6] == ' ' && formatted[9] == ':' &&
             formatted[12] == ']') {
        // BART's [dd.mm hh:mm] author: text. Do not interpret an arbitrary
        // colon in a message body as a sender, or manufacture an epoch date.
        bool date = true;
        const unsigned digits[] = {1, 2, 4, 5, 7, 8, 10, 11};
        for (unsigned i = 0; i < sizeof digits / sizeof digits[0]; ++i)
            date = date && formatted[digits[i]].isDigit();
        const int colon = formatted.find(": ", 14), line = formatted.find('\n');
        if (date && colon >= 14 && colon < 160 && (line < 0 || colon < line))
            length = colon + 2;
    }
    result.header = formatted.left(length);
    result.body = formatted.mid(length);
    result.newLine = length && newLine;
    if (length && !result.body.isEmpty() && result.body[0] == '\n') {
        result.newLine = true;
        result.body = result.body.mid(1);
    }
    return result;
}
namespace {
class Wrapper {
    ChatLayout &layout_;
    int width_, x_, y_;
    bool fresh_;
    void nextLine() {
        x_ = 0;
        y_ += layout_.lineHeight;
        fresh_ = true;
    }
    void append(const QString &text, int width, bool header) {
        if (text.isEmpty())
            return;
        if (!layout_.runs.empty() && !fresh_ && layout_.runs.back().header == header) {
            layout_.runs.back().text += text;
            layout_.runs.back().width += width;
        } else {
            ChatRun run;
            run.text = text;
            run.x = x_;
            run.y = y_;
            run.width = width;
            run.header = header;
            layout_.runs.push_back(run);
        }
        x_ += width;
        fresh_ = false;
    }

  public:
    Wrapper(ChatLayout &layout, int width)
        : layout_(layout), width_(std::max(1, width)), x_(0), y_(0), fresh_(true) {}
    void text(const QString &text, const QFontMetrics &metrics, bool header) {
        for (unsigned i = 0; i < text.length();) {
            if (text[i] == '\n') {
                nextLine();
                ++i;
                continue;
            }
            if (text[i].isSpace()) {
                QString space = text[i] == '\t' ? "    " : " ";
                int width = metrics.width(space);
                if (x_ + width <= width_)
                    append(space, width, header);
                else
                    nextLine();
                ++i;
                continue;
            }
            unsigned end = i + 1;
            while (end < text.length() && !text[end].isSpace())
                ++end;
            QString word = text.mid(i, end - i);
            int width = metrics.width(word);
            if (x_ && x_ + width > width_)
                nextLine();
            if (width <= width_) {
                append(word, width, header);
                i = end;
                continue;
            }
            // Long URLs/filenames also wrap, without splitting a UTF-16 pair.
            while (i < end) {
                unsigned count = 1;
                unsigned code = text[i].unicode();
                if (code >= 0xd800 && code <= 0xdbff && i + 1 < end &&
                    text[i + 1].unicode() >= 0xdc00 && text[i + 1].unicode() <= 0xdfff)
                    count = 2;
                QString character = text.mid(i, count);
                width = metrics.width(character);
                if (x_ && x_ + width > width_)
                    nextLine();
                append(character, width, header);
                i += count;
            }
        }
    }
    void separate() {
        if (x_)
            nextLine();
    }
    void finish() {
        layout_.height = y_ + layout_.lineHeight;
    }
};
} // namespace
ChatLayout layoutChatText(const ChatText &text, const QFont &font, int width) {
    ChatLayout layout;
    QFont bold = font;
    bold.setBold(true);
    QFontMetrics normalMetrics(font), boldMetrics(bold);
    layout.lineHeight = std::max(normalMetrics.height(), boldMetrics.height());
    Wrapper wrapper(layout, width);
    wrapper.text(text.header, boldMetrics, true);
    if (text.newLine)
        wrapper.separate();
    wrapper.text(text.body, normalMetrics, false);
    wrapper.finish();
    return layout;
}
QColor chatHeaderColor(bool outgoing, const QColor &background) {
    const int light =
        (background.red() * 299 + background.green() * 587 + background.blue() * 114) / 1000;
    // Java uses red for incoming and blue for outgoing. Keep those semantic
    // colors readable on the system theme's dark/selected backgrounds too.
    if (light < 128)
        return outgoing ? QColor(128, 200, 255) : QColor(255, 144, 144);
    return outgoing ? QColor(0, 0, 255) : QColor(255, 0, 0);
}
QColor chatSelectionColor(const QColor &background, const QColor &text) {
    const int base =
        (background.red() * 299 + background.green() * 587 + background.blue() * 114) / 1000;
    const int ink = (text.red() * 299 + text.green() * 587 + text.blue() * 114) / 1000;
    // Java's default message cursor is a pale tint, not a full saturated menu
    // highlight. Use neutral grey with a small contrast against either theme.
    const int shade = (base * 9 + ink) / 10;
    return QColor(shade, shade, shade);
}
} // namespace tmm
