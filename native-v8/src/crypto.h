#ifndef TMM_NATIVE_CRYPTO_H
#define TMM_NATIVE_CRYPTO_H
#include <string>
#include <stddef.h>
#include <stdint.h>
namespace tmm {
namespace crypto {
std::string md5(const std::string &data);
std::string sha256(const std::string &data);
std::string hmac(const std::string &key, const std::string &data);
bool derivePsk(const std::string &phrase, std::string &key, std::string &error);
bool randomBytes(size_t length, std::string &data, std::string &error);
std::string clientHello(const std::string &key, const std::string &nonce16);
bool finishHandshake(const std::string &key, const std::string &request,
                     const std::string &response, std::string &finish, std::string &sessionKeys128,
                     std::string &error);
class RecordCipher {
    std::string enc_, mac_;
    uint64_t counter_;
    bool ready_, exhausted_;

  public:
    RecordCipher();
    bool reset(const std::string &encKey32, const std::string &macKey32);
    bool seal(const std::string &plain, std::string &record, std::string &error);
    bool open(const std::string &record, std::string &plain, std::string &error);
};
} // namespace crypto
} // namespace tmm
#endif
