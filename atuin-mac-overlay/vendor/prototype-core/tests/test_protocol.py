"""Transport contracts against arbitrary fragmentation and untrusted output."""

import random
import unittest

from atuin_ssh.protocol import Frame, FrameParser, MAX_FRAME, encode, response


NONCE = "a123456789abcdefa123456789abcdef"


class Framing(unittest.TestCase):
    def test_every_split_preserves_bytes_and_extracts_only_negotiated_frame(self):
        frame = Frame("REQUEST", 1, ("12", "ctrl-r", "é界\n'quote'\n", "4", "0", "emacs"))
        before = b"\x00\xff\x1b[32mordinary\r\n\x1b]133;A\x07"
        after = b"\x1bPunrelated DCS\x1b\\\x1b]0;window title\x07"
        wire = before + encode(NONCE, frame) + after
        for split in range(len(wire)+1):
            with self.subTest(split=split):
                parser = FrameParser(NONCE)
                result = parser.feed(wire[:split]) + parser.feed(wire[split:])
                result.append(parser.finish())
                self.assertEqual([part for part in result if isinstance(part, Frame)], [frame])
                self.assertEqual(b"".join(part for part in result if isinstance(part, bytes)), before+after)

    def test_byte_at_a_time_and_coalesced_events(self):
        frames = [Frame("HELLO", 1, ("host", "account", "/remote/path", "session", "bash")),
                  Frame("START", 2, ("1", "printf 'hello\\n'", "host")),
                  Frame("END", 3, ("1", "23", "1000000"))]
        wire = b"".join(encode(NONCE, frame) for frame in frames)
        for chunks in ([wire], [wire[i:i+1] for i in range(len(wire))]):
            parser = FrameParser(NONCE)
            self.assertEqual([part for chunk in chunks for part in parser.feed(chunk)], frames)

    def test_ordinary_random_transport_is_unchanged(self):
        source = random.Random(417).randbytes(80_000)
        parser = FrameParser(NONCE)
        parts = []
        for offset in range(0, len(source), 137):
            parts.extend(parser.feed(source[offset:offset+137]))
        parts.append(parser.finish())
        self.assertTrue(all(isinstance(part, bytes) for part in parts))
        self.assertEqual(b"".join(parts), source)

    def test_unnegotiated_malformed_stale_truncated_frames_stay_output(self):
        parser = FrameParser(NONCE)
        good = encode(NONCE, Frame("HELLO", 5, ("host",)))
        invalid = [encode("b"*32, Frame("HELLO", 6, ("other nonce",))),
                   encode(NONCE, Frame("UNKNOWN", 6, ("unknown",))),
                   encode(NONCE, Frame("START", 4, ("stale",))),
                   encode(NONCE, Frame("START", 6, ("nul\0inside",))),
                   good.replace(b";5;HELLO;", b";not-int;HELLO;"),
                   good.replace(b"686f7374", b"nothex"),
                   good[:-1]]
        self.assertEqual(parser.feed(good), [Frame("HELLO", 5, ("host",))])
        for wire in invalid[:-1]:
            self.assertEqual(parser.feed(wire), [wire])
        self.assertEqual(parser.feed(invalid[-1]), [])
        self.assertEqual(parser.finish(), invalid[-1])

    def test_oversized_frame_and_resynchronization(self):
        parser = FrameParser(NONCE)
        prefix = f"\x1b]777;atuin-ssh;1;{NONCE};".encode()
        oversized = prefix+b"1;START;"+b"41"*(MAX_FRAME//2)+b"\x07"
        good = Frame("HELLO", 2, ("next",))
        results = parser.feed(oversized+encode(NONCE, good))
        self.assertEqual(b"".join(item for item in results if isinstance(item, bytes)), oversized)
        self.assertEqual([item for item in results if isinstance(item, Frame)], [good])

    def test_selected_multiline_data_never_becomes_shell_syntax(self):
        selected = "'$(touch /tmp/never)'\n" + "界"*5000 + "\n\n"
        wire = response(NONCE, "7", "insert", selected)
        self.assertNotIn(b"touch /tmp/never", wire)
        lines = wire.splitlines()
        self.assertTrue(all(len(line) < 1200 for line in lines))
        self.assertEqual(lines[-1], f"!{NONCE}:7:DONE:insert".encode())
        encoded = b"".join(line.split(b":DATA:", 1)[1] for line in lines[:-1])
        self.assertEqual(bytes.fromhex(encoded.decode()).decode(), selected)
        with self.assertRaises(ValueError):
            response(NONCE, "7;rm", "insert", "")


if __name__ == "__main__":
    unittest.main()
