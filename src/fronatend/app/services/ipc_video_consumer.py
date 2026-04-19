from __future__ import annotations

import mmap
import os
import struct
from dataclasses import dataclass

from PySide6.QtGui import QImage, QPixmap

_MAGIC = b"MOOVIPC1"
_HEADER_SIZE = 64
_SLOT_HEADER_SIZE = 16


@dataclass(frozen=True)
class IPCHeader:
    width: int
    height: int
    pixel_format: str
    slot_count: int
    slot_size: int


class IPCVideoConsumer:
    def __init__(self, path: str) -> None:
        self._path = path
        self._fd: int | None = None
        self._mmap: mmap.mmap | None = None
        self._header: IPCHeader | None = None
        self._last_seq = 0
        self._last_frame_counter = 0

    def open(self) -> None:
        self.close()
        self._fd = os.open(self._path, os.O_RDONLY)
        file_size = os.path.getsize(self._path)
        self._mmap = mmap.mmap(self._fd, file_size, access=mmap.ACCESS_READ)
        self._header = self._read_header()

    def close(self) -> None:
        if self._mmap is not None:
            self._mmap.close()
            self._mmap = None
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        self._header = None
        self._last_seq = 0
        self._last_frame_counter = 0

    def read_latest_pixmap(self) -> QPixmap | None:
        if self._mmap is None or self._header is None:
            return None

        write_index = struct.unpack_from("<Q", self._mmap, 40)[0]
        frame_counter = struct.unpack_from("<Q", self._mmap, 48)[0]
        if frame_counter == 0:
            return None
        if frame_counter < self._last_frame_counter:
            # Writer restarted and reset counters.
            self._last_seq = 0
            self._last_frame_counter = 0

        # Try newest slot first, then fall back to older slots if the newest
        # one is being written concurrently.
        for offset in range(self._header.slot_count):
            slot_index = int((write_index - offset) % self._header.slot_count)
            slot_offset = _HEADER_SIZE + slot_index * (
                _SLOT_HEADER_SIZE + self._header.slot_size
            )
            seq_before = struct.unpack_from("<Q", self._mmap, slot_offset)[0]
            if seq_before == 0 or seq_before <= self._last_seq:
                continue

            size = struct.unpack_from("<I", self._mmap, slot_offset + 8)[0]
            if size <= 0 or size > self._header.slot_size:
                continue

            payload_start = slot_offset + _SLOT_HEADER_SIZE
            data = self._mmap[payload_start : payload_start + size]
            seq_after = struct.unpack_from("<Q", self._mmap, slot_offset)[0]
            if seq_after != seq_before:
                continue

            pixmap = self._to_pixmap(bytes(data), self._header)
            if pixmap is None:
                continue

            self._last_seq = seq_after
            self._last_frame_counter = frame_counter
            return pixmap
        return None

    def _read_header(self) -> IPCHeader:
        if self._mmap is None:
            raise RuntimeError("IPC mmap is not open")

        magic = self._mmap[0:8]
        if magic != _MAGIC:
            raise RuntimeError("invalid IPC magic")

        width = struct.unpack_from("<I", self._mmap, 12)[0]
        height = struct.unpack_from("<I", self._mmap, 16)[0]
        pixel_raw = self._mmap[20:36]
        pixel_format = pixel_raw.split(b"\x00", 1)[0].decode("utf-8", errors="ignore")
        slot_count = struct.unpack_from("<I", self._mmap, 36)[0]
        slot_size = struct.unpack_from("<I", self._mmap, 56)[0]

        if width <= 0 or height <= 0 or slot_count <= 0 or slot_size <= 0:
            raise RuntimeError("invalid IPC header")

        return IPCHeader(
            width=int(width),
            height=int(height),
            pixel_format=pixel_format,
            slot_count=int(slot_count),
            slot_size=int(slot_size),
        )

    def _to_pixmap(self, data: bytes, header: IPCHeader) -> QPixmap | None:
        if header.pixel_format == "rgb24":
            bytes_per_line = header.width * 3
            expected = bytes_per_line * header.height
            if len(data) < expected:
                return None
            image = QImage(
                data,
                header.width,
                header.height,
                bytes_per_line,
                QImage.Format.Format_RGB888,
            )
            return QPixmap.fromImage(image.copy())

        if header.pixel_format == "rgba":
            bytes_per_line = header.width * 4
            expected = bytes_per_line * header.height
            if len(data) < expected:
                return None
            image = QImage(
                data,
                header.width,
                header.height,
                bytes_per_line,
                QImage.Format.Format_RGBA8888,
            )
            return QPixmap.fromImage(image.copy())

        if header.pixel_format == "yuv420p" and hasattr(
            QImage.Format, "Format_YUV420P"
        ):
            expected = (header.width * header.height * 3) // 2
            if len(data) < expected:
                return None
            image = QImage(
                data, header.width, header.height, QImage.Format.Format_YUV420P
            )
            return QPixmap.fromImage(image.copy())

        return None
