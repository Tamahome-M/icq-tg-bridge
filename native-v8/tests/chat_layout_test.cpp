#include "zapplication_v8.h"
#include "chat_layout.h"
#include <qfontmetrics.h>
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
using namespace tmm;
static QString u(const char *s) {
    return QString::fromUtf8(s);
}
int main(int argc, char **argv) {
    if (!getenv("V8_QWS_LOCAL_ONLY"))
        return 3;
    ZApplication app(argc, argv, QApplication::GuiServer);
    const QString header = formatChatHeader(u("Анна"), 1700000000, true, true, false, 180);
    assert(header == u("Анна (01:13): "));
    assert(formatChatHeader(u("Я"), 1700000000, true, false, false, 0) == u("Я: "));
    assert(formatChatHeader(u("Я"), 0, true, true, true, 0).isEmpty());
    assert(formatChatHeader(u("Я"), 1700000000, false, false, false, 0).isEmpty());
    ChatText parts = splitChatText(header + u("Привет\nСледующая строка"), header, false);
    assert(parts.header == header && parts.body == u("Привет\nСледующая строка") && !parts.newLine);
    ChatText history = splitChatText(u("[17.11 12:05] Борис: История"), "", true, true);
    assert(history.header == u("[17.11 12:05] Борис: ") && history.body == u("История") &&
           history.newLine);
    assert(splitChatText(u("[17.11 12:05] Текст: тело"), "", false).header.isEmpty());
    assert(splitChatText(u("[ошибка] Имя: тело"), "", false, true).header.isEmpty());
    assert(splitChatText(u("URL: http://server:8080/path"), "", false, true).header.isEmpty());
    ChatText separated = splitChatText(header + u("\nтекст"), header, false);
    assert(separated.newLine && separated.body == u("текст"));
    const QFont font = QApplication::font();
    ChatLayout inlineText = layoutChatText(parts, font, 1000);
    assert(inlineText.runs.size() >= 3 && inlineText.runs[0].header && !inlineText.runs[1].header &&
           inlineText.runs[0].y == inlineText.runs[1].y &&
           inlineText.runs[1].x >= inlineText.runs[0].width);
    ChatLayout newLine = layoutChatText(separated, font, 1000, 17);
    assert(newLine.runs.size() == 2 && newLine.runs[0].x == 17 && newLine.runs[1].x == 0 &&
           newLine.runs[1].y > newLine.runs[0].y);
    const int glyph = QFontMetrics(font).width("W");
    ChatText token;
    token.body = "WWWWWWWWWWWWWW";
    ChatLayout wrapped = layoutChatText(token, font, glyph * 6, glyph * 2);
    assert(wrapped.runs.size() == 3);
    assert(wrapped.runs[0].x == glyph * 2 && wrapped.runs[0].y == 0 &&
           wrapped.runs[0].text == "WWWW");
    assert(wrapped.runs[1].x == 0 && wrapped.runs[1].text == "WWWWWW");
    assert(wrapped.runs[2].x == 0 && wrapped.runs[2].text == "WWWW");
    parts.body += u(" https://example.test/оченьдлинноеназваниебезпробелов/abcdefghijk");
    for (int width = 25; width <= 210; width += 37) {
        ChatLayout layout = layoutChatText(parts, font, width);
        for (size_t i = 0; i < layout.runs.size(); ++i) {
            const ChatRun &run = layout.runs[i];
            assert(run.x >= 0 && run.y >= 0 && run.x + run.width <= width);
            assert(run.y + layout.lineHeight <= layout.height);
        }
        assert(layout.height >= layout.lineHeight * 2);
    }
    QColor incoming = chatHeaderColor(false, QColor(255, 255, 255)),
           outgoing = chatHeaderColor(true, QColor(255, 255, 255));
    assert(incoming.red() == 255 && outgoing.blue() == 255 && incoming != outgoing);
    incoming = chatHeaderColor(false, QColor(0, 0, 128));
    outgoing = chatHeaderColor(true, QColor(0, 0, 128));
    assert(incoming.green() > 100 && outgoing.green() > 100 && incoming != outgoing);
    const QColor lightSelection = chatSelectionColor(QColor(255, 255, 255), QColor(0, 0, 0));
    const QColor darkSelection = chatSelectionColor(QColor(0, 0, 0), QColor(255, 255, 255));
    assert(lightSelection.red() == lightSelection.green() &&
           lightSelection.green() == lightSelection.blue());
    assert(lightSelection.red() >= 220 && lightSelection.red() < 255);
    assert(darkSelection.red() == darkSelection.green() &&
           darkSelection.green() == darkSelection.blue());
    assert(darkSelection.red() > 0 && darkSelection.red() < 40);
    puts("CHAT LAYOUT PASS: Java headers, history dates, separate bold/color spans, line breaks, "
         "narrow wrapping and theme contrast");
    return 0;
}
