// LinuxThreads clone is unavailable under QEMU-user. Run the actual worker
// after Client::start releases its mutex; this fixture does not test scheduling.
#include <pthread.h>
#include <sys/socket.h>
#include <errno.h>
#include <assert.h>
static void *(*entry)(void *);
static void *argument;
static int createFailure;
void scheduleNetworkWorker(int failure) {
    assert(!entry);
    createFailure = failure;
}
void runNetworkWorker() {
    assert(entry);
    void *(*run)(void *) = entry;
    entry = 0;
    run(argument);
}
extern "C" int __wrap_pthread_create(pthread_t *thread, const pthread_attr_t *,
                                     void *(*run)(void *), void *data) {
    if (createFailure)
        return createFailure;
    assert(!entry);
    entry = run;
    argument = data;
    *thread = 100;
    return 0;
}
extern "C" int __wrap_pthread_join(pthread_t, void **) {
    assert(!entry);
    return 0;
}
extern "C" int __wrap_connect(int, const struct sockaddr *, socklen_t) {
    errno = ECONNREFUSED;
    return -1;
}
