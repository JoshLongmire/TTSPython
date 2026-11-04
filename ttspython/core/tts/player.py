"""Audio output: one PortAudio stream fed with rendered chunks.

The stream callback only copies samples and posts tiny events to a queue; it
never runs application code and never raises (an exception would abort the
stream for good). Volume is a playback gain, so it changes instantly. Pause
outputs silence without consuming audio, and stops the stream after a while.

Speed: each chunk keeps the audio as the engine rendered it and the rate it was
rendered at. The callback plays it through a streaming time-stretch that reads the
target rate every 10 ms, so a speed slider is heard while it is being dragged.
"""
from __future__ import annotations

import collections
import math
import queue
import threading
import time
from dataclasses import dataclass

import numpy as np

from ..resample import resample
from .stretch import Stretcher, speed_factor

PAUSE_STOP_SECONDS = 10  # a stream paused this long is stopped (restarted on resume)


@dataclass(frozen=True)
class Marker:
    utt_id: int
    index: int = 0
    total: int = 0
    pos16: int = 0
    end16: int = 0
    generation: int = 0
    end: bool = False
    item_id: str = ""
    shown: int = 0  # chunks heard before the text was split again (voice change): for display


class _Segment:
    """Speech (native set) plays through a Stretcher at the target rate; silence and end
    markers are copied as they are (offset counts what has played)."""

    __slots__ = ("samples", "marker", "offset", "native", "stretcher", "announced")

    def __init__(self, samples, marker, native=None, rate=0):
        self.samples = samples
        self.marker = marker
        self.offset = 0
        self.native = native
        self.stretcher = Stretcher(samples, rate) if native else None
        self.announced = False

    def fraction(self):
        """How far into the chunk playback is, 0..1."""
        if self.stretcher is not None:
            return self.stretcher.fraction()
        return self.offset / max(1, self.samples.size)

    def remaining(self, target_wpm):
        if self.stretcher is not None:
            return self.stretcher.remaining(speed_factor(target_wpm, self.native))
        return self.samples.size - self.offset


class AudioPlayer:
    def __init__(self, events: "queue.Queue", sd_module=None, preferred_rate=22050, idle_close=15.0):
        self._events = events
        self._sd = sd_module
        self._preferred_rate = preferred_rate
        self._idle_close = idle_close
        self._lock = threading.Lock()
        self._segments = collections.deque()
        self._stream = None
        self._rate = preferred_rate
        self._device = None
        self._gain = 1.0
        self._paused = False
        self._level = 0.0
        self._opened = threading.Event()
        self._open_error = None
        self._opening = False
        self._last_active = time.monotonic()
        self._last_progress = time.monotonic()
        self._min_generation = 0
        self._closer = None
        self._target_wpm = None
        self._paused_since = None
        self._stream_stopped = False
        self.callback_errors = 0

    # --- configuration --------------------------------------------------------
    @property
    def sd(self):
        if self._sd is None:
            import sounddevice

            self._sd = sounddevice
        return self._sd

    @property
    def stream_rate(self):
        return self._rate

    @property
    def device(self):
        return self._device

    def set_device(self, index):
        if index == self._device:
            return
        self._device = index
        self.close()

    def set_gain(self, gain):
        self._gain = max(0.0, min(1.0, float(gain)))

    @property
    def level(self):
        return self._level

    def pause(self):
        self._paused = True
        self._paused_since = time.monotonic()
        self._schedule_pause_stop()

    def resume(self):
        self._paused = False
        self._paused_since = None
        self._last_progress = time.monotonic()
        if self._stream_stopped:
            self._stream_stopped = False
            stream = self._stream
            if stream is not None:
                try:
                    stream.start()
                except Exception:
                    pass

    def _schedule_pause_stop(self):
        timer = threading.Timer(PAUSE_STOP_SECONDS, self._stop_if_still_paused)
        timer.daemon = True
        timer.start()

    def _stop_if_still_paused(self):
        """A long pause should not keep the audio device busy (and the audio thread awake)."""
        since = self._paused_since
        if not self._paused or since is None or time.monotonic() - since < PAUSE_STOP_SECONDS - 0.5:
            return
        stream = self._stream
        if stream is None or self._stream_stopped:
            return
        try:
            stream.stop()
            self._stream_stopped = True
        except Exception:
            pass

    # --- speed -------------------------------------------------------------------
    @property
    def target_wpm(self):
        return self._target_wpm

    def set_target_wpm(self, wpm):
        """Play at this rate; the callback picks it up within 10 ms, even mid-chunk."""
        self._target_wpm = wpm

    # --- stream lifecycle -----------------------------------------------------
    def prepare(self):
        """Start opening the stream in the background if it is closed."""
        with self._lock:
            self._last_active = time.monotonic()
            if self._stream is not None or self._opening:
                return
            self._opening = True
            self._opened.clear()
            self._open_error = None
        threading.Thread(target=self._open, name="audio-open", daemon=True).start()

    def _open(self):
        device = self._device
        stream = None
        error = None
        for rate in self._candidate_rates(device):
            try:
                stream = self.sd.OutputStream(
                    samplerate=rate, channels=1, dtype="float32", device=device,
                    latency="low", callback=self._callback,
                )
                stream.start()
                self._rate = rate
                break
            except Exception as exc:  # device rejects the rate: try its default
                error = exc
                stream = None
        stale = None
        with self._lock:
            if stream is not None and device != self._device:
                # The device changed while we were opening: do not keep this one.
                stale, stream = stream, None
                error = RuntimeError("output device changed")
            self._stream = stream
            self._open_error = None if stream is not None else error
            self._opening = False
            self._last_progress = time.monotonic()
        if stale is not None:
            self._close_stream(stale)
        self._opened.set()
        self._schedule_idle_close()

    def _candidate_rates(self, device):
        rates = [self._preferred_rate]
        try:
            info = self.sd.query_devices(device, "output")
            default = int(info.get("default_samplerate") or 0)
            if default and default not in rates:
                rates.append(default)
        except Exception:
            pass
        for r in (48000, 44100):
            if r not in rates:
                rates.append(r)
        return rates

    def wait_open(self, timeout=5.0):
        for _attempt in range(2):
            self.prepare()
            self._opened.wait(timeout)
            if self._stream is not None:
                return
            if self._open_error is not None and "device changed" not in str(self._open_error):
                break
        raise RuntimeError(f"Could not open audio output: {self._open_error or 'the device did not respond'}")

    @staticmethod
    def _close_stream(stream):
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass

    def close(self):
        with self._lock:
            stream, self._stream = self._stream, None
            self._segments.clear()
        if stream is not None:
            self._close_stream(stream)
        self._level = 0.0

    def stream_alive(self):
        """False if the stream died (device unplugged, driver error)."""
        stream = self._stream
        if stream is None:
            return False
        try:
            return bool(getattr(stream, "active", True))
        except Exception:
            return False

    def stalled(self, seconds=5.0):
        """True if audio is queued, not paused, but nothing has played for a while."""
        with self._lock:
            pending = bool(self._segments)
        if not pending or self._paused:
            return False
        return time.monotonic() - self._last_progress > seconds or not self.stream_alive()

    def _schedule_idle_close(self):
        if self._closer is not None:
            self._closer.cancel()
        self._closer = threading.Timer(self._idle_close, self._maybe_close)
        self._closer.daemon = True
        self._closer.start()

    def _maybe_close(self):
        stream = None
        with self._lock:
            idle = not self._segments and time.monotonic() - self._last_active >= self._idle_close - 0.5
            if idle:
                stream, self._stream = self._stream, None
        if not idle:
            self._schedule_idle_close()
            return
        if stream is not None:
            self._close_stream(stream)
        self._level = 0.0

    # --- feeding ----------------------------------------------------------------
    def _append(self, samples, marker, **segment):
        """Append unless the marker belongs to a stopped job. Reopens a stream closed meanwhile."""
        for _attempt in range(2):
            self.wait_open()
            with self._lock:
                if marker is not None and marker.generation < self._min_generation:
                    return False
                if self._stream is None:
                    continue
                self._segments.append(_Segment(samples, marker, **segment))
                self._last_active = time.monotonic()
                if len(self._segments) == 1:
                    self._last_progress = time.monotonic()
                return True
        raise RuntimeError("Audio output closed unexpectedly")

    def enqueue(self, pcm_int16, sample_rate, marker, native_wpm=None):
        """native_wpm: the rate the engine rendered at; the audio is played at the target rate."""
        self.wait_open()
        samples = pcm_int16.astype(np.float32)
        samples *= 1.0 / 32768.0
        samples = resample(samples, sample_rate, self._rate)
        return self._append(samples, marker, native=native_wpm, rate=self._rate)

    def enqueue_silence(self, seconds, marker=None):
        self.wait_open()
        return self._append(np.zeros(int(self._rate * seconds), dtype=np.float32), marker)

    def enqueue_end(self, marker):
        with self._lock:
            if marker.generation < self._min_generation:
                return
            alive = self._stream is not None
            if alive:
                self._segments.append(_Segment(np.zeros(0, dtype=np.float32), marker))
        if not alive:
            self._events.put(("drained", marker))

    def flush(self, min_generation=None):
        """Drop queued audio. Later enqueues with an older generation are ignored."""
        with self._lock:
            if min_generation is not None:
                self._min_generation = max(self._min_generation, min_generation)
            self._segments.clear()
        self._level = 0.0

    def drop_queued(self, utt_id):
        """Drop segments of utt_id that have not started. Returns the lowest dropped index."""
        dropped = []
        with self._lock:
            keep = collections.deque()
            for seg in self._segments:
                if seg.marker is not None and seg.marker.utt_id == utt_id and not seg.announced:
                    if not seg.marker.end:
                        dropped.append(seg.marker.index)
                    continue
                keep.append(seg)
            self._segments = keep
        return min(dropped) if dropped else None

    def drop_utterance(self, utt_id):
        """Drop every segment of utt_id, the playing one included."""
        with self._lock:
            self._segments = collections.deque(
                seg for seg in self._segments if seg.marker is None or seg.marker.utt_id != utt_id)

    def position(self, utt_id):
        """(chunk index, fraction played) of the chunk of utt_id being heard, or None."""
        with self._lock:
            for seg in self._segments:
                m = seg.marker
                if m is not None and m.utt_id == utt_id and not m.end and seg.announced:
                    return m.index, seg.fraction()
        return None

    def queued_seconds(self, utt_id):
        """Audio of utt_id still to play, in seconds."""
        with self._lock:
            left = sum(seg.remaining(self._target_wpm) for seg in self._segments
                       if seg.marker is not None and seg.marker.utt_id == utt_id)
        return left / float(self._rate or 1)

    def pending_count(self):
        with self._lock:
            return len(self._segments)

    # --- realtime callback --------------------------------------------------------
    def _callback(self, outdata, frames, _time, _status):
        out = outdata[:, 0]
        try:
            if self._paused:
                out.fill(0)
                self._level = 0.0
                return
            filled = 0
            target = self._target_wpm
            with self._lock:
                segs = self._segments
                while filled < frames and segs:
                    seg = segs[0]
                    if not seg.announced:
                        seg.announced = True
                        if seg.marker is not None:
                            kind = "drained" if seg.marker.end else "chunk"
                            self._events.put_nowait((kind, seg.marker))
                    if seg.stretcher is not None:
                        try:
                            filled += seg.stretcher.read(out[filled:], speed_factor(target, seg.native))
                        except Exception:
                            # Never lose the chunk: play the rest as rendered.
                            self.callback_errors += 1
                            seg.offset = min(seg.samples.size, int(seg.stretcher.pos))
                            seg.stretcher = None
                            continue
                        finished = seg.stretcher.done
                    else:
                        take = min(frames - filled, seg.samples.size - seg.offset)
                        if take > 0:
                            out[filled:filled + take] = seg.samples[seg.offset:seg.offset + take]
                            filled += take
                            seg.offset += take
                        finished = seg.offset >= seg.samples.size
                    if finished:
                        segs.popleft()
                    else:
                        break
                if filled or not segs:
                    self._last_progress = time.monotonic()
            if filled < frames:
                out[filled:] = 0
            if filled:
                played = out[:filled]
                played *= self._gain
                self._level = math.sqrt(float(np.dot(played, played)) / filled)
                self._last_active = time.monotonic()
            else:
                self._level *= 0.5
        except Exception:
            # Never let an exception escape: sounddevice would abort the stream.
            self.callback_errors += 1
            out.fill(0)
