#include "window.h"
#include "ui_language.h"
#include "ui_files.h"
#include <sys/stat.h>
#include <set>
#include <stdlib.h>
namespace tmm {
static QString u(const char *s) {
    return uiText(s);
}
static QString u(const std::string &s) {
    return QString::fromUtf8(s.c_str());
}
static std::vector<std::string> phoneRoots() {
    std::vector<std::string> roots;
    const char *configured = getenv("MYSTUFF_DATA_PATH");
    if (configured && *configured)
        roots.push_back(configured);
    roots.push_back("/ezxlocal/download/mystuff");
    roots.push_back("/ezxlocal");
    roots.push_back("/mmc/mmca1");
    roots.push_back("/mnt/mmc/mmca1");
    roots.push_back("/");
    return roots;
}
static bool isPhoneRoot(const std::string &directory) {
    std::vector<std::string> roots = phoneRoots();
    for (size_t i = 0; i < roots.size(); ++i) {
        std::string canonical;
        if (readableMediaDirectory(roots[i], canonical) && canonical == directory)
            return true;
    }
    return directory == "/";
}
static std::string parentDirectory(const std::string &directory) {
    if (isPhoneRoot(directory))
        return "";
    size_t slash = directory.find_last_of('/');
    return slash == std::string::npos || !slash ? "/" : directory.substr(0, slash);
}
void Window::files(const std::string &directory, const std::string &action) {
    View v(View::Files, u("Root"));
    v.directory = directory;
    v.context = action;
    push(v);
    loadFiles();
}
void Window::loadFiles() {
    View &v = view();
    v.rows.clear();
    v.selected = v.top = 0;
    if (v.directory.empty()) {
        // Java's FileSystem2 opens Root and shows the available root names.
        // Native paths differ from JSR-75 aliases, but selection/back are the
        // same operations and the visible list has no extra storage menu.
        v.title = u("Root");
        std::set<std::string> seen;
        std::vector<std::string> roots = phoneRoots();
        for (size_t i = 0; i < roots.size(); ++i) {
            std::string canonical;
            if (!readableMediaDirectory(roots[i], canonical) || !seen.insert(canonical).second)
                continue;
            v.rows.push_back(
                Row(u(roots[i] == "/" ? "/" : roots[i] + "/"), "directory:" + canonical));
        }
        if (v.rows.empty())
            v.rows.push_back(Row(u("/"), "directory:/"));
        update();
        return;
    }
    std::string canonical, error;
    std::vector<MediaFileEntry> entries;
    bool truncated = false;
    bool loaded = listMediaDirectory(v.directory, canonical, entries, truncated, error);
    if (loaded)
        v.directory = canonical;
    v.rows.push_back(Row(u("../"), "directory:" + parentDirectory(v.directory)));
    v.title =
        v.directory == "/" ? u("Root") : u(v.directory.substr(v.directory.find_last_of('/') + 1));
    if (!loaded) {
        info(u(error));
        update();
        return;
    }
    if (v.context == "save-media")
        v.rows.push_back(Row(u("Сохранить здесь: ") + u(downloadName_), "save-here"));
    unsigned visible = 0;
    for (size_t i = 0; i < entries.size(); ++i) {
        const MediaFileEntry &entry = entries[i];
        if (entry.directory) {
            v.rows.push_back(Row(u(entry.name + "/"), "directory:" + entry.path));
            ++visible;
        } else if (v.context != "save-media") {
            v.rows.push_back(Row(u(entry.name), "file-select"));
            ++visible;
        }
    }
    if (truncated)
        info(u("Показана только часть папки: слишком много файлов"));
    else if (!visible)
        info(u(v.context == "save-media" ? "В папке нет вложенных папок" : "Папка пуста"));
    update();
}
} // namespace tmm
