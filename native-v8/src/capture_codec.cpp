#include "capture_codec.h"
#include <dlfcn.h>
#include <cstdlib>
#include <cstring>
namespace tmm {
namespace {
template <class T> T fn(void *p) {
    T f;
    std::memcpy(&f, &p, sizeof(f));
    return f;
}
typedef void (*Destroy)(void *);
typedef unsigned short (*Close)(void *);
} // namespace
AmrWriter::AmrWriter() : library_(0), source_(0), encoder_(0), error_(0) {}
AmrWriter::~AmrWriter() {
    close();
    if (library_)
        dlclose(library_);
}
bool AmrWriter::load() {
    if (!library_)
        library_ = dlopen("libezxamr.so.1", RTLD_NOW | RTLD_LOCAL);
    if (!library_ || sizeof(void *) != 4)
        return false;
    const char *symbols[] = {"_ZN16CODEC_FileSourceC1EPKcRtb",
                             "_ZN16CODEC_FileSourceD1Ev",
                             "_ZN14CE_AMR_EncoderC1Ev",
                             "_ZN14CE_AMR_EncoderD1Ev",
                             "_ZN14CE_AMR_Encoder4openEP18CODEC_StreamSource",
                             "_ZN14CE_AMR_Encoder10setBitRateEj",
                             "_ZN14CE_AMR_Encoder17putNextAudioFrameEPsj",
                             "_ZN14CE_AMR_Encoder5closeEv"};
    for (unsigned i = 0; i < sizeof(symbols) / sizeof(symbols[0]); ++i)
        if (!dlsym(library_, symbols[i]))
            return false;
    // Exact sizes from stock VoiceNote, pinned to native constructor/vtable pairs.
    void *table = dlsym(library_, "_ZTV14CE_AMR_Encoder"),
         *files = dlsym(library_, "_ZTV16CODEC_FileSource");
    return table && files &&
           reinterpret_cast<unsigned long>(dlsym(library_, symbols[2])) -
                   reinterpret_cast<unsigned long>(table) ==
               0x426ab4ccUL - 0x426d4238UL &&
           reinterpret_cast<unsigned long>(dlsym(library_, symbols[0])) -
                   reinterpret_cast<unsigned long>(files) ==
               0x426ad04cUL - 0x426d4328UL;
}
bool AmrWriter::open(const char *path, unsigned bitrate) {
    close();
    error_ = 0;
    if (!path || !load()) {
        error_ = 100;
        return false;
    }
    const unsigned rates[] = {4750, 5150, 5900, 6700, 7400, 7950, 10200, 12200};
    bool rate = false;
    for (unsigned i = 0; i < 8; ++i)
        if (rates[i] == bitrate)
            rate = true;
    if (!rate) {
        error_ = 101;
        return false;
    }
    source_ = std::calloc(1, 20);
    encoder_ = std::calloc(1, 76);
    if (!source_ || !encoder_) {
        std::free(source_);
        std::free(encoder_);
        source_ = encoder_ = 0;
        error_ = 102;
        return false;
    }
    unsigned short code = 0;
    fn<void (*)(void *, const char *, unsigned short &, bool)>(
        dlsym(library_, "_ZN16CODEC_FileSourceC1EPKcRtb"))(source_, path, code, true);
    fn<void (*)(void *)>(dlsym(library_, "_ZN14CE_AMR_EncoderC1Ev"))(encoder_);
    if (!code)
        code = fn<unsigned short (*)(void *, void *)>(
            dlsym(library_, "_ZN14CE_AMR_Encoder4openEP18CODEC_StreamSource"))(encoder_, source_);
    if (code) {
        error_ = code;
        close();
        return false;
    }
    fn<void (*)(void *, unsigned)>(dlsym(library_, "_ZN14CE_AMR_Encoder10setBitRateEj"))(encoder_,
                                                                                         bitrate);
    return true;
}
bool AmrWriter::write(short *samples) {
    if (!encoder_ || error_ || !samples)
        return false;
    error_ = fn<unsigned short (*)(void *, short *, unsigned)>(
        dlsym(library_, "_ZN14CE_AMR_Encoder17putNextAudioFrameEPsj"))(encoder_, samples, 0);
    return !error_;
}
bool AmrWriter::close() {
    if (encoder_) {
        unsigned short result = fn<Close>(dlsym(library_, "_ZN14CE_AMR_Encoder5closeEv"))(encoder_);
        if (result && !error_)
            error_ = result;
        fn<Destroy>(dlsym(library_, "_ZN14CE_AMR_EncoderD1Ev"))(encoder_);
        std::free(encoder_);
        encoder_ = 0;
    }
    if (source_) {
        fn<Destroy>(dlsym(library_, "_ZN16CODEC_FileSourceD1Ev"))(source_);
        std::free(source_);
        source_ = 0;
    }
    return !error_;
}
} // namespace tmm
