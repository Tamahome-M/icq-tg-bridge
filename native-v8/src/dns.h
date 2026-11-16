#ifndef TMM_DNS_H
#define TMM_DNS_H
#include "transport.h"
#include <vector>
namespace tmm {
bool isIPv4(const std::string &host);
std::vector<std::string> resolveDns(const std::string &host, const std::string &server,
                                    Cancellation &cancel, bool tcpOnly = true, unsigned port = 53);
struct DnsServer {
    std::string address;
    unsigned port;
    DnsServer(const std::string &a, unsigned p) : address(a), port(p) {}
};
std::vector<DnsServer> systemDnsServers();
} // namespace tmm
#endif
