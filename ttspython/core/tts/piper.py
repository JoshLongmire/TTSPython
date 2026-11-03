"""Piper neural voices, run by the official Piper program as a separate process.

Piper needs espeak-ng (GPL-3.0). Running the downloaded Piper program instead of
linking it keeps TTSPython itself MIT. The program and each voice are downloaded
once, on first use, into the per-user data folder:

    <data dir>/piper/       the Piper program (piper.exe / piper and its files)
    <data dir>/voices/      <key>.onnx and <key>.onnx.json per voice
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import weakref
from dataclasses import dataclass

from ..download import fetch
from ..platform import IS_WINDOWS, data_dir
from ..settings import NORMAL_WPM
from .render import Cancelled, Voice
from .wavparse import parse_wav

PREFIX = "piper:"
RELEASE = "2023.11.14-2"
RELEASE_URL = f"https://github.com/rhasspy/piper/releases/download/{RELEASE}/"
# The official builds, pinned by checksum.
PROGRAMS = {
    ("win32", "AMD64"): ("piper_windows_amd64.zip", "f3c58906402b24f3a96d92145f58acba6d86c9b5db896d207f78dc80811efcea"),
    ("linux", "x86_64"): ("piper_linux_x86_64.tar.gz", "a50cb45f355b7af1f6d758c1b360717877ba0a398cc8cbe6d2a7a3a26e225992"),
    ("linux", "aarch64"): ("piper_linux_aarch64.tar.gz", "fea0fd2d87c54dbc7078d0f878289f404bd4d6eea6e7444a77835d1537ab88eb"),
}
PROGRAM_MB = 23
VOICES_REVISION = "b4e358ffcb232591bf73a540e70f7de528e4174a"
VOICES_URL = f"https://huggingface.co/rhasspy/piper-voices/resolve/{VOICES_REVISION}/"
SAMPLES_PAGE = "https://rhasspy.github.io/piper-samples/"
QUALITY = {"x_low": "smallest", "low": "small", "medium": "medium", "high": "best"}


@dataclass(frozen=True)
class CatalogVoice:
    key: str
    name: str
    quality: str
    speakers: int
    lang: str
    language: str
    country: str
    model: str
    model_md5: str
    size: int
    config: str
    config_md5: str

    @property
    def id(self):
        return PREFIX + self.key

    @property
    def label(self):
        """e.g. "Lessac (English, United States, medium)"."""
        name = self.name.replace("_", " ").title()
        return f"{name} ({self.language}, {self.country}, {QUALITY.get(self.quality, self.quality)})"


_catalog = []


def catalog():
    """Every Piper voice (bundled list, so it works offline)."""
    if not _catalog:
        path = os.path.join(os.path.dirname(__file__), "piper_voices.json")
        with open(path, encoding="utf-8") as f:
            _catalog.extend(CatalogVoice(**v) for v in json.load(f)["voices"])
    return list(_catalog)


def find(key_or_id):
    key = key_or_id[len(PREFIX):] if key_or_id.startswith(PREFIX) else key_or_id
    return next((v for v in catalog() if v.key == key), None)


# --- where things live ------------------------------------------------------------------------
def program_dir():
    return os.path.join(data_dir(), "piper")


def voices_dir():
    return os.path.join(data_dir(), "voices")


def program_path():
    return os.path.join(program_dir(), "piper.exe" if IS_WINDOWS else "piper")


def program_installed():
    return os.path.isfile(program_path())


def model_path(key):
    return os.path.join(voices_dir(), key + ".onnx")


def installed_keys():
    try:
        names = os.listdir(voices_dir())
    except OSError:
        return []
    return sorted(n[:-5] for n in names
                  if n.endswith(".onnx") and os.path.isfile(os.path.join(voices_dir(), n + ".json")))


def installed_voices():
    """Downloaded voices as Voice entries (only when the program is there to speak them)."""
    if not program_installed():
        return []
    out = []
    for key in installed_keys():
        entry = find(key)
        name = entry.label if entry else key
        lang = entry.lang if entry else key.split("-")[0]
        out.append(Voice(id=PREFIX + key, name=f"{name} - Piper", language=lang))
    return out


# --- downloads ----------------------------------------------------------------------------------
def _platform_key():
    import platform
    import sys

    machine = platform.machine()
    return ("win32" if IS_WINDOWS else sys.platform), {"x86_64": "x86_64", "AMD64": "AMD64", "amd64": "AMD64",
                                                         "aarch64": "aarch64", "arm64": "aarch64"}.get(machine, machine)


def program_available():
    """Is there an official Piper build for this computer?"""
    return _platform_key() in PROGRAMS


def install_program(progress=None, cancel=None, opener=None):
    """Download and unpack the Piper program. progress(done_bytes, total_bytes)."""
    if program_installed():
        return program_path()
    entry = PROGRAMS.get(_platform_key())
    if entry is None:
        raise OSError("There is no Piper build for this computer.")
    name, sha256 = entry
    work = tempfile.mkdtemp(prefix="ttspython-piper-")
    try:
        archive = os.path.join(work, name)
        kwargs = {"opener": opener} if opener else {}
        fetch(RELEASE_URL + name, archive, progress, sha256=sha256, cancel=cancel, **kwargs)
        unpack = os.path.join(work, "unpacked")
        import tarfile
        import zipfile

        if name.endswith(".zip"):
            with zipfile.ZipFile(archive) as z:
                z.extractall(unpack)
        else:
            with tarfile.open(archive) as t:
                try:
                    t.extractall(unpack, filter="data")
                except TypeError:  # Python without extraction filters
                    t.extractall(unpack)  # noqa: S202 (checksum-verified official archive)
        src = os.path.join(unpack, "piper")
        target = program_dir()
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.move(src, target)
        if not IS_WINDOWS:
            os.chmod(program_path(), 0o755)
        return program_path()
    finally:
        shutil.rmtree(work, ignore_errors=True)


def install_voice(key, progress=None, cancel=None, opener=None):
    """Download one voice (and the Piper program first, if needed).

    progress(done_mb, total_mb, what) with what "program" or "voice".
    """
    entry = find(key)
    if entry is None:
        raise KeyError(key)
    kwargs = {"opener": opener} if opener else {}
    if not program_installed():
        install_program(lambda d, t: progress and progress(d // 1_000_000, (t or PROGRAM_MB * 1_000_000) // 1_000_000,
                                                           "program"), cancel, **kwargs)
    folder = voices_dir()
    os.makedirs(folder, exist_ok=True)
    fetch(VOICES_URL + entry.config, model_path(key) + ".json", md5=entry.config_md5, cancel=cancel, **kwargs)
    try:
        fetch(VOICES_URL + entry.model, model_path(key),
              (lambda d, t: progress(d // 1_000_000, (t or entry.size) // 1_000_000, "voice")) if progress else None,
              md5=entry.model_md5, cancel=cancel, **kwargs)
    except BaseException:
        _remove_files(key)
        raise
    return PREFIX + key


def _remove_files(key):
    for path in (model_path(key), model_path(key) + ".json"):
        try:
            os.remove(path)
        except OSError:
            pass


def remove_voice(key):
    _remove_files(key[len(PREFIX):] if key.startswith(PREFIX) else key)


# --- speaking -------------------------------------------------------------------------------------
class _Process:
    """One running Piper program for one voice at one speed: a line of JSON in, a WAV file out."""

    def __init__(self, key, length_scale):
        self.key = key
        self.length_scale = length_scale
        self.out_dir = tempfile.mkdtemp(prefix="ttspython-piper-out-")
        env = dict(os.environ)
        if not IS_WINDOWS:
            env["LD_LIBRARY_PATH"] = program_dir() + os.pathsep + env.get("LD_LIBRARY_PATH", "")
        self.proc = subprocess.Popen(
            [program_path(), "--model", model_path(key), "--json-input", "--quiet",
             "--length_scale", f"{length_scale:.3f}", "--sentence_silence", "0.15",
             "--espeak_data", os.path.join(program_dir(), "espeak-ng-data")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
            cwd=program_dir(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.count = 0

    def alive(self):
        return self.proc.poll() is None

    def say(self, text, cancel):
        self.count += 1
        path = os.path.join(self.out_dir, f"{self.count}.wav")
        line = json.dumps({"text": " ".join(text.split()), "output_file": path}) + "\n"
        self.proc.stdin.write(line.encode("utf-8"))
        self.proc.stdin.flush()
        result = {}

        def read():
            result["line"] = self.proc.stdout.readline()

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        while reader.is_alive():
            reader.join(0.03)
            if cancel.is_set():
                self.close()  # the next render starts a fresh process
                raise Cancelled()
        if not result.get("line"):
            raise RuntimeError("The Piper program stopped unexpectedly.")
        try:
            with open(path, "rb") as f:
                data = f.read()
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        return parse_wav(data)

    def close(self):
        try:
            self.proc.kill()
            self.proc.wait(2)
        except Exception:
            pass
        shutil.rmtree(self.out_dir, ignore_errors=True)


# Piper's speech length grows only about as length_scale ** 0.71 (measured), so the scale is
# raised to the power 1.4 to make the speed follow the slider. That holds within 2% from 150 to
# 300 words per minute; beyond, Piper renders at the edge and the player stretches the rest.
LENGTH_POWER = 1.4
NATIVE_MIN_WPM, NATIVE_MAX_WPM = 150, 300
IDLE_SECONDS = 120  # a Piper program not used for this long is closed (it holds the voice in memory)


class PiperRenderer:
    """Speaks downloaded Piper voices; the program runs only while a Piper voice is in use."""

    name = "piper"
    sample_rate = 22050

    def __init__(self):
        self._proc = None
        self._idle_timer = None
        self._lock = threading.Lock()  # the idle timer must not close a program mid-render
        self._finalizer = weakref.finalize(self, PiperRenderer._close, self.__dict__)

    @staticmethod
    def _close(state):
        proc = state.get("_proc")
        if proc is not None:
            proc.close()

    def list_voices(self):
        return installed_voices()

    @staticmethod
    def native_wpm(wpm, voice_id=None):
        return max(NATIVE_MIN_WPM, min(NATIVE_MAX_WPM, wpm))

    def render(self, text, voice_id, wpm, cancel):
        if cancel.is_set():
            raise Cancelled()
        key = voice_id[len(PREFIX):]
        if not program_installed() or not os.path.isfile(model_path(key)):
            raise RuntimeError("This Piper voice is not downloaded. Open Settings > Speech > Get more voices.")
        length_scale = round((NORMAL_WPM / float(self.native_wpm(wpm))) ** LENGTH_POWER, 3)
        with self._lock:
            proc = self._proc
            if proc is None or proc.key != key or proc.length_scale != length_scale or not proc.alive():
                if proc is not None:
                    proc.close()
                proc = self._proc = _Process(key, length_scale)
            try:
                return proc.say(text, cancel)
            except Cancelled:
                self._proc = None
                raise
            finally:
                self._close_when_idle(proc)

    def _close_when_idle(self, proc):
        if self._idle_timer is not None:
            self._idle_timer.cancel()

        def close():
            with self._lock:
                if self._proc is proc:
                    self._proc = None
                    proc.close()

        self._idle_timer = threading.Timer(IDLE_SECONDS, close)
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def close(self):
        if self._proc is not None:
            self._proc.close()
            self._proc = None
