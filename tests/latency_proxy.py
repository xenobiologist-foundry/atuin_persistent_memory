"""Bounded stdlib ProxyCommand fixture: delay each encrypted SSH direction.

Executed only on the hub by OpenSSH during an explicit disposable test. It adds
two one-way delays to the hub/destination transport; it runs no destination code
and needs no privileged network capabilities. This is latency injection, not a
complete bandwidth/loss/real-network emulator.
"""

import collections
import os
import select
import socket
import sys
import time


def main():
    host, port, delay = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]) / 1000
    connection = socket.create_connection((host, port), timeout=15)
    connection.setblocking(False)
    os.set_blocking(0, False)
    os.set_blocking(1, False)
    queues = {0: collections.deque(), connection.fileno(): collections.deque()}
    sizes = {0: 0, connection.fileno(): 0}
    output = {0: connection.fileno(), connection.fileno(): 1}
    opened = {0, connection.fileno()}
    shutdown = False
    while opened or any(queues.values()):
        now = time.monotonic()
        readers = [fd for fd in opened if sizes[fd] < 1_048_576]
        writers = [output[fd] for fd, queue in queues.items() if queue and queue[0][0] <= now]
        readable, writable, _ = select.select(readers, writers, [], .005)
        for fd in readable:
            try:
                payload = os.read(fd, 65536)
            except BlockingIOError:
                continue
            if not payload:
                opened.remove(fd)
            else:
                queues[fd].append([time.monotonic()+delay, payload])
                sizes[fd] += len(payload)
        for fd, queue in queues.items():
            if output[fd] in writable:
                try:
                    count = os.write(output[fd], queue[0][1])
                except BlockingIOError:
                    continue
                sizes[fd] -= count
                queue[0][1] = queue[0][1][count:]
                if not queue[0][1]:
                    queue.popleft()
        if 0 not in opened and not queues[0] and not shutdown:
            connection.shutdown(socket.SHUT_WR)
            shutdown = True
    connection.close()


if __name__ == "__main__":
    main()
