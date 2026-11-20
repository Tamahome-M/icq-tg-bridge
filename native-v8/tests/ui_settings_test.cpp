#include "ui_settings.h"
#include <assert.h>
#include <stdio.h>
using namespace tmm;
int main() {
    Settings s;
    std::string error;
    assert(!validateNetworkSettings(s, error));
    s.set("host", "bridge.example");
    assert(validateNetworkSettings(s, error)); // Auto may use an existing system route.
    s.set("network", "mobile");
    assert(!validateNetworkSettings(s, error));
    s.set("network_profile", "Internet");
    assert(validateNetworkSettings(s, error));
    s.setBool("encryption", true);
    assert(!validateNetworkSettings(s, error));
    s.set("psk", "1234");
    assert(validateNetworkSettings(s, error));
    s.setBool("startup_dns", true);
    s.set("dns_server", "invalid");
    assert(!validateNetworkSettings(s, error));
    s.setBool("startup_dns", false);
    assert(validateNetworkSettings(s, error)); // Irrelevant DNS setting is ignored.
    s.set("port", "0");
    assert(!validateNetworkSettings(s, error));
    s.set("port", "5190");
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
    assert(c.media[12] == 512 && c.media[21] == 2);
    s.set("video_rotate", "0");
    assert(mediaSettings(s)[8] == 1); // Auto enables source-aware rotation at the bridge.
    s.set("video_rotate", "2");
    assert(mediaSettings(s)[8] == 2);
    s.set("video_kb", "256");
    assert(mediaSettings(s)[12] == 256);
    s.set("video_kb", "0");
    s.set("media_memory_kb", "0");
    assert(mediaSettings(s)[12] == 8192); // Native disk-backed transfer budget, not Java heap.
    s.set("video_seconds", "3600");
    s.set("video_kbps", "1024");
    s.set("video_kb", "524288");
    assert(validateSetting(*settingField("video_seconds"), "3600", error));
    assert(!validateSetting(*settingField("video_seconds"), "3601", error));
    assert(validateSetting(*settingField("video_kbps"), "1024", error));
    assert(validateSetting(*settingField("video_kb"), "524288", error));
    assert(!validateSetting(*settingField("video_kb"), "1048576", error));
    const std::map<unsigned, unsigned> large = mediaSettings(s);
    assert(large.find(7)->second == 3600 && large.find(6)->second == 1024 &&
           large.find(12)->second == 65535 && large.find(22)->second == 512 &&
           large.find(23)->second == 1);
    assert(videoLimitKB(s) == 524288);
    s.set("video_kb", "8192");
    assert(!mediaSettings(s).count(22));
    s.set("video_kb", "0");
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
    // Java form values do not reuse native history retention or font storage.
    Settings defaults;
    assert(settingNumber(defaults, "server_history_count") == 10);
    assert(settingNumber(defaults, "history_count") == 200);
    assert(settingFlag(defaults, "save_history") && settingIsToggle("save_history"));
    assert(std::string(settingField("save_history")->section) == "interface");
    Settings disabled;
    disabled.setInt("history_count", 0);
    assert(!settingFlag(disabled, "save_history"));
    disabled.setBool("save_history", true);
    assert(settingFlag(disabled, "save_history"));
    assert(settingNumber(defaults, "chat_messages") == 15);
    assert(!validateSetting(*settingField("server_history_count"), "0", error));
    assert(validateSetting(*settingField("server_history_count"), "100", error));
    assert(!validateSetting(*settingField("server_history_count"), "101", error));
    assert(validateSetting(*settingField("photo_quality"), "95", error));
    assert(validateSetting(*settingField("camera_size"), "", error));
    const char *removed[] = {"theme",           "background_kind", "background_mode",
                             "background_file", "colored_text",    "small_font",
                             "chat_small_font"};
    for (unsigned i = 0; i < sizeof(removed) / sizeof(removed[0]); ++i)
        assert(!settingField(removed[i]));
    assert(!settingIsToggle("font_size") && !settingIsToggle("chat_font_size"));
    const char *sizes[] = {"12", "14", "16", "18", "20", "22", "24"};
    for (unsigned i = 0; i < sizeof(sizes) / sizeof(sizes[0]); ++i) {
        assert(validateSetting(*settingField("font_size"), sizes[i], error));
        assert(validateSetting(*settingField("chat_font_size"), sizes[i], error));
    }
    assert(!validateSetting(*settingField("font_size"), "0", error));
    assert(!validateSetting(*settingField("chat_font_size"), "1000", error));
    assert(validateSetting(*settingField("typing_sound"), "display", error));
    assert(validateSetting(*settingField("sound_locked"), "custom.mp3", error));
    assert(!validateSetting(*settingField("sound_locked"), "../outside.mp3", error));
    assert(settingNumber(s, "running_icon") == 1 && !settingIsToggle("running_icon"));
    for (unsigned icon = 0; icon <= 2; ++icon) {
        s.setInt("running_icon", icon);
        assert(validateSetting(*settingField("running_icon"), s.get("running_icon"), error));
    }
    assert(!validateSetting(*settingField("running_icon"), "3", error));
    assert(settingIsToggle("show_receipts") && settingIsToggle("telegram_on"));
    assert(!settingIsToggle("startup_dns") && !settingIsToggle("sort_by"));
    assert(std::string(settingField("async_transfer")->section) == "_native");
    assert(!settingField("account.2.uin") && !settingField("account.2.password"));
    s.setBool("cp1251", false);
    assert(clientSettings(s, "", quiet).ssiEncoding == "UTF-8");
    s.setBool("cp1251", true);
    assert(clientSettings(s, "", quiet).ssiEncoding == "CP1251");
    // Existing native custom sizes/fonts/history survive a one-time migration.
    Settings previous;
    previous.setInt("font_size", 18);
    previous.setInt("chat_font_size", 14);
    previous.setInt("history_count", 500);
    previous.setInt("caption_offset", 24);
    previous.set("background_file", "/outside/custom.png");
    previous.set("background_mode", "tile");
    assert(migrateJavaSettings(previous));
    assert(previous.getInt("font_size") == 18 && previous.getInt("chat_font_size") == 14);

    assert(previous.getInt("caption_offset") == 10);
    assert(previous.getInt("history_count") == 500 &&
           settingNumber(previous, "server_history_count") == 10);
    for (unsigned i = 0; i < sizeof(removed) / sizeof(removed[0]); ++i)
        assert(previous.get(removed[i], "missing") == "missing");
    Settings javaFonts;
    javaFonts.set("java_ui_version", "1");
    javaFonts.setBool("small_font", true);
    javaFonts.setBool("chat_small_font", false);
    javaFonts.set("theme", "dark");
    javaFonts.set("background_file", "old.png");
    assert(migrateJavaSettings(javaFonts));
    assert(javaFonts.getInt("font_size") == 14 && javaFonts.getInt("chat_font_size") == 16);
    for (unsigned i = 0; i < sizeof(removed) / sizeof(removed[0]); ++i)
        assert(javaFonts.get(removed[i], "missing") == "missing");
    assert(!migrateJavaSettings(javaFonts));
    assert(previous.getInt("volume_locked") == 70 && previous.getInt("chat_messages") == 100);
    assert(!settingFlag(previous, "full_editor"));
    assert(!migrateJavaSettings(previous) && previous.getInt("caption_offset") == 10);
    Settings selected;
    selected.set("java_ui_version", "1");
    selected.setInt("accounts", 3);
    selected.setInt("account_index", 2);
    selected.set("uin", "345678");
    selected.set("password", "");
    selected.set("account.0.uin", "123456");
    selected.set("account.0.password", "first");
    selected.set("account.2.uin", "345678");
    selected.set("account.2.password", "old-password");
    selected.set("account.99.password", "obsolete");
    assert(migrateJavaSettings(selected));
    assert(selected.get("uin") == "345678" && selected.get("password", "missing").empty());
    assert(selected.get("accounts", "missing") == "missing" &&
           selected.get("account_index", "missing") == "missing" &&
           selected.get("account.0.password", "missing") == "missing" &&
           selected.get("account.2.uin", "missing") == "missing" &&
           selected.get("account.99.password", "missing") == "missing");
    assert(!migrateJavaSettings(selected));
    Settings slots;
    slots.setInt("accounts", 2);
    slots.setInt("account_index", 1);
    slots.set("account.0.uin", "123456");
    slots.set("account.1.uin", "234567");
    slots.set("account.1.password", "selected-password");
    assert(migrateJavaSettings(slots));
    assert(slots.get("uin") == "234567" && slots.get("password") == "selected-password");
    assert(slots.get("account.1.password", "missing") == "missing");
    Settings fresh;
    assert(migrateJavaSettings(fresh));
    assert(settingNumber(fresh, "volume_locked") == 50 &&
           settingNumber(fresh, "chat_messages") == 15);
    assert(settingNumber(fresh, "ping_seconds") == 120);
    assert(javaHotkeyActions().size() == 21);
    assert(javaHotkeyDefault("0") == "info" && javaHotkeyDefault("*") == "light");
    assert(javaHotkeyDefault("#") == "lock" && javaHotkeyDefault("4") == "none");
    puts("UI settings: defaults, choices, single account and font migration, obsolete visuals "
         "removed, wire mapping PASS");
}
