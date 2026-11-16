#include "window.h"
#include "ui_language.h"
#include "ui_files.h"
#include <dirent.h>
#include <sys/stat.h>
#include <set>
namespace tmm {
static QString u(const char *s) {
    return uiText(s);
}
static QString u(const std::string &s) {
    return QString::fromUtf8(s.c_str());
}
static std::string parentDirectory(const std::string &path) {
    size_t slash = path.find_last_of('/');
    return slash == std::string::npos || !slash ? "/" : path.substr(0, slash);
}
static bool additionalStorage(const std::string &path) {
    // Firmware aliases /mmc/mmca1 to the internal phone memory. Real mounted
    // cards can also be empty; an unused, empty mount-point is not a storage.
    struct stat current, parent;
    if (!stat(path.c_str(), &current) && !stat(parentDirectory(path).c_str(), &parent) &&
        current.st_dev != parent.st_dev)
        return true;
    DIR *directory = opendir(path.c_str());
    if (!directory)
        return false;
    bool content = false;
    struct dirent *entry;
    while ((entry = readdir(directory))) {
        std::string name = entry->d_name;
        if (name != "." && name != "..") {
            content = true;
            break;
        }
    }
    closedir(directory);
    return content;
}
void Window::files(const std::string &directory, const std::string &action) {
    View v(View::Files, u("Файлы"));
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
        v.title = u("Выберите память");
        std::set<std::string> seen;
        seen.insert("/");
        std::string canonical;
        if (readableMediaDirectory("/ezxlocal/download/mystuff", canonical)) {
            v.rows.push_back(Row(u("Память телефона"), "directory:" + canonical));
            seen.insert(canonical);
        }
        const char *cards[] = {"/mmc/mmca1", "/mnt/mmc/mmca1"};
        unsigned count = 0;
        for (unsigned i = 0; i < sizeof(cards) / sizeof(cards[0]); ++i)
            if (readableMediaDirectory(cards[i], canonical) && !seen.count(canonical) &&
                additionalStorage(canonical)) {
                v.rows.push_back(
                    Row(u(count++ ? "Другая память" : "Дополнительная память"),
                        "directory:" + canonical));
                seen.insert(canonical);
            }
        v.rows.push_back(Row(u("Файловая система"), "directory:/"));
        update();
        return;
    }
    std::string canonical, error;
    std::vector<MediaFileEntry> entries;
    bool truncated = false;
    bool loaded = listMediaDirectory(v.directory, canonical, entries, truncated, error);
    if (loaded)
        v.directory = canonical;
    if (v.directory != "/")
        v.rows.push_back(Row(u("На уровень выше"), "directory:" + parentDirectory(v.directory)));
    v.rows.push_back(Row(u("Выбрать память"), "directory:"));
    if (!loaded) {
        // Keep this picker usable even when media disappears or a folder is
        // inaccessible. Never retain stale file rows with the failed path.
        v.title = u("Файлы");
        info(u(error));
        update();
        return;
    }
    if (v.directory == "/")
        v.title = u("Файловая система");
    else if (v.directory == "/ezxlocal/download/mystuff")
        v.title = u("Память телефона");
    else
        v.title = u(v.directory.substr(v.directory.find_last_of('/') + 1));
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
