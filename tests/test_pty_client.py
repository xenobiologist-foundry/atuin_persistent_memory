"""Check the test terminal's query responses against a real child PTY."""

import json
import os
import sys
import unittest

from pty_client import PTYClient


@unittest.skipUnless(os.name == "posix", "Linux PTY required")
class TestTerminalQueries(unittest.TestCase):
    def test_coalesced_and_split_terminal_queries_have_exactly_one_response(self):
        script = r'''
import json, os, select, time, tty
tty.setraw(0)
os.write(1, b"\x1b[6n\x1b[c")
time.sleep(.04)
os.write(1, b"unrelated-output")
time.sleep(.04)
os.write(1, b"\x1b[")
time.sleep(.04)
os.write(1, b"6n\x1b")
time.sleep(.04)
os.write(1, b"[c")
time.sleep(.04)
os.write(1, b"more-output")
received=b""
deadline=time.monotonic()+.3
while time.monotonic()<deadline:
    if select.select([0],[],[],.01)[0]: received+=os.read(0,4096)
report={"cursor":received.count(b"\x1b[1;1R"),"attributes":received.count(b"\x1b[?1;2c")}
os.write(1,b"__REPORT__"+json.dumps(report).encode()+b"__END__")
'''
        client = PTYClient([sys.executable, "-c", script])
        self.addCleanup(client.close)
        client.expect(b"__REPORT__")
        result = client.expect(b"__END__")
        self.assertEqual(json.loads(result.string[:result.start()]), {"cursor": 2, "attributes": 2})


if __name__ == "__main__":
    unittest.main()
