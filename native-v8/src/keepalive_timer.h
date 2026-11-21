#ifndef TMM_KEEPALIVE_TIMER_H
#define TMM_KEEPALIVE_TIMER_H

#include <stdint.h>

namespace tmm {
// The Motorola driver associates jobs with the calling thread, including poll
// and close. Only the BOS worker may operate an active timer.
class KeepaliveTimer {
    int fd_;
    unsigned seconds_, count_;
    bool armed_, pending_;
    uint64_t lastUptime_, lastWall_;

    void closeDevice();
    void deviceError(const char *operation);

  public:
    KeepaliveTimer();
    ~KeepaliveTimer();
    void reset(unsigned seconds);
    int fd() const {
        return fd_;
    }
    short pollNow() const;
    void observed(short events);
    bool due();
    void sent();

  private:
    KeepaliveTimer(const KeepaliveTimer &);
    KeepaliveTimer &operator=(const KeepaliveTimer &);
};
} // namespace tmm
#endif
