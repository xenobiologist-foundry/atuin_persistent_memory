/* No Python post-fork path: posix_spawn execs this controlling-PTY adapter. */
#include <sys/ioctl.h>
#include <unistd.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv) {
    if (argc < 2) return 64;
    if (setsid() == -1 || ioctl(STDIN_FILENO, TIOCSCTTY, 0) == -1) {
        perror("atuin-layer: controlling terminal"); return 126;
    }
    signal(SIGTTOU, SIG_IGN);
    if (tcsetpgrp(STDIN_FILENO, getpgrp()) == -1) return 126;
    signal(SIGTTOU, SIG_DFL);
    execvp(argv[1], argv + 1);
    perror("atuin-layer: child executable");
    return 127;
}
