#ifndef TMM_MOBILE_NETWORK_H
#define TMM_MOBILE_NETWORK_H
#include "client.h"
#include "transport.h"
#include <csignal>

namespace tmm {

// One downloader process owns one NAPI session, including DNS and socket binding.
class MobileNetwork {
  public:
    MobileNetwork();
    ~MobileNetwork();
    bool open(const ClientConfig &config, Cancellation &cancel, std::string &error);
    void close();
    bool bind_socket(int socket, std::string &error);

  private:
    void *library;
    int notification, link;
    int (*init)(int);
    void (*finish)();
    int (*open_link)(const char *);
    int (*close_link)(int);
    int (*dns_config)(int);
    int (*bind_link)(int, int);
    MobileNetwork(const MobileNetwork &);
    MobileNetwork &operator=(const MobileNetwork &);
};
} // namespace tmm
#endif
