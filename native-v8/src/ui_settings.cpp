#include "ui_settings.h"
#include <stdlib.h>
#include <stdio.h>
#include <errno.h>
#include <limits.h>
#include <algorithm>
namespace tmm {
static const SettingField fields[] = {
    {"account", "uin", "UIN", "", "", 12, false},
    {"account", "password", "Пароль", "", "", 64, true},
    {"network", "host", "Имя сервера", "", "", 512, false},
    {"network", "port", "Порт", "5190", "", 65535, false},
    {"network", "startup_dns", "DNS при запуске", "0", "0=Выкл|1=Вкл", 0, false},
    {"network", "dns_server", "DNS-сервер", "1.1.1.1", "", 15, false},
    // Java's VM owns these two settings outside the MIDlet. A native client
    // must expose its own equivalent to obtain an APN on a fresh installation.
    {"network", "network", "Доступ в сеть", "auto",
     "auto=Автоматически|system=Системный маршрут|mobile=Мобильный профиль", 0, false},
    {"network", "network_profile", "Профиль Интернета", "", "", 256, false},
    {"network", "keepalive", "Поддерживать подключение?", "1", "0=Нет|1=Да", 0, false},
    {"network", "ping_seconds", "Интервал пингов, с", "120", "", 999, false},
    {"network", "missed_pings", "Пингов без ответа", "3", "1|2|3|4|5|6|7|8|9|10", 0, false},
    {"network", "auto_connect", "Подключаться автоматически?", "0", "0=Нет|1=Да", 0, false},
    {"network", "md5_login", "Безопасный логин", "1", "0=Нет|1=Да", 0, false},
    {"_native", "async_transfer", "Асинхронная передача", "0", "0=Нет|1=Да", 0, false},
    {"network", "auto_reconnect", "Переподключение", "1", "0=Нет|1=Да", 0, false},
    {"network", "reconnect_attempts", "Количество попыток подключения", "10", "", 99, false},
    {"network", "encryption", "Шифровать соединение", "0", "0=Нет|1=Да", 0, false},
    {"network", "psk", "Ключ / кодовая фраза", "", "", 64, true},
    {"interface", "lock_pin", "PIN блокировки (пусто — выкл.)", "", "", 8, true},
    {"interface", "flip_lock_minutes", "Блокировка после ухода в фон, мин (0 — выкл.)", "2", "",
     999, false},
    {"interface", "display_date", "Дата на заставке", "0", "0=Нет|1=Да", 0, false},
    {"interface", "fullscreen", "Полный экран", "0", "0=Нет|1=Да", 0, false},
    {"interface", "running_icon", "Значок запущенного приложения", "1",
     "1=Строка статуса (вместо BT/USB)|2=Экран ожидания|0=Нет", 0, false},
    {"interface", "mirror_menu", "'Зеркальные' меню", "0", "0=Нет|1=Да", 0, false},
    {"interface", "font_size", "Размер шрифта", "16", "12|14|16|18|20|22|24", 0, false},
    {"interface", "use_groups", "Группы контактов", "0", "0=Нет|1=Да", 0, false},
    {"interface", "hide_empty", "Скрывать пустые группы", "0", "0=Нет|1=Да", 0, false},
    {"interface", "hide_offline", "Скрывать отключившихся", "0", "0=Нет|1=Да", 0, false},
    {"interface", "show_deleted", "Показывать удаленные контакты", "0", "0=Нет|1=Да", 0, false},
    {"interface", "sort_by", "Сортировать контакт-лист", "status",
     "status=По статусу|name=По имени", 0, false},
    {"interface", "cp1251", "Win1251 кодировка", "1", "0=Нет|1=Да", 0, false},
    {"interface", "initial_caps", "Авторегистр", "1", "0=Нет|1=Да", 0, false},
    {"interface", "show_receipts", "Доставка и прочтение", "1", "0=Нет|1=Да", 0, false},
    {"interface", "save_history", "Сохранять локальную историю", "1", "0=Нет|1=Да", 0, false},
    {"interface", "server_history_count", "Сообщений в истории с сервера", "10", "", 100, false},
    {"interface", "chat_messages", "Сообщений в чате", "15", "", 100, false},
    {"interface", "chat_font_size", "Размер шрифта в чате", "14", "12|14|16|18|20|22|24", 0, false},
    {"interface", "show_icons", "Иконка", "1", "0=Нет|1=Да", 0, false},
    {"interface", "show_sender", "Ник", "0", "0=Нет|1=Да", 0, false},
    {"interface", "show_time", "Время", "1", "0=Нет|1=Да", 0, false},
    {"interface", "show_newlines", "Перевод строки", "0", "0=Нет|1=Да", 0, false},
    {"interface", "show_smileys", "Смайлики", "1", "0=Нет|1=Да", 0, false},
    {"interface", "full_editor", "Поле ввода текста без заголовка", "0", "0=Нет|1=Да", 0, false},
    {"interface", "light_seconds", "Время подсветки (сек)", "5", "", 99, false},
    {"interface", "manual_light", "Управлять подсветкой", "1", "0=Нет|1=Да", 0, false},
    {"interface", "caption_offset", "Смещение заголовка (%)", "0", "", 99, false},
    {"camera", "camera_encoding", "Формат снимка", "jpeg", "jpeg=jpeg", 0, false},
    {"camera", "camera_size", "Разрешение", "960x1280",
     "=как решит телефон|176x144|320x240|960x1280|480x640|640x480|240x320|160x120", 0, false},
    {"media", "photo_size", "Фото: размер", "",
     "=как в профиле моста|176x176|176x220|240x320|320x240|480x640|640x480", 0, false},
    {"media", "photo_quality", "Фото: качество JPEG", "0",
     "0=как в профиле моста|40|50|60|70|80|90|95", 0, false},
    {"media", "photo_kb", "Фото: не больше, КБ", "0", "0=как в профиле моста|20|40|60|100|150|250",
     0, false},
    {"media", "photo_rotate", "Фото боком", "0", "0=авто (широкий — боком)|1=всегда|2=никогда", 0,
     false},
    {"media", "video_size", "Видео: кадр", "",
     "=как в профиле моста|176x144|144x176|240x180|320x240|240x320|480x640|640x480", 0, false},
    {"media", "video_kbps", "Видео: битрейт, кбит/с", "0",
     "0=как в профиле моста|32|48|64|96|128|192|256|384", 0, false},
    {"media", "video_seconds", "Видео: длина, с", "0",
     "0=как в профиле моста|5|10|15|20|30|60|120|180|300", 0, false},
    {"media", "video_kb", "Видео: не больше, КБ", "0",
     "0=как в профиле моста|16|24|32|48|64|128|256|512", 0, false},
    {"media", "video_rotate", "Ролик боком", "0", "0=авто (широкий — боком)|1=всегда|2=никогда", 0,
     false},
    {"media", "voice_kbps10", "Голосовое: битрейт, кбит/с", "0",
     "0=как в профиле моста|48=4.8|52=5.2|59=5.9|67=6.7|74=7.4|80=8.0|102=10.2|122=12.2", 0, false},
    {"media", "voice_seconds", "Голосовое: длина, с", "0",
     "0=как в профиле моста|30|60|120|300|600", 0, false},
    {"media", "media_memory_kb", "Ролик в памяти, КБ (0 — по куче)", "0", "", 8192, false},
    {"telegram", "telegram_on", "Включена", "1", "0=Нет|1=Да", 0, false},
    {"telegram", "telegram_limit", "Чатов в списке (0 — все, пусто — по профилю)", "", "", 9999,
     false},
    {"max", "max_on", "Включена", "1", "0=Нет|1=Да", 0, false},
    {"max", "max_limit", "Чатов в списке (0 — все, пусто — по профилю)", "", "", 9999, false},
    {"express", "express_on", "Включена", "1", "0=Нет|1=Да", 0, false},
    {"express", "express_limit", "Чатов в списке (0 — все, пусто — по профилю)", "", "", 9999,
     false},
    {"notifications", "sound_unlocked", "Сообщения: обычный режим", "msg_low.mp3",
     "=Нет|tone=Сигнал|message.mp3|msg_low.mp3|tg.mp3|typing.mp3", 0, false},
    {"notifications", "volume_unlocked", "Громкость", "50", "0|10|20|30|40|50|60|70|80|90|100", 0,
     false},
    {"notifications", "vibration_unlocked", "Вибрация: обычный режим, с", "0",
     "0=Нет|100=0.1|200=0.2|500=0.5|1000=1|1500=1.5|2000=2", 0, false},
    {"notifications", "sound_locked", "Сообщения: при блокировке", "message.mp3",
     "=Нет|tone=Сигнал|message.mp3|msg_low.mp3|tg.mp3|typing.mp3", 0, false},
    {"notifications", "volume_locked", "Громкость", "50", "0|10|20|30|40|50|60|70|80|90|100", 0,
     false},
    {"notifications", "vibration_locked", "Вибрация: при блокировке, с", "0",
     "0=Нет|100=0.1|200=0.2|500=0.5|1000=1|1500=1.5|2000=2", 0, false},
    {"notifications", "typing_sound", "Оповещение о наборе", "tone",
     "=Нет|display=Только оповещение|tone=Сигнал|message.mp3|msg_low.mp3|tg.mp3|typing.mp3", 0,
     false},
    {"notifications", "typing_volume", "Громкость", "50", "0|10|20|30|40|50|60|70|80|90|100", 0,
     false},
    {"notifications", "disconnect_sound", "Обрыв связи", "1", "0=Нет|1=Три ноты", 0, false},
    {"notifications", "disconnect_volume", "Громкость", "50", "0|10|20|30|40|50|60|70|80|90|100", 0,
     false},
    {"notifications", "ticker", "Бегущая строка", "0", "0=Нет|1=Да", 0, false},
    {"timezone", "timezone", "Часовой пояс", "3",
     "-12=GMT-12:00|-11=GMT-11:00|-10=GMT-10:00|-9=GMT-9:00|-8=GMT-8:00|-7=GMT-7:00|-6=GMT-6:00|-5="
     "GMT-5:00|-4=GMT-4:00|-3=GMT-3:00|-2=GMT-2:00|-1=GMT-1:00|0=GMT+0:00|1=GMT+1:00|2=GMT+2:00|3="
     "GMT+3:00|4=GMT+4:00|5=GMT+5:00|6=GMT+6:00|7=GMT+7:00|8=GMT+8:00|9=GMT+9:00|10=GMT+10:00|11="
     "GMT+11:00|12=GMT+12:00|13=GMT+13:00",
     0, false},
    {"timezone", "local_hour", "Местное время", "", "", 23, false},
    {"timezone", "daylight", "Летнее время", "0", "0=Стд время|1=Летнее время", 0, false},
    // Preserved native implementation preferences, not extra Java menu items.
    {"_native", "history_count", "Локальная история", "200", "", 999, false},
    {"_native", "language", "Язык", "ru", "ru=Русский|en=English", 0, false},
    {"_native", "reconnect_seconds", "Интервал повторов, с", "5", "", 600, false},
    {"_native", "external_preview", "Текст на внешнем экране", "0",
     "0=Только число сообщений|1=Имя и текст", 0, false},
    {"_native", "time_offset_minutes", "Поправка времени, минут", "0", "", 1440, false}};
const std::vector<SettingField> &settingFields() {
    static std::vector<SettingField> v(fields, fields + sizeof(fields) / sizeof(fields[0]));
    return v;
}
const SettingField *settingField(const std::string &key) {
    const std::vector<SettingField> &v = settingFields();
    for (size_t i = 0; i < v.size(); ++i)
        if (key == v[i].key)
            return &v[i];
    return 0;
}
std::string settingValue(const Settings &s, const std::string &key) {
    const SettingField *f = settingField(key);
    // Honor the old hidden zero-retention setting until the new switch is used.
    const char *initial = f ? f->initial : "";
    if (key == "save_history" && s.get("history_count") == "0")
        initial = "0";
    return s.get(key, initial);
}
int settingNumber(const Settings &s, const std::string &key) {
    return atoi(settingValue(s, key).c_str());
}
bool settingFlag(const Settings &s, const std::string &key) {
    return settingValue(s, key) == "1";
}
bool settingIsToggle(const std::string &key) {
    const char *keys[] = {"keepalive",    "auto_connect", "md5_login",     "auto_reconnect",
                          "encryption",   "display_date", "fullscreen",    "mirror_menu",
                          "use_groups",   "hide_empty",   "hide_offline",  "show_deleted",
                          "cp1251",       "initial_caps", "show_receipts", "save_history",
                          "show_icons",   "show_sender",  "show_time",     "show_newlines",
                          "show_smileys", "full_editor",  "manual_light",  "telegram_on",
                          "max_on",       "express_on",   "ticker"};
    for (unsigned i = 0; i < sizeof(keys) / sizeof(keys[0]); ++i)
        if (key == keys[i])
            return true;
    return false;
}
const char *settingGroup(const std::string &key) {
    if (key == "display_date")
        return "Разное";
    if (key == "use_groups")
        return "Контакт-лист";
    if (key == "cp1251")
        return "Настройки чата";
    if (key == "chat_font_size")
        return "Формат сообщения";
    if (key == "md5_login")
        return "Настройки подключения";
    if (key == "telegram_on" || key == "max_on" || key == "express_on")
        return "Сеть моста";
    if (key == "ticker")
        return "Разное";
    return "";
}
bool migrateJavaSettings(Settings &s) {
    const bool existing = !s.get("host").empty() || !s.get("uin").empty() ||
                          !s.get("accounts").empty() || !s.get("font_size").empty() ||
                          !s.get("chat_font_size").empty() ||
                          s.get("status", "missing") != "missing";
    // The global credentials are the currently selected account. Only very
    // old files lacking them need the selected slot as a fallback. Preserve
    // an intentionally empty password and erase every obsolete credential.
    if (s.get("uin", "missing") == "missing") {
        int selected = std::max(0, std::min(4, s.getInt("account_index", 0)));
        char prefix[32];
        snprintf(prefix, sizeof(prefix), "account.%d.", selected);
        if (s.get(std::string(prefix) + "uin", "missing") != "missing") {
            s.set("uin", s.get(std::string(prefix) + "uin"));
            s.set("password", s.get(std::string(prefix) + "password"));
        }
    }
    bool changed = false;
    if (s.get("font_size").empty() && !s.get("small_font").empty()) {
        s.setInt("font_size", s.getBool("small_font", false) ? 14 : 16);
        changed = true;
    }
    if (s.get("chat_font_size").empty() && !s.get("chat_small_font").empty()) {
        s.setInt("chat_font_size", s.getBool("chat_small_font", true) ? 14 : 16);
        changed = true;
    }
    const char *removed[] = {"theme",           "background_kind", "background_file",
                             "background_mode", "colored_text",    "small_font",
                             "chat_small_font"};
    for (unsigned i = 0; i < sizeof(removed) / sizeof(removed[0]); ++i)
        changed = s.remove(removed[i]) || changed;
    changed = s.removePrefix("account.") || changed;
    changed = s.remove("accounts") || changed;
    changed = s.remove("account_index") || changed;
    if (s.get("java_ui_version") == "1")
        return changed;
    if (existing) {
        // Old native files stored only changed fields. Materialize previous
        // defaults before switching the defaults for newly installed clients.
        static const char *previous[][2] = {
            {"ping_seconds", "110"},    {"reconnect_attempts", "5"}, {"media_memory_kb", "8192"},
            {"camera_size", "640x480"}, {"display_date", "1"},       {"fullscreen", "1"},
            {"use_groups", "1"},        {"hide_empty", "1"},         {"show_deleted", "1"},
            {"show_sender", "1"},       {"show_newlines", "1"},      {"chat_messages", "100"},
            {"volume_unlocked", "10"},  {"volume_locked", "70"},     {"vibration_locked", "500"},
            {"typing_sound", ""},       {"typing_volume", "10"},     {"disconnect_volume", "30"},
            {"manual_light", "0"},      {"light_seconds", "15"},     {"font_size", "16"},
            {"chat_font_size", "16"}};
        for (unsigned i = 0; i < sizeof(previous) / sizeof(previous[0]); ++i)
            if (s.get(previous[i][0], "missing") == "missing")
                s.set(previous[i][0], previous[i][1]);
        // Both old editor choices displayed the title; height is now always
        // full screen and this Java flag controls only the title visibility.
        s.setBool("full_editor", false);
    }
    if (!s.get("caption_offset").empty())
        s.setInt("caption_offset",
                 std::min(99, std::max(0, (s.getInt("caption_offset") * 100 + 120) / 240)));
    s.set("java_ui_version", "1");
    return true;
}
const std::vector<HotkeySetting> &javaHotkeyActions() {
    static const HotkeySetting entries[] = {{"none", "Нет"},
                                            {"info", "Информация"},
                                            {"compose", "Сообщение"},
                                            {"groups", "Показ./скр. группы"},
                                            {"offline-toggle", "Показ./скр. отключенных"},
                                            {"settings", "Настройки"},
                                            {"main", "Меню"},
                                            {"lock", "Блокировка"},
                                            {"local-info", "Инфо о клиенте"},
                                            {"fullscreen", "Полный экран"},
                                            {"silent", "Откл. звук"},
                                            {"light", "ВКЛ/ВЫКЛ подсветки"},
                                            {"up", "Вверх"},
                                            {"down", "Вниз"},
                                            {"top", "В начало"},
                                            {"bottom", "В конец"},
                                            {"page-up", "На стр. вверх"},
                                            {"page-down", "На стр. вниз"},
                                            {"next-chat", "След. чат"},
                                            {"previous-chat", "Предыдущ. чат"},
                                            {"select", "Выбрать"}};
    static const std::vector<HotkeySetting> result(entries,
                                                   entries + sizeof(entries) / sizeof(entries[0]));
    return result;
}
std::string javaHotkeyDefault(const std::string &key) {
    if (key == "0")
        return "info";
    if (key == "1")
        return "top";
    if (key == "2")
        return "up";
    if (key == "3")
        return "page-up";
    if (key == "5")
        return "select";
    if (key == "7")
        return "bottom";
    if (key == "8")
        return "down";
    if (key == "9")
        return "page-down";
    if (key == "*")
        return "light";
    if (key == "#")
        return "lock";
    if (key == "call")
        return "compose";
    return "none";
}
const char *javaHotkeyLabel(const std::string &action) {
    const std::vector<HotkeySetting> &entries = javaHotkeyActions();
    for (size_t i = 0; i < entries.size(); ++i)
        if (action == entries[i].action)
            return entries[i].label;
    if (action == "connect")
        return "Подключение";
    if (action == "history")
        return "История сообщений";
    if (action == "minimize")
        return "Свернуть";
    return "Сохраненное действие";
}
static bool numeric(const std::string &s) {
    if (s.empty())
        return true;
    size_t i = s[0] == '-' ? 1 : 0;
    if (i == s.size())
        return false;
    for (; i < s.size(); ++i)
        if (s[i] < '0' || s[i] > '9')
            return false;
    return true;
}
bool validateSetting(const SettingField &f, const std::string &v, std::string &e) {
    std::string key = f.key;
    if (*f.choices) {
        std::string choices = f.choices;
        bool found = false;
        for (size_t at = 0; at <= choices.size();) {
            size_t end = choices.find('|', at), equal = choices.find('=', at);
            if (end == std::string::npos)
                end = choices.size();
            if (equal == std::string::npos || equal > end)
                equal = end;
            if (choices.substr(at, equal - at) == v)
                found = true;
            if (end == choices.size())
                break;
            at = end + 1;
        }
        bool sound = key == "sound_unlocked" || key == "sound_locked" || key == "typing_sound";
        bool custom =
            sound && !v.empty() && v.size() <= 128 && v.find(char(47)) == std::string::npos &&
            v.find(char(92)) == std::string::npos && v.find(char(13)) == std::string::npos &&
            v.find(char(10)) == std::string::npos;
        if (!found && !custom) {
            e = "Значение отсутствует в списке";
            return false;
        }
    }
    if (v.size() > 4096) {
        e = "Слишком длинное значение";
        return false;
    }
    if (key == "uin" || key == "lock_pin") {
        if (!numeric(v) || v.find('-') != std::string::npos || (int)v.size() > f.maximum) {
            e = "Введите цифры допустимой длины";
            return false;
        }
        if (key == "uin" && !v.empty()) {
            errno = 0;
            char *end = 0;
            unsigned long n = strtoul(v.c_str(), &end, 10);
            if (errno == ERANGE || *end || !n || n > 4294967295UL) {
                e = "Некорректный UIN";
                return false;
            }
        }
    } else if (f.maximum && key != "host" && key != "password" && key != "psk" &&
               key != "dns_server" && key != "network_profile") {
        char *end = 0;
        long n = strtol(v.c_str(), &end, 10);
        if (!numeric(v) || n > f.maximum || (n < 0 && key != "time_offset_minutes")) {
            e = "Число вне допустимого диапазона";
            return false;
        }
        if ((key == "port" || key == "server_history_count" || key == "chat_messages" ||
             key == "ping_seconds") &&
            n == 0) {
            e = key == "port" ? "Порт должен быть от 1 до 65535" : "Число должно быть больше нуля";
            return false;
        }
    } else if (f.maximum && (int)v.size() > f.maximum) {
        e = "Слишком длинное значение";
        return false;
    }
    if (key == "host" && v.find_first_of("/\r\n\t ") != std::string::npos) {
        e = "Укажите имя сервера или IP без URL";
        return false;
    }
    if (key == "dns_server") {
        unsigned parts = 0;
        size_t at = 0;
        while (at < v.size()) {
            size_t end = v.find('.', at);
            if (end == std::string::npos)
                end = v.size();
            std::string part = v.substr(at, end - at);
            if (part.empty() || part.size() > 3 || !numeric(part) ||
                part.find('-') != std::string::npos || atoi(part.c_str()) > 255) {
                e = "Нужен IPv4 адрес DNS-сервера";
                return false;
            }
            ++parts;
            at = end + 1;
        }
        if (parts != 4 || v.empty() || v[v.size() - 1] == '.') {
            e = "Нужен IPv4 адрес DNS-сервера";
            return false;
        }
    }
    return true;
}
bool validateNetworkSettings(const Settings &s, std::string &error) {
    if (settingValue(s, "host").empty()) {
        error = "Укажите сервер моста в настройках сети";
        return false;
    }
    const char *keys[] = {"host",       "port", "network",    "network_profile",
                          "encryption", "psk",  "startup_dns"};
    for (unsigned i = 0; i < sizeof(keys) / sizeof(keys[0]); ++i)
        if (!validateSetting(*settingField(keys[i]), settingValue(s, keys[i]), error))
            return false;
    if (settingValue(s, "network") == "mobile" && settingValue(s, "network_profile").empty()) {
        error = "Выберите профиль Интернета в настройках сети";
        return false;
    }
    if (settingFlag(s, "encryption") && settingValue(s, "psk").empty()) {
        error = "Укажите общий ключ PSK или отключите шифрование";
        return false;
    }
    if (settingFlag(s, "startup_dns") &&
        !validateSetting(*settingField("dns_server"), settingValue(s, "dns_server"), error))
        return false;
    return true;
}
static unsigned limit(const Settings &s, const char *k) {
    std::string v = settingValue(s, k);
    return v.empty() ? 0 : (atoi(v.c_str()) == 0 ? 65535 : atoi(v.c_str()));
}
std::map<unsigned, unsigned> mediaSettings(const Settings &s) {
    std::map<unsigned, unsigned> m;
    m[1] = m[2] = m[4] = m[5] = 0;
    const char *keys[] = {"photo_quality", "video_kbps",    "video_seconds", "video_rotate",
                          "voice_kbps10",  "voice_seconds", "photo_kb",      "video_kb"};
    unsigned ids[] = {3, 6, 7, 8, 9, 10, 11, 12};
    for (unsigned i = 0; i < 8; ++i)
        m[ids[i]] = settingNumber(s, keys[i]);
    for (unsigned i = 0; i < 2; ++i) {
        std::string v = settingValue(s, i ? "video_size" : "photo_size");
        size_t x = v.find('x');
        if (x != std::string::npos) {
            m[i ? 4 : 1] = atoi(v.substr(0, x).c_str());
            m[i ? 5 : 2] = atoi(v.substr(x + 1).c_str());
        }
    }
    m[13] = limit(s, "telegram_limit");
    m[14] = settingFlag(s, "express_on") ? 1 : 2;
    m[15] = settingFlag(s, "max_on") ? 1 : 2;
    m[16] = settingFlag(s, "telegram_on") ? 1 : 2;
    m[17] = limit(s, "max_limit");
    m[18] = limit(s, "express_limit");
    m[19] = 131;
    m[20] = 3;
    return m;
}
ClientConfig clientSettings(const Settings &s, const std::string &cache,
                            const std::vector<uint32_t> &quiet) {
    ClientConfig c;
    c.host = settingValue(s, "host");
    c.port = settingNumber(s, "port");
    c.uin = settingValue(s, "uin");
    c.password = settingValue(s, "password");
    c.psk = settingValue(s, "psk");
    c.encryption = settingFlag(s, "encryption");
    c.startupDns = settingFlag(s, "startup_dns");
    c.dnsServer = settingValue(s, "dns_server");
    c.autoReconnect = settingFlag(s, "auto_reconnect");
    c.reconnectSeconds = settingNumber(s, "reconnect_seconds");
    c.network = settingValue(s, "network");
    c.profile = settingValue(s, "network_profile");
    c.md5Login = settingFlag(s, "md5_login");
    c.ssiEncoding = settingFlag(s, "cp1251") ? "CP1251" : "UTF-8";
    c.reconnectAttempts = settingNumber(s, "reconnect_attempts");
    c.maxMediaBytes = settingNumber(s, "media_memory_kb")
                          ? settingNumber(s, "media_memory_kb") * 1024
                          : 8 * 1024 * 1024;
    c.pingSeconds = settingFlag(s, "keepalive") ? settingNumber(s, "ping_seconds") : 0;
    c.missedPings = settingNumber(s, "missed_pings");
    c.cacheDir = cache;
    c.media = mediaSettings(s);
    c.quietChats = quiet;
    c.status = s.getInt("status", 0);
    return c;
}
} // namespace tmm
