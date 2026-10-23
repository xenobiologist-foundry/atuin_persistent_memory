"""Bounded, byte-preserving in-band protocol. Ordinary PTY bytes stay bytes."""
from dataclasses import dataclass
import re

MAX_FRAME = 1_048_576
KINDS = {"HELLO", "REQUEST", "HANDOVER", "START", "END", "PROMPT", "DEGRADED", "BYE", "ABORT", "RELEASE"}


@dataclass(frozen=True)
class Frame:
    kind: str
    sequence: int
    fields: tuple[str, ...]


def encode(nonce: str, frame: Frame) -> bytes:
    fields = b";".join(s.encode("utf-8", "surrogateescape").hex().encode() for s in frame.fields)
    return f"\x1b]777;atuin-ssh;1;{nonce};{frame.sequence};{frame.kind};".encode() + fields + b"\x07"


class FrameParser:
    def __init__(self, nonce: str):
        if not re.fullmatch(r"[a-f0-9]{32}", nonce):
            raise ValueError("invalid nonce")
        self.prefix = f"\x1b]777;atuin-ssh;1;{nonce};".encode()
        self.buffer = bytearray()
        self.sequence = 0

    def feed(self, data: bytes) -> list[bytes | Frame]:
        self.buffer.extend(data)
        result = []
        while self.buffer:
            start = self.buffer.find(self.prefix)
            if start < 0:
                keep = 0
                for n in range(1, min(len(self.buffer), len(self.prefix) - 1) + 1):
                    if self.buffer[-n:] == self.prefix[:n]:
                        keep = n
                count = len(self.buffer) - keep
                if count:
                    result.append(bytes(self.buffer[:count]))
                    del self.buffer[:count]
                break
            if start:
                result.append(bytes(self.buffer[:start]))
                del self.buffer[:start]
            end = self.buffer.find(7, len(self.prefix))
            if end < 0:
                if len(self.buffer) > MAX_FRAME:
                    result.append(bytes(self.buffer[:1]))
                    del self.buffer[:1]
                    continue
                break
            raw = bytes(self.buffer[:end + 1])
            del self.buffer[:end + 1]
            try:
                if len(raw) > MAX_FRAME:
                    raise ValueError("oversized")
                parts = raw[len(self.prefix):-1].decode("ascii").split(";")
                sequence = int(parts[0])
                kind = parts[1]
                if sequence <= self.sequence or kind not in KINDS:
                    raise ValueError("stale or unknown")
                fields = tuple(bytes.fromhex(s).decode("utf-8", "surrogateescape") for s in parts[2:])
                if any("\0" in field for field in fields):
                    raise ValueError("Bash strings cannot contain NUL")
                self.sequence = sequence
                result.append(Frame(kind, sequence, fields))
            except (ValueError, IndexError, UnicodeError):
                result.append(raw)
        return result

    def finish(self) -> bytes:
        data = bytes(self.buffer)
        self.buffer.clear()
        return data


def response(nonce: str, request: str, action: str, command: str = "") -> bytes:
    if action not in {"insert", "accept", "cancel"} or not re.fullmatch(r"[0-9]+", request):
        raise ValueError("invalid response")
    encoded = command.encode("utf-8", "surrogateescape").hex()
    prefix = f"!{nonce}:{request}:"
    chunks = [f"{prefix}DATA:{encoded[i:i+1024]}\n" for i in range(0, len(encoded), 1024)]
    chunks.append(f"{prefix}DONE:{action}\n")
    return "".join(chunks).encode()
