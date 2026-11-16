#include "network_profile.h"

#include <dlfcn.h>
#include <cstring>
#include <algorithm>

namespace tmm {
bool loadInternetProfiles(std::vector<std::string> &profiles, std::string &error) {
    profiles.clear();
    error.clear();
    void *library = dlopen("libnapi.so", RTLD_NOW | RTLD_LOCAL);
    int (*maximum)() = 0;
    int (*list)(char (*)[64], unsigned int *) = 0;
    void *maxAddress = library ? dlsym(library, "NAPI_GetMaxProfiles") : 0;
    void *listAddress = library ? dlsym(library, "NAPI_ListAllProfile") : 0;
    if (!maxAddress || !listAddress || sizeof(maximum) != sizeof(maxAddress) ||
        sizeof(list) != sizeof(listAddress)) {
        if (library)
            dlclose(library);
        error = "Не найдена служба профилей Motorola";
        return false;
    }
    std::memcpy(&maximum, &maxAddress, sizeof(maximum));
    std::memcpy(&list, &listAddress, sizeof(list));
    // SAedition: 64-byte name slots, count is capacity on entry and total on exit.
    // No NAPI_Init/OpenLink here: only read existing profile names, with no GUI.
    int capacity = maximum();
    char names[128][64];
    std::memset(names, 0, sizeof(names));
    unsigned int count = capacity > 0 ? static_cast<unsigned int>(capacity) : 0;
    int result = capacity > 0 && capacity <= 128 ? list(names, &count) : -1;
    dlclose(library);
    if (result < 0 || count > 128 || count > static_cast<unsigned int>(capacity)) {
        error = "Не удалось прочитать интернет-профили";
        return false;
    }
    for (unsigned int i = 0; i < count; ++i) {
        if (!std::memchr(names[i], 0, sizeof(names[i])))
            continue;
        std::string name(names[i]);
        if (!name.empty() && name.size() < 64 && name.find_first_of("\r\n") == std::string::npos &&
            std::find(profiles.begin(), profiles.end(), name) == profiles.end())
            profiles.push_back(name);
    }
    if (profiles.empty()) {
        error = "В телефоне нет доступных интернет-профилей";
        return false;
    }
    return true;
}

} // namespace tmm
