"""Speech renderers: turn text into PCM samples without playing them.

A renderer belongs to the thread that created it (SAPI is a COM object in a
single-threaded apartment), so the controller creates and uses it on its own
synth thread.
"""
from __future__ import annotations

import contextlib
import gc
import math
import os
import shutil
import subprocess
import tempfile
import threading
import weakref
from dataclasses import dataclass

import numpy as np

from ..platform import IS_WINDOWS, child_env
from .wavparse import parse_wav


class Cancelled(Exception):
    """Rendering stopped because the cancel event was set."""


@dataclass(frozen=True)
class Voice:
    id: str
    name: str
    language: str = ""
    gender: str = ""


def pick_default_voice(voices, preferred_id=""):
    """The saved voice if present, else the first female/Zira voice (v4 rule), else the first."""
    ids = {v.id for v in voices}
    if preferred_id and preferred_id in ids:
        return preferred_id
    # Prefer English voices so a missing saved voice never falls back to a random language.
    english = [v for v in voices if _is_english(v)]
    pool = english or list(voices)
    for v in pool:
        if "female" in v.name.lower() or "zira" in v.name.lower() or v.gender.lower() == "female":
            return v.id
    return pool[0].id if pool else ""


def _is_english(voice):
    lang = (voice.language or "").lower()
    # SAPI uses hex LCIDs: 409 en-US, 809 en-GB, c09 en-AU, 1009 en-CA, 4009 en-IN
    return lang.startswith("en") or lang in ("409", "809", "c09", "1009", "1409", "4009") or "english" in voice.name.lower()


SAPI_WPM_AT_0 = 156.63  # pyttsx3's words-per-minute scale for SAPI rates (as in v4)
SAPI_STEP = 1.11


def sapi_rate(wpm):
    """Nearest SAPI rate (-10..10) for a words-per-minute speed."""
    try:
        value = round(math.log(max(1.0, float(wpm)) / SAPI_WPM_AT_0, SAPI_STEP))
    except (TypeError, ValueError):
        value = 0
    return max(-10, min(10, value))


def sapi_wpm(rate):
    """The words-per-minute speed SAPI speaks at for an integer rate."""
    return SAPI_WPM_AT_0 * SAPI_STEP ** rate


ONECORE_VOICES = r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices"


def _base_voice_name(name):
    """ "Microsoft Zira Desktop - English (United States)" and "Microsoft Zira - English
    (United States)" are the same voice."""
    return name.replace(" Desktop", "").strip().lower()


class SapiRenderer:
    """Windows SAPI5 rendering into an in-memory stream (22 kHz, 16-bit, mono).

    Besides the classic SAPI5 voices it lists the Windows 10/11 ("OneCore") voices, which
    SAPI can speak but does not list by default (e.g. Mark).
    """

    name = "sapi5"
    sample_rate = 22050
    _FORMAT_22KHZ_16BIT_MONO = 22
    _FLAGS = 1 | 2 | 16  # async | purge before speak | not XML

    def __init__(self):
        import comtypes.client

        self._client = comtypes.client
        self._voice = self._client.CreateObject("SAPI.SpVoice")
        self._tokens = {}
        self._current_voice = None

    def _onecore_tokens(self):
        try:
            category = self._client.CreateObject("SAPI.SpObjectTokenCategory")
            category.SetId(ONECORE_VOICES, False)
            tokens = category.EnumerateTokens()
            return [tokens.Item(i) for i in range(tokens.Count)]
        except Exception:
            return []  # older Windows, or the category is missing

    def list_voices(self):
        voices = []
        self._tokens = {}
        tokens = self._voice.GetVoices()
        seen = set()
        for tok in [tokens.Item(i) for i in range(tokens.Count)] + self._onecore_tokens():
            try:
                name = tok.GetDescription()
            except Exception:
                continue
            if _base_voice_name(name) in seen:
                continue  # the same voice in both lists: keep the classic one
            seen.add(_base_voice_name(name))
            try:
                gender = tok.GetAttribute("Gender") or ""
            except Exception:
                gender = ""
            try:
                language = tok.GetAttribute("Language") or ""
            except Exception:
                language = ""
            self._tokens[tok.Id] = tok
            voices.append(Voice(id=tok.Id, name=name, language=language, gender=gender))
        return voices

    def _apply_voice(self, voice_id):
        if not voice_id or voice_id == self._current_voice:
            return
        if not self._tokens:
            self.list_voices()
        tok = self._tokens.get(voice_id)
        if tok is not None:
            self._voice.Voice = tok
            self._current_voice = voice_id

    @staticmethod
    def native_wpm(wpm, voice_id=None):
        """The speed audio rendered for wpm really has (SAPI only has 21 rates)."""
        return sapi_wpm(sapi_rate(wpm))

    def render(self, text, voice_id, wpm, cancel):
        self._apply_voice(voice_id)
        self._voice.Rate = sapi_rate(wpm)
        self._voice.Volume = 100
        stream = self._client.CreateObject("SAPI.SpMemoryStream")
        fmt = self._client.CreateObject("SAPI.SpAudioFormat")
        fmt.Type = self._FORMAT_22KHZ_16BIT_MONO
        stream.Format = fmt
        self._voice.AllowAudioOutputFormatChangesOnNextSet = False
        self._voice.AudioOutputStream = stream
        self._voice.Speak(text, self._FLAGS)
        while not self._voice.WaitUntilDone(30):
            if cancel.is_set():
                self._voice.Speak("", 3)
                self._voice.WaitUntilDone(500)
                raise Cancelled()
        if cancel.is_set():
            raise Cancelled()
        data = bytes(stream.GetData())
        return np.frombuffer(data, dtype=np.int16).copy(), self.sample_rate


class EspeakRenderer:
    """Linux espeak-ng via subprocess (killable for instant cancel)."""

    name = "espeak-ng"
    sample_rate = 22050

    def __init__(self, binary=None):
        self.binary = binary or shutil.which("espeak-ng") or shutil.which("espeak")
        if not self.binary:
            raise RuntimeError("espeak-ng is not installed")

    def list_voices(self):
        out = subprocess.run([self.binary, "--voices"], capture_output=True, text=True, timeout=10,
                             env=child_env()).stdout
        voices = []
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 4:
                continue
            language, age_gender, name = parts[1], parts[2], parts[3]
            gender = {"M": "Male", "F": "Female"}.get(age_gender.split("/")[-1], "")
            voices.append(Voice(id=language, name=f"{name.replace('_', ' ')} ({language})",
                                language=language, gender=gender))
        return voices

    def render(self, text, voice_id, wpm, cancel):
        cmd = [self.binary, "-s", str(int(wpm)), "-a", "100", "-b", "1", "--stdout"]
        if voice_id:
            cmd[1:1] = ["-v", voice_id]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                env=child_env())
        result = {}

        def run():
            result["out"], _ = proc.communicate(text.encode("utf-8"))

        th = threading.Thread(target=run, daemon=True)
        th.start()
        while th.is_alive():
            th.join(0.03)
            if cancel.is_set():
                proc.kill()
                th.join(1)
                raise Cancelled()
        return parse_wav(result.get("out", b""))


class Pyttsx3FileRenderer:
    """Fallback: pyttsx3 save_to_file into a private temp WAV.

    pyttsx3 shares one engine per driver across the process, so all instances
    take turns through a class lock (speech and export can both use it).
    """

    name = "pyttsx3"
    sample_rate = 22050
    _engine_lock = threading.Lock()

    def __init__(self):
        import pyttsx3

        if IS_WINDOWS:
            self._engine = pyttsx3.init()
        else:
            try:
                self._engine = pyttsx3.init("espeak")
            except Exception:
                self._engine = pyttsx3.init()
        self._dir = tempfile.mkdtemp(prefix="ttspython_")
        weakref.finalize(self, shutil.rmtree, self._dir, True)

    def list_voices(self):
        out = []
        for v in self._engine.getProperty("voices"):
            out.append(Voice(id=v.id, name=v.name or v.id, language=",".join(map(str, v.languages or [])),
                             gender=v.gender or ""))
        return out

    def render(self, text, voice_id, wpm, cancel):
        if cancel.is_set():
            raise Cancelled()
        path = os.path.join(self._dir, "chunk.wav")
        with self._engine_lock:
            with contextlib.suppress(FileNotFoundError):
                os.remove(path)  # so an engine that writes nothing cannot replay the last chunk
            if voice_id:
                self._engine.setProperty("voice", voice_id)
            self._engine.setProperty("rate", int(wpm))
            self._engine.setProperty("volume", 1.0)
            self._engine.save_to_file(text, path)
            self._engine.runAndWait()
            if cancel.is_set():
                raise Cancelled()
            if not os.path.exists(path):
                raise RuntimeError("The pyttsx3 speech engine produced no audio.")
            with open(path, "rb") as f:
                data = f.read()
        return parse_wav(data)


class MultiRenderer:
    """The system voices plus downloaded Piper voices; each render goes to the engine
    that owns the voice (Piper voice ids start with "piper:")."""

    def __init__(self, system, piper=None, system_voices=None):
        self.system = system
        self._system_voices = system_voices  # already listed while choosing the engine
        if piper is None:
            from .piper import PiperRenderer

            piper = PiperRenderer()
        self.piper = piper
        self.name = system.name
        self.sample_rate = system.sample_rate

    def _engine(self, voice_id):
        return self.piper if voice_id and voice_id.startswith("piper:") else self.system

    def list_voices(self):
        system, self._system_voices = self._system_voices, None
        if system is None:
            system = self.system.list_voices()
        return list(system) + self.piper.list_voices()

    def warm_up(self, wpm):
        """Pay the system engine's one-time costs (a Piper voice starts on first use)."""
        self.system.render("a", "", wpm, threading.Event())

    def native_wpm(self, wpm, voice_id=None):
        engine = self._engine(voice_id)
        return engine.native_wpm(wpm, voice_id) if hasattr(engine, "native_wpm") else wpm

    def render(self, text, voice_id, wpm, cancel):
        return self._engine(voice_id).render(text, voice_id, wpm, cancel)


def create_system_renderer():
    """Best system-voice renderer for this platform, falling back to pyttsx3 files.
    Returns (renderer, its voices)."""
    errors = []
    candidates = [SapiRenderer] if IS_WINDOWS else [EspeakRenderer]
    for cls in candidates + [Pyttsx3FileRenderer]:
        try:
            renderer = cls()
            return renderer, renderer.list_voices()
        except Exception as exc:
            errors.append(f"{cls.__name__}: {exc}")
    raise RuntimeError("No speech engine available. " + "; ".join(errors))


def create_renderer():
    system, voices = create_system_renderer()
    return MultiRenderer(system, system_voices=voices)


def trim_leading_silence(pcm, sample_rate, threshold=104, max_seconds=0.3, keep_seconds=0.02):
    """Drop up to max_seconds of near-silence (-50 dBFS) from the start."""
    if pcm.size == 0:
        return pcm
    loud = np.flatnonzero(np.abs(pcm.astype(np.int32)) > threshold)
    if loud.size == 0:
        return pcm
    cut = min(int(loud[0]) - int(keep_seconds * sample_rate), int(max_seconds * sample_rate))
    return pcm[cut:] if cut > 0 else pcm


def list_voices_once():
    """Enumerate voices with a throwaway renderer (used by check_voices.py)."""
    from ..platform import com_apartment

    with com_apartment():
        renderer = create_renderer()
        result = renderer.name, renderer.list_voices()
        del renderer  # its COM objects must go while the apartment is open
        gc.collect()
    return result
