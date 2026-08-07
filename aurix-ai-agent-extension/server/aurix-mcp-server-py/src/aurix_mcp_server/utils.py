"""Small helpers. Mirrors src/utils.ts."""

from __future__ import annotations

import os
import re

MAX_CAPTURE_BYTES = 64 * 1024


def ensure_directory(dir_path: str) -> str:
    resolved = os.path.abspath(dir_path)
    if not os.path.isdir(resolved):
        raise ValueError(f"Directory does not exist: {resolved}")
    return resolved


def parse_address(address: str) -> int:
    value = address.strip()
    if re.fullmatch(r"0x[0-9a-fA-F]+", value):
        return int(value[2:], 16)
    if re.fullmatch(r"[0-9]+", value):
        return int(value, 10)
    raise ValueError(f"Invalid address format: {address}")


def clamp_length(length: int, max_value: int = 4096) -> int:
    if not isinstance(length, int) or length <= 0:
        raise ValueError("length must be a positive integer")
    if length > max_value:
        raise ValueError(f"length exceeds max ({max_value})")
    return length


def to_hex(buffer: bytes) -> str:
    return buffer.hex()


def safe_error_message(error: BaseException) -> str:
    return str(error)


class LimitedBuffer:
    """Accumulates bytes up to MAX_CAPTURE_BYTES, mirroring appendLimited."""

    def __init__(self, max_bytes: int = MAX_CAPTURE_BYTES) -> None:
        self._chunks: list[bytes] = []
        self._size = 0
        self._max = max_bytes

    def append(self, chunk: bytes) -> None:
        if self._size >= self._max:
            return
        remaining = self._max - self._size
        piece = chunk[:remaining]
        self._chunks.append(piece)
        self._size += len(piece)

    def text(self, encoding: str = "utf-8") -> str:
        return b"".join(self._chunks).decode(encoding, errors="replace")
