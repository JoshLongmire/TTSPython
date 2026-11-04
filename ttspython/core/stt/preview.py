"""Instant live preview: a small streaming recognizer that shows each word about a third
of a second after it is said, while Whisper (slower, more accurate) checks the text and
types the final result.

The model (a streaming Zipformer, Apache-2.0, run by sherpa-onnx) is downloaded on first
use into the data folder, checked against pinned SHA-256 digests. English only.
"""
from __future__ import annotations

import os
import queue
import shutil
import threading

import numpy as np

from ..platform import data_dir

MODEL_NAME = "zipformer-en-2023-06-26"
REPO = "csukuangfj/sherpa-onnx-streaming-zipformer-en-2023-06-26"
REVISION = "672fbf1b30579d6585301139bb363f42a0ad4a24"
BASE_URL = f"https://huggingface.co/{REPO}/resolve/{REVISION}/"
FILES = {  # name: (bytes, sha256)
    "encoder": ("encoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx", 71083163,
                "563fde436d16cf7607cf408cd6b30909819d03162652ef389c2450ced3f45ac1"),
    "decoder": ("decoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx", 1307236,
                "98da299f471e38bb4e1a8df579b8cc9122d6039576a77e357b3c60f17dd83b02"),
    "joiner": ("joiner-epoch-99-avg-1-chunk-16-left-128.int8.onnx", 259335,
               "d944208d660d67c8d72cd2acaeac971fa5ceb8c80e76c1968148846fedd6e297"),
    "tokens": ("tokens.txt", 5048, "49e3c2646595fd907228b3c6787069658f67b17377c60aeb8619c4551b2316fb"),
}
DOWNLOAD_MB = round(sum(size for _n, size, _h in FILES.values()) / 1e6)
SAMPLE_RATE = 16000
PAUSE_SECONDS = 0.6   # the recognizer starts a new stretch after this much quiet
QUICK_PAUSE = 0.25    # this much quiet after speech is a pause: Whisper checks the text right away
QUIET_SHARE = 0.2     # "quiet" is below this share of the recent speech level

_shared = {"recognizer": None}
_shared_lock = threading.Lock()


def shared_recognizer():
    """The loaded model, kept between dictations (loading takes about 1.5 s)."""
    with _shared_lock:
        if _shared["recognizer"] is None:
            _shared["recognizer"] = PreviewSession.create_recognizer()
        return _shared["recognizer"]


def release():
    """Free the loaded model (with Whisper's idle unload). True if one was loaded."""
    with _shared_lock:
        had = _shared["recognizer"] is not None
        _shared["recognizer"] = None
    return had


def model_dir():
    return os.path.join(data_dir(), "preview", MODEL_NAME)


def available():
    """True if the sherpa-onnx engine is installed (it ships with the app)."""
    try:
        import sherpa_onnx  # noqa: F401
    except Exception:
        return False
    return True


def installed():
    folder = model_dir()
    return all(os.path.getsize(os.path.join(folder, name)) == size if os.path.isfile(os.path.join(folder, name))
               else False for name, size, _sha in FILES.values())


def size_on_disk():
    folder = model_dir()
    return sum(os.path.getsize(os.path.join(folder, f)) for f in os.listdir(folder)) if os.path.isdir(folder) else 0


def install(progress=None, cancel=None, opener=None):
    """Download the model. progress(done_mb, total_mb) as it goes."""
    from ..download import fetch

    folder = model_dir()
    total = sum(size for _n, size, _h in FILES.values())
    done_before = 0
    kwargs = {"opener": opener} if opener is not None else {}
    for name, size, sha in FILES.values():
        dest = os.path.join(folder, name)
        if not (os.path.isfile(dest) and os.path.getsize(dest) == size):
            def report(done, _total, base=done_before):
                if progress is not None:
                    progress(round((base + done) / 1e6), round(total / 1e6))

            fetch(BASE_URL + name, dest, report, sha256=sha, cancel=cancel, **kwargs)
        done_before += size
    return folder


def remove():
    """Delete the downloaded model. Returns the bytes freed."""
    freed = size_on_disk()
    shutil.rmtree(os.path.join(data_dir(), "preview"), ignore_errors=True)
    return freed


def _words(text):
    """The recognizer writes in capitals without punctuation: show it as plain lower case."""
    out = []
    for w in text.lower().split():
        out.append("I" if w == "i" else ("I" + w[1:] if w.startswith("i'") else w))
    return out


class PreviewSession:
    """Runs the recognizer on its own thread for one dictation.

    feed(block) takes blocks from the recorder callback (cheap: only queued); convert(block)
    turns them into 16 kHz float32 on the preview thread.
    on_words(words) gets [(word, start_seconds)] for everything heard so far; on_pause()
    when the speaker paused after speech (QUICK_PAUSE of quiet). Both are called on the
    preview thread.
    """

    def __init__(self, on_words, on_pause=None, recognizer=None, convert=None):
        self._on_words = on_words
        self._convert = convert or (lambda block: block)
        self._on_pause = on_pause
        self._recognizer = recognizer
        self._blocks = queue.Queue()
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._run, name="stt-preview", daemon=True)
        self.error = None

    @staticmethod
    def create_recognizer(folder=None):
        import sherpa_onnx

        folder = folder or model_dir()
        path = {key: os.path.join(folder, name) for key, (name, _s, _h) in FILES.items()}
        return sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=path["tokens"], encoder=path["encoder"], decoder=path["decoder"], joiner=path["joiner"],
            num_threads=1, sample_rate=SAMPLE_RATE, feature_dim=80, decoding_method="greedy_search",
            enable_endpoint_detection=True, rule1_min_trailing_silence=2.4,
            rule2_min_trailing_silence=PAUSE_SECONDS, rule3_min_utterance_length=300)

    def start(self):
        self._thread.start()
        return self

    def feed(self, samples):
        if not self._stopped.is_set():
            self._blocks.put(samples)

    def stop(self):
        self._stopped.set()
        self._blocks.put(None)

    def _run(self):
        try:
            rec = self._recognizer or shared_recognizer()
            stream = rec.create_stream()
            done = []  # words of finished stretches (before a pause)
            shown = []
            while not self._stopped.is_set():
                block = self._blocks.get()
                if block is None:
                    break
                while True:  # catch up on everything already queued before decoding
                    try:
                        more = self._blocks.get_nowait()
                    except queue.Empty:
                        break
                    if more is None:
                        self._stopped.set()
                        break
                    self._accept(stream, block)
                    block = more
                self._accept(stream, block)
                while rec.is_ready(stream):
                    rec.decode_stream(stream)
                result = rec.get_result_all(stream)
                current = self._timed(result)
                if done + current != shown:
                    shown = done + current
                    self._on_words(list(shown))
                if rec.is_endpoint(stream):
                    done += current
                    rec.reset(stream)
        except Exception as exc:  # no preview this time; Whisper still captions and types
            self.error = exc
            self._stopped.set()  # or feed() would keep queueing audio nobody reads

    _peak = 0.0
    _floor = None
    _quiet = 0.0
    _spoke = False

    def _accept(self, stream, block):
        x = self._convert(block)
        stream.accept_waveform(SAMPLE_RATE, x)
        self._watch_level(x)

    def _watch_level(self, x):
        """Report a pause QUICK_PAUSE after speech goes quiet (from the sound level: sooner
        than the recognizer, which only knows once its words are out)."""
        if not x.size:
            return
        level = float(np.sqrt(np.dot(x, x) / x.size))
        self._peak = max(level, self._peak * 0.995)
        # Background noise: drops to quiet moments at once, rises slowly (about 16% a second)
        # so it finds the room's noise but not the speech. Exact silence (a stream starting) is ignored.
        if level > 1e-5:
            self._floor = level if self._floor is None else min(level, self._floor * 1.01)
        floor = self._floor or 0.0
        if level > max(0.002, 2.0 * floor, QUIET_SHARE * self._peak):
            self._spoke, self._quiet = True, 0.0
            return
        self._quiet += x.size / SAMPLE_RATE
        if self._spoke and self._quiet >= QUICK_PAUSE:
            self._spoke = False
            if self._on_pause is not None:
                self._on_pause()

    @staticmethod
    def _timed(result):
        """[(word, start seconds)] from a result: a word starts at its first token."""
        out = []
        start = float(getattr(result, "start_time", 0.0) or 0.0)
        stamps = list(result.timestamps)
        for i, token in enumerate(result.tokens):
            t = start + (float(stamps[i]) if i < len(stamps) else 0.0)
            if token.startswith(" ") or not out:
                for w in _words(token):
                    out.append([w, t])
            else:
                out[-1][0] += token.lower()
        return [(w, t) for w, t in out if w]
