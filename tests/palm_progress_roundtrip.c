/* Validate the upstream streaming sender over a local socket, without IR.
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include <openobex/obex.h>
#include "obex_io.h"
#include "obex_put_common.h"
#include <sys/socket.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>

obex_t *handle;
volatile int finished;
static size_t expected_size;
static int received_ok;
extern volatile int last_rsp;

static void receiver(obex_t *self, obex_object_t *object, int mode,
                     int event, int command, int response)
{
    (void)mode; (void)command; (void)response;
    if (event == OBEX_EV_REQHINT)
        OBEX_ObjectSetRsp(object, OBEX_RSP_CONTINUE, OBEX_RSP_SUCCESS);
    if (event == OBEX_EV_REQ) {
        obex_headerdata_t data;
        uint8_t id;
        uint32_t length;
        while (OBEX_ObjectGetNextHeader(self, object, &id, &data, &length)) {
            if (id == OBEX_HDR_BODY || id == OBEX_HDR_BODY_END) {
                received_ok = length == expected_size;
                for (size_t n = 0; n < length; n++)
                    if (data.bs[n] != (uint8_t)(n % 251)) received_ok = 0;
            }
        }
        OBEX_ObjectSetRsp(object, OBEX_RSP_CONTINUE,
                         received_ok ? OBEX_RSP_SUCCESS : OBEX_RSP_BAD_REQUEST);
    }
}

int main(void)
{
    const size_t sizes[] = {1, 1024, 1025, 79026};
    for (size_t sample = 0; sample < sizeof(sizes)/sizeof(sizes[0]); sample++) {
        char filename[] = "/tmp/retromodem-obex-test-XXXXXX";
        int file = mkstemp(filename), sockets[2];
        if (file < 0 || socketpair(AF_UNIX, SOCK_STREAM, 0, sockets)) return 1;
        fcntl(sockets[0], F_SETFL, O_NONBLOCK);
        fcntl(sockets[1], F_SETFL, O_NONBLOCK);
        expected_size = sizes[sample];
        for (size_t n = 0; n < expected_size; n++) {
            uint8_t value = n % 251;
            if (write(file, &value, 1) != 1) return 2;
        }
        close(file);
        handle = OBEX_Init(OBEX_TRANS_FD, obex_event, 0);
        obex_t *server = OBEX_Init(OBEX_TRANS_FD, receiver, 0);
        if (!handle || !server) return 3;
        if (FdOBEX_TransportSetup(handle, sockets[0], sockets[0], 1024) < 0 ||
            FdOBEX_TransportSetup(server, sockets[1], sockets[1], 1024) < 0) return 4;
        received_ok = finished = 0;
        obex_object_t *object = build_object_from_file(handle, filename, 0x6c6e6368);
        if (!object || OBEX_Request(handle, object) < 0) return 5;
        for (int step = 0; step < 10000 && !finished; step++) {
            if (OBEX_HandleInput(handle, 0) < 0) return 6;
            if (!finished && OBEX_HandleInput(server, 0) < 0) return 6;
        }
        unlink(filename);
        if (!finished || !received_ok || last_rsp != OBEX_RSP_SUCCESS) return 7;
        OBEX_Cleanup(handle);
        OBEX_Cleanup(server);
        close(sockets[0]); close(sockets[1]);
    }
    puts("Palm progress roundtrip: all payloads byte-for-byte correct");
    return 0;
}
