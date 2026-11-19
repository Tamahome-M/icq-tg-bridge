#include "theme_patch.h"
#include <cstdio>
#include <string>
int main(int argc, char **argv) {
    std::string error;
    bool ok = false;
    if (argc == 5 && std::string(argv[1]) == "merge")
        ok = tmm::mergeStatusIcons(std::string(argv[2]) == "-" ? "" : argv[2], argv[3], argv[4],
                                   error);
    else if (argc == 5)
        ok = tmm::patchStatusTheme(argv[2], argv[3], argv[4], std::string(argv[1]) == "restore",
                                   error);
    if (!ok)
        std::fprintf(stderr, "%s\n", error.c_str());
    return ok ? 0 : 1;
}
