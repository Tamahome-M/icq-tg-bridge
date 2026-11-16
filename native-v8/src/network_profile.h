#ifndef TMM_NETWORK_PROFILE_H
#define TMM_NETWORK_PROFILE_H
#include <string>
#include <vector>
// Read names through C NAPI. Selection stays in Yam's existing main window.
namespace tmm {
bool loadInternetProfiles(std::vector<std::string> &profiles, std::string &error);
}
#endif
