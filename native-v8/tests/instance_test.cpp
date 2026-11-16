#include "instance.h"
#include <assert.h>
#include <sys/wait.h>
#include <unistd.h>
#include <signal.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
int main(int argc, char **argv) {
    std::string error;
    if (argc == 3 && strcmp(argv[1], "--activate") == 0) {
        tmm::Instance other;
        return other.acquire(argv[2], error) == 0 ? 0 : 2;
    }
    char path[] = "/tmp/tmm-instance-XXXXXX";
    assert(mkdtemp(path));
    tmm::Instance owner;
    assert(owner.acquire(path, error) == 1);
    assert(!tmm::takeActivationRequest());
    pid_t child = fork();
    assert(child >= 0);
    if (child == 0) {
        execl(argv[0], argv[0], "--activate", path, (char *)0);
        _exit(3);
    }
    int result = 0;
    while (waitpid(child, &result, 0) < 0) {
    }
    assert(WIFEXITED(result) && WEXITSTATUS(result) == 0);
    assert(tmm::takeActivationRequest());
    assert(!tmm::takeActivationRequest());
    for (unsigned i = 0; i < 100; ++i)
        raise(SIGUSR1);
    assert(tmm::takeActivationRequest());
    assert(!tmm::takeActivationRequest());
    printf("single-instance restore OK\n");
    return 0;
}
