"""Bounded zsh history decoding. History text is data and is never evaluated."""
from __future__ import annotations
from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat

from atuin_ssh.atuin import MAX_COMMAND_BYTES
from atuin_ssh.importing import HistoryEntry, ImportLedger


@dataclass(frozen=True)
class ZshEntry(HistoryEntry):
    duration_ns: int = -1


def parse_zsh_history(raw: bytes, max_entries=100000):
    decoded = bytearray()
    index = 0
    while index < len(raw):
        byte = raw[index]
        if byte == 0x83:
            index += 1
            if index == len(raw):
                raise ValueError("incomplete zsh meta byte")
            byte = raw[index] ^ 32
        decoded.append(byte)
        index += 1
    if b"\0" in decoded:
        raise ValueError("unrepresentable NUL in zsh history")
    text = decoded.decode("utf-8", "strict")
    records = []
    pending = ""
    start = 1
    lines = text.split("\n")
    for number, line in enumerate(lines, 1):
        if not pending:
            start = number
        if number < len(lines) and line.endswith("\\"):
            pending += line[:-1] + "\n"
            continue
        record = pending + line
        pending = ""
        if not record:
            continue
        match = re.match(r"^: (-?\d+):(\d+);", record)
        command = record[match.end():] if match else record
        if len(command.encode("utf-8")) > MAX_COMMAND_BYTES:
            raise ValueError("zsh command exceeds bound")
        records.append(ZshEntry(command, str(int(match[1])*1000000000) if match else None,
                                start, match is None, int(match[2])*1000000000 if match else -1))
        if len(records) > max_entries:
            raise ValueError("history exceeds maximum entries")
    if pending:
        raise ValueError("incomplete multiline zsh history")
    return records


def import_local(**options):
    configured = os.environ.get("ATUIN_LAYER_HISTFILE", os.environ.get("HISTFILE", ""))
    if not configured:
        raise ValueError("run local import in the entry shell so its configured HISTFILE is known")
    target = Path(configured).expanduser().absolute()
    maximum = options["max_bytes"]
    descriptor = os.open(target, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum:
            raise ValueError("invalid history file type or size")
        content = stream.read(maximum + 1)
    if len(content) > maximum:
        raise ValueError("history exceeds bound")
    source = dict(target="local", host=os.environ["ATUIN_HOST_NAME"], user=os.environ["ATUIN_HOST_USER"],
                  histfile=str(target), shell="zsh")
    return ImportLedger().import_bytes(source, content, **options)
