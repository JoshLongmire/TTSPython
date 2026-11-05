"""Dictation service: record, transcribe with faster-whisper, unload when idle.

Events:
  state_changed(SttState)
  partial(settled, checked, preview)  while recording: the words heard so far. settled is
      final, checked is Whisper's text for the rest, preview the newest words from the
      instant preview that Whisper has not checked yet
  transcript_ready(text, target)
  model_status(str)
  preview_status(str)  the instant preview's model download (in the background; nothing waits on it)
  error(message)

Live captions: while recording, the worker transcribes what was said since the last
"settled" point, again and again. Up to WHOLE_SECONDS nothing is settled: every pass
covers the whole recording, which costs little more (Whisper always works on a 30 s
window; only the decoding grows with the text). After that, text settles only at real
pauses (checked in the audio, never at Whisper's rough segment times), so no word is cut
and each pass stays about a second. At stop, only the open tail is transcribed. If
nothing new was said since the last pass, its text is used at once.

Instant preview (preview.py): a streaming recognizer shows words about 0.4 s after they
are said. Whisper runs at once when you pause (so its text is usually ready when you press
stop), otherwise after LIVE_PREVIEW_REST, and replaces the preview words with its own.
"""
from __future__ import annotations

import enum
import gc
import logging
import os
import queue
import threading

import numpy as np

from ..events import EventEmitter
from ..transcript import normalize_transcript_text
from . import preview as preview_mod
from .recorder import Recorder, resample

log = logging.getLogger(__name__)

INITIAL_PROMPT = "Use normal capitalization and punctuation."
WHOLE_SECONDS = 8.0    # up to this much unsettled audio, every pass covers all of it (no cuts)
SETTLE_GAP = 1.5       # only text ending this long before the end of the audio can settle
MAX_TAIL = 28.0        # past this, settle even without a clear pause (Whisper's 30 s window)
PAUSE_WINDOW = 0.2     # settle only where the audio is this long and quiet...
PAUSE_LEVEL = 0.25     # ...below this share of the speech level
REUSE_SECONDS = 0.1    # at stop, a pass that ended this close to the end is used as it is
SEAM_SECONDS = 0.5     # preview words this close to where Whisper's text ends may repeat its last words
LIVE_MIN_AUDIO = 0.6   # seconds of new audio before the first caption pass
LIVE_REST = 0.5        # pause between passes, at least this...
LIVE_REST_SHARE = 0.5  # ...or half the last pass's time, so dictation does not keep the CPU busy
LIVE_PREVIEW_REST = 1.0  # with the instant preview, Whisper rests longer, but a pause wakes it
PROMPT_TAIL = 200      # characters of settled text given to Whisper as context


SILENT_PEAK = 1e-4  # a microphone blocked by privacy settings delivers exact zeros
SILENT_MIC_MESSAGE = ("The microphone sent only silence. Check that it is not muted"
                      + (", and that Windows allows apps to use it (Settings > Privacy & security > Microphone)."
                         if os.name == "nt" else "."))


def friendly_audio_error(exc):
    """PortAudio's messages in plain words."""
    text = str(exc)
    low = text.lower()
    if "invalid device" in low or "device unavailable" in low or "-9996" in low or "-9985" in low:
        return "the microphone is unplugged or in use by another app. Pick another one in Settings > Listen."
    if "invalid sample rate" in low or "-9997" in low:
        return "the microphone does not support the needed sample rate. Pick another one in Settings > Listen."
    return text


_NUMBER_WORDS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
                 "fifteen sixteen seventeen eighteen nineteen twenty").split()


def _plain(word):
    """Lower case without punctuation; Whisper's digits as the preview spells them ("3" -> "three")."""
    plain = "".join(ch for ch in word.lower() if ch.isalnum() or ch == "'")
    return _NUMBER_WORDS[int(plain)] if plain.isdigit() and int(plain) < len(_NUMBER_WORDS) else plain


def _same_word(a, b):
    """Whisper's word and the preview's: equal, or one cut short ("fin" / "finished")."""
    a, b = _plain(a), _plain(b)
    return a == b or (min(len(a), len(b)) >= 3 and (a.startswith(b) or b.startswith(a)))


def _after_overlap(text, preview, longest=5, skip=2):
    """(preview words without the ones that repeat the end of text, whether text's last word
    should be hidden). This is the seam between Whisper's text and the preview's newer words.
    The repeat may start a word or two into the preview, where it heard the seam differently
    ("week and we could" after "weekend we could"). If it only lines up without text's last
    word, that word was Whisper's guess at a half-heard word ("boards are so" while the
    preview says "boards are still in"), so the preview's version is shown instead."""
    words = text.split()
    for guessed in (False, True):
        tail = (words[:-1] if guessed else words)[-longest:]
        for start in range(min(skip, len(preview)) + 1):
            for k in range(min(longest, len(preview) - start, len(tail)), 0, -1):
                if (start or guessed) and k < 2:
                    break
                if all(_same_word(a, b) for a, b in zip(tail[-k:], preview[start:start + k])):
                    return preview[start + k:], guessed
    return preview, False


def _block_converter(rate):
    """Recorder blocks (int16 at the capture rate) to what the preview wants (float32, 16 kHz)."""
    def convert(block):
        x = np.asarray(block)
        if x.dtype != np.float32:
            x = x.astype(np.float32) * (1.0 / 32768.0)
        return resample(x, rate, preview_mod.SAMPLE_RATE) if rate != preview_mod.SAMPLE_RATE else x
    return convert


def _has_speech(audio, rate):
    """True if audio holds speech (the Silero VAD that Whisper's own filter uses)."""
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        return bool(get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=300), sampling_rate=rate))
    except Exception:
        return True  # unsure: transcribe again


def _loud_part(rest, audio, rate):
    """True if any 50 ms of rest is at least a third as loud as the recording's speech."""
    win = max(1, int(rate * 0.05))
    if rest.size < win:
        return False
    frames = rest[: rest.size // win * win].reshape(-1, win)
    loudest = float(np.sqrt(np.max(np.mean(frames * frames, axis=1))))
    whole = audio[: audio.size // win * win].reshape(-1, win)
    speech = float(np.sqrt(np.percentile(np.mean(whole * whole, axis=1), 90))) if whole.size else 0.0
    return speech > 0 and loudest >= speech / 3


def whisper_threads():
    """CTranslate2 gets no faster from hyperthreads; half the logical cores (max 8) was 22%
    faster than all 16 on the test PC and leaves room for the UI and audio."""
    return max(1, min(8, (os.cpu_count() or 4) // 2))


class SttState(enum.Enum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"


def _load_whisper(name_or_path):
    from faster_whisper import WhisperModel

    return WhisperModel(name_or_path, device="cpu", compute_type="int8", cpu_threads=whisper_threads())


# Download sizes, for the progress message when the downloader does not report a total.
MODEL_MB = {"tiny": 75, "base": 145, "small": 484, "medium": 1530, "large-v3": 3090,
            "large-v3-turbo": 1620, "distil-large-v3": 1510}
WHISPER_FILES = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]
REQUIRED_FILES = ("model.bin", "config.json", "tokenizer.json")


WHISPER_REPOS = {
    "tiny": "Systran/faster-whisper-tiny", "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small", "medium": "Systran/faster-whisper-medium",
    "large-v3": "Systran/faster-whisper-large-v3",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
}


def downloaded_models(scan=None):
    """[(model name, bytes on disk)] for the Whisper models in the download cache."""
    try:
        if scan is None:
            from huggingface_hub import scan_cache_dir as scan
        info = scan()
    except Exception:
        return []
    by_repo = {repo: name for name, repo in WHISPER_REPOS.items()}
    return sorted((by_repo[r.repo_id], r.size_on_disk) for r in info.repos if r.repo_id in by_repo)


def delete_model(name, scan=None):
    """Remove a downloaded Whisper model from the cache. Returns the bytes freed."""
    if scan is None:
        from huggingface_hub import scan_cache_dir as scan
    info = scan()
    repo = WHISPER_REPOS.get(name)
    hashes = [rev.commit_hash for r in info.repos if r.repo_id == repo for rev in r.revisions]
    if not hashes:
        return 0
    strategy = info.delete_revisions(*hashes)
    strategy.execute()
    return strategy.expected_freed_size


def model_complete(folder):
    """True when a downloaded model folder has every file a load needs."""
    return all(os.path.isfile(os.path.join(folder, f)) for f in REQUIRED_FILES)


_SINK = []


def _sink():
    """One shared file that swallows progress-bar output (never closed: bars write on cleanup)."""
    if not _SINK:
        _SINK.append(open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115
    return _SINK[0]


def _progress_class(bars):
    """A huggingface_hub progress bar that prints nothing but keeps counting, so the
    download can be reported in the app. Every bar it creates is added to bars."""
    from huggingface_hub.utils import tqdm as hf_tqdm

    class Progress(hf_tqdm):
        def __init__(self, *args, **kwargs):
            kwargs["disable"] = False  # a disabled bar stops counting
            kwargs["file"] = _sink()
            super().__init__(*args, **kwargs)
            bars.append(self)

    return Progress


def download_whisper(name, progress=None):
    """Return the local folder of Whisper model name, downloading it first if needed.

    progress(done_mb, total_mb, seconds) is called about once a second while downloading;
    done_mb is None when this huggingface_hub version does not report bytes.
    """
    import time

    if os.path.isdir(name):
        return name  # a model folder on disk
    from faster_whisper.utils import _MODELS
    from huggingface_hub import snapshot_download

    repo = name if "/" in name else _MODELS.get(name, name)
    try:
        local = snapshot_download(repo, allow_patterns=WHISPER_FILES, local_files_only=True)
        if model_complete(local):
            return local
        # The folder exists but a download was interrupted: the online call below resumes it.
    except Exception:
        pass  # not downloaded yet
    bars, done = [], threading.Event()
    t0 = time.perf_counter()

    def watch():
        while not done.wait(1.0):
            sized = [b for b in list(bars) if getattr(b, "unit", "") == "B" and b.total]
            total = max((b.total for b in sized), default=0)
            got = max((b.n for b in sized), default=0)
            progress(round(got / 1e6) if total else None, round(total / 1e6) if total else MODEL_MB.get(name),
                     int(time.perf_counter() - t0))

    if progress is not None:
        threading.Thread(target=watch, name="stt-download-progress", daemon=True).start()
    try:
        try:
            return snapshot_download(repo, allow_patterns=WHISPER_FILES, tqdm_class=_progress_class(bars))
        except TypeError:  # an older huggingface_hub without tqdm_class
            return snapshot_download(repo, allow_patterns=WHISPER_FILES)
    finally:
        done.set()


class _Worker:
    """One daemon thread running jobs in order.

    A ThreadPoolExecutor's threads are joined at interpreter exit, so quitting in
    the middle of a model download or transcription would leave the process alive.
    """

    def __init__(self, name="stt"):
        self._jobs = queue.Queue()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()

    def submit(self, fn, *args):
        self._jobs.put((fn, args))

    def _run(self):
        while True:
            job = self._jobs.get()
            if job is None:
                return
            fn, args = job
            try:
                fn(*args)
            except Exception:
                pass  # jobs report their own errors through events

    def shutdown(self):
        while True:
            try:
                self._jobs.get_nowait()
            except queue.Empty:
                break
        self._jobs.put(None)


class ModelCache:
    """Holds at most one Whisper model; a different name replaces it.

    downloader(name, progress) returns the model's local folder, fetching it first if needed.
    By default only the real Whisper loader gets one (test loaders never touch the network).
    """

    def __init__(self, loader=_load_whisper, downloader=None):
        self._loader = loader
        self._downloader = downloader or (download_whisper if loader is _load_whisper else None)
        self._lock = threading.Lock()
        self._name = None
        self._model = None
        self._release_after_load = False

    @property
    def loaded_name(self):
        return self._name if self._model is not None else None

    def get(self, name, notify=None):
        """notify("download", done_mb, total_mb, seconds) while downloading, then notify("load")."""
        with self._lock:
            self._release_after_load = False
            if self._model is not None and self._name == name:
                return self._model
            self._model = None
            gc.collect()
            path = None
            if self._downloader is not None:
                path = self._downloader(name, (lambda *a: notify("download", *a)) if notify else None)
            if notify:
                notify("load")
            # A local folder also skips the online update check WhisperModel(name) makes on every load.
            model = self._loader(path or name)
            if self._release_after_load:  # a release was asked for while loading
                self._release_after_load = False
                return model  # use it once, but do not keep it
            self._model = model
            self._name = name
            return self._model

    def release(self):
        """Drop the model. Never blocks: if a load is running, it is dropped when the load ends."""
        if not self._lock.acquire(blocking=False):
            self._release_after_load = True
            return False
        try:
            had = self._model is not None
            self._model = None
            self._name = None
        finally:
            self._lock.release()
        if had:
            gc.collect()
        return had


class SttService:
    def __init__(self, recorder=None, cache=None, timer_factory=threading.Timer,
                 model="small", language="en", unload_when_idle=False,
                 auto_unload=True, auto_unload_minutes=3):
        self.events = EventEmitter()
        self.recorder = recorder or Recorder()
        self.cache = cache or ModelCache()
        self._timer_factory = timer_factory
        self._timer = None
        self._lock = threading.Lock()
        self._state = SttState.IDLE
        self._target = None
        self._pool = _Worker()
        self._load_failed = None  # (model name, exception) from this recording's preload
        self.downloading = False
        self.model = model
        self.language = language
        self.unload_when_idle = unload_when_idle
        self.auto_unload = auto_unload
        self.auto_unload_minutes = auto_unload_minutes
        self.input_device = None
        self.live = True  # send partial captions while recording
        self._session = 0  # bumped by start/stop/cancel: a pass from an old session never reports
        self._recording = 0  # the session that start() opened: stop keeps it, a new start replaces it
        self._cancelled = False
        self._settled_text = ""
        self._settled_samples = 0
        self._last_pass = None  # (settled_samples, end_samples, tail_text) of the newest live pass
        self.preview_enabled = True  # instant preview words (English, once its model is downloaded)
        self.preview_factory = None  # tests: callable(on_words, on_pause) -> session with feed/stop
        self._preview = None
        self._preview_words = []
        self._preview_installing = False
        self._preview_failed = False
        self._checked = ("", 0.0)  # Whisper's text after the settled part, and the audio second it reaches
        self._pass_now = threading.Event()
        self._caption_lock = threading.Lock()
        self.recorder.on_limit = lambda: self.stop()

    @property
    def state(self):
        return self._state

    def level(self):
        return self.recorder.level

    def _set_state(self, state):
        self._state = state
        self.events.emit("state_changed", state)

    # --- configuration -------------------------------------------------------------
    def set_model(self, name):
        if name and name != self.model:
            self.model = name
            if self.cache.loaded_name not in (None, name):
                self.cache.release()
                self.events.emit("model_status", "Model will load on next use")

    def configure(self, *, unload_when_idle, auto_unload, minutes):
        self.unload_when_idle = unload_when_idle
        self.auto_unload = auto_unload
        self.auto_unload_minutes = max(1, min(60, int(minutes)))
        self.went_idle()  # like v4: saving with "unload when idle" frees the model right away

    # --- recording ---------------------------------------------------------------------
    def toggle(self, target=None):
        if self._state is SttState.RECORDING:
            self.stop()
            return
        if self._state is SttState.TRANSCRIBING:
            self.events.emit("model_status", self.busy_message())
            return
        self.start(target)

    def start(self, target=None):
        with self._lock:
            if self._state is not SttState.IDLE:
                return False
            self._cancel_timer()
            failure = None
            try:
                self.recorder.start(self.input_device)
            except Exception as exc:
                failure = f"Could not start recording: {friendly_audio_error(exc)}"
                self._schedule_unload()  # the timer was cancelled above
            else:
                self._target = target
                self._load_failed = None
                self._cancelled = False
                self._settled_text = ""
                self._settled_samples = 0
                self._last_pass = None
                self._checked = ("", 0.0)
                self._preview_words = []
                self._pass_now.clear()
                self._session += 1
                session = self._recording = self._session
                self._set_state(SttState.RECORDING)
                self._start_preview(session)
        if failure:  # after the lock: the message box runs its own event loop, where a hotkey can call start again
            self.events.emit("error", failure)
            return False
        if self.cache.loaded_name != self.model:
            self._pool.submit(self._preload)
        if self.live and hasattr(self.recorder, "snapshot"):
            self._pool.submit(self._live_loop, session)
        return True

    def busy_message(self):
        if self.downloading:
            return f"Still downloading the {self.model} model (first use only)..."
        return "Still transcribing the last recording..."

    def _notify(self, kind, done=None, total=None, seconds=0):
        """Model progress from the cache, as model_status messages."""
        if kind == "download":
            self.downloading = True
            if done is not None and total:
                text = f"Downloading the {self.model} model... {done} of {total} MB (first use only)"
            else:
                size = f"about {total} MB, " if total else ""
                text = f"Downloading the {self.model} model... {size}{seconds} s so far (first use only)"
        else:
            self.downloading = False
            text = f"Loading {self.model} model..."
        self.events.emit("model_status", text)

    def _get_model(self):
        try:
            return self.cache.get(self.model, self._notify)
        finally:
            self.downloading = False

    def _preload(self):
        try:
            self._get_model()
            self.events.emit("model_status", f"{self.model} model ready")
        except Exception as exc:
            # Remembered so the transcription does not repeat the same slow failing load.
            self._load_failed = (self.model, exc)
            self.events.emit("model_status", f"Model failed to load: {exc}")

    def stop(self):
        with self._lock:
            if self._state is not SttState.RECORDING:
                return False
            audio = self.recorder.stop()
            self._stop_preview()
            target = self._target
            self._session += 1
            self._set_state(SttState.TRANSCRIBING)
        self._pool.submit(self._transcribe, audio, target)
        return True

    def cancel(self):
        """Throw the recording away: nothing is typed. Works while recording or transcribing."""
        with self._lock:
            if self._state is SttState.IDLE:
                return False
            self._session += 1
            self._cancelled = True
            if self._state is SttState.RECORDING:
                self.recorder.stop()
                self._stop_preview()
                self._set_state(SttState.IDLE)
                self._schedule_unload()
        self.events.emit("model_status", "Dictation cancelled")
        return True

    # --- instant preview ------------------------------------------------------------------
    def preview_wanted(self):
        return self.live and self.preview_enabled and self.language == "en"

    def _start_preview(self, session):
        """Feed the recorder's blocks to the instant preview, if it can run this time."""
        self._preview = None
        self.recorder.on_block = None
        if not self.preview_wanted() or self._preview_failed:
            return
        if self.preview_factory is None:
            if not preview_mod.available():
                return
            if not preview_mod.installed():
                self._install_preview()
                return

        def on_words(words):
            if self._session == session:
                with self._caption_lock:
                    self._preview_words = words
                self._emit_partial(session)

        def on_pause():
            self._pass_now.set()

        try:
            if self.preview_factory is not None:
                session_obj = self.preview_factory(on_words, on_pause)
            else:
                rate = getattr(self.recorder, "capture_rate", self.recorder.sample_rate)
                session_obj = preview_mod.PreviewSession(on_words, on_pause, convert=_block_converter(rate)).start()
        except Exception:
            log.exception("The live preview could not start")
            return
        self._preview = session_obj
        self.recorder.on_block = session_obj.feed

    def _preview_alive(self):
        """Whether the preview is running. One that failed is dropped, and the user is told once."""
        session = self._preview
        if session is None:
            return False
        error = getattr(session, "error", None)
        if error is None:
            return True
        self._preview = None
        self.recorder.on_block = None
        self._preview_failed = True  # try again after a restart, not on every dictation
        self.events.emit("preview_status", f"Live preview failed: {error}. Captions come from Whisper alone for now.")
        return False

    def _stop_preview(self):
        self.recorder.on_block = None
        if self._preview is not None:
            self._preview.stop()
            self._preview = None

    def _install_preview(self):
        """Download the preview model in the background (once); the next dictation uses it."""
        if self._preview_installing or self._preview_failed:
            return
        self._preview_installing = True

        def progress(done, total):
            self.events.emit("preview_status", f"Downloading the live preview... {done} of {total} MB (first use only)")

        def run():
            try:
                preview_mod.install(progress)
                self.events.emit("preview_status", "Live preview ready")
            except Exception as exc:
                self._preview_failed = True  # try again after a restart, not on every dictation
                self.events.emit("preview_status", f"Live preview download failed: {exc}")
            finally:
                self._preview_installing = False

        threading.Thread(target=run, name="stt-preview-download", daemon=True).start()

    def _emit_partial(self, session):
        """Settled + checked text from Whisper, then the preview words it has not reached yet."""
        with self._caption_lock:
            if self._session != session or self._state is not SttState.RECORDING:
                return
            settled = normalize_transcript_text(self._settled_text) if self._settled_text else ""
            checked, reached = self._checked
            if checked.endswith("..."):  # Whisper's mark for a word it only half heard
                checked = checked[:-3].rstrip()
            if checked.endswith("-"):  # a word cut off ("r-"): the preview shows it whole
                checked = checked.rsplit(" ", 1)[0] if " " in checked else ""
            newer = [w for w, start in self._preview_words if start >= reached - SEAM_SECONDS]
            newer, guessed = _after_overlap(f"{settled} {checked}", newer)
            if guessed and checked:  # Whisper's last word was a guess the preview has heard better
                checked = checked.rsplit(" ", 1)[0] if " " in checked else ""
            self.events.emit("partial", settled, checked, " ".join(newer))

    # --- live captions ----------------------------------------------------------------------
    def _whisper(self, model, audio, words=False):
        """[(start, end, text)] per segment, or per word with words=True (long live passes:
        run-on speech can be one long segment, and only word times show where it pauses)."""
        language = None if self.language == "auto" else self.language
        prompt = INITIAL_PROMPT
        if self._settled_text:
            prompt = f"{INITIAL_PROMPT} {self._settled_text[-PROMPT_TAIL:]}"
        segments, _ = model.transcribe(
            audio, language=language, beam_size=1, best_of=1, temperature=0.0,
            condition_on_previous_text=True, vad_filter=True, initial_prompt=prompt,
            **({"word_timestamps": True} if words else {}),
        )
        units = []
        for seg in segments:
            parts = [(w.start, w.end, w.word) for w in (getattr(seg, "words", None) or [])] if words else []
            units += parts or [(seg.start, seg.end, seg.text)]
        # A piece without a single letter or digit ("______", "...") is Whisper hearing noise.
        return [(start, end, (text or "").strip()) for start, end, text in units
                if any(ch.isalnum() for ch in (text or ""))]

    @staticmethod
    def _quiet_point(audio, rate, start, end, speech):
        """The middle of the quietest PAUSE_WINDOW in audio[start:end] (seconds), or None
        if nothing there is quiet enough to be a pause between words (speech: the recording's level)."""
        win = int(rate * PAUSE_WINDOW)
        a, b = max(0, int(start * rate)), min(audio.size, int(end * rate))
        if b - a < win:
            a, b = max(0, (a + b - win) // 2), min(audio.size, (a + b + win) // 2)
            if b - a < win:
                return None
        hop = max(1, win // 4)
        frames = np.lib.stride_tricks.sliding_window_view(audio[a:b], win)[::hop]
        levels = np.sqrt(np.mean(frames * frames, axis=1))
        i = int(np.argmin(levels))
        if levels[i] > PAUSE_LEVEL * speech:
            return None
        return a + i * hop + win // 2

    def _settle(self, segments, audio):
        """For a long recording, make text that ended at a real pause final. Returns the
        text of the rest (the tail, which may still change)."""
        rate = self.recorder.sample_rate
        seconds = audio.size / rate
        cut, cut_sample = 0, 0
        if seconds > WHOLE_SECONDS - SETTLE_GAP:
            speech = float(np.sqrt(np.mean(audio * audio))) or 1e-9
            for i in range(len(segments) - 2, -1, -1):  # the latest real pause is the one wanted
                end = segments[i][1]
                if end > seconds - SETTLE_GAP:
                    continue
                point = self._quiet_point(audio, rate, end - 0.15, segments[i + 1][0] + 0.15, speech)
                if point is not None:
                    cut, cut_sample = i + 1, point
                    break
            if not cut and seconds > MAX_TAIL and len(segments) > 1:  # no pause: cut at the last segment
                cut, cut_sample = len(segments) - 1, int(segments[-2][1] * rate)
        if cut:
            settled = " ".join(t for _s, _e, t in segments[:cut] if t)
            self._settled_text = f"{self._settled_text} {settled}".strip()
            self._settled_samples += cut_sample
        return " ".join(t for _s, _e, t in segments[cut:] if t)

    def _live_loop(self, session):
        """Runs on the worker while recording: transcribe the new audio, report it, rest."""
        import time

        rate = self.recorder.sample_rate
        while self._session == session and self._state is SttState.RECORDING:
            if self.cache.loaded_name != self.model:
                if self._load_failed or self.downloading:
                    return  # no captions this time; the final transcription reports the problem
                time.sleep(0.2)
                continue
            audio = self.recorder.snapshot(self._settled_samples)
            if audio.size < rate * LIVE_MIN_AUDIO:
                time.sleep(0.2)
                continue
            self._pass_now.clear()
            started = time.monotonic()
            base = self._settled_samples
            try:
                segments = self._whisper(self._get_model(), audio,
                                         words=audio.size / rate > WHOLE_SECONDS - SETTLE_GAP)
            except Exception:
                log.exception("A live caption pass failed; captions stop until the next dictation")
                return
            # Kept even if dictation stopped meanwhile: stop can use it instead of a new pass.
            # Not if a newer dictation began: this text is not part of that one.
            if self._recording == session:
                self._last_pass = (base, base + audio.size, " ".join(t for _s, _e, t in segments if t))
            if self._session != session:
                return
            with self._caption_lock:
                tail = self._settle(segments, audio)
                self._checked = (tail, (base + audio.size) / rate)
            if self._settled_samples != base:
                self._last_pass = None
            self._emit_partial(session)
            spent = time.monotonic() - started
            rest = max(LIVE_PREVIEW_REST if self._preview_alive() else LIVE_REST, spent * LIVE_REST_SHARE)
            end = time.monotonic() + rest
            while time.monotonic() < end and self._session == session and not self._pass_now.is_set():
                time.sleep(0.02)

    def _transcribe(self, audio, target):
        try:
            if self._cancelled:
                return
            if audio.size < self.recorder.sample_rate * 0.2:
                self.events.emit("model_status", "No audio captured")
                return
            if float(abs(audio).max()) < SILENT_PEAK:
                self.events.emit("error", SILENT_MIC_MESSAGE)
                return
            failed, self._load_failed = self._load_failed, None
            if failed and failed[0] == self.model:
                self.events.emit("error", f"Could not transcribe: the {self.model} model failed to load ({failed[1]})")
                return
            tail = self._reusable_tail(audio)
            if tail is None:
                # Only what the live captions have not settled yet (all of it if they never ran).
                tail_audio = audio[self._settled_samples:]
                tail = ""
                if tail_audio.size >= self.recorder.sample_rate * 0.2:
                    tail = " ".join(t for _s, _e, t in self._whisper(self._get_model(), tail_audio) if t)
            text = normalize_transcript_text(f"{self._settled_text} {tail}".strip())
            if self._cancelled:
                return
            if text:
                self.events.emit("transcript_ready", text, target)
            else:
                self.events.emit("model_status", "No speech detected")
        except Exception as exc:
            self.events.emit("error", f"Failed to transcribe: {exc}")
        finally:
            self._set_state(SttState.IDLE)
            if self.unload_when_idle:
                self.unload()
            else:
                self._schedule_unload()

    def _reusable_tail(self, audio):
        """The newest live pass's text, if it covered the audio up to the end or only
        silence came after it; None if the end has to be transcribed again."""
        last = self._last_pass
        if last is None or last[0] != self._settled_samples:
            return None
        rate = self.recorder.sample_rate
        rest = audio[last[1]:]
        if rest.size <= rate * REUSE_SECONDS:
            return last[2]
        # Only silence after it: both the voice detector and the sound level must agree, so a
        # short last word said right before stop is never dropped.
        if not _has_speech(rest, rate) and not _loud_part(rest, audio, rate):
            return last[2]
        return None

    # --- idle unload -----------------------------------------------------------------------
    def _cancel_timer(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _schedule_unload(self):
        self._cancel_timer()
        if not self.auto_unload or self.cache.loaded_name is None:
            return
        self._timer = self._timer_factory(self.auto_unload_minutes * 60, self._on_idle_timeout)
        self._timer.daemon = True
        self._timer.start()

    def went_idle(self):
        """Apply the unload rules (used when the user leaves Listen mode)."""
        if self._state is not SttState.IDLE:
            return
        if self.unload_when_idle:
            self.unload()
        else:
            self._schedule_unload()

    def _on_idle_timeout(self):
        self._timer = None
        if self._state is not SttState.IDLE:
            return
        self.unload()

    def unload(self):
        self._cancel_timer()
        preview_mod.release()
        if self.cache.release():
            self.events.emit("model_status", "Model unloaded to free memory")

    def shutdown(self):
        if self._state is SttState.RECORDING:
            self.recorder.stop()
        self._cancel_timer()
        self._pool.shutdown()
