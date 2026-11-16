// Actual V8 Qt + AMR codec; microphone and thread scheduling are fixtures.
// QEMU user mode cannot run V8 LinuxThreads clone flags, so the worker is
// driven deterministically. This tests ownership/cleanup, not OS scheduling.
#include <qobject.h>
#include <qstring.h>
#include <qstringlist.h>
#include <qtimer.h>
#define private public
#include "capture.h"
#undef private
#include "capture_media.h"
#include <qapplication.h>
#include <ezxsound.h>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <unistd.h>
#include <cstdlib>
#include <sys/stat.h>
#include <pthread.h>
static void *(*pendingWorker)(void *);
static void *pendingArgument;
static void driveWorker() {
    if (pendingWorker) {
        void *(*run)(void *) = pendingWorker;
        void *argument = pendingArgument;
        pendingWorker = 0;
        run(argument);
    }
}
extern "C" int pthread_create(pthread_t *id, const pthread_attr_t *, void *(*run)(void *),
                              void *argument) {
    assert(!pendingWorker);
    *id = 1;
    pendingWorker = run;
    pendingArgument = argument;
    return 0;
}
extern "C" int pthread_join(pthread_t, void **result) {
    driveWorker();
    if (result)
        *result = 0;
    return 0;
}
static volatile bool microphoneWaiting;
static unsigned inputOpened, inputClosed;
AM_NORMAL_DEV_INTERFACE::AM_NORMAL_DEV_INTERFACE(SOUNDM_AUDIO_NORMALDEV_TYPE_ENUM_T mode) {
    assert(static_cast<int>(mode) == 0x303);
    ++inputOpened;
}
AM_NORMAL_DEV_INTERFACE::~AM_NORMAL_DEV_INTERFACE() {}
int AM_NORMAL_DEV_INTERFACE::canRead() {
    return microphoneWaiting ? 1 : 0;
}
int AM_NORMAL_DEV_INTERFACE::read(short *out, unsigned count) {
    assert(count == 4000);
    std::memset(out, 0, count * sizeof(short));
    return count;
}
void AM_NORMAL_DEV_INTERFACE::close() {
    ++inputClosed;
}
static void await(tmm::CaptureController &capture) {
    driveWorker();
    for (int i = 0; i < 500 && capture.busy(); ++i) {
        usleep(10000);
        capture.poll();
    }
    assert(!capture.busy());
}
int main(int argc, char **argv) {
    QApplication app(argc, argv, false);
    char directory[] = "/tmp/tmm-capture-life-XXXXXX";
    assert(mkdtemp(directory));
    QString first = QString(directory) + "/first.amr",
            cancelled = QString(directory) + "/cancel.amr",
            destroyed = QString(directory) + "/destroy.amr";
    {
        tmm::CaptureController capture;
        capture.recordVoice(first, 1);
        assert(capture.busy());
        await(capture);
        assert(capture.durationSeconds() == 1);
        assert(tmm::captureDuration(first.local8Bit().data()) == 1);
        assert(inputOpened == 1 && inputClosed == 1);
        // Existing media must never be truncated when timestamp/path is repeated.
        capture.recordVoice(first, 1);
        assert(!capture.busy());
        assert(tmm::captureDuration(first.local8Bit().data()) == 1);
        microphoneWaiting = true;
        capture.recordVoice(cancelled, 600);
        assert(capture.busy());
        capture.cancel();
        await(capture);
        assert(access(cancelled.local8Bit().data(), F_OK) != 0);
    }
    {
        tmm::CaptureController capture;
        capture.recordVoice(destroyed, 600);
        assert(capture.busy());
    }
    assert(access(destroyed.local8Bit().data(), F_OK) != 0);
    assert(!unlink(first.local8Bit().data()));
    assert(!rmdir(directory));
    std::puts("V8 capture unit: real AMR + scheduled-worker fixture, duration, exclusive file, "
              "cancel/shutdown cleanup PASS");
    return 0;
}
