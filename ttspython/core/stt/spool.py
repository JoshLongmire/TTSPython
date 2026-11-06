"""A recording on disk while it is being made, so that a crash or a power cut cannot lose it.

The recorder keeps the audio in memory too: this file is only read after a crash. It is deleted
as soon as the text has been delivered, or the recording thrown away. A plain 16-bit WAV file,
readable by anything, in a folder only this user can open. The sizes in its header are filled
in at the end, so read() goes by the file's size: after a crash they were never written.
"""
from __future__ import annotations

import contextlib
import logging
import os
import queue
import struct
import threading
import time
import uuid

import numpy as np

log = logging.getLogger(__name__)

HEADER_BYTES = 44
SYNC_SECONDS = 1.0  # at most this much is lost when the power goes
_PREFIX = "recording-"
_SUFFIX = ".wav"
_DELIVERED_SUFFIX = ".delivered"


def _header(rate, data_bytes):
    return struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", min(0xFFFFFFFF, 36 + data_bytes), b"WAVE", b"fmt ", 16, 1, 1, rate,
                       rate * 2, 2, 16, b"data", min(0xFFFFFFFF, data_bytes))


class Spool:
    """Takes int16 blocks without ever making the caller wait: the microphone's callback feeds it."""

    def __init__(self, folder, rate):
        os.makedirs(folder, mode=0o700, exist_ok=True)
        self.path = os.path.join(folder, f"{_PREFIX}{uuid.uuid4().hex[:12]}{_SUFFIX}")
        self.rate = rate
        self.written = 0  # samples
        self.failed = None
        self._discard = False
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._blocks = queue.SimpleQueue()  # the same arrays the recorder keeps, not copies
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        self._file = os.fdopen(fd, "wb", buffering=0)
        try:
            self._file.write(_header(rate, 0))
        except OSError:
            self._file.close()
            _remove(self.path)
            raise
        threading.Thread(target=self._run, name="dictation-spool", daemon=True).start()

    def feed(self, block):
        self._blocks.put(block)

    def finish(self):
        """No more audio. Returns at once; the file stays."""
        self._blocks.put(None)

    def discard(self):
        """Delete the file, now or as soon as the last block is written. Returns at once."""
        with self._lock:
            self._discard = True
            done = self._done.is_set()
        self._blocks.put(None)
        if done:
            _remove(self.path)

    def wait(self, timeout=None):
        return self._done.wait(timeout)

    def _write(self, data):
        self._file.write(data)

    def _sync(self):
        os.fsync(self._file.fileno())

    def _run(self):
        synced = time.monotonic()
        while True:
            try:
                block = self._blocks.get(timeout=SYNC_SECONDS)
            except queue.Empty:
                block = False
            if block is None:
                break
            if self.failed is not None or block is False:
                pass
            else:
                try:
                    self._write(block.tobytes())
                    self.written += block.size
                except OSError as exc:  # a full disk must not stop a recording, which is also in memory
                    self._fail(exc)
            if self.failed is None and time.monotonic() - synced >= SYNC_SECONDS:
                synced = time.monotonic()
                try:
                    self._sync()
                except OSError as exc:
                    self._fail(exc)
        self._close()

    def _fail(self, exc):
        self.failed = exc
        log.warning("Could not keep the recording on disk: %s", exc)

    def _close(self):
        try:
            if self.failed is None:
                self._file.seek(0)
                self._file.write(_header(self.rate, self.written * 2))
                self._sync()
        except OSError as exc:
            self._fail(exc)
        with contextlib.suppress(OSError):
            self._file.close()
        with self._lock:
            self._done.set()
            delete = self._discard or self.failed is not None
        if delete:
            _remove(self.path)


def _remove(path):
    with contextlib.suppress(OSError):
        os.remove(path)
    with contextlib.suppress(OSError):
        os.remove(path + _DELIVERED_SUFFIX)


def remove(path):
    _remove(path)


def mark_delivered(path, seconds):
    """Its first seconds have been typed already: a later Try again must not type them twice."""
    with contextlib.suppress(OSError), open(path + _DELIVERED_SUFFIX, "w", encoding="ascii") as f:
        f.write(f"{seconds:.3f}")


def delivered_seconds(path):
    try:
        with open(path + _DELIVERED_SUFFIX, encoding="ascii") as f:
            return max(0.0, float(f.read()))
    except (OSError, ValueError):
        return 0.0


def find(folder):
    """The recordings in folder, newest first."""
    try:
        names = [n for n in os.listdir(folder) if n.startswith(_PREFIX) and n.endswith(_SUFFIX)]
    except OSError:
        return []
    paths = [os.path.join(folder, n) for n in names]

    def age(path):
        try:
            return os.path.getmtime(path)
        except OSError:
            return 0

    return sorted(paths, key=age, reverse=True)


def remove_all(folder, keep=()):
    """keep: the paths to leave."""
    for path in find(folder):
        if path not in keep:
            _remove(path)


def _rate_of(path):
    """The sample rate in a recording's header, or None if this is not one of ours."""
    try:
        with open(path, "rb") as f:
            head = f.read(HEADER_BYTES)
    except OSError:
        return None
    if len(head) < HEADER_BYTES or head[:4] != b"RIFF" or head[8:12] != b"WAVE" or head[36:40] != b"data":
        return None
    rate = struct.unpack("<I", head[24:28])[0]
    return rate if 1000 <= rate <= 384000 else None


def seconds_in(path):
    """How long a recording is, going by the file's size. 0 if it is not one."""
    rate = _rate_of(path)
    if rate is None:
        return 0.0
    try:
        return max(0, os.path.getsize(path) - HEADER_BYTES) / 2 / rate
    except OSError:
        return 0.0


def read(path):
    """(int16 samples, rate), or None if the file is not a recording."""
    rate = _rate_of(path)
    if rate is None:
        return None
    try:
        return np.fromfile(path, dtype="<i2", offset=HEADER_BYTES), rate
    except (OSError, ValueError):
        return None
