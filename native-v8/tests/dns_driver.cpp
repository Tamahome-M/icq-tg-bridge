#include "dns.h"
#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <resolv.h>
#include <iostream>
static int targetPort;
extern "C" int __real_connect(int, const struct sockaddr *, socklen_t);
extern "C" int __wrap_connect(int fd, const struct sockaddr *address, socklen_t size) {
    if (address->sa_family == AF_INET && size >= sizeof(sockaddr_in)) {
        sockaddr_in a = *reinterpret_cast<const sockaddr_in *>(address);
        if (ntohs(a.sin_port) == 53 && ntohl(a.sin_addr.s_addr) == 0x7f000001) {
            a.sin_port = htons(targetPort);
            return __real_connect(fd, reinterpret_cast<sockaddr *>(&a), sizeof a);
        }
    }
    return __real_connect(fd, address, size);
}
struct Cancel : tmm::Cancellation {
    mutable pthread_mutex_t m;
    bool stop;
    int p[2];
    unsigned delay;
    Cancel() : stop(false), delay(0) {
        pthread_mutex_init(&m, 0);
        pipe(p);
        fcntl(p[0], F_SETFL, O_NONBLOCK);
        fcntl(p[1], F_SETFL, O_NONBLOCK);
    }
    ~Cancel() {
        close(p[0]);
        close(p[1]);
        pthread_mutex_destroy(&m);
    }
    bool cancelled() const {
        pthread_mutex_lock(&m);
        bool value = stop;
        pthread_mutex_unlock(&m);
        return value;
    }
    int wakeFd() const {
        return p[0];
    }
    static void *run(void *x) {
        Cancel *c = static_cast<Cancel *>(x);
        usleep(c->delay * 1000);
        pthread_mutex_lock(&c->m);
        c->stop = true;
        pthread_mutex_unlock(&c->m);
        char b = 1;
        ssize_t n = write(c->p[1], &b, 1);
        (void)n;
        return 0;
    }
};
int main(int argc, char **argv) {
    if (argc < 4)
        return 2;
    targetPort = atoi(argv[1]);
    unsigned mode = atoi(argv[2]);
    bool tcp = mode == 1;
    unsigned port = 53;
    if (mode == 2) {
        res_state state = __res_state();
        state->options |= RES_INIT;
        state->nscount = 1;
        memset(&state->nsaddr_list[0], 0, sizeof(sockaddr_in));
        state->nsaddr_list[0].sin_family = AF_INET;
        state->nsaddr_list[0].sin_port = htons(targetPort);
        inet_pton(AF_INET, "127.0.0.1", &state->nsaddr_list[0].sin_addr);
        std::vector<tmm::DnsServer> servers = tmm::systemDnsServers();
        if (servers.size() != 1 || servers[0].address != "127.0.0.1" ||
            servers[0].port != unsigned(targetPort))
            return 4;
        port = servers[0].port;
        targetPort = 0;
    }
    Cancel c;
    pthread_t timer;
    bool started = false;
    if (argc > 4 && atoi(argv[4])) {
        c.delay = atoi(argv[4]);
        pthread_create(&timer, 0, Cancel::run, &c);
        started = true;
    }
    int code = 0;
    try {
        std::vector<std::string> ips = tmm::resolveDns(argv[3], "127.0.0.1", c, tcp, port);
        for (size_t i = 0; i < ips.size(); ++i)
            std::cout << ips[i] << '\n';
    } catch (const std::exception &e) {
        std::cout << "ERR " << e.what() << '\n';
        code = 3;
    }
    if (started)
        pthread_join(timer, 0);
    return code;
}
