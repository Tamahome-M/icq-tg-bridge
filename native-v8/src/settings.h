#ifndef TMM_NATIVE_SETTINGS_H
#define TMM_NATIVE_SETTINGS_H
#include <string>
#include <map>
#include <stddef.h>
namespace tmm {
class Settings {
    std::map<std::string, std::string> values_;
    std::string path_;
    bool writable_;

  public:
    Settings();
    bool load(const std::string &path, std::string &error);
    bool save(std::string &error) const;
    void reset(); // only after an explicit user reset; preserves the file path
    std::string get(const std::string &key, const std::string &fallback = "") const;
    int getInt(const std::string &key, int fallback = 0) const;
    bool getBool(const std::string &key, bool fallback = false) const;
    void set(const std::string &key, const std::string &value);
    void setInt(const std::string &key, int value);
    void setBool(const std::string &key, bool value);
    const std::string &path() const {
        return path_;
    }
};
typedef Settings Config;
// All writes use an owned temporary file + fsync + rename, preserving the
// previous valid file on failure. No server-controlled path is used here.
bool ensureDirectory(const std::string &path, std::string &error);
bool atomicWrite(const std::string &path, const std::string &data, std::string &error);
bool readBounded(const std::string &path, std::string &data, size_t maxBytes);
} // namespace tmm
#endif
