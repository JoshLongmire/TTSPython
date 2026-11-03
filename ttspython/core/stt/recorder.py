"""In-memory microphone recorder with a live level for the waveform."""
from __future__ import annotations

import threading

import numpy as np

SAMPLE_RATE = 16000
MAX_SECONDS = 30 * 60


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


def resample(samples, src_rate, dst_rate):
    if src_rate == dst_rate or samples.size == 0:
        return samples
    n = max(1, int(round(samples.size * dst_rate / src_rate)))
    return np.interp(np.linspace(0.0, samples.size - 1, n), np.arange(samples.size), samples).astype(np.float32)


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
        self._stream = None
        self.level = 0.0
        self.on_limit = None
        self.on_block = None  # gets each captured block (int16 at capture_rate): the instant preview

    @property
    def capture_rate(self):
        return self._capture_rate

    @property
    def sd(self):
        if self._sd is None:
            import sounddevice

            self._sd = sounddevice
        return self._sd

    @property
    def recording(self):
        return self._stream is not None

    def start(self, device=None):
        if self._stream is not None:
            return
        with self._lock:
            self._blocks = []
            self._frames = 0
            self._limit_fired = False
        stream, rate = open_input_stream(self.sd, device, self.sample_rate, self._callback)
        self._capture_rate = rate
        self._max_frames = int(rate * self._max_seconds)
        try:
            stream.start()
        except Exception:
            try:
                stream.close()
            except Exception:
                pass
            raise
        self._stream = stream

    def _callback(self, indata, frames, _time, _status):
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
        """int16 blocks -> float32 in [-1, 1] at sample_rate, without extra full-size copies."""
        if not blocks:
            return np.zeros(0, dtype=np.float32)
        audio = np.concatenate(blocks).astype(np.float32)
        audio *= 1.0 / 32768.0
        return resample(audio, self._capture_rate, self.sample_rate)

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
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        self.level = 0.0
        with self._lock:
            blocks, self._blocks = self._blocks, []
            self._frames = 0
        audio = self._to_float(blocks)
        del blocks
        return audio
