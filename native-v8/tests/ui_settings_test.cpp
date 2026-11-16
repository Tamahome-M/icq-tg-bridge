#include "ui_settings.h"
#include <assert.h>
#include <stdio.h>
using namespace tmm;
int main() {
    Settings s;
    std::string error;
    const std::vector<SettingField> &fields = settingFields();
    for (size_t i = 0; i < fields.size(); ++i) {
        if (!validateSetting(fields[i], fields[i].initial, error)) {
            fprintf(stderr, "invalid default %s: %s\n", fields[i].key, error.c_str());
            return 1;
        }
    }
    s.set("uin", "123456");
    s.set("host", "bridge.example");
    s.set("port", "5191");
    s.set("network", "mobile");
    s.set("network_profile", "Internet");
    s.setBool("md5_login", false);
    s.setBool("encryption", true);
    s.set("psk", "1234");
    s.setInt("media_memory_kb", 512);
    s.setInt("reconnect_attempts", 8);
    s.set("video_size", "320x240");
    s.set("video_kbps", "96");
    s.set("video_rotate", "1");
    s.set("telegram_limit", "0");
    s.set("max_limit", "12");
    s.setBool("express_on", false);
    std::vector<uint32_t> quiet;
    quiet.push_back(1000011);
    ClientConfig c = clientSettings(s, "/tmp/cache", quiet);
    assert(c.host == "bridge.example" && c.port == 5191 && c.uin == "123456");
    assert(c.network == "mobile" && c.profile == "Internet");
    assert(!c.md5Login && c.encryption && c.psk == "1234");
    assert(c.maxMediaBytes == 512 * 1024 && c.reconnectAttempts == 8 && c.quietChats == quiet);
    assert(c.media[4] == 320 && c.media[5] == 240 && c.media[6] == 96 && c.media[8] == 1);
    assert(c.media[13] == 65535 && c.media[14] == 2 && c.media[17] == 12);
    s.set("video_size", "");
    s.set("photo_size", "");
    std::map<unsigned, unsigned> m = mediaSettings(s);
    assert(m[1] == 0 && m[2] == 0 && m[4] == 0 && m[5] == 0);
    assert(!validateSetting(*settingField("port"), "0", error));
    assert(validateSetting(*settingField("uin"), "4294967295", error));
    assert(!validateSetting(*settingField("uin"), "4294967296", error));
    assert(!validateSetting(*settingField("uin"), "4295090752", error));
    assert(!validateSetting(*settingField("uin"), "0", error));
    assert(!validateSetting(*settingField("lock_pin"), "12a4", error));
    assert(!validateSetting(*settingField("lock_pin"), "123456789", error));
    assert(validateSetting(*settingField("lock_pin"), "", error));
    assert(validateSetting(*settingField("dns_server"), "1.1.1.1", error));
    assert(!validateSetting(*settingField("dns_server"), "1.1.1.999", error));
    assert(!validateSetting(*settingField("dns_server"), "example.org", error));
    assert(!validateSetting(*settingField("dns_server"), "1.1.1.1.", error));
    assert(!validateSetting(*settingField("video_kbps"), "9999", error));
    assert(!validateSetting(*settingField("camera_encoding"), "png", error));
    assert(validateSetting(*settingField("camera_size"), "960x1280", error));
    puts("UI settings defaults, wire mapping, validation passed");
}
