#ifndef TMM_NATIVE_INSTANCE_H
#define TMM_NATIVE_INSTANCE_H
#include <string>
namespace tmm {
// Handler only writes a nonblocking pipe. The UI consumes it on the Qt thread.
bool takeActivationRequest();
class Instance {
    int fd_;
    Instance(const Instance &);
    Instance &operator=(const Instance &);

  public:
    Instance() : fd_(-1) {}
    ~Instance();
    // 1: this process owns the lock, 0: existing instance activated, -1: error.
    int acquire(const std::string &directory, std::string &error);
};
} // namespace tmm
#endif
