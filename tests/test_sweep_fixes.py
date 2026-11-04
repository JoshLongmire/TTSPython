"""Bugs found by the 5.0.0 code sweep: each of these failed before its fix."""
import os
import queue
import stat
import threading
import urllib.error

import numpy as np
import pytest

from fakes import wait_for
from test_stt_service import FakeRecorder, FakeTimer, make_service
from test_ui import make_controller
from ttspython.core import download, keys, search, textio
from ttspython.core.stt import preview
from ttspython.core.stt.service import ModelCache, SttService
from ttspython.core.tts import piper, render
from ttspython.core.tts.player import AudioPlayer
from ttspython.platform import inject


# --- hotkeys ----------------------------------------------------------------------------------
@pytest.mark.parametrize("combo", ["D", "Space", "Return", "Backspace", "Left", "1"])
def test_a_global_hotkey_on_a_typing_key_is_refused(combo):
    assert keys.global_hotkey_problem(combo) == "Add Ctrl, Alt or Shift"


@pytest.mark.parametrize("combo", ["", "Ctrl+D", "Alt+Space", "Shift+Left", "F9", "Ctrl+Alt+Shift+M"])
def test_normal_global_hotkeys_are_fine(combo):
    assert keys.global_hotkey_problem(combo) is None


def test_settings_will_not_save_a_global_hotkey_that_would_swallow_a_key(qtbot, tmp_path):
    from PySide6.QtGui import QKeySequence

    c = make_controller(qtbot, tmp_path)
    try:
        c.open_settings("shortcuts")
        dlg = c._settings_dialog
        edit, status = dlg.global_edits["stop_speech"]
        edit.setKeySequence(QKeySequence("D"))
        assert status.text() == "Add Ctrl, Alt or Shift"
        assert dlg._save() is False
        assert c.settings["global_hotkeys"]["stop_speech"] != "D"
        edit.setKeySequence(QKeySequence("Ctrl+Alt+F8"))
        assert status.text() == "" and dlg._save() is True
    finally:
        c.quit()


# --- find and replace --------------------------------------------------------------------------
def test_replace_all_agrees_with_find_about_empty_matches():
    assert search.match_starts("abc", "x*", use_regex=True) == []
    assert search.replace_all("abc", "x*", "-", use_regex=True) == ("abc", 0)
    assert search.replace_all("axxb", "x*", "-", use_regex=True) == ("a-b", 1)


def test_replace_all_still_expands_groups_and_refuses_bad_replacements():
    assert search.replace_all("john smith", r"(\w+) (\w+)", r"\2 \1", use_regex=True) == ("smith john", 1)
    with pytest.raises(search.SearchError):
        search.replace_all("no match here", "zzz", r"\9", use_regex=True)


# --- saving ------------------------------------------------------------------------------------
def test_saving_over_a_read_only_file_is_refused_and_leaves_it_alone(tmp_path):
    path = tmp_path / "protected.txt"
    path.write_text("keep me", encoding="utf-8")
    os.chmod(path, stat.S_IREAD)
    try:
        with pytest.raises(PermissionError, match="read-only"):
            textio.write_text_file(str(path), "overwritten", "utf-8")
        assert path.read_text(encoding="utf-8") == "keep me"
        assert not os.access(path, os.W_OK)
        assert os.listdir(tmp_path) == ["protected.txt"]  # no temp file left beside it
    finally:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)


# --- dictation ---------------------------------------------------------------------------------
def test_a_failed_recording_start_still_unloads_the_model_later():
    svc, _calls, _loads, _events = make_service()
    try:
        svc.configure(unload_when_idle=False, auto_unload=True, minutes=3)
        svc.cache.get(svc.model, lambda *_a, **_k: None)
        FakeTimer.created.clear()

        def refuse(_device=None):
            raise RuntimeError("Device unavailable")

        svc.recorder.start = refuse
        assert svc.start() is False
        assert any(not t.cancelled for t in FakeTimer.created), "no unload timer is left running"
    finally:
        svc.shutdown()


def test_cancelling_before_the_last_pass_skips_it():
    svc, calls, _loads, events = make_service()
    try:
        svc.live = False
        svc._cancelled = True
        svc._transcribe(np.full(16000, 0.01, dtype=np.float32), "editor")
        assert calls == [] and not [e for e in events if e[0] == "transcript_ready"]
    finally:
        svc.shutdown()


class _DeadRecognizer:
    def create_stream(self):
        raise RuntimeError("the model file is damaged")


def test_a_preview_that_died_stops_collecting_audio():
    session = preview.PreviewSession(lambda _w: None, lambda: None, recognizer=_DeadRecognizer()).start()
    assert wait_for(lambda: session.error is not None)
    session.feed(np.zeros(512, dtype=np.float32))
    session.feed(np.zeros(512, dtype=np.float32))
    assert session._blocks.qsize() == 0


class _FailingPreview:
    error = None

    def feed(self, _samples):
        pass

    def stop(self):
        pass


class _Growing(FakeRecorder):
    capture_rate = 16000
    on_block = None

    def snapshot(self, start=0):
        return np.full(max(0, 16000 * 2 - start), 0.2, dtype=np.float32)


def test_the_service_notices_a_dead_preview_says_so_once_and_carries_on():
    session = _FailingPreview()
    svc = SttService(recorder=_Growing(), cache=ModelCache(lambda _n: None), timer_factory=FakeTimer)
    svc.preview_enabled = True
    svc.preview_factory = lambda _words, _pause: session
    messages = []
    svc.events.on("preview_status", messages.append)
    try:
        svc._start_preview(svc._session)
        assert svc.recorder.on_block is not None
        session.error = RuntimeError("the model file is damaged")
        assert svc._preview_alive() is False
        assert svc._preview_alive() is False
        assert svc.recorder.on_block is None and svc._preview is None
        assert len(messages) == 1 and "failed" in messages[0] and "damaged" in messages[0]
        svc._start_preview(svc._session)
        assert svc._preview is None  # not tried again until the app restarts
    finally:
        svc.shutdown()


# --- resampling -------------------------------------------------------------------------------
def resample(*args):
    from ttspython.core.stt.recorder import resample as recorder_resample  # the one dictation uses

    return recorder_resample(*args)


def test_resampling_steps_evenly_even_on_short_blocks():
    ramp = np.arange(300, dtype=np.float32)
    out = resample(ramp, 48000, 16000)
    assert out.size == 100
    assert np.allclose(np.diff(out[10:-10]), 3.0, atol=0.01)  # the old grid stepped 3.02 and drifted at every block


def test_resampling_down_removes_what_would_fold_back_as_noise():
    # A 10 kHz hiss cannot exist at 16 kHz: picked up by a 48 kHz mic it must not come out as a 6 kHz tone.
    t = np.arange(48000) / 48000
    out = resample(np.sin(2 * np.pi * 10000 * t).astype(np.float32), 48000, 16000)
    assert np.sqrt(np.mean(out[1000:-1000] ** 2)) < 0.02


def test_resampling_down_keeps_speech_frequencies():
    t = np.arange(48000) / 48000
    wave = np.sin(2 * np.pi * 1000 * t).astype(np.float32)
    out = resample(wave, 48000, 16000)
    assert out.size == 16000
    assert abs(np.sqrt(np.mean(out[1000:-1000] ** 2)) - np.sqrt(0.5)) < 0.01


def test_resampling_up_is_not_filtered():
    t = np.arange(16000) / 16000
    out = resample(np.sin(2 * np.pi * 6000 * t).astype(np.float32), 16000, 48000)
    assert np.sqrt(np.mean(out[1000:-1000] ** 2)) > 0.45  # the same as before: only going down is filtered


# --- error messages ---------------------------------------------------------------------------
def test_no_internet_is_said_plainly_and_leaves_no_part_file(tmp_path):
    dest = tmp_path / "voice.onnx"

    def offline(_url, timeout=30):
        raise urllib.error.URLError("[Errno 11001] getaddrinfo failed")

    with pytest.raises(OSError, match="check your internet connection"):
        download.fetch("https://example.invalid/voice.onnx", str(dest), opener=offline)
    assert os.listdir(tmp_path) == []


def test_a_hung_audio_device_is_named_not_none():
    player = AudioPlayer.__new__(AudioPlayer)
    player.prepare = lambda: None
    player._opened = threading.Event()
    player._stream = None
    player._open_error = None
    with pytest.raises(RuntimeError) as err:
        player.wait_open(timeout=0.01)
    assert "None" not in str(err.value) and "did not respond" in str(err.value)


def test_no_engine_message_gives_the_cause():
    from fakes import FakeSD
    from ttspython.core.queue_model import SpeechQueue
    from ttspython.core.tts.controller import SpeechController

    def broken():
        raise RuntimeError("SAPI is not registered")

    ctl = SpeechController(SpeechQueue(), renderer_factory=broken, player=AudioPlayer(queue.Queue(), sd_module=FakeSD()))
    try:
        assert ctl.wait_ready(5)
        assert "SAPI is not registered" in ctl.no_engine_message()
    finally:
        ctl.shutdown()


def test_piper_says_why_it_stopped(tmp_path):
    process = piper._Process.__new__(piper._Process)
    process.stderr_path = str(tmp_path / "stderr.txt")
    (tmp_path / "stderr.txt").write_bytes(b"x" * 1000 + b"\nUnable to load model\n")
    message = process.failure_message()
    assert message.startswith("The Piper program stopped unexpectedly")
    assert "Unable to load model" in message and len(message) < 400


def test_piper_without_output_keeps_the_plain_message(tmp_path):
    process = piper._Process.__new__(piper._Process)
    process.stderr_path = str(tmp_path / "missing.txt")
    assert process.failure_message() == "The Piper program stopped unexpectedly."


def test_pyttsx3_never_replays_the_last_chunk(tmp_path):
    class SilentEngine:
        def setProperty(self, *_a):  # noqa: N802
            pass

        def save_to_file(self, *_a):
            pass

        def runAndWait(self):  # noqa: N802
            pass

    rend = render.Pyttsx3FileRenderer.__new__(render.Pyttsx3FileRenderer)
    rend._engine = SilentEngine()
    rend._engine_lock = threading.Lock()
    rend._dir = str(tmp_path)
    (tmp_path / "chunk.wav").write_bytes(b"RIFF the previous chunk")
    with pytest.raises(RuntimeError, match="no audio"):
        rend.render("hello", "", 200, threading.Event())


# --- paste ------------------------------------------------------------------------------------
def test_a_paste_that_blows_up_does_not_leave_the_injector_busy(monkeypatch):
    injector = inject.TextInjector.__new__(inject.TextInjector)
    finished = []

    class Signal:
        def emit(self, *args):
            finished.append(args)

    injector.finished = Signal()
    injector._busy = False

    def blow_up(_text, _target):
        injector._busy = True
        raise RuntimeError("clipboard is locked")

    monkeypatch.setattr(injector, "_inject_windows", blow_up, raising=False)
    monkeypatch.setattr(injector, "_inject_x11", lambda _t: blow_up(_t, None), raising=False)
    monkeypatch.setattr(injector, "_inject_wayland", lambda _t: blow_up(_t, None), raising=False)
    copied = []
    monkeypatch.setattr(injector, "copy_only", lambda text, reason="": copied.append((text, reason)), raising=False)
    injector.inject("my dictation")
    assert injector._busy is False
    assert copied and copied[0][0] == "my dictation" and "clipboard is locked" in copied[0][1]


# --- self-test --------------------------------------------------------------------------------
GOOD_REPORT = {"sounddevice": "ok", "lameenc": "ok", "numpy": "ok", "ctranslate2": "ok", "onnxruntime": "ok",
               "faster_whisper": "ok", "vad_model": "ok", "ui_automation": "ok", "preview_engine": "ok",
               "output_devices": 3, "piper_catalog": 178, "engine_ready": True, "voices": 4, "mp3_export_bytes": 24000}


def test_self_test_finds_nothing_wrong_in_a_good_report():
    from ttspython.app import self_test_problems

    assert self_test_problems(GOOD_REPORT) == []


@pytest.mark.parametrize("change, word", [
    ({"onnxruntime": "ImportError: DLL load failed"}, "onnxruntime"),
    ({"preview_engine": "missing"}, "preview_engine"),
    ({"output_devices": "OSError: no PortAudio"}, "output_devices"),
    ({"engine_ready": False}, "engine_ready"),
    ({"voices": 0}, "voices"),
    ({"mp3_export_bytes": 0}, "mp3_export"),
])
def test_self_test_reports_each_kind_of_failure(change, word):
    from ttspython.app import self_test_problems

    problems = self_test_problems({**GOOD_REPORT, **change})
    assert len(problems) == 1 and problems[0].startswith(word)
