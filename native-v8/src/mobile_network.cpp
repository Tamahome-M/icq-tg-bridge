#include "mobile_network.h"
#include <dlfcn.h>
#include <sys/socket.h>
#include <sys/select.h>
#include <unistd.h>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <ctime>

namespace tmm {

template <typename Function>
static bool symbol(void *library, const char *name, Function &function) {
    void *address = dlsym(library, name);
    if (!address || sizeof(function) != sizeof(address))
        return false;
    std::memcpy(&function, &address, sizeof(function));
    return true;
}

MobileNetwork::MobileNetwork()
    : library(0), notification(-1), link(-1), init(0), finish(0), open_link(0), close_link(0),
      dns_config(0), bind_link(0) {}
MobileNetwork::~MobileNetwork() {
    close();
}
void MobileNetwork::close() {
    if (link >= 0)
        close_link(link);
    if (notification >= 0)
        finish();
    if (library)
        dlclose(library);
    library = 0;
    notification = link = -1;
}

bool MobileNetwork::open(const ClientConfig &config, Cancellation &cancel, std::string &error) {
    close();
    if (cancel.cancelled()) {
        error = "Cancelled";
        return false;
    }
    if (config.network == "system" || (config.network == "auto" && config.profile.empty()))
        return true;
    if (config.profile.empty()) {
        error = "Select an Internet profile in Settings";
        return false;
    }
    library = dlopen("libnapi.so", RTLD_NOW | RTLD_LOCAL);
    if (!library || !symbol(library, "NAPI_Init", init) || !symbol(library, "NAPI_Fini", finish) ||
        !symbol(library, "NAPI_OpenLink", open_link) ||
        !symbol(library, "NAPI_CloseLink", close_link) ||
        !symbol(library, "NAPI_DnsResolverConfig", dns_config) ||
        !symbol(library, "NAPI_BindSocket2Link", bind_link)) {
        error = "Motorola Internet service (libnapi) unavailable";
        return false;
    }
    notification = init(0);
    if (notification < 0) {
        error = "Cannot initialize Motorola Internet service";
        return false;
    }
    if (notification >= FD_SETSIZE) {
        error = "Too many open network descriptors";
        return false;
    }
    link = open_link(config.profile.c_str());
    if (link < 0 || link > 255) {
        link = -1;
        error = "Cannot open selected Internet profile";
        return false;
    }
    std::fprintf(stderr, "Network: opening Motorola Internet profile, link %d\n", link);
    const uint64_t deadline = monotonicMs() + 60000;
    while (!cancel.cancelled() && monotonicMs() < deadline) {
        fd_set ready;
        FD_ZERO(&ready);
        FD_SET(notification, &ready);
        timeval timeout = {1, 0};
        int result = select(notification + 1, &ready, 0, 0, &timeout);
        if (result < 0) {
            if (errno == EINTR)
                continue;
            error = "Motorola Internet notification failed";
            return false;
        }
        if (!result)
            continue;
        // SAedition V8's ZDataSessionManager reads 112-byte notifications:
        // uint16 event at 0, uint8 link at 2, failure codes at 108/110.
        // See docs/v8-network.md for firmware evidence and the ABI test.
        unsigned char event[113];
        ssize_t count = recv(notification, event, sizeof(event), 0);
        if (count < 0 && errno == EINTR)
            continue;
        if (count != 112 || event[2] != link)
            continue;
        unsigned int type = event[0] | (static_cast<unsigned int>(event[1]) << 8);
        if (type == 16) {
            if (dns_config(link) < 0) {
                error = "Cannot configure mobile DNS";
                return false;
            }
            std::fprintf(stderr, "Network: mobile link ready, DNS configured\n");
            return true;
        }
        if (type == 17 || type == 32) {
            unsigned int reason = event[108] | (static_cast<unsigned int>(event[109]) << 8);
            unsigned int detail = event[110] | (static_cast<unsigned int>(event[111]) << 8);
            char message[100];
            std::sprintf(message, "Internet profile failed (NAPI %u/%u)", reason, detail);
            error = message;
            return false;
        }
    }
    error = cancel.cancelled() ? "Cancelled" : "Internet profile timed out; check SIM and profile";
    return false;
}

bool MobileNetwork::bind_socket(int socket, std::string &error) {
    if (link < 0)
        return true;
    if (bind_link(socket, link) < 0) {
        error = "Cannot bind socket to mobile Internet";
        return false;
    }
    return true;
}
} // namespace tmm
