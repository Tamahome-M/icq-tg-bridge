#ifndef TMM_UI_LINKS_H
#define TMM_UI_LINKS_H
#include <string>
#include <vector>
namespace tmm {
// Java Util.parseMessageForURL: ordered, unique, Latin-1 URL characters.
std::vector<std::string> javaMessageUrls(const std::string &utf8);
// Display only: keep the original message/URL available for browser and quote actions.
std::string videoMessageText(const std::string &text, const std::string &browserUrl);
} // namespace tmm
#endif
