#include "ui_settings.h"
#include <stdlib.h>
#include <errno.h>
#include <limits.h>
namespace tmm {
static const SettingField fields[] = {
    {"account", "uin", "UIN", "", "", 10, false},
    {"account", "password", "Пароль", "", "", 64, true},
    {"network", "host", "Сервер", "", "", 512, false},
    {"network", "port", "Порт", "5190", "", 65535, false},
    {"network", "network", "Доступ в сеть", "auto",
     "auto=Автоматически|system=Системный маршрут|mobile=Мобильный профиль", 0, false},
    {"network", "network_profile", "Профиль Интернета", "", "", 256, false},
    {"network", "md5_login", "Вход по MD5", "1", "0=Нет|1=Да", 0, false},
    {"network", "keepalive", "Пинги", "1", "0=Нет|1=Да", 0, false},
    {"network", "ping_seconds", "Интервал пингов, с", "110", "", 999, false},
    {"network", "missed_pings", "Пропущено пингов до обрыва", "3", "1|2|3|4|5|6|7|8|9|10", 0,
     false},
    {"network", "auto_connect", "Подключаться при запуске", "0", "0=Нет|1=Да", 0, false},
    {"network", "auto_reconnect", "Переподключаться", "1", "0=Нет|1=Да", 0, false},
    {"network", "reconnect_attempts", "Быстрых повторов", "5", "", 99, false},
    {"network", "reconnect_seconds", "Интервал повторов, с", "5", "", 600, false},
    {"network", "encryption", "Шифрование", "0", "0=Нет|1=Да", 0, false},
    {"network", "psk", "Общий ключ PSK", "", "", 64, true},
    {"network", "startup_dns", "DNS при запуске", "0", "0=Системный DNS|1=Один запрос при запуске",
     0, false},
    {"network", "dns_server", "DNS-сервер", "1.1.1.1", "", 15, false},
    {"telegram", "telegram_on", "Telegram включён", "1", "0=Нет|1=Да", 0, false},
    {"telegram", "telegram_limit", "Чатов: пусто — мост, 0 — все", "", "", 9999, false},
    {"max", "max_on", "MAX включён", "1", "0=Нет|1=Да", 0, false},
    {"max", "max_limit", "Чатов: пусто — мост, 0 — все", "", "", 9999, false},
    {"express", "express_on", "eXpress включён", "1", "0=Нет|1=Да", 0, false},
    {"express", "express_limit", "Чатов: пусто — мост, 0 — все", "", "", 9999, false},
    {"media", "photo_size", "Фото: размер", "",
     "=Мост|176x176|176x220|240x320|320x240|480x640|640x480", 0, false},
    {"media", "photo_quality", "Фото: качество", "0", "0=Мост|20|30|40|50|60|70|80|90", 0, false},
    {"media", "photo_kb", "Фото: максимум КБ", "0", "0=Мост|20|40|60|100|150|250", 0, false},
    {"media", "photo_rotate", "Фото: поворот", "0", "0=Авто|1=90°|2=Нет", 0, false},
    {"media", "video_size", "Видео: размер", "",
     "=Мост|176x144|144x176|240x180|320x240|240x320|480x640|640x480", 0, false},
    {"media", "video_kbps", "Видео: кбит/с", "0", "0=Мост|32|48|64|96|128|192|256|384", 0, false},
    {"media", "video_seconds", "Видео: секунды", "0", "0=Мост|5|10|15|20|30|60|120|180|300", 0,
     false},
    {"media", "video_kb", "Видео: максимум КБ", "0", "0=Мост|16|24|32|48|64|128|256|512", 0, false},
    {"media", "video_rotate", "Видео: поворот", "0", "0=Авто|1=90°|2=Нет", 0, false},
    {"media", "voice_kbps10", "Голос: кбит/с", "0",
     "0=Мост|48=4.8|52=5.2|59=5.9|67=6.7|74=7.4|80=8.0|102=10.2|122=12.2", 0, false},
    {"media", "voice_seconds", "Голос: секунды", "0", "0=Мост|30|60|120|300|600", 0, false},
    {"media", "media_memory_kb", "Предел загрузки, КБ (0 — авто)", "8192", "", 65536, false},
    {"camera", "camera_size", "Камера: размер", "640x480",
     "960x1280|480x640|640x480|320x240|240x320|160x120", 0, false},
    {"camera", "camera_encoding", "Камера: формат", "jpeg", "jpeg=JPEG", 0, false},
    {"interface", "lock_pin", "PIN блокировки (пусто — #)", "", "", 8, true},
    {"interface", "flip_lock_minutes", "Блокировка после закрытия, мин (0 — нет)", "2", "", 999,
     false},
    {"interface", "display_date", "Показывать дату", "1", "0=Нет|1=Да", 0, false},
    {"interface", "fullscreen", "Полный экран", "1", "0=Нет|1=Да", 0, false},
    {"interface", "mirror_menu", "Поменять местами софт-клавиши", "0", "0=Нет|1=Да", 0, false},
    {"interface", "font_size", "Размер шрифта", "16", "12|14|16|18|20|22", 0, false},
    {"interface", "language", "Язык", "ru", "ru=Русский|en=English", 0, false},
    {"interface", "use_groups", "Группы контактов", "1", "0=Нет|1=Да", 0, false},
    {"interface", "hide_empty", "Скрыть пустые группы", "1", "0=Нет|1=Да", 0, false},
    {"interface", "hide_offline", "Скрыть оффлайн без непрочитанных", "0", "0=Нет|1=Да", 0, false},
    {"interface", "show_deleted", "Показывать удалённые контакты", "1", "0=Нет|1=Да", 0, false},
    {"interface", "sort_by", "Сортировка", "status", "status=Статус|name=Имя", 0, false},
    {"interface", "caption_offset", "Смещение заголовка", "0", "", 30, false},
    {"chat", "chat_font_size", "Шрифт чата", "16", "12|14|16|18|20|22", 0, false},
    {"chat", "show_icons", "Значки сообщений", "1", "0=Нет|1=Да", 0, false},
    {"chat", "show_sender", "Имя автора", "1", "0=Нет|1=Да", 0, false},
    {"chat", "show_time", "Время сообщения", "1", "0=Нет|1=Да", 0, false},
    {"chat", "show_newlines", "Перенос строки после имени", "1", "0=Нет|1=Да", 0, false},
    {"chat", "colored_text", "Цветной текст сообщений", "1", "0=Нет|1=Да", 0, false},
    {"chat", "show_smileys", "Смайлы", "1", "0=Нет|1=Да", 0, false},
    {"chat", "show_receipts", "Доставка и прочтение", "1", "0=Нет|1=Да", 0, false},
    {"chat", "initial_caps", "Заглавная буква в редакторе", "1", "0=Нет|1=Да", 0, false},
    {"chat", "full_editor", "Редактор на весь экран", "1", "0=Нет|1=Да", 0, false},
    {"chat", "history_count", "Сообщений локальной истории", "200", "", 999, false},
    {"chat", "chat_messages", "Сообщений в открытом чате", "100", "", 999, false},
    {"notifications", "sound_unlocked", "Звук: открыто", "msg_low.mp3",
     "=Нет|tone=Сигнал|message.mp3|msg_low.mp3|tg.mp3|typing.mp3", 0, false},
    {"notifications", "volume_unlocked", "Громкость: открыто", "10",
     "0|10|20|30|40|50|60|70|80|90|100", 0, false},
    {"notifications", "vibration_unlocked", "Вибрация: открыто", "0",
     "0=Нет|100=0.1 с|200=0.2 с|500=0.5 с|1000=1 с|1500=1.5 с|2000=2 с", 0, false},
    {"notifications", "sound_locked", "Звук: блокировка/крышка", "message.mp3",
     "=Нет|tone=Сигнал|message.mp3|msg_low.mp3|tg.mp3|typing.mp3", 0, false},
    {"notifications", "volume_locked", "Громкость: блокировка/крышка", "70",
     "0|10|20|30|40|50|60|70|80|90|100", 0, false},
    {"notifications", "vibration_locked", "Вибрация: блокировка/крышка", "500",
     "0=Нет|100=0.1 с|200=0.2 с|500=0.5 с|1000=1 с|1500=1.5 с|2000=2 с", 0, false},
    {"notifications", "typing_sound", "Звук: печатает", "",
     "=Нет|tone=Сигнал|typing.mp3|msg_low.mp3|tg.mp3", 0, false},
    {"notifications", "typing_volume", "Громкость: печатает", "10",
     "0|10|20|30|40|50|60|70|80|90|100", 0, false},
    {"notifications", "disconnect_sound", "Звук отключения", "1", "0=Нет|1=Три ноты", 0, false},
    {"notifications", "disconnect_volume", "Громкость отключения", "30",
     "0|10|20|30|40|50|60|70|80|90|100", 0, false},
    {"notifications", "ticker", "Бегущая строка", "0", "0=Нет|1=Да", 0, false},
    {"notifications", "external_preview", "Текст на внешнем экране", "0",
     "0=Только число сообщений|1=Имя и текст", 0, false},
    {"theme", "theme", "Цветовая схема", "light",
     "light=Светлая|dark=Тёмная|blue=Синяя|green=Зелёная", 0, false},
    {"background", "background_file", "Фоновая картинка", "", "", 4096, false},
    {"background", "background_mode", "Размещение фона", "fit",
     "fit=Вписать|stretch=Растянуть|tile=Мозаика", 0, false},
    {"timezone", "timezone", "Часовой пояс UTC", "3",
     "-12|-11|-10|-9|-8|-7|-6|-5|-4|-3|-2|-1|0|1|2|3|4|5|6|7|8|9|10|11|12|13|14", 0, false},
    {"timezone", "daylight", "Летнее время", "0", "0=Нет|1=Да", 0, false},
    {"timezone", "time_offset_minutes", "Поправка времени, минут", "0", "", 1440, false},
    {"backlight", "manual_light", "Подсветка вручную", "0", "0=Нет|1=Да", 0, false},
    {"backlight", "light_seconds", "Таймаут подсветки, секунд", "15", "", 999, false}};
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
    return s.get(key, f ? f->initial : "");
}
int settingNumber(const Settings &s, const std::string &key) {
    return atoi(settingValue(s, key).c_str());
}
bool settingFlag(const Settings &s, const std::string &key) {
    return settingValue(s, key) == "1";
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
        if (!found) {
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
               key != "dns_server" && key != "background_file" && key != "network_profile") {
        char *end = 0;
        long n = strtol(v.c_str(), &end, 10);
        if (!numeric(v) || n > f.maximum || (n < 0 && key != "time_offset_minutes")) {
            e = "Число вне допустимого диапазона";
            return false;
        }
        if (key == "port" && n == 0) {
            e = "Порт должен быть от 1 до 65535";
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
