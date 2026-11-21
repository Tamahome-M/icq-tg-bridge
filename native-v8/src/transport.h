#ifndef TMM_TRANSPORT_H
#define TMM_TRANSPORT_H
#include "crypto.h"
#include <stdint.h>
#include <string>
namespace tmm {
uint64_t monotonicMs();
class Cancellation {
  public:
    virtual ~Cancellation() {}
    virtual bool cancelled() const = 0;
    virtual int wakeFd() const = 0;
    virtual void bindSocket(int) {}
};
// The BOS worker may send a keepalive while a partial incoming frame is
// waiting for more bytes. Writes are always completed by the same thread.
class ReadWatch {
  public:
    virtual ~ReadWatch() {}
    virtual void checkKeepalive(bool received) = 0;
};
class Transport {
    int fd_;
    Cancellation &cancel_;
    ReadWatch *readWatch_;
    bool secure_, failed_;
    std::string plain_;
    size_t at_;
    crypto::RecordCipher tx_, rx_;
    void rawRead(char *data, size_t size, uint64_t deadline);
    void rawWrite(const char *data, size_t size, uint64_t deadline);

  public:
    explicit Transport(Cancellation &c);
    ~Transport();
    void connect(const std::string &ipv4, unsigned port, uint64_t deadline);
    void close();
    int fd() const {
        return fd_;
    }
    bool failed() const {
        return failed_;
    }
    bool buffered() const {
        return at_ < plain_.size();
    }
    void watchReads(ReadWatch &watch) {
        readWatch_ = &watch;
    }
    bool wait(bool write, uint64_t deadline);
    std::string read(size_t size, uint64_t deadline);
    void write(const std::string &data, uint64_t deadline);
    void secure(const std::string &keys);

  private:
    Transport(const Transport &);
    Transport &operator=(const Transport &);
};
} // namespace tmm
#endif
