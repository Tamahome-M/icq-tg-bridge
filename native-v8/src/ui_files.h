#ifndef TMM_UI_FILES_H
#define TMM_UI_FILES_H
#include <string>
namespace tmm {
bool imageDimensions(const std::string &, unsigned &, unsigned &, std::string &);
bool copyMediaFile(const std::string &, const std::string &, std::string &);
} // namespace tmm
#endif
