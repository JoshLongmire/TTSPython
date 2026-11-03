"""Load the v4.1.0 tkinter app from git with fake speech/audio modules.

Nothing here touches the real clipboard, microphone, speakers or settings:
v4 keeps its settings next to its own file, which lives in a temp folder.
"""
import importlib.util
import os
import struct
import subprocess
import sys
import threading
import time
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


CHILD_ENV = "TTSPYTHON_LEGACY_CHILD"


def pytest_collection_modifyitems(items):
    for item in items:
        if "legacy" in str(item.fspath):
            item.add_marker(pytest.mark.legacy)


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    """Run each v4 spec in its own process: v4 threads and Tk do not survive reuse."""
    if "legacy" not in str(pyfuncitem.fspath) or os.environ.get(CHILD_ENV):
        return None
    env = dict(os.environ, **{CHILD_ENV: "1"})
    cmd = [sys.executable, "-m", "pytest", pyfuncitem.nodeid, "-m", "legacy", "--runxfail", "-q",
           "-p", "no:cacheprovider", "-p", "no:warnings"]
    out = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        lines = [ln for ln in out.stdout.splitlines() if ln.startswith("E ")]
        raise AssertionError("\n".join(lines[:12]) or out.stdout[-2000:])
    return True


class FakeVoice:
    def __init__(self, vid, name):
        self.id, self.name, self.languages, self.gender = vid, name, ["en_US"], "Female"


VOICES = [FakeVoice("v-david", "Microsoft David Desktop"), FakeVoice("v-zira", "Microsoft Zira Desktop")]


class FakeEngine:
    """pyttsx3 engine stand-in. runAndWait 'speaks' for run_seconds; stop() lands after stop_lag."""

    lock = threading.Lock()
    running = 0
    max_running = 0
    said = []
    instances = []
    run_seconds = 0.15
    stop_lag = 0.25

    @classmethod
    def reset(cls):
        cls.running = cls.max_running = 0
        cls.said = []
        cls.instances = []
        cls.run_seconds = 0.15
        cls.stop_lag = 0.25

    def __init__(self):
        self.props = {"rate": 200, "volume": 1.0, "voice": "v-david"}
        self.callbacks = {}
        self.stop_calls = 0
        self.save_path = None
        self._stop = threading.Event()
        FakeEngine.instances.append(self)

    def getProperty(self, name):  # noqa: N802
        return VOICES if name == "voices" else self.props.get(name)

    def setProperty(self, name, value):  # noqa: N802
        self.props[name] = value

    def say(self, text):
        FakeEngine.said.append(text)

    def connect(self, name, cb):
        self.callbacks[name] = cb

    def save_to_file(self, text, path):
        self.save_path = path

    def runAndWait(self):  # noqa: N802
        with FakeEngine.lock:
            FakeEngine.running += 1
            FakeEngine.max_running = max(FakeEngine.max_running, FakeEngine.running)
        try:
            cb = self.callbacks.get("started-word")
            if cb:
                cb("word", 0, 4)
            end = time.monotonic() + FakeEngine.run_seconds
            while time.monotonic() < end:
                if self._stop.is_set():
                    time.sleep(FakeEngine.stop_lag)
                    break
                time.sleep(0.005)
            if self.save_path:
                data = b"\x00\x00" * 2205
                header = (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt "
                          + struct.pack("<IHHIIHH", 16, 1, 1, 22050, 44100, 2, 16) + b"data" + struct.pack("<I", len(data)))
                with open(self.save_path, "wb") as f:
                    f.write(header + data)
        finally:
            with FakeEngine.lock:
                FakeEngine.running -= 1

    def stop(self):
        self.stop_calls += 1
        self._stop.set()

    def endLoop(self):  # noqa: N802
        pass


class FakeInputStream:
    devices = []

    def __init__(self, samplerate=None, channels=None, dtype=None, device=None, callback=None, **_):
        FakeInputStream.devices.append(device)
        self.callback = callback

    def start(self):
        pass

    def stop(self):
        pass

    def close(self):
        pass


class FakeWhisper:
    loaded = []

    def __init__(self, name, **_):
        FakeWhisper.loaded.append(name)
        self.name = name

    def transcribe(self, *_a, **_k):
        return [types.SimpleNamespace(text="hello there")], None


@pytest.fixture(scope="session")
def v4_source(tmp_path_factory):
    try:
        src = subprocess.check_output(["git", "show", "v4.1.0:TTSPython.py"], cwd=ROOT)
    except Exception as exc:
        pytest.skip(f"v4.1.0 source not available from git: {exc}")
    folder = tmp_path_factory.mktemp("v4")
    path = folder / "TTSPython.py"
    path.write_bytes(src)
    return str(path)


class StubMessagebox:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args))
            return True
        return record


@pytest.fixture
def v4(v4_source, monkeypatch, tmp_path):
    """(module, app, root, clip) for a fresh v4 ReaderApp (built only in the child process)."""
    if not os.environ.get(CHILD_ENV):
        yield None
        return
    FakeEngine.reset()
    FakeInputStream.devices = []
    FakeWhisper.loaded = []
    fake_pyttsx3 = types.ModuleType("pyttsx3")
    fake_pyttsx3.init = lambda *a, **k: FakeEngine()
    fake_sd = types.ModuleType("sounddevice")
    fake_sd.InputStream = FakeInputStream
    fake_sd.query_devices = lambda *a, **k: []
    fake_fw = types.ModuleType("faster_whisper")
    fake_fw.WhisperModel = FakeWhisper
    monkeypatch.setitem(sys.modules, "pyttsx3", fake_pyttsx3)
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_fw)
    # Fresh copy per test so v4's settings file starts empty.
    src_copy = tmp_path / "TTSPython.py"
    with open(v4_source, "rb") as f:
        src_copy.write_bytes(f.read())
    spec = importlib.util.spec_from_file_location("ttspython_v4", str(src_copy))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.messagebox = StubMessagebox()

    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    clip = {"text": ""}
    root.clipboard_get = lambda *a, **k: clip["text"]
    app = mod.ReaderApp(root)
    yield mod, app, root, clip
    try:
        app.clipboard_monitor_enabled = False
        app.speech_queue = []
        app.clipboard_auto_queue = False
        app.on_stop()
    except Exception:
        pass
    def workers():
        return [t for t in threading.enumerate() if t.daemon and t.is_alive() and t.name.startswith("Thread")]

    pump(root, lambda: FakeEngine.running == 0 and not workers(), 5)
    pump(root, lambda: False, 0.2)
    try:
        root.destroy()
    except Exception:
        pass


def pump(root, cond, timeout):
    """Run the real Tk main loop until cond() or timeout.

    v4's worker threads call into Tk (variables, after()); tkinter only
    marshals those calls while mainloop() is running, so update() is not enough.
    """
    end = time.monotonic() + timeout

    def check():
        if cond() or time.monotonic() >= end:
            root.quit()
            return
        root.after(10, check)

    try:
        root.after(10, check)
        root.mainloop()
    except Exception:
        pass
    return cond()
