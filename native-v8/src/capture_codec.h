#ifndef TMM_NATIVE_CAPTURE_CODEC_H
#define TMM_NATIVE_CAPTURE_CODEC_H
namespace tmm {
// V8 stock AMR-NB codec: one 160-sample, signed 8 kHz mono PCM frame.
class AmrWriter {
  public:
    AmrWriter();
    ~AmrWriter();
    bool open(const char *path, unsigned bitrate = 6700);
    bool write(short *samples);
    bool close();
    unsigned error() const {
        return error_;
    }

  private:
    AmrWriter(const AmrWriter &);
    AmrWriter &operator=(const AmrWriter &);
    bool load();
    void *library_, *source_, *encoder_;
    unsigned error_;
};
} // namespace tmm
#endif
