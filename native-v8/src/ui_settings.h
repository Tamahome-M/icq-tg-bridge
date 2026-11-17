#ifndef TMM_UI_SETTINGS_H
#define TMM_UI_SETTINGS_H
#include "settings.h"
#include "client.h"
#include <vector>
namespace tmm {
struct SettingField {
    const char *section, *key, *label, *initial, *choices;
    int maximum;
    bool secret;
};
const std::vector<SettingField> &settingFields();
const SettingField *settingField(const std::string &key);
std::string settingValue(const Settings &, const std::string &key);
int settingNumber(const Settings &, const std::string &key);
bool settingFlag(const Settings &, const std::string &key);
bool settingIsToggle(const std::string &key);
const char *settingGroup(const std::string &key);
bool migrateJavaSettings(Settings &);
struct HotkeySetting {
    const char *action;
    const char *label;
};
const std::vector<HotkeySetting> &javaHotkeyActions();
std::string javaHotkeyDefault(const std::string &key);
const char *javaHotkeyLabel(const std::string &action);
bool validateSetting(const SettingField &, const std::string &value, std::string &error);
bool validateNetworkSettings(const Settings &, std::string &error);
std::map<unsigned, unsigned> mediaSettings(const Settings &);
ClientConfig clientSettings(const Settings &, const std::string &cache,
                            const std::vector<uint32_t> &quiet);
} // namespace tmm
#endif
