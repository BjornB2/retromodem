/* Keep the IrDA modem discovery hints advertised for Windows IrEnum. */
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#include "irda.h"

static volatile sig_atomic_t running = 1;

static void stop(int signo)
{
    (void)signo;
    running = 0;
}

int main(void)
{
    int fd;
    int hints;
    struct sigaction action;

    fd = socket(AF_IRDA, SOCK_STREAM, 0);
    if (fd < 0) {
        fprintf(stderr, "irda-modem-hints: socket: %s\n", strerror(errno));
        return 1;
    }

    /* The extension bit makes the second hint byte (IrCOMM) significant. */
    hints = HINT_MODEM | HINT_COMPUTER | HINT_EXTENSION |
        (HINT_COMM << 8);
    if (setsockopt(fd, SOL_IRLMP, IRLMP_HINTS_SET,
                   &hints, sizeof(hints)) < 0) {
        fprintf(stderr, "irda-modem-hints: setsockopt: %s\n",
                strerror(errno));
        close(fd);
        return 1;
    }

    memset(&action, 0, sizeof(action));
    action.sa_handler = stop;
    sigemptyset(&action.sa_mask);
    sigaction(SIGTERM, &action, NULL);
    sigaction(SIGINT, &action, NULL);

    while (running)
        pause();

    close(fd);
    return 0;
}
