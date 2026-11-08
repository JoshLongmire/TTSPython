"""Instant live preview: a small streaming recognizer that shows each word about a third
of a second after it is said, while Whisper (slower, more accurate) checks the text and
types the final result.

Each language's model (a streaming Zipformer, Apache-2.0, run by sherpa-onnx) is downloaded
on first use into the data folder, checked against pinned SHA-256 digests. Other languages
have no model good enough for this, so their captions come from Whisper alone.
"""
from __future__ import annotations

import os
import queue
import re
import shutil
import threading
from typing import NamedTuple

import numpy as np

from ..platform import data_dir


class Model(NamedTuple):
    name: str
    files: dict  # role: (file name, bytes, sha256)
    base_url: str = ""  # the files one by one, or
    archive: tuple = ()  # (url, bytes, sha256) of a .tar.bz2 that holds them


MODELS = {
    "en": Model(
        "zipformer-en-2023-06-26",
        {"encoder": ("encoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx", 71083163,
                     "563fde436d16cf7607cf408cd6b30909819d03162652ef389c2450ced3f45ac1"),
         "decoder": ("decoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx", 1307236,
                     "98da299f471e38bb4e1a8df579b8cc9122d6039576a77e357b3c60f17dd83b02"),
         "joiner": ("joiner-epoch-99-avg-1-chunk-16-left-128.int8.onnx", 259335,
                    "d944208d660d67c8d72cd2acaeac971fa5ceb8c80e76c1968148846fedd6e297"),
         "tokens": ("tokens.txt", 5048, "49e3c2646595fd907228b3c6787069658f67b17377c60aeb8619c4551b2316fb")},
        base_url="https://huggingface.co/csukuangfj/sherpa-onnx-streaming-zipformer-en-2023-06-26/resolve/"
                 "672fbf1b30579d6585301139bb363f42a0ad4a24/"),
    "fr": Model(
        "zipformer-fr-2023-04-14",
        {"encoder": ("encoder-epoch-29-avg-9-with-averaged-model.int8.onnx", 126655903,
                     "47a94a7fdc8dff63d708be4ea0535747640224467f91e238311f1ddbdd09327e"),
         "decoder": ("decoder-epoch-29-avg-9-with-averaged-model.int8.onnx", 1307157,
                     "e72b2b9ed36355bd0dd43433f7dd258e7226ab54c9ef42b28c73ebb785805623"),
         "joiner": ("joiner-epoch-29-avg-9-with-averaged-model.int8.onnx", 259572,
                    "fc2f3bb851a15a532c6f2422d53eecd1ca949f12b0897e07a852021c30481711"),
         "tokens": ("tokens.txt", 4819, "37fb3f2a7bcb85e5fff3f1f66be04e6fbb05077a22f56d177fe85704e945fb31")},
        base_url="https://huggingface.co/shaojieli/sherpa-onnx-streaming-zipformer-fr-2023-04-14/resolve/"
                 "3db9565d9633758d6b87b9a7b3dc09ebfb6b2c73/"),
    "zh": Model(
        "x-asr-zh-en-2026-06-05",
        {"encoder": ("encoder.int8.onnx", 155278641, "aad87c04ae3a6332f14560f602b830bafa669e6d8f0db9879debc7c5071765c8"),
         "decoder": ("decoder.onnx", 11309084, "fd2ac10c5936a1411f7a68e669e8cfec882b17791dd2ca44ab9baf69bb8ab855"),
         "joiner": ("joiner.int8.onnx", 2581422, "82e88dad29301e29144565cd3b7347fa163f07ddb30ea60346b7c4c536adf4ba"),
         "tokens": ("tokens.txt", 59240, "ad0df596d9cc60c90795409549ccf7d1c4f901bdc060dd6b2b067d9ef2fddfaf")},
        archive=("https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
                 "sherpa-onnx-x-asr-160ms-streaming-zipformer-transducer-zh-en-int8-2026-06-05.tar.bz2",
                 134400000, "bdf2c0f2474d34bf479871b0f298c74a6f6bf15f24a492dc5401aa3041811915")),
}
SAMPLE_RATE = 16000
PAUSE_SECONDS = 0.6   # the recognizer starts a new stretch after this much quiet
QUICK_PAUSE = 0.25    # this much quiet after speech is a pause: Whisper checks the text right away
QUIET_SHARE = 0.2     # "quiet" is below this share of the recent speech level

_CJK = re.compile("[\u3000-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]")

_shared = {"recognizer": None, "language": None}
_shared_lock = threading.Lock()


def supports(language):
    return language in MODELS


def download_mb(language="en"):
    model = MODELS[language]
    return round((model.archive[1] if model.archive else sum(f[1] for f in model.files.values())) / 1e6)


def is_cjk(character):
    return bool(_CJK.match(character))


def units(text):
    """The pieces a text wraps and compares by: its words, and each Chinese or Japanese character."""
    out = []
    for part in text.split():
        word = ""
        for character in part:
            if is_cjk(character):
                if word:
                    out.append(word)
                    word = ""
                out.append(character)
            else:
                word += character
        if word:
            out.append(word)
    return out


def spaced(before, after):
    """Whether two pieces are shown with a space between them."""
    return not (is_cjk(before[-1]) or is_cjk(after[0]))


def shared_recognizer(language="en"):
    """The loaded model, kept between dictations (loading takes about 1.5 s). One at a time."""
    with _shared_lock:
        if _shared["recognizer"] is None or _shared["language"] != language:
            _shared["recognizer"] = None  # freed before the next one loads
            _shared["recognizer"] = PreviewSession.create_recognizer(language=language)
            _shared["language"] = language
        return _shared["recognizer"]


def release():
    """Free the loaded model (with Whisper's idle unload). True if one was loaded."""
    with _shared_lock:
        had = _shared["recognizer"] is not None
        _shared["recognizer"] = None
        _shared["language"] = None
    return had


def model_dir(language="en"):
    return os.path.join(data_dir(), "preview", MODELS[language].name)


def available():
    """True if the sherpa-onnx engine is installed (it ships with the app)."""
    try:
        import sherpa_onnx  # noqa: F401
    except Exception:
        return False
    return True


def installed(language="en"):
    folder = model_dir(language)
    return all(os.path.getsize(os.path.join(folder, name)) == size if os.path.isfile(os.path.join(folder, name))
               else False for name, size, _sha in MODELS[language].files.values())


def any_installed():
    return any(installed(language) for language in MODELS)


def size_on_disk():
    """Bytes used by the models of every language."""
    return sum(os.path.getsize(os.path.join(folder, name))
               for folder, _dirs, names in os.walk(os.path.join(data_dir(), "preview")) for name in names)


def _unpack(archive, folder, files):
    """Take the wanted files out of the archive, each checked against its digest."""
    import hashlib  # with tarfile, only for a download: kept off the way to the first window
    import tarfile

    wanted = {name: (size, sha) for name, size, sha in files.values()}
    with tarfile.open(archive, "r:bz2") as tar:
        for member in tar:
            if not wanted:  # the rest of the archive would only be decompressed to be skipped
                break
            name = os.path.basename(member.name)
            if name not in wanted or not member.isfile():
                continue
            size, sha = wanted.pop(name)
            digest = hashlib.sha256()
            part = os.path.join(folder, name + ".part")
            with tar.extractfile(member) as source, open(part, "wb") as out:
                while True:
                    block = source.read(1024 * 1024)
                    if not block:
                        break
                    digest.update(block)
                    out.write(block)
            if digest.hexdigest() != sha or os.path.getsize(part) != size:
                os.remove(part)
                raise ValueError(f"{name} in the download is damaged")
            os.replace(part, os.path.join(folder, name))
    if wanted:
        raise ValueError(f"The download lacks {', '.join(sorted(wanted))}")


def install(progress=None, cancel=None, opener=None, language="en"):
    """Download a language's model. progress(done_mb, total_mb) as it goes."""
    from ..download import fetch

    model = MODELS[language]
    folder = model_dir(language)
    kwargs = {"opener": opener} if opener is not None else {}
    if model.archive:
        url, _size, sha = model.archive
        archive = os.path.join(folder, "download.tar.bz2")

        def report_archive(done, total):
            if progress is not None:
                progress(round(done / 1e6), round((total or model.archive[1]) / 1e6))

        try:
            fetch(url, archive, report_archive, sha256=sha, cancel=cancel, **kwargs)
            _unpack(archive, folder, model.files)
        finally:
            if os.path.exists(archive):
                os.remove(archive)
        return folder
    total = sum(size for _n, size, _h in model.files.values())
    done_before = 0
    for name, size, sha in model.files.values():
        dest = os.path.join(folder, name)
        if not (os.path.isfile(dest) and os.path.getsize(dest) == size):
            def report(done, _total, base=done_before):
                if progress is not None:
                    progress(round((base + done) / 1e6), round(total / 1e6))

            fetch(model.base_url + name, dest, report, sha256=sha, cancel=cancel, **kwargs)
        done_before += size
    return folder


def remove():
    """Delete the downloaded model. Returns the bytes freed."""
    freed = size_on_disk()
    shutil.rmtree(os.path.join(data_dir(), "preview"), ignore_errors=True)
    return freed


def _words(text, language="en"):
    """The recognizer writes in capitals without punctuation: show it as plain lower case."""
    out = []
    for w in text.lower().split():
        out.append("I" if language == "en" and w == "i" else ("I" + w[1:] if language == "en" and w.startswith("i'") else w))
    return out


class PreviewSession:
    """Runs the recognizer on its own thread for one dictation.

    feed(block) takes blocks from the recorder callback (cheap: only queued); convert(block)
    turns them into 16 kHz float32 on the preview thread.
    on_words(words) gets [(word, start_seconds)] for everything heard so far; on_pause()
    when the speaker paused after speech (QUICK_PAUSE of quiet). Both are called on the
    preview thread.
    """

    def __init__(self, on_words, on_pause=None, recognizer=None, convert=None, language="en"):
        self._on_words = on_words
        self._language = language
        self._convert = convert or (lambda block: block)
        self._on_pause = on_pause
        self._recognizer = recognizer
        self._blocks = queue.Queue()
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._run, name="stt-preview", daemon=True)
        self.error = None

    @staticmethod
    def create_recognizer(folder=None, language="en"):
        import sherpa_onnx

        folder = folder or model_dir(language)
        path = {key: os.path.join(folder, name) for key, (name, _s, _h) in MODELS[language].files.items()}
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
            rec = self._recognizer or shared_recognizer(self._language)
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
                current = self._timed(result, self._language)
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
    def _timed(result, language="en"):
        """[(word, start seconds)] from a result: a word starts at its first token, and each
        Chinese character counts as a word."""
        out = []
        start = float(getattr(result, "start_time", 0.0) or 0.0)
        stamps = list(result.timestamps)
        new_word = True
        for i, token in enumerate(result.tokens):
            if not token.strip():  # a token that is only a space ends the word before it
                new_word = True
                continue
            t = start + (float(stamps[i]) if i < len(stamps) else 0.0)
            if new_word or token.startswith(" ") or is_cjk(token[0]) or is_cjk(out[-1][0][-1]):
                for w in _words(token, language):
                    out.append([w, t])
            else:
                out[-1][0] += token.lower()
            new_word = False
        return [(w, t) for w, t in out if w]
