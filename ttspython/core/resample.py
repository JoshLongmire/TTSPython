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
    n = max(1, int(round(samples.size * dst_rate / src_rate)))
    x_old = np.linspace(0.0, 1.0, samples.size, endpoint=False)
    x_new = np.linspace(0.0, 1.0, n, endpoint=False)
    return np.interp(x_new, x_old, samples).astype(np.float32)
