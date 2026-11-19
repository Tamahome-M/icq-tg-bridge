// Real V8 ringtone reader/decoder through EOF, real packaged MP3 bytes.
// Only the output/callback interfaces are inert. No play(), worker, AAL or
// speaker is started. Short originals reproduce the phone's MPError 2.
#include <dlfcn.h>
#include <cassert>
#include <cstdio>
#include <cstring>
namespace {
template <class T> T fn(void *pointer) {
    assert(pointer);
    T result;
    std::memcpy(&result, &pointer, sizeof(result));
    return result;
}
unsigned outputCalls;
unsigned short output(void *, ...) {
    ++outputCalls;
    return 0;
}
unsigned short callback(void *, ...) {
    return 0;
}
void *method(unsigned short (*function)(void *, ...)) {
    void *result;
    std::memcpy(&result, &function, sizeof(result));
    return result;
}
struct Interface {
    void **table;
};
} // namespace
int main() {
    assert(sizeof(void *) == 4);
    void *library = dlopen("libezx_mpsdk_ringtone.so", RTLD_NOW | RTLD_GLOBAL);
    assert(library);
    void *create = dlsym(library, "MP_CreateInstance"),
         *destroy = dlsym(library, "MP_FreeInstance");
    assert(create && destroy);
    void *outputMethods[16], *callbackMethods[16];
    for (unsigned i = 0; i < 16; ++i) {
        outputMethods[i] = method(&output);
        callbackMethods[i] = method(&callback);
    }
    Interface device = {outputMethods}, events = {callbackMethods};
    const struct {
        const char *path;
        unsigned expected;
    } cases[] = {{"sounds/message.mp3", 0},
                 {"sounds/msg_low.mp3", 0},
                 {"sounds/typing.mp3", 0},
                 {"../telemotomax/res/MIDP2/sounds/tg.mp3", 0},
                 {"../telemotomax/res/MIDP2/sounds/message.mp3", 2},
                 {"../telemotomax/res/MIDP2/sounds/msg_low.mp3", 2},
                 {"../telemotomax/res/MIDP2/sounds/typing.mp3", 2}};
    for (unsigned i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
        void *engine = 0;
        assert(fn<unsigned short (*)(void **)>(create)(&engine) == 0 && engine);
        void **table = *static_cast<void ***>(engine);
        assert(reinterpret_cast<unsigned long>(table[0x2c / 4]) -
                   reinterpret_cast<unsigned long>(create) ==
               0x41e26a70UL - 0x41e26cb8UL);
        assert(fn<unsigned short (*)(void *, void *)>(table[0])(engine, &device) == 0);
        assert(fn<unsigned short (*)(void *, void *)>(table[0xc / 4])(engine, &events) == 0);
        outputCalls = 0;
        unsigned code =
            fn<unsigned short (*)(void *, const char *)>(table[0x2c / 4])(engine, cases[i].path);
        std::printf("V8 native reader: %s -> %u\n", cases[i].path, code);
        assert(code == cases[i].expected);
        assert(cases[i].expected ? !outputCalls : outputCalls > 0);
        if (!code) {
            // The native read worker calls this decoder method with a timestamp
            // and an owned DecoderBuffer**. Drive it synchronously without its
            // threads or output device. V8's buffer length is at +12.
            void *decoder = 0;
            std::memcpy(&decoder, static_cast<char *>(engine) + 32, 4);
            assert(decoder);
            void **decoderTable = *static_cast<void ***>(decoder);
            assert(reinterpret_cast<unsigned long>(decoderTable[2]) -
                       reinterpret_cast<unsigned long>(create) ==
                   0x41e2b3c8UL - 0x41e26cb8UL);
            unsigned configured = outputCalls, blocks = 0, bytes = 0, timestamp = 0, terminal = 0;
            for (unsigned n = 0; n < 2048; ++n) {
                void *pcm = 0;
                unsigned result = fn<unsigned short (*)(void *, unsigned *, void **)>(
                    decoderTable[2])(decoder, &timestamp, &pcm);
                if (result) {
                    terminal = result;
                    break;
                }
                if (pcm) {
                    unsigned length = 0;
                    std::memcpy(&length, static_cast<char *>(pcm) + 12, 4);
                    assert(length <= 65536);
                    bytes += length;
                    ++blocks;
                }
            }
            assert(terminal == 4 && blocks > 0 && bytes > 0 && outputCalls == configured);
            std::printf("V8 native decoder: %u PCM blocks, %u bytes, normal EOF\n", blocks, bytes);
        }
        fn<void (*)(void *)>(destroy)(engine);
    }
    std::puts(
        "V8 alerts: all packaged MP3s decoded through EOF; short originals return 2 before any "
        "output call PASS");
}
