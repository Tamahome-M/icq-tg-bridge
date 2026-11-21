// Host test adapter for Motorola's per-thread stopwatch. A Linux timerfd makes
// the real network poll wake, including with both application clocks stopped.
#include <sys/ioctl.h>
#include <sys/time.h>
#include <sys/timerfd.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

extern "C" int __real_open(const char *, int, ...);
extern "C" int __real_ioctl(int, unsigned long, ...);
extern "C" int __real_gettimeofday(struct timeval *, void *);

static int timer = -1;
static pthread_t owner;
extern "C" int __wrap_open(const char *name, int flags, ...) {
    if (strcmp(name, "/dev/rtc_sw") == 0 && getenv("TMM_TEST_RTC")) {
        owner = pthread_self();
        timer = timerfd_create(CLOCK_MONOTONIC, TFD_NONBLOCK);
        return timer;
    }
    if ((flags & O_CREAT) || (flags & O_TMPFILE) == O_TMPFILE) {
        va_list ap;
        va_start(ap, flags);
        int mode = va_arg(ap, int);
        va_end(ap);
        return __real_open(name, flags, mode);
    }
    return __real_open(name, flags);
}

extern "C" int __wrap_ioctl(int fd, unsigned long request, ...) {
    va_list ap;
    va_start(ap, request);
    void *argument = va_arg(ap, void *);
    va_end(ap);
    if (fd != timer || _IOC_TYPE(request) != 'q')
        return __real_ioctl(fd, request, argument);
    if (!pthread_equal(owner, pthread_self()))
        abort();
    if (request == _IO('q', 4)) {
        uint64_t ticks = 0;
        return read(fd, &ticks, sizeof ticks) == sizeof ticks && ticks ? 0 : -1;
    }
    itimerspec time = {};
    if (request == _IOW('q', 1, unsigned *)) {
        if (getenv("TMM_TEST_RTC_DENIED")) {
            errno = EACCES;
            return -1;
        }
        const unsigned *p = static_cast<const unsigned *>(argument);
        if (p[0] >= 24 || p[1] >= 60 || p[2] >= 60 || p[3] >= 100)
            abort();
        time.it_value.tv_sec = p[0] * 3600 + p[1] * 60 + p[2];
        time.it_value.tv_nsec = p[3] * 10000000;
        time.it_interval = time.it_value;
    } else if (request != _IOW('q', 3, unsigned *))
        abort();
    return timerfd_settime(fd, 0, &time, 0);
}
extern "C" int __wrap_gettimeofday(struct timeval *out, void *zone) {
    int result = __real_gettimeofday(out, zone);
    if (result == 0 && getenv("TMM_TEST_FROZEN_WALL")) {
        out->tv_sec = 1000000000;
        out->tv_usec = 0;
    }
    return result;
}
