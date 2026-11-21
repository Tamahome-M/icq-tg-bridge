#ifndef TMM_PHONE_NUMBER_H
#define TMM_PHONE_NUMBER_H
#include <string>
namespace tmm {
// Only ordinary telephone numbers go to Motorola's voice-call interface.
inline std::string phoneNumber(const std::string &value) {
    std::string result;
    unsigned digits = 0;
    for (size_t i = 0; i < value.size(); ++i) {
        char c = value[i];
        if (c >= '0' && c <= '9') {
            if (++digits > 32)
                return "";
            result += c;
        } else if (c == '+' && result.empty())
            result += c;
        else if (c != ' ' && c != '(' && c != ')' && c != '-' && c != '.')
            return "";
    }
    return digits ? result : "";
}
} // namespace tmm
#endif
