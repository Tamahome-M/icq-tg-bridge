// Filesystem boundary adapter for QEMU-user only. This old Qt build enumerates
// no .km files on the host filesystem and silently falls back to English.
// Open the real RU/EN firmware files explicitly, using its own parser. Do not
// replace the keyboard engine, field, language switch or status events.
#include <qvaluelist.h>
#include <qmap.h>
#include <qstring.h>
#include <assert.h>
#include <stdio.h>
namespace ZKbGlobal {
struct ZKbLangContext {
    int id;
    QMap<unsigned short, QString> mapping;
    unsigned int flags;
};
} // namespace ZKbGlobal
class ZKbConfig {
  public:
    static void getLangContext(QValueList<ZKbGlobal::ZKbLangContext> &);
    static void readLangContext(QValueList<ZKbGlobal::ZKbLangContext> &, const QString &,
                                const QString &, QString);
};
void ZKbConfig::getLangContext(QValueList<ZKbGlobal::ZKbLangContext> &contexts) {
    assert(sizeof(ZKbGlobal::ZKbLangContext) == 12);
    contexts.clear();
    const char *codes[] = {"ru", "en-gb"};
    for (unsigned i = 0; i < 2; ++i)
        readLangContext(contexts, QString("/usr/language/inputmethods/iTap/") + codes[i] + ".km",
                        QString(codes[i]), QString("flags"));
    assert(contexts.count() == 2);
    fprintf(stderr, "KEYS fixture: loaded real RU/EN .km files explicitly\n");
}
