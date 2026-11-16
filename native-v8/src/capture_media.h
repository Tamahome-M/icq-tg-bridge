#ifndef TMM_NATIVE_CAPTURE_MEDIA_H
#define TMM_NATIVE_CAPTURE_MEDIA_H
namespace tmm {
// Bounded metadata reader; no decoder or audio device is opened. Returns zero
// for malformed, unsupported or excessively large files.
unsigned captureDuration(const char *path);
} // namespace tmm
#endif
