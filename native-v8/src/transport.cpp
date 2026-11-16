#include "transport.h"
#include "oscar.h"
#include <sys/socket.h>
#include <sys/time.h>
#include <arpa/inet.h>
#include <netinet/tcp.h>
#include <fcntl.h>
#include <unistd.h>
#include <poll.h>
#include <errno.h>
#include <string.h>
#include <time.h>
#include <algorithm>
namespace tmm {
uint64_t monotonicMs() {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t) == 0)
        return uint64_t(t.tv_sec) * 1000 + t.tv_nsec / 1000000;
    struct timeval v;
    gettimeofday(&v, 0);
    return uint64_t(v.tv_sec) * 1000 + v.tv_usec / 1000;
}
Transport::Transport(Cancellation &c)
    : fd_(-1), cancel_(c), secure_(false), failed_(false), at_(0) {}
Transport::~Transport() {
    close();
}
void Transport::close() {
    if (fd_ >= 0) {
        ::close(fd_);
        fd_ = -1;
    }
    secure_ = false;
    failed_ = false;
    plain_.clear();
    at_ = 0;
}
bool Transport::wait(bool write, uint64_t deadline) {
    if (fd_ < 0)
        throw wire::Error("Соединение закрыто");
    for (;;) {
        if (cancel_.cancelled())
            throw wire::Error("Подключение отменено");
        uint64_t now = monotonicMs();
        if (now >= deadline)
            return false;
        struct pollfd p[2];
        p[0].fd = fd_;
        p[0].events = write ? POLLOUT : POLLIN;
        p[0].revents = 0;
        p[1].fd = cancel_.wakeFd();
        p[1].events = POLLIN;
        p[1].revents = 0;
        int n = poll(p, 2, int(std::min<uint64_t>(deadline - now, 1000)));
        if (n < 0) {
            if (errno == EINTR)
                continue;
            throw wire::Error(strerror(errno));
        }
        if (p[1].revents) {
            char b[64];
            while (::read(p[1].fd, b, sizeof b) > 0) {
            }
            if (cancel_.cancelled())
                throw wire::Error("Подключение отменено");
        }
        if (p[0].revents & (POLLIN | POLLOUT | POLLHUP | POLLERR | POLLNVAL))
            return true;
    }
}
void Transport::connect(const std::string &ip, unsigned port, uint64_t deadline) {
    close();
    if (cancel_.cancelled())
        throw wire::Error("Подключение отменено");
    struct sockaddr_in a;
    memset(&a, 0, sizeof a);
    a.sin_family = AF_INET;
    a.sin_port = htons(port);
    if (!port || port > 65535 || inet_pton(AF_INET, ip.c_str(), &a.sin_addr) != 1)
        throw wire::Error("Ожидался IP-адрес сервера");
    fd_ = socket(AF_INET, SOCK_STREAM, 0);
    if (fd_ < 0)
        throw wire::Error(strerror(errno));
    if (ip.substr(0, 4) != "127.")
        cancel_.bindSocket(fd_);
    if (fcntl(fd_, F_SETFL, O_NONBLOCK) < 0 || fcntl(fd_, F_SETFD, FD_CLOEXEC) < 0)
        throw wire::Error(strerror(errno));
    int one = 1;
    setsockopt(fd_, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    if (::connect(fd_, reinterpret_cast<sockaddr *>(&a), sizeof a) < 0) {
        if (errno != EINPROGRESS)
            throw wire::Error(strerror(errno));
        if (!wait(true, deadline))
            throw wire::Error("Время подключения истекло");
        int error = 0;
        socklen_t n = sizeof error;
        if (getsockopt(fd_, SOL_SOCKET, SO_ERROR, &error, &n) < 0 || error)
            throw wire::Error(error ? strerror(error) : strerror(errno));
    }
}
void Transport::rawRead(char *d, size_t size, uint64_t deadline) {
    while (size) {
        if (!wait(false, deadline))
            throw wire::Error("Сервер не отвечает");
        ssize_t n = recv(fd_, d, size, 0);
        if (n < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)
                continue;
            throw wire::Error(strerror(errno));
        }
        if (!n)
            throw wire::Error("Сервер закрыл соединение");
        d += n;
        size -= n;
    }
}
void Transport::rawWrite(const char *d, size_t size, uint64_t deadline) {
    while (size) {
        if (!wait(true, deadline))
            throw wire::Error("Не удалось передать данные вовремя");
        ssize_t n = send(fd_, d, size, MSG_NOSIGNAL);
        if (n < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)
                continue;
            throw wire::Error(strerror(errno));
        }
        if (!n)
            throw wire::Error("Соединение закрыто");
        d += n;
        size -= n;
    }
}
std::string Transport::read(size_t size, uint64_t deadline) {
    if (size > 65535)
        throw wire::Error("Слишком большой сетевой буфер");
    std::string result(size, 0);
    size_t offset = 0;
    while (offset < size) {
        if (!secure_) {
            rawRead(&result[offset], size - offset, deadline);
            break;
        }
        if (at_ == plain_.size()) {
            std::string record(2, 0);
            rawRead(&record[0], 2, deadline);
            wire::Reader h(record);
            unsigned n = h.u16();
            if (!n || n > 1024)
                throw wire::Error("Неверная длина TMME");
            record.resize(n + 18);
            rawRead(&record[2], n + 16, deadline);
            std::string error;
            if (!rx_.open(record, plain_, error))
                throw wire::Error(error);
            at_ = 0;
        }
        size_t n = std::min(size - offset, plain_.size() - at_);
        result.replace(offset, n, plain_, at_, n);
        at_ += n;
        offset += n;
    }
    return result;
}
void Transport::write(const std::string &data, uint64_t deadline) {
    try {
        if (failed_)
            throw wire::Error("Соединение повреждено при отправке");
        if (!secure_) {
            rawWrite(data.data(), data.size(), deadline);
            return;
        }
        for (size_t i = 0; i < data.size(); i += 1024) {
            std::string record, error;
            if (!tx_.seal(data.substr(i, 1024), record, error))
                throw wire::Error(error);
            rawWrite(record.data(), record.size(), deadline);
        }
    } catch (...) {
        // A partial FLAP or encrypted record cannot be followed by another
        // packet. Its byte boundary and (for TMME) sequence are already lost.
        close();
        failed_ = true;
        throw;
    }
}
void Transport::secure(const std::string &keys) {
    if (keys.size() != 128 || !tx_.reset(keys.substr(0, 32), keys.substr(32, 32)) ||
        !rx_.reset(keys.substr(64, 32), keys.substr(96, 32)))
        throw wire::Error("Неверные ключи TMME");
    secure_ = true;
    plain_.clear();
    at_ = 0;
}
} // namespace tmm
