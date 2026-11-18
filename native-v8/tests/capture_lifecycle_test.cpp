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
#include "capture_test_observer.h"
#include <qapplication.h>
#include <ezxsound.h>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <unistd.h>
#include <cstdlib>
#include <sys/stat.h>
#include <pthread.h>
#include <errno.h>
CaptureTestObserver::CaptureTestObserver(tmm::CaptureController &capture)
    : readyCount(0), errorCount(0), cancelledCount(0), terminalWhileBusy(false), capture_(capture) {
    connect(&capture, SIGNAL(ready(const QString &, const QString &)), this,
            SLOT(ready(const QString &, const QString &)));
    connect(&capture, SIGNAL(error(const QString &)), this, SLOT(error(const QString &)));
    connect(&capture, SIGNAL(cancelled()), this, SLOT(cancelled()));
}
void CaptureTestObserver::ready(const QString &value, const QString &type) {
    ++readyCount;
    terminalWhileBusy = terminalWhileBusy || capture_.busy();
    path = value;
    mime = type;
}
void CaptureTestObserver::error(const QString &) {
    ++errorCount;
    terminalWhileBusy = terminalWhileBusy || capture_.busy();
}
void CaptureTestObserver::cancelled() {
    ++cancelledCount;
    terminalWhileBusy = terminalWhileBusy || capture_.busy();
}
static void *(*pendingWorker)(void *);
static void *pendingArgument;
static bool failCreate;
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
    if (failCreate) {
        failCreate = false;
        return EAGAIN;
    }
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
static bool failRead;
static unsigned inputOpened, inputClosed, readCalls;
static unsigned stopOnRead;
static bool stopOnReady;
static tmm::CaptureController *stopTarget;
AM_NORMAL_DEV_INTERFACE::AM_NORMAL_DEV_INTERFACE(SOUNDM_AUDIO_NORMALDEV_TYPE_ENUM_T mode) {
    assert(static_cast<int>(mode) == 0x303);
    ++inputOpened;
}
AM_NORMAL_DEV_INTERFACE::~AM_NORMAL_DEV_INTERFACE() {}
int AM_NORMAL_DEV_INTERFACE::canRead() {
    if (stopOnReady && stopTarget) {
        stopOnReady = false;
        stopTarget->cancel();
    }
    return microphoneWaiting ? 1 : 0;
}
int AM_NORMAL_DEV_INTERFACE::read(short *out, unsigned count) {
    assert(count == 4000); // Preserve the stock VoiceNote packet size.
    ++readCalls;
    if (stopOnRead && readCalls == stopOnRead && stopTarget)
        stopTarget->stop();
    if (failRead)
        return -1;
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
            failed = QString(directory) + "/failed.amr",
            retried = QString(directory) + "/retried.amr",
            destroyed = QString(directory) + "/destroy.amr",
            stopped = QString(directory) + "/stopped.amr";
    {
        QObject owner;
        tmm::CaptureController capture(&owner);
        assert(!capture.signalsBlocked());
        capture.blockSignals(true);
        assert(capture.signalsBlocked());
        capture.blockSignals(false);
        assert(!capture.signalsBlocked());
        CaptureTestObserver observer(capture);
        const int source[][2] = {{640, 480}, {480, 640}, {320, 240}, {960, 1280}, {1280, 960}};
        const int bounds[][2] = {{480, 640}, {640, 480}, {640, 480}, {480, 640}, {960, 1280}};
        const int fitted[][2] = {{480, 360}, {360, 480}, {320, 240}, {480, 640}, {960, 720}};
        for (unsigned i = 0; i < 5; ++i) {
            int width = source[i][0], height = source[i][1];
            tmm::CaptureController::fitPhotoSize(width, height, bounds[i][0], bounds[i][1]);
            assert(width == fitted[i][0] && height == fitted[i][1]);
        }
        const unsigned rounded[] = {4800, 5200, 5900, 6700, 7400, 8000, 10200, 12200};
        const unsigned exact[] = {4750, 5150, 5900, 6700, 7400, 7950, 10200, 12200};
        for (unsigned i = 0; i < 8; ++i) {
            capture.setVoiceBitrate(rounded[i]);
            assert(capture.voiceBitrate_ == exact[i]);
        }
        capture.setVoiceBitrate(6700);
        capture.recordVoice(first, 1);
        assert(capture.busy());
        assert(capture.durationSeconds() == 0);
        driveWorker();
        assert(capture.busy() && capture.durationSeconds() == 1);
        await(capture);
        assert(capture.durationSeconds() == 1);
        assert(tmm::captureDuration(first.local8Bit().data()) == 1);
        assert(observer.readyCount == 1 && observer.errorCount == 0 &&
               observer.cancelledCount == 0);
        assert(observer.path == first && observer.mime == "audio/amr" &&
               !observer.terminalWhileBusy);
        assert(inputOpened == 1 && inputClosed == 1);
        // Existing media must never be truncated when timestamp/path is repeated.
        capture.recordVoice(first, 1);
        assert(!capture.busy());
        assert(observer.errorCount == 1 && observer.readyCount == 1);
        assert(tmm::captureDuration(first.local8Bit().data()) == 1);
        microphoneWaiting = true;
        capture.recordVoice(cancelled, 600);
        assert(capture.busy());
        capture.cancel();
        assert(observer.cancelledCount == 0);
        await(capture);
        assert(observer.cancelledCount == 1 && observer.errorCount == 1);
        assert(access(cancelled.local8Bit().data(), F_OK) != 0);
        microphoneWaiting = false;
        failCreate = true;
        capture.recordVoice(failed, 1);
        assert(!capture.busy() && capture.destination_.isEmpty());
        assert(access(failed.local8Bit().data(), F_OK) != 0);
        assert(observer.errorCount == 2);
        failRead = true;
        capture.recordVoice(failed, 1);
        await(capture);
        assert(access(failed.local8Bit().data(), F_OK) != 0);
        assert(observer.errorCount == 3 && observer.readyCount == 1);
        failRead = false;
        capture.recordVoice(retried, 1);
        await(capture);
        assert(observer.readyCount == 2 && observer.errorCount == 3 &&
               observer.cancelledCount == 1);
        assert(!observer.terminalWhileBusy && capture.destination_.isEmpty());
        readCalls = 0;
        stopTarget = &capture;
        stopOnRead = 13; // Stop during the read immediately following six seconds.
        capture.recordVoice(stopped, 60);
        await(capture);
        assert(readCalls == 13 && capture.durationSeconds() == 6 &&
               tmm::captureDuration(stopped.local8Bit().data()) == 6);
        assert(observer.readyCount == 3 && observer.errorCount == 3 &&
               observer.cancelledCount == 1 && !observer.terminalWhileBusy);
        stopOnRead = 0;
        readCalls = 0;
        stopOnReady = true;
        capture.recordVoice(cancelled, 60);
        await(capture);
        assert(!readCalls && observer.cancelledCount == 2);
        assert(access(cancelled.local8Bit().data(), F_OK) != 0);
        stopTarget = 0;
        assert(!unlink(stopped.local8Bit().data()));
        assert(!unlink(retried.local8Bit().data()));
    }
    {
        tmm::CaptureController capture;
        capture.recordVoice(destroyed, 600);
        assert(capture.busy());
    }
    assert(access(destroyed.local8Bit().data(), F_OK) != 0);
    assert(!unlink(first.local8Bit().data()));
    assert(!rmdir(directory));
    std::puts("V8 capture unit: real AMR + scheduled-worker fixture, live duration, UI bitrate "
              "normalization, Stop at six seconds/during readiness, signals, retry and shutdown "
              "cleanup PASS");
    return 0;
}
