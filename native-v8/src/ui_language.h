#ifndef TMM_UI_LANGUAGE_H
#define TMM_UI_LANGUAGE_H
#include <qstring.h>
#include <string>
namespace tmm {
void setUiLanguage(const std::string &);
QString uiText(const char *);
} // namespace tmm
#endif
