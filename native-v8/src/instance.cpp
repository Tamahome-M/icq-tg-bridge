#include "instance.h"
#include <sys/file.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <signal.h>
#include <unistd.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
namespace tmm {
static int activationPipe[2] = {-1, -1};
static void activate(int) {
    int saved = errno;
    char byte = 1;
    if (activationPipe[1] >= 0) {
        ssize_t unused = write(activationPipe[1], &byte, 1);
        (void)unused;
    }
    errno = saved;
}
bool takeActivationRequest() {
    if (activationPipe[0] < 0)
        return false;
    bool result = false;
    char bytes[256];
    for (unsigned i = 0; i < 4; ++i) {
        ssize_t n = read(activationPipe[0], bytes, sizeof bytes);
        if (n > 0)
            result = true;
        else if (n < 0 && errno == EINTR)
            continue;
        else
            break;
    }
    return result;
}
Instance::~Instance() {
    if (fd_ >= 0)
        close(fd_);
}
int Instance::acquire(const std::string &directory, std::string &error) {
    error = "Cannot activate the running client; close it before updating";
    if (activationPipe[0] < 0) {
        if (pipe(activationPipe) < 0)
            return -1;
        for (unsigned i = 0; i < 2; ++i)
            if (fcntl(activationPipe[i], F_SETFL, O_NONBLOCK) < 0 ||
                fcntl(activationPipe[i], F_SETFD, FD_CLOEXEC) < 0) {
                close(activationPipe[0]);
                close(activationPipe[1]);
                activationPipe[0] = activationPipe[1] = -1;
                return -1;
            }
    }
    struct sigaction action;
    memset(&action, 0, sizeof(action));
    action.sa_handler = activate;
    sigemptyset(&action.sa_mask);
    action.sa_flags = SA_RESTART;
    if (sigaction(SIGUSR1, &action, 0) < 0)
        return -1;
    int fd = open((directory + "/instance.lock").c_str(), O_CREAT | O_RDWR | O_NOFOLLOW, 0600);
    if (fd < 0)
        return -1;
    struct stat st;
    if (fstat(fd, &st) < 0 || !S_ISREG(st.st_mode) || st.st_uid != getuid()) {
        close(fd);
        return -1;
    }
    fcntl(fd, F_SETFD, FD_CLOEXEC);
    if (flock(fd, LOCK_EX | LOCK_NB) == 0) {
        char text[32];
        int size = snprintf(text, sizeof(text), "%ld\n", (long)getpid());
        if (ftruncate(fd, 0) < 0 || write(fd, text, size) != size) {
            close(fd);
            return -1;
        }
        fd_ = fd;
        error.clear();
        return 1;
    }
    if (errno != EWOULDBLOCK && errno != EAGAIN) {
        close(fd);
        return -1;
    }
    char text[32];
    ssize_t size = read(fd, text, sizeof(text) - 1);
    close(fd);
    if (size <= 0)
        return -1;
    text[size] = 0;
    char *end = 0;
    errno = 0;
    long pid = strtol(text, &end, 10);
    if (errno || pid <= 1 || pid > 0x7fffffffL || end == text || (*end && strcmp(end, "\n")))
        return -1;
    // Do not signal an unrelated PID from an old or damaged lock file.
    char target[80];
    snprintf(target, sizeof(target), "/proc/%ld/exe", pid);
    struct stat mine, other;
    if (stat("/proc/self/exe", &mine) < 0 || stat(target, &other) < 0 ||
        mine.st_dev != other.st_dev || mine.st_ino != other.st_ino)
        return -1;
    if (kill((pid_t)pid, SIGUSR1) < 0)
        return -1;
    error.clear();
    return 0;
}
} // namespace tmm
