"""Minimal, tolerant WAV parser (espeak writes bogus sizes when streaming)."""
from __future__ import annotations

import struct

import numpy as np


class WavError(ValueError):
    pass


def parse_wav(data: bytes):
    """Return (int16 mono samples, sample_rate)."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise WavError("not a WAV file")
    pos = 12
    fmt = None
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = pos + 8
        if cid == b"fmt ":
            audio_format, channels, rate, _, _, bits = struct.unpack("<HHIIHH", data[body:body + 16])
            fmt = (audio_format, channels, rate, bits)
        elif cid == b"data":
            if fmt is None:
                raise WavError("data before fmt")
            end = len(data) if size in (0, 0xFFFFFFFF) or body + size > len(data) else body + size
            return _decode(data[body:end], *fmt)
        pos = body + size + (size & 1)
    raise WavError("no data chunk")


def _decode(raw, audio_format, channels, rate, bits):
    if audio_format not in (1, 0xFFFE):
        raise WavError(f"unsupported WAV format {audio_format}")
    if bits == 16:
        usable = len(raw) - (len(raw) % (2 * channels))
        samples = np.frombuffer(raw[:usable], dtype="<i2")
    elif bits == 8:
        samples = ((np.frombuffer(raw, dtype=np.uint8).astype(np.int16) - 128) << 8)
    else:
        raise WavError(f"unsupported bit depth {bits}")
    if channels > 1:
        usable = len(samples) - (len(samples) % channels)
        samples = samples[:usable].reshape(-1, channels).mean(axis=1).astype(np.int16)
    return samples.astype(np.int16, copy=True), int(rate)
