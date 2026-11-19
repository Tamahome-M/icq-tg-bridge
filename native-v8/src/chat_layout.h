#ifndef TMM_CHAT_LAYOUT_H
#define TMM_CHAT_LAYOUT_H
#include <qstring.h>
#include <qfont.h>
#include <qcolor.h>
#include <stdint.h>
#include <vector>
namespace tmm {
struct ChatText {
    QString header, body;
    bool newLine;
    ChatText() : newLine(false) {}
};
struct ChatRun {
    QString text;
    int x, y, width;
    bool header;
};
struct ChatLayout {
    std::vector<ChatRun> runs;
    int height, lineHeight;
    ChatLayout() : height(0), lineHeight(0) {}
};
QString formatChatHeader(const QString &sender, uint32_t time, bool showSender, bool showTime,
                         bool showDate, int offsetMinutes);
ChatText splitChatText(const QString &formatted, const QString &generatedHeader, bool newLine,
                       bool serverHistory = false);
ChatLayout layoutChatText(const ChatText &, const QFont &, int width);
QColor chatHeaderColor(bool outgoing, const QColor &background);
} // namespace tmm
#endif
