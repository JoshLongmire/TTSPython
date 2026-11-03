"""Fake audio backends so engine tests run fast and silent."""
import threading
import time

import numpy as np

from ttspython.core.tts.render import Cancelled, Voice


class FakeRenderer:
    """Renders a short tone per chunk; tracks concurrent renders."""

    name = "fake"
    sample_rate = 22050
    instances = []

    def __init__(self, seconds_per_chunk=0.05, render_delay=0.0):
        self.seconds = seconds_per_chunk
        self.delay = render_delay
        self.rendered = []
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()
        FakeRenderer.instances.append(self)

    def list_voices(self):
        return [Voice("v-david", "Microsoft David Desktop"), Voice("v-zira", "Microsoft Zira Desktop", gender="Female")]

    def render(self, text, voice_id, wpm, cancel):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            end = time.monotonic() + self.delay
            while time.monotonic() < end:
                if cancel.is_set():
                    raise Cancelled()
                time.sleep(0.002)
            if cancel.is_set():
                raise Cancelled()
            self.rendered.append((text, voice_id, wpm))
            n = int(self.sample_rate * self.seconds)
            t = np.arange(n) / self.sample_rate
            return (np.sin(2 * np.pi * 220 * t) * 8000).astype(np.int16), self.sample_rate
        finally:
            with self._lock:
                self.active -= 1


class FakeStream:
    def __init__(self, sd, samplerate, channels, dtype, device, latency, callback):
        if sd.reject_rates and samplerate in sd.reject_rates:
            raise RuntimeError("Invalid sample rate")
        self.sd = sd
        self.samplerate = samplerate
        self.device = device
        self.callback = callback
        self.running = False
        self.thread = None
        self.output = []

    def start(self):
        self.running = True
        with self.sd.lock:
            self.sd.open_streams += 1
            self.sd.max_open = max(self.sd.max_open, self.sd.open_streams)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        frames = 256
        while self.running:
            out = np.zeros((frames, 1), dtype=np.float32)
            self.callback(out, frames, None, None)
            if self.sd.capture:
                self.output.append(out[:, 0].copy())
            time.sleep(frames / self.samplerate / self.sd.speed)

    def stop(self):
        if self.running:
            self.running = False
            with self.sd.lock:
                self.sd.open_streams -= 1

    def close(self):
        self.stop()


class FakeSD:
    """Stands in for the sounddevice module."""

    def __init__(self, speed=20.0, reject_rates=(), default_rate=48000):
        self.speed = speed
        self.reject_rates = set(reject_rates)
        self.default_rate = default_rate
        self.streams = []
        self.lock = threading.Lock()
        self.open_streams = 0
        self.max_open = 0
        self.capture = False

    def OutputStream(self, samplerate, channels, dtype, device, latency, callback):  # noqa: N802
        stream = FakeStream(self, samplerate, channels, dtype, device, latency, callback)
        self.streams.append(stream)
        return stream

    def query_devices(self, device=None, kind=None):
        return {"default_samplerate": self.default_rate}


def wait_for(predicate, timeout=5.0, interval=0.005):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class FakeSelection:
    """Stands in for platform.selection.SelectionGrabber: text is "highlighted in another app"."""

    def __init__(self, text=None):
        self.text = text
        self.busy = False
        self.calls = 0

    def grab(self, callback):
        self.calls += 1
        callback(self.text)
        return True
