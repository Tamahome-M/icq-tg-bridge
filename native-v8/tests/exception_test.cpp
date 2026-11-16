// Regression for the SDK linker discarding live ARM exception/unwind tables.
#include "transport.h"
#include "oscar.h"
#include <assert.h>
#include <stdio.h>
struct Cancel : tmm::Cancellation {
    bool cancelled() const {
        return false;
    }
    int wakeFd() const {
        return -1;
    }
};
struct Cleanup {
    bool &done;
    explicit Cleanup(bool &value) : done(value) {}
    ~Cleanup() {
        done = true;
    }
};
int main() {
    Cancel cancel;
    tmm::Transport transport(cancel);
    unsigned caught = 0;
    bool cleaned = false;
    try {
        Cleanup cleanup(cleaned);
        transport.connect("invalid-ip", 5190, 0);
    } catch (const std::exception &e) {
        assert(*e.what());
        ++caught;
    }
    assert(cleaned);
    try {
        const std::string empty;
        tmm::wire::Reader reader(empty);
        reader.u32();
    } catch (const std::exception &e) {
        assert(*e.what());
        ++caught;
    }
    try {
        transport.read(65536, 0);
    } catch (const std::exception &e) {
        assert(*e.what());
        ++caught;
    }
    assert(caught == 3);
    puts("ARM exceptions: transport/parser errors caught across object files; cleanup ran");
}
