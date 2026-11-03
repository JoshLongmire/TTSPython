"""Change the speed of speech audio without changing its pitch (WSOLA).

Engines speak at a few fixed rates (SAPI has 21 steps); the player stretches the
difference so every speed step is heard. Playback uses Stretcher, which works one
10 ms hop at a time and reads the speed at every hop, so a slider is heard while it
is being dragged. stretch() does a whole buffer at once (export).
"""
from __future__ import annotations

import numpy as np

FRAME_SECONDS = 0.02    # overlap-add frame (50% overlap)
SEARCH_SECONDS = 0.006  # how far a frame may shift to line up with the previous one
DEAD_ZONE = 0.04        # within 4% of the engine's own rate the audio is left untouched (100% on SAPI is 3.6% off)


def speed_factor(target_wpm, native_wpm):
    """How much faster than rendered to play; 1.0 inside the dead zone or when unknown."""
    if not target_wpm or not native_wpm:
        return 1.0
    factor = float(target_wpm) / float(native_wpm)
    return 1.0 if abs(factor - 1.0) <= DEAD_ZONE else factor


def stretch(x, factor, rate):
    """Return x played factor times faster (factor > 1 shortens it), same pitch.

    x: float32 mono samples at rate Hz. Output length is round(len(x) / factor).
    """
    x = np.asarray(x, dtype=np.float32)
    if x.size == 0 or abs(factor - 1.0) < 1e-3:
        return x
    n = max(16, int(rate * FRAME_SECONDS) // 2 * 2)
    hs = n // 2                       # synthesis hop
    ha = hs * float(factor)           # analysis hop
    tol = max(1, int(rate * SEARCH_SECONDS))
    step = 2 if rate >= 16000 else 1  # the alignment search runs on every 2nd sample
    win = _window(n)
    out_len = int(round(x.size / factor))
    out = np.zeros(out_len + 2 * n, dtype=np.float32)
    weight = np.zeros_like(out)
    pad = np.concatenate([np.zeros(tol, np.float32), x, np.zeros(2 * n + 2 * tol, np.float32)])
    prev = None
    k = 0
    while True:
        ideal = int(round(k * ha))
        pos = k * hs
        if ideal >= x.size or pos >= out_len:
            break
        if prev is None:
            start = ideal
        else:
            # The frame that would naturally follow the previous one: find the input
            # offset near "ideal" that lines up with it best.
            natural = prev + hs
            ref = pad[natural + tol:natural + tol + n:step]
            region = pad[ideal:ideal + n + 2 * tol:step]
            corr = np.correlate(region, ref, mode="valid")
            start = ideal - tol + int(np.argmax(corr)) * step
        frame = pad[start + tol:start + tol + n]
        out[pos:pos + n] += frame * win
        weight[pos:pos + n] += win
        prev = start
        k += 1
    weight[weight < 1e-3] = 1.0
    return (out[:out_len] / weight[:out_len]).astype(np.float32)


class Stretcher:
    """Plays one buffer at a speed that may change at any moment (streaming WSOLA).

    Each hop outputs half a frame: the overlap of the previous frame's second half and
    the next frame's first half (periodic Hann windows at 50% overlap sum to 1). The next
    frame is taken near pos, shifted to line up with the audio that naturally follows
    the previous frame. At speed 1.0 that natural frame is used as is, which gives the
    original samples back exactly, so moving in and out of the dead zone is seamless.
    """

    def __init__(self, x, rate):
        self.x = np.asarray(x, dtype=np.float32)
        self.n = max(16, int(rate * FRAME_SECONDS) // 2 * 2)
        self.hs = self.n // 2
        self.tol = max(1, int(rate * SEARCH_SECONDS))
        self.step = 2 if rate >= 16000 else 1
        self.win = _window(self.n)
        self.pos = 0.0     # where the next frame ideally starts, in input samples
        self.prev = None   # where the last frame started
        self.tail = None   # second half of the last frame, windowed, still to be added
        self.factor = 1.0  # the speed of the last hop
        self._pending = np.zeros(0, dtype=np.float32)
        self._offset = 0
        self._ended = self.x.size == 0

    @property
    def done(self):
        return self._ended and self._offset >= self._pending.size

    def fraction(self):
        """How far into the input playback is, 0..1."""
        return min(1.0, self.pos / max(1, self.x.size))

    def remaining(self, factor):
        """Output samples still to come at this speed (estimate)."""
        left = max(0.0, self.x.size - self.pos) / (factor or 1.0)
        return int(left) + self._pending.size - self._offset

    def _frame(self, start):
        """n input samples from start, zero-padded outside the buffer."""
        n, size = self.n, self.x.size
        if 0 <= start and start + n <= size:
            return self.x[start:start + n]
        out = np.zeros(n, dtype=np.float32)
        a, b = max(0, start), min(size, start + n)
        if b > a:
            out[a - start:b - start] = self.x[a:b]
        return out

    def _region(self, start, length):
        if 0 <= start and start + length <= self.x.size:
            return self.x[start:start + length]
        out = np.zeros(length, dtype=np.float32)
        a, b = max(0, start), min(self.x.size, start + length)
        if b > a:
            out[a - start:b - start] = self.x[a:b]
        return out

    def _hop(self, factor):
        hs, n, win = self.hs, self.n, self.win
        if self.prev is not None and self.pos >= self.x.size:
            self._ended = True
            return self.tail  # fade out the last frame
        if self.prev is None:
            start = int(round(self.pos))
            frame = self._frame(start)
            out = frame[:hs].copy()  # the very first half frame plays as is
        else:
            natural = self.prev + hs
            if factor == 1.0:
                start = natural
            else:
                tol, step = self.tol, self.step
                ideal = int(round(self.pos))
                ref = self._region(natural, n)[::step]
                region = self._region(ideal - tol, n + 2 * tol)[::step]
                corr = np.correlate(region, ref, mode="valid")
                start = ideal - tol + int(np.argmax(corr)) * step
            frame = self._frame(start)
            out = self.tail + frame[:hs] * win[:hs]
        self.tail = frame[hs:] * win[hs:]
        self.prev = start
        # At speed 1.0 follow the frames actually used, so leaving the dead zone starts from here.
        self.pos = (start + hs) if factor == 1.0 else self.pos + hs * factor
        self.factor = factor
        return out

    def read(self, out, factor):
        """Fill out with the next samples at this speed. Returns how many were written
        (fewer than out.size only at the end of the buffer)."""
        filled, want = 0, out.size
        while filled < want:
            if self._offset >= self._pending.size:
                if self._ended:
                    break
                self._pending = self._hop(factor)
                self._offset = 0
                continue
            take = min(want - filled, self._pending.size - self._offset)
            out[filled:filled + take] = self._pending[self._offset:self._offset + take]
            self._offset += take
            filled += take
        return filled


_WINDOWS = {}


def _window(n):
    """Periodic Hann window (50% overlaps sum to exactly 1), cached per size."""
    win = _WINDOWS.get(n)
    if win is None:
        win = _WINDOWS[n] = np.hanning(n + 1)[:n].astype(np.float32)
    return win
