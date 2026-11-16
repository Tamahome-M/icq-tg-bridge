// Runs against the user's extracted libraries under ARM QEMU. No display,
// camera, microphone, messages or phone-state changes are performed.
#include <qstring.h>
#include <qdatastream.h>
#include <qbuffer.h>
#include <dlfcn.h>
#include <cstring>
#include <cassert>
#include <cstdio>
template <class T> T fn(void *p) {
    assert(p);
    T f;
    std::memcpy(&f, &p, sizeof(f));
    return f;
}
int main() {
    void *lib = dlopen("libezxopenwindow.so.1", RTLD_NOW | RTLD_LOCAL);
    if (!lib) {
        std::puts(dlerror());
        return 1;
    }
    unsigned long memory[12];
    std::memset(memory, 0, sizeof(memory));
    memory[0] = 0x12345678;
    memory[11] = 0x87654321;
    void *data = memory + 1;
    QString title = QString::fromUtf8("Телеграм"), text = QString::fromUtf8("Новое сообщение"),
            empty("");
    typedef void (*Ctor)(void *, const QString &, const QString &, unsigned char, const QString &,
                         const QString &, const QString &, int);
    fn<Ctor>(dlsym(lib, "_ZN3CLI8InfoDataC1ERK7QStringS3_hS3_S3_S3_NS_15CLI_INFO_DLG_IDE"))(
        data, title, text, 0, empty, empty, empty, 18);
    assert(memory[0] == 0x12345678 && memory[11] == 0x87654321);
    assert(fn<bool (*)(void *)>(dlsym(lib, "_ZNK3CLI8InfoData10validationEv"))(data));
    assert(fn<bool (*)(void *)>(dlsym(lib, "_ZNK3CLI8InfoData16isSupportingTypeEv"))(data));
    QByteArray payload;
    QDataStream out(payload, IO_WriteOnly);
    fn<QDataStream &(*)(QDataStream &, const void *)>(
        dlsym(lib, "_ZN3CLIlsER11QDataStreamRKNS_8InfoDataE"))(out, data);
    QDataStream in(payload, IO_ReadOnly);
    QString a, b, left, right, image;
    Q_INT8 buttons;
    Q_INT32 id, progress, percentage;
    in >> a >> b >> buttons >> id >> left >> right >> image >> progress >> percentage;
    assert(a == title && b == text && buttons == 0 && id == 18 && left.isEmpty() &&
           right.isEmpty() && image.isEmpty() && progress == 0 && percentage == 0);
    fn<void (*)(void *)>(dlsym(lib, "_ZN3CLI8InfoDataD1Ev"))(data);
    assert(memory[0] == 0x12345678 && memory[11] == 0x87654321);
    std::puts("stock V8 InfoData: size, validation, Cyrillic wire payload PASS");
    return 0;
}
