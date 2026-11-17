// Execute the production Platform on firmware Qt; observe only the final
// player call. Speaker/vibration hardware is not opened by this test.
#include "platform.h"
#define private public
#include "media.h"
#undef private
#include <qapplication.h>
#include <qfileinfo.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
static unsigned calls;
static QString played;
static int level;
static bool audioOnly;
extern "C" bool __wrap__ZN3tmm15MediaController4playERK7QStringib(tmm::MediaController *media,
                                                                  const QString &path, int volume,
                                                                  bool audio) {
    assert(media->notification_);
    media->active_ = true;
    ++calls;
    played = path;
    level = volume;
    audioOnly = audio;
    return true;
}
int main(int argc, char **argv) {
    QApplication app(argc, argv, false);
    QString tone;
    {
        tmm::Platform platform;
        platform.notifyMessage("sounds/tg.mp3", 30, 0);
        assert(calls == 1 && played == "sounds/tg.mp3" && level == 30 && audioOnly);
        platform.notifyMessage("sounds/message.mp3", 70, 0);
        assert(calls == 1); // Burst coalesces while the first alert is playing.
        platform.stopNotificationSound();
        platform.notifyMessage("sounds/message.mp3", 70, 0);
        assert(calls == 2 && played == "sounds/message.mp3" && level == 70 && audioOnly);
        platform.notifyMessage("sounds/message.mp3", 0, 0);
        platform.notifyMessage(QString::null, 50, 0);
        assert(calls == 2);
        platform.stopNotificationSound();
        platform.notifyMessage("tone", 50, 0);
        assert(calls == 3 && level == 50 && audioOnly);
        tone = played;
        FILE *file = fopen(tone.local8Bit().data(), "rb");
        assert(file);
        char header[12];
        assert(fread(header, 1, sizeof(header), file) == sizeof(header));
        assert(!memcmp(header, "RIFF", 4) && !memcmp(header + 8, "WAVE", 4));
        fclose(file);
        platform.notifyDisconnected(80);
        assert(calls == 3); // Disconnect must not restart an active alert either.
        platform.stopNotificationSound();
        platform.notifyDisconnected(80);
        assert(calls == 4 && played == tone && level == 80 && audioOnly);
    }
    assert(access(tone.local8Bit().data(), F_OK) != 0);
    puts("V8 notifications: actual Platform routes file/volume to audio-only player, "
         "bursts/zero/none "
         "suppressed, three-note WAV reused and cleaned PASS");
    return 0;
}
