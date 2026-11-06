"""Change the sample rate of a block of audio."""
from __future__ import annotations

from functools import lru_cache

import numpy as np


@lru_cache(maxsize=8)
def _low_pass_taps(ratio):
    """A filter that keeps what the lower rate can hold and removes the rest (ratio = new rate / old rate)."""
    half = int(np.ceil(8 / ratio))
    n = np.arange(-half, half + 1)
    cutoff = 0.45 * ratio  # of the old rate; 0.5 * ratio is the new rate's limit
    taps = 2 * cutoff * np.sinc(2 * cutoff * n) * np.hanning(2 * half + 3)[1:-1]
    return (taps / taps.sum()).astype(np.float32)


def resample(samples, src_rate, dst_rate):
    """Without the filter, a microphone's sound above the new rate's limit folds back down as noise."""
    if src_rate == dst_rate or samples.size == 0:
        return samples
    if dst_rate < src_rate:
        taps = _low_pass_taps(dst_rate / src_rate)
        half = taps.size // 2
        # Repeating the edge samples keeps a short block from fading out at both ends.
        samples = np.convolve(np.pad(samples, half, mode="edge"), taps, mode="valid")
    n = max(1, round(samples.size * dst_rate / src_rate))
    x_old = np.linspace(0.0, 1.0, samples.size, endpoint=False)
    x_new = np.linspace(0.0, 1.0, n, endpoint=False)
    return np.interp(x_new, x_old, samples).astype(np.float32)


class StreamResampler:
    """The same conversion for audio that arrives in blocks: nothing is heard where two blocks meet."""

    def __init__(self, src_rate, dst_rate):
        self._same = src_rate == dst_rate
        self._step = src_rate / dst_rate if dst_rate else 1.0
        self._taps = _low_pass_taps(dst_rate / src_rate) if dst_rate < src_rate else None
        self._context = None   # the input samples the filter still needs
        self._last = None      # the last filtered sample, to draw a line from it into the next block
        self._seen = 0         # filtered samples so far
        self._made = 0         # samples returned so far

    def _filtered(self, samples):
        if self._taps is None:
            return samples
        if self._context is None:  # as resample() does: repeat the edge, so the start does not fade in
            self._context = np.full(self._taps.size // 2, samples[0], dtype=np.float32)
        joined = np.concatenate([self._context, samples])
        if joined.size < self._taps.size:
            self._context = joined
            return np.zeros(0, dtype=np.float32)
        self._context = joined[-(self._taps.size - 1):]
        return np.convolve(joined, self._taps, mode="valid")

    def feed(self, samples):
        """float32 samples in, float32 samples out, at the new rate."""
        if self._same or samples.size == 0:
            return samples
        filtered = self._filtered(samples)
        if filtered.size == 0:
            return filtered
        first = self._seen - (1 if self._last is not None else 0)
        points = filtered if self._last is None else np.concatenate([[self._last], filtered])
        self._seen += filtered.size
        self._last = float(filtered[-1])
        count = int((self._seen - 1) / self._step) + 1 - self._made  # outputs that fall before the last sample
        if count <= 0:
            return np.zeros(0, dtype=np.float32)
        where = (self._made + np.arange(count)) * self._step
        self._made += count
        return np.interp(where, first + np.arange(points.size), points).astype(np.float32)

    def finish(self):
        """What the filter was still holding back."""
        if self._same or self._taps is None or self._context is None:
            return np.zeros(0, dtype=np.float32)
        return self.feed(np.full(self._taps.size // 2, self._context[-1], dtype=np.float32))
