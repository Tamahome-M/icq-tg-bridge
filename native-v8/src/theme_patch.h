#ifndef TMM_THEME_PATCH_H
#define TMM_THEME_PATCH_H
#include <string>
namespace tmm {
// Rebuild only the selected skin's pack. Common firmware resources are never
// rewritten. Image payloads are streamed unchanged, including Motorola raw .k.
bool mergeStatusIcons(const std::string &base, const std::string &bundle, const std::string &output,
                      std::string &error);
bool patchStatusTheme(const std::string &config, const std::string &directory,
                      const std::string &bundle, bool restore, std::string &error);
} // namespace tmm
#endif
