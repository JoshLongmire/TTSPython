"""Export speech to WAV or MP3 on a background thread."""
from __future__ import annotations

import gc
import os
import threading
import wave

import numpy as np

from ..chunking import split_chunks
from ..events import EventEmitter
from ..platform import com_apartment
from ..settings import atomic_replace
from .player import resample
from .render import Cancelled, create_renderer
from .stretch import speed_factor, stretch

def mp3_available():
    try:
        import lameenc  # noqa: F401
    except ImportError:
        return False
    return True


def apply_gain(pcm_int16, gain):
    if gain >= 0.999:
        return pcm_int16
    return np.clip(pcm_int16.astype(np.float32) * gain, -32768, 32767).astype(np.int16)


class AudioWriter:
    """Writes WAV or MP3 chunk by chunk to path.part; commit() replaces path atomically.

    A whole book never sits in memory: each rendered chunk is written and dropped.
    """

    def __init__(self, path, fmt, sample_rate, bitrate=128):
        self.path = path
        self.part = path + ".part"
        self.fmt = fmt
        self.sample_rate = sample_rate
        if fmt == "mp3":
            import lameenc

            self._enc = lameenc.Encoder()
            self._enc.set_bit_rate(bitrate)
            self._enc.set_in_sample_rate(sample_rate)
            self._enc.set_channels(1)
            self._enc.set_quality(2)
            self._file = open(self.part, "wb")  # noqa: SIM115
        else:
            self._enc = None
            self._file = wave.open(self.part, "wb")  # noqa: SIM115
            self._file.setnchannels(1)
            self._file.setsampwidth(2)
            self._file.setframerate(sample_rate)

    def write(self, pcm_int16):
        data = pcm_int16.astype("<i2").tobytes()
        if self._enc is not None:
            self._file.write(bytes(self._enc.encode(data)))
        else:
            self._file.writeframes(data)

    def close(self):
        if self._file is None:
            return
        if self._enc is not None:
            self._file.write(bytes(self._enc.flush()))
        self._file.close()
        self._file = None

    def commit(self):
        self.close()
        atomic_replace(self.part, self.path)


def format_for_path(path):
    return "mp3" if path.lower().endswith(".mp3") else "wav"


class AudioExporter:
    """Events: progress(done, total), finished(path), failed(message), cancelled()."""

    def __init__(self, renderer_factory=create_renderer):
        self.events = EventEmitter()
        self._factory = renderer_factory
        self._cancel = threading.Event()
        self._thread = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, text, path, voice_id, rate, volume):
        if self.running:
            return False
        fmt = format_for_path(path)
        if fmt == "mp3" and not mp3_available():
            self.events.emit("failed", "MP3 export needs the lameenc package (pip install lameenc).")
            return False
        self._cancel.clear()
        self._thread = threading.Thread(target=self._run, args=(text, path, fmt, voice_id, rate, volume),
                                        name="tts-export", daemon=True)
        self._thread.start()
        return True

    def cancel(self):
        self._cancel.set()

    def join(self, timeout=None):
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self, text, path, fmt, voice_id, rate, volume):
        writer = None
        try:
            with com_apartment():
                renderer = self._factory()
                try:
                    chunks = split_chunks(text)
                    if not chunks:
                        raise ValueError("No text to export.")
                    for i, chunk in enumerate(chunks):
                        pcm, sr = renderer.render(chunk.text, voice_id, rate, self._cancel)
                        native = renderer.native_wpm(rate, voice_id) if hasattr(renderer, "native_wpm") else rate
                        factor = speed_factor(rate, native)
                        if factor != 1.0:  # the same exact speed as playback
                            audio = stretch(pcm.astype(np.float32) / 32768.0, factor, sr)
                            pcm = np.clip(audio * 32768.0, -32768, 32767).astype(np.int16)
                        if writer is None:
                            writer = AudioWriter(path, fmt, sr)
                        elif sr != writer.sample_rate:
                            pcm = resample(pcm.astype(np.float32), sr, writer.sample_rate).astype(np.int16)
                        writer.write(apply_gain(pcm, volume))
                        writer.write(np.zeros(int(writer.sample_rate * 0.12), dtype=np.int16))
                        self.events.emit("progress", i + 1, len(chunks))
                        if self._cancel.is_set():
                            raise Cancelled()
                finally:
                    del renderer  # COM objects must be released before the apartment closes
                    gc.collect()
            writer.commit()
            self.events.emit("finished", path)
        except Cancelled:
            self._abort(writer, path)
            self.events.emit("cancelled")
        except Exception as exc:
            self._abort(writer, path)
            self.events.emit("failed", str(exc))

    def _abort(self, writer, path):
        if writer is not None:
            try:
                writer.close()
            except Exception:
                pass
        self._cleanup(path)

    @staticmethod
    def _cleanup(path):
        try:
            os.remove(path + ".part")
        except OSError:
            pass
