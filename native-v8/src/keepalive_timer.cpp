#include "keepalive_timer.h"
#include "transport.h"
#include <sys/ioctl.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

namespace tmm {
namespace {
// Motorola's linux/rtc.h uses a pointer, not the struct size, in the ioctl ABI.
struct StopwatchPeriod {
    unsigned hours, minutes, seconds, hundredths;
};
const unsigned long setPeriod = _IOW('q', 1, StopwatchPeriod *);
const unsigned long deletePeriod = _IOW('q', 3, StopwatchPeriod *);
const unsigned long jobDone = _IO('q', 4);

int stopwatch(int fd, unsigned long action, void *argument = 0) {
    int result;
    do {
        result = ioctl(fd, action, argument);
    } while (result < 0 && errno == EINTR);
    return result;
}
bool elapsed(uint64_t now, uint64_t &start, uint64_t period) {
    if (!now)
        return false;
    if (!start || now < start)
        start = now;
    return now - start >= period;
}
} // namespace

KeepaliveTimer::KeepaliveTimer()
    : fd_(-1), seconds_(0), count_(0), armed_(false), pending_(false), lastUptime_(0),
      lastWall_(0) {}
KeepaliveTimer::~KeepaliveTimer() {
    closeDevice();
}
void KeepaliveTimer::closeDevice() {
    if (fd_ >= 0) {
        if (pending_)
            stopwatch(fd_, jobDone);
        ::close(fd_); // rtc_sw_release removes the worker's requests, including unclaimed ticks.
    }
    fd_ = -1;
    armed_ = pending_ = false;
}
void KeepaliveTimer::deviceError(const char *operation) {
    fprintf(stderr, "OSCAR keepalive: %s: %s, using software timer\n", operation, strerror(errno));
    closeDevice();
}
void KeepaliveTimer::reset(unsigned seconds) {
    closeDevice();
    seconds_ = seconds;
    count_ = 0;
    if (!seconds)
        return;
    fd_ = open("/dev/rtc_sw", O_RDWR | O_NONBLOCK);
    if (fd_ < 0 || fcntl(fd_, F_SETFD, FD_CLOEXEC) < 0)
        deviceError("/dev/rtc_sw");
}
short KeepaliveTimer::pollNow() const {
    if (fd_ < 0)
        return 0;
    pollfd timer = {fd_, POLLIN, 0};
    return poll(&timer, 1, 0) > 0 ? timer.revents : 0;
}
void KeepaliveTimer::observed(short events) {
    // rtc_sw_poll itself claims one expiration. A read would wait for another.
    if (events & POLLIN)
        pending_ = true;
    if (events & (POLLERR | POLLHUP | POLLNVAL)) {
        errno = EIO;
        deviceError("poll(/dev/rtc_sw)");
    }
}
bool KeepaliveTimer::due() {
    if (!seconds_)
        return false;
    if (!count_ || pending_)
        return true;
    const uint64_t period = uint64_t(seconds_) * 1000;
    return elapsed(uptimeMs(), lastUptime_, period) || elapsed(wallMs(), lastWall_, period);
}
void KeepaliveTimer::sent() {
    const char *source = !count_ ? "initial" : pending_ ? "rtc_sw" : "software";
    lastUptime_ = uptimeMs();
    lastWall_ = wallMs();
    ++count_;
    // Restart from the successful write so delayed or simultaneous expirations
    // cannot send a burst or shorten the next probe's reply window.
    if (fd_ >= 0) {
        StopwatchPeriod period = {seconds_ / 3600, seconds_ / 60 % 60, seconds_ % 60, 0};
        if (pending_ && stopwatch(fd_, jobDone) < 0)
            deviceError("RTC_SW_JOB_DONE");
        pending_ = false;
        if (armed_ && stopwatch(fd_, deletePeriod, &period) < 0)
            deviceError("RTC_SW_DELTIME");
        if (fd_ >= 0) {
            if (stopwatch(fd_, setPeriod, &period) == 0)
                armed_ = true;
            else
                deviceError("RTC_SW_SETTIME");
        }
    }
    fprintf(stderr, "OSCAR keepalive #%u sent (%s, %u s, rtc_sw %s)\n", count_, source, seconds_,
            armed_ ? "on" : "off");
}
} // namespace tmm
