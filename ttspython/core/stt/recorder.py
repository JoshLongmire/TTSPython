"""Microphone recorder with a live level for the waveform. The audio is kept in memory; if given a
folder, it also goes to a file there as it is said (spool.py), so that a crash cannot lose it."""
from __future__ import annotations

import contextlib
import logging
import threading
import time

import numpy as np

from ..resample import StreamResampler
from .spool import Spool

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
MAX_SECONDS = 30 * 60
NO_SOUND_SECONDS = 3      # a microphone that gives nothing for this long has gone (unplugged, or its driver stopped)...
FIRST_SOUND_SECONDS = 10  # ...though one that is starting up (Bluetooth) can take this long


def blocks_to_float(blocks, rate, target):
    """int16 blocks at rate -> float32 in [-1, 1] at target, without extra full-size copies."""
    if not blocks:
        return np.zeros(0, dtype=np.float32)
    if rate == target:
        audio = np.concatenate(blocks).astype(np.float32)
        audio *= 1.0 / 32768.0
        return audio
    # Block by block: all at once took 146 MB for 2 minutes of recording, which grows with its length.
    converter = StreamResampler(rate, target)
    parts = [converter.feed(block.astype(np.float32) * (1.0 / 32768.0)) for block in blocks]
    parts.append(converter.finish())
    return np.concatenate(parts)


def open_input_stream(sd, device, sample_rate, callback, dtype="int16", blocksize=1024):
    """Open an input stream at sample_rate, or at the device's own rate when it refuses that
    (WASAPI and ALSA hw devices only run at their configured rate). Returns (stream, rate)."""
    try:
        return sd.InputStream(samplerate=sample_rate, channels=1, dtype=dtype, blocksize=blocksize,
                              device=device, callback=callback), sample_rate
    except Exception:
        info = sd.query_devices(device, "input")
        rate = int(info.get("default_samplerate") or 0)
        if not rate or rate == sample_rate:
            raise
        size = max(256, int(blocksize * rate / sample_rate))
        return sd.InputStream(samplerate=rate, channels=1, dtype=dtype, blocksize=size,
                              device=device, callback=callback), rate


class Recorder:
    def __init__(self, sd_module=None, sample_rate=SAMPLE_RATE, max_seconds=MAX_SECONDS):
        self._sd = sd_module
        self.sample_rate = sample_rate
        self._max_seconds = max_seconds
        self._capture_rate = sample_rate
        self._max_frames = int(sample_rate * max_seconds)
        self._lock = threading.Lock()
        self._blocks = []
        self._frames = 0
        self._limit_fired = False
        self._last_block = None
        self._stream = None
        self.level = 0.0
        self.on_limit = None
        self.on_lost = None   # the microphone stopped giving audio, without any error
        self.on_block = None  # gets each captured block (int16 at capture_rate): the instant preview
        self.spool_folder = None  # where the recording also goes as it is said (None: memory only)
        self.spool = None

    @property
    def capture_rate(self):
        return self._capture_rate

    @property
    def sd(self):
        if self._sd is None:
            import sounddevice

            self._sd = sounddevice
        return self._sd

    def start(self, device=None):
        if self._stream is not None:
            return
        self._last_block = None
        stream, rate = open_input_stream(self.sd, device, self.sample_rate, self._callback)
        with self._lock:
            before = self._blocks, self._frames
            self._blocks = []
            self._frames = 0
            self._limit_fired = False
        self._capture_rate = rate
        self._max_frames = int(rate * self._max_seconds)
        self.spool = self._open_spool(rate)
        try:
            stream.start()
        except Exception:
            with contextlib.suppress(Exception):
                stream.close()
            if self.spool is not None:
                self.spool.discard()
                self.spool = None
            with self._lock:  # a microphone that will not start leaves the last recording alone
                self._blocks, self._frames = before
            raise
        self._stream = stream
        threading.Thread(target=self._watch, args=(stream,), name="mic-watch", daemon=True).start()

    def _open_spool(self, rate):
        if not self.spool_folder:
            return None
        try:
            return Spool(self.spool_folder, rate)
        except OSError as exc:  # the recording still works, in memory
            log.warning("Could not keep the recording on disk: %s", exc)
            return None

    def _watch(self, stream):
        started = time.monotonic()
        while self._stream is stream:
            time.sleep(min(0.25, NO_SOUND_SECONDS / 2))
            last = self._last_block
            silent = time.monotonic() - last > NO_SOUND_SECONDS if last else time.monotonic() - started > FIRST_SOUND_SECONDS
            if silent and self._stream is stream:
                if self.on_lost:
                    self.on_lost()
                return

    def _callback(self, indata, frames, _time, _status):
        self._last_block = time.monotonic()
        block = indata[:, 0].copy()
        limit_hit = kept = False
        with self._lock:
            if self._frames >= self._max_frames:
                limit_hit = not self._limit_fired
                self._limit_fired = True
            else:
                self._blocks.append(block)
                self._frames += frames
                kept = True
        spool = self.spool
        if spool is not None and kept:
            spool.feed(block)
        on_block = self.on_block
        if on_block is not None and kept:
            on_block(block)
        if block.size:
            x = block.astype(np.float32)
            rms = float(np.sqrt(np.dot(x, x) / block.size)) / 32768.0
        else:
            rms = 0.0
        self.level = min(1.0, rms * 6.0)
        if limit_hit and self.on_limit:
            # Never stop a stream from inside its own callback.
            threading.Thread(target=self.on_limit, daemon=True).start()

    def _to_float(self, blocks):
        return blocks_to_float(blocks, self._capture_rate, self.sample_rate)

    def snapshot(self, start=0):
        """Audio captured so far from sample start (at sample_rate), without stopping."""
        with self._lock:
            blocks = list(self._blocks)
        # Skip whole blocks before start so a long recording is not converted again each time.
        skip = int(start * self._capture_rate / self.sample_rate)
        first = 0
        while first < len(blocks) and skip >= blocks[first].size:
            skip -= blocks[first].size
            first += 1
        if first < len(blocks) and skip:
            blocks = [blocks[first][skip:]] + blocks[first + 1:]
        else:
            blocks = blocks[first:]
        return self._to_float(blocks)

    def stop(self):
        """Stop and return float32 samples in [-1, 1] (empty if nothing captured)."""
        self.stop_capture()
        return self.take_audio()

    def stop_capture(self):
        """The microphone closes now. take_audio then gives what it heard; for half an hour at 48 kHz
        that takes over 2 s, which is not for the window's thread."""
        stream, self._stream = self._stream, None
        if stream is not None:
            with contextlib.suppress(Exception):
                stream.stop()
                stream.close()
            if self.spool is not None:
                self.spool.finish()
        self.level = 0.0

    def take_audio(self):
        with self._lock:
            blocks = list(self._blocks)
        audio = self._to_float(blocks)  # the blocks stay until this has worked
        self.drop_audio()
        return audio

    def drop_audio(self):
        with self._lock:
            self._blocks = []
            self._frames = 0
