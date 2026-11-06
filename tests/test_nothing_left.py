"""What was set aside after the deep scan, done for 5.1. Most of these failed before the fixes."""
from __future__ import annotations

import hashlib
import os
import re
import struct
import subprocess
import sys
import threading
import time

import numpy as np
import pytest

from test_ui import make_controller
from ttspython.core import textio
from ttspython.core.stt.recorder import Recorder
from ttspython.core.stt.service import ModelCache, SttService, SttState
from ttspython.core.tts.controller import SpeechController, State
from ttspython.core.tts.render import Cancelled

try:
    from ttspython.core.stt import spool as spool_mod
except ImportError:  # for measuring these tests on the code from before them
    spool_mod = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def wait_until(condition, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.005)
    return condition()


# --- the recording on disk ------------------------------------------------------------------------
class FakeStream:
    def __init__(self, **kw):
        self.callback = kw["callback"]

    def start(self):
        pass

    def stop(self):
        pass

    def close(self):
        pass


class FakeSd:
    def InputStream(self, **kw):
        self.stream = FakeStream(**kw)
        return self.stream


def speak_into(recorder, seconds, rate=16000):
    block = (np.sin(np.arange(1024) / 8) * 9000).astype(np.int16).reshape(-1, 1)
    for _ in range(int(seconds * rate / 1024)):
        recorder._sd.stream.callback(block, 1024, None, None)


def make_service(tmp_path, transcribe=None, **kw):
    class Segment:
        start, end, text = 0.0, 1.0, "hello there"

    class Model:
        def transcribe(self, audio, **_kw):
            if transcribe:
                transcribe(audio)
            return iter([Segment()]), None

    recorder = Recorder(sd_module=FakeSd())
    svc = SttService(recorder=recorder, cache=kw.pop("cache", None) or ModelCache(lambda _name: Model()),
                     timer_factory=lambda *_a: threading.Timer(1000, lambda: None))
    svc.live = False
    svc.spool_folder = str(tmp_path / "dictation")
    return svc, recorder


def finish(svc):
    assert wait_until(lambda: svc.state is SttState.IDLE, 10)


def files_in(folder):
    return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


def test_a_recording_reaches_the_disk_while_it_is_being_made(tmp_path):
    svc, rec = make_service(tmp_path)
    svc.start()
    speak_into(rec, 1.0)
    path = rec.spool.path
    assert wait_until(lambda: os.path.getsize(path) > 16000, 3)  # about 2 s at most after being said
    audio, rate = spool_mod.read(path)  # while still recording, as after a crash
    assert rate == 16000 and audio.size >= 15000
    svc.cancel()


def test_the_file_goes_once_the_text_is_delivered(tmp_path):
    svc, rec = make_service(tmp_path)
    texts = []
    svc.events.on("transcript_ready", lambda text, _t: texts.append(text))
    svc.start()
    speak_into(rec, 1.0)
    svc.stop()
    finish(svc)
    assert texts == ["Hello there"] or texts
    assert wait_until(lambda: not files_in(svc.spool_folder))


def test_stopping_does_not_make_the_window_convert_the_recording(tmp_path, monkeypatch):
    svc, rec = make_service(tmp_path)
    svc.start()
    speak_into(rec, 0.5)
    thread = []
    real = rec._to_float
    monkeypatch.setattr(rec, "_to_float", lambda blocks: (thread.append(threading.current_thread()), real(blocks))[1])
    svc.stop()
    finish(svc)
    assert thread and threading.current_thread() not in thread


def test_a_recording_that_will_not_convert_is_kept_for_try_again(tmp_path, monkeypatch):
    svc, rec = make_service(tmp_path)
    errors = []
    svc.events.on("error", errors.append)
    svc.start()
    speak_into(rec, 0.5)
    real = rec._to_float
    monkeypatch.setattr(rec, "_to_float", lambda _blocks: (_ for _ in ()).throw(MemoryError("out of memory")))
    svc.stop()
    finish(svc)
    assert errors and "Try again" in errors[0]
    monkeypatch.setattr(rec, "_to_float", real)
    assert svc.retry()
    finish(svc)


def test_cancel_deletes_the_recording(tmp_path):
    svc, rec = make_service(tmp_path)
    svc.start()
    speak_into(rec, 0.5)
    svc.cancel()
    assert wait_until(lambda: not files_in(svc.spool_folder))


def test_a_failed_transcription_keeps_the_file_and_try_again_removes_it(tmp_path):
    fail = [True]

    def transcribe(_audio):
        if fail[0]:
            raise RuntimeError("no")

    svc, rec = make_service(tmp_path, transcribe)
    svc.events.on("error", lambda _m: None)
    svc.start()
    speak_into(rec, 1.0)
    svc.stop()
    finish(svc)
    assert files_in(svc.spool_folder)
    fail[0] = False
    assert svc.retry()
    finish(svc)
    assert wait_until(lambda: not files_in(svc.spool_folder))


def test_a_new_dictation_replaces_what_was_kept(tmp_path):
    svc, rec = make_service(tmp_path, lambda _a: (_ for _ in ()).throw(RuntimeError("no")))
    svc.events.on("error", lambda _m: None)
    svc.start()
    speak_into(rec, 1.0)
    svc.stop()
    finish(svc)
    old = files_in(svc.spool_folder)
    assert len(old) == 1
    svc.start()
    assert wait_until(lambda: old[0] not in files_in(svc.spool_folder))
    assert len(files_in(svc.spool_folder)) == 1
    svc.cancel()


def leave_a_crashed_recording(folder, seconds=1.0, rate=16000):
    """What a crash leaves: the sizes in the header were never filled in."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "recording-crashed.wav")
    with open(path, "wb") as f:
        f.write(spool_mod._header(rate, 0))
        f.write((np.sin(np.arange(int(seconds * rate)) / 8) * 9000).astype(np.int16).tobytes())
    return path


def test_what_a_crash_left_is_offered_after_a_restart_and_goes_to_the_editor(tmp_path):
    heard = []
    svc, _rec = make_service(tmp_path, lambda audio: heard.append(audio.size))
    path = leave_a_crashed_recording(svc.spool_folder)
    shown, texts = [], []
    svc.events.on("retry_available", shown.append)
    svc.events.on("transcript_ready", lambda text, target: texts.append((text, target)))
    assert svc.recover() == pytest.approx(1.0, abs=0.01)
    assert shown == [True]
    assert svc.retry()
    finish(svc)
    assert heard == [16000]
    assert texts and texts[0][1] == "editor"  # never typed into whatever app is in front
    assert wait_until(lambda: not os.path.exists(path))


def test_a_recording_too_short_to_hold_a_word_is_not_offered(tmp_path):
    svc, _rec = make_service(tmp_path)
    leave_a_crashed_recording(svc.spool_folder, seconds=0.05)
    assert not svc.recover()
    assert wait_until(lambda: not files_in(svc.spool_folder))


def test_a_new_dictation_does_not_delete_what_a_crash_left(tmp_path):
    """--toggle-dictation after a crash, or a hotkey pressed in the first seconds."""
    svc, rec = make_service(tmp_path)
    path = leave_a_crashed_recording(svc.spool_folder)
    shown, texts = [], []
    svc.events.on("retry_available", shown.append)
    svc.events.on("transcript_ready", lambda text, target: texts.append(target))
    assert svc.recover()
    svc.start("the new one")
    speak_into(rec, 0.5)
    svc.stop()
    finish(svc)
    assert texts == ["the new one"]
    assert os.path.exists(path) and shown == [True]
    assert wait_until(lambda: files_in(svc.spool_folder) == [os.path.basename(path)])
    assert svc.retry()
    finish(svc)
    assert texts == ["the new one", "editor"]
    assert wait_until(lambda: not files_in(svc.spool_folder))


def test_a_failed_try_again_keeps_what_a_crash_left(tmp_path):
    fail = [True]

    def transcribe(_audio):
        if fail[0]:
            raise RuntimeError("no")

    svc, _rec = make_service(tmp_path, transcribe)
    svc.events.on("error", lambda _m: None)
    path = leave_a_crashed_recording(svc.spool_folder)
    assert svc.recover()
    assert svc.retry()
    finish(svc)
    assert os.path.exists(path)
    fail[0] = False
    assert svc.retry()
    finish(svc)
    assert wait_until(lambda: not os.path.exists(path))


def test_quitting_while_transcribing_keeps_the_file(tmp_path):
    svc, rec = make_service(tmp_path)
    svc.start()
    speak_into(rec, 0.5)
    svc.closing = True  # as the app does before it stops listening to the service
    svc.stop()
    finish(svc)
    assert files_in(svc.spool_folder)


def test_what_was_typed_before_a_failure_is_not_typed_again(tmp_path):
    heard = []
    svc, rec = make_service(tmp_path, lambda audio: heard.append(audio.size))
    svc.events.on("error", lambda _m: None)
    svc.start()
    speak_into(rec, 2.0)
    svc.stop_capture = None
    rec.stop_capture()
    samples = rec.spool
    assert samples.wait(3)
    svc._settled_text = "Already typed."
    svc._settled_samples = 16000
    svc._keep_for_retry(np.zeros(100, dtype=np.float32), "editor", "Failed.")
    svc._state = SttState.IDLE
    svc._kept = None
    assert svc.recover() == pytest.approx(1.0, abs=0.1)  # as at the next start
    assert svc.retry()
    finish(svc)
    assert heard and heard[0] == pytest.approx(16000, abs=2048)


def test_turning_the_switch_off_also_takes_back_the_offer(tmp_path):
    svc, _rec = make_service(tmp_path)
    folder = svc.spool_folder
    leave_a_crashed_recording(folder)
    shown = []
    svc.events.on("retry_available", shown.append)
    assert svc.recover()
    svc.stop_keeping_files(folder)
    assert shown == [True, False] and not svc.retry() and not files_in(folder)


def test_cancelling_a_long_recording_does_not_convert_it(tmp_path, monkeypatch):
    svc, rec = make_service(tmp_path)
    svc.start()
    speak_into(rec, 0.5)
    monkeypatch.setattr(rec, "_to_float", lambda _b: pytest.fail("converted a recording being thrown away"))
    assert svc.cancel()
    assert svc.state is SttState.IDLE
    svc.start()
    speak_into(rec, 0.2)
    svc.shutdown()


def test_a_microphone_that_will_not_start_leaves_the_last_recording(tmp_path):
    svc, rec = make_service(tmp_path)
    rec._sd.fail_next = True
    rec._blocks = [np.ones(10, dtype=np.int16)]
    rec._frames = 10

    def failing(**kw):
        stream = FakeStream(**kw)
        stream.start = lambda: (_ for _ in ()).throw(OSError("in use"))
        return stream

    rec._sd.InputStream = failing
    with pytest.raises(OSError):
        rec.start()
    assert rec.take_audio().size == 10


def test_discard_deletes_what_was_kept(tmp_path):
    svc, _rec = make_service(tmp_path)
    leave_a_crashed_recording(svc.spool_folder)
    shown = []
    svc.events.on("retry_available", shown.append)
    assert svc.recover()
    assert svc.discard_kept()
    assert shown == [True, False]
    assert wait_until(lambda: not files_in(svc.spool_folder))
    assert not svc.retry()


def test_a_full_disk_never_stops_a_recording(tmp_path, monkeypatch):
    svc, rec = make_service(tmp_path)
    svc.start()
    monkeypatch.setattr(rec.spool, "_write", lambda _data: (_ for _ in ()).throw(OSError("disk full")))
    speak_into(rec, 1.0)
    assert wait_until(lambda: rec.spool.failed is not None)
    svc.stop()
    finish(svc)
    assert not files_in(svc.spool_folder)


def test_no_folder_means_no_file(tmp_path):
    svc, rec = make_service(tmp_path)
    svc.spool_folder = None
    svc.start()
    speak_into(rec, 0.3)
    assert rec.spool is None
    svc.cancel()
    assert not svc.recover()


def test_a_damaged_file_is_no_recording(tmp_path):
    path = tmp_path / "x.wav"
    path.write_bytes(b"not a wave file at all, and long enough to be read as one.....")
    assert spool_mod.read(str(path)) is None


def test_the_file_is_an_ordinary_wave_file_once_finished(tmp_path):
    import wave

    spool = spool_mod.Spool(str(tmp_path), 48000)
    spool.feed(np.zeros(4800, dtype=np.int16))
    spool.finish()
    assert spool.wait(3)
    with wave.open(spool.path, "rb") as w:
        assert (w.getframerate(), w.getnframes(), w.getnchannels(), w.getsampwidth()) == (48000, 4800, 1, 2)


@pytest.mark.skipif(os.name == "nt", reason="file modes are POSIX")
def test_only_you_can_read_the_file(tmp_path):
    spool = spool_mod.Spool(str(tmp_path / "d"), 16000)
    assert os.stat(spool.path).st_mode & 0o077 == 0
    assert os.stat(tmp_path / "d").st_mode & 0o077 == 0
    spool.discard()


def test_killing_the_process_loses_at_most_about_a_second(tmp_path):
    """The real thing: a process is killed outright in the middle of a recording."""
    folder = tmp_path / "killed"
    script = f"""
import sys, time
sys.path.insert(0, {ROOT!r})
import numpy as np
from ttspython.core.stt.spool import Spool
spool = Spool({str(folder)!r}, 16000)
block = (np.sin(np.arange(1024) / 8) * 9000).astype(np.int16)
sent = 0
while True:
    spool.feed(block)
    sent += 1024
    if sent >= 16000 * 3:
        print(sent, flush=True)
        time.sleep(0.03)
    time.sleep(0.004)
"""
    proc = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip()
    finally:
        proc.kill()
        proc.wait()
    path = spool_mod.find(str(folder))[0]
    audio, rate = spool_mod.read(path)
    assert rate == 16000 and audio.size >= 16000 * 2


# --- Stop never holds up the window ----------------------------------------------------------------
class SlowToStop:
    """An engine that takes its time to notice Cancel, as SAPI or a slow model step can."""
    name = "slow"
    sample_rate = 22050

    def __init__(self, delay=1.5):
        self.delay = delay
        self.rendering = threading.Event()
        self.rendered = []

    def list_voices(self):
        return []

    def warm_up(self, _wpm):
        pass

    def render(self, text, _voice, _wpm, cancel):
        self.rendered.append(text)
        self.rendering.set()
        end = time.monotonic() + self.delay
        while time.monotonic() < end:
            time.sleep(0.01)
        if cancel.is_set():
            raise Cancelled()
        return np.zeros(2205, dtype=np.int16), 22050


class QuietPlayer:
    device = None
    level = 0.0

    def __init__(self):
        self.paused = False

    def set_gain(self, _g):
        pass

    def set_target_wpm(self, _w):
        pass

    def prepare(self):
        pass

    @property
    def sd(self):
        return None

    def flush(self, min_generation=None):
        pass

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def stalled(self, _s):
        return False

    def queued_seconds(self, _u):
        return 0.0

    def enqueue(self, _pcm, _rate, marker, native_wpm=None):
        self._events.put(("chunk", marker))
        return True

    def enqueue_end(self, marker):
        self._events.put(("drained", marker))

    def close(self):
        pass


def slow_controller(renderer):
    speech = SpeechController(renderer_factory=lambda: renderer, player=QuietPlayer())
    assert speech.wait_ready(5)
    return speech


def test_asking_to_stop_returns_at_once():
    renderer = SlowToStop()
    speech = slow_controller(renderer)
    try:
        assert speech.speak("One sentence.")
        assert renderer.rendering.wait(3)
        started = time.perf_counter()
        speech.request_stop()
        assert time.perf_counter() - started < 0.05  # it was the whole wait: 1.5 s here, up to 2 s
        assert speech.state is State.STOPPING
        assert speech.stop(5)
    finally:
        speech.shutdown()


def test_new_speech_can_be_asked_for_while_the_old_is_stopping():
    renderer = SlowToStop(0.4)
    speech = slow_controller(renderer)
    done = threading.Event()
    speech.events.on("utterance_finished", lambda _u, stopped: not stopped and done.set())
    try:
        assert speech.speak("The old text.")
        assert renderer.rendering.wait(3)
        speech.request_stop()
        assert speech.speak("The new text.")  # was: refused, "Still stopping"
        assert speech.state is State.STARTING
        assert done.wait(5)
        assert renderer.rendered[-1] == "The new text."
    finally:
        speech.shutdown()


def test_speech_already_playing_is_still_not_replaced_by_accident():
    renderer = SlowToStop(0.3)
    speech = slow_controller(renderer)
    try:
        assert speech.speak("The old text.")
        assert renderer.rendering.wait(3)
        assert not speech.speak("Without a stop first.")
    finally:
        speech.shutdown()


def test_pressing_stop_and_play_again_and_again_ends_with_the_last():
    renderer = SlowToStop(0.05)
    speech = slow_controller(renderer)
    try:
        for i in range(20):
            speech.request_stop()
            assert speech.speak(f"Text {i}.")
        assert wait_until(lambda: speech.state is State.IDLE, 10)
        assert renderer.rendered[-1] == "Text 19."
        assert len(renderer.rendered) < 20  # the ones in between are skipped, not all read out
    finally:
        speech.shutdown()


def test_a_voice_change_while_stopping_does_not_restart_the_next_speech():
    renderer = SlowToStop(0.3)
    speech = slow_controller(renderer)
    done = threading.Event()
    speech.events.on("utterance_finished", lambda _u, stopped: done.set() if not stopped else None)
    try:
        assert speech.speak("The old text.")
        assert renderer.rendering.wait(3)
        speech.request_stop()
        speech.set_voice("another")
        assert speech.speak("The new text.")
        assert done.wait(5)
        assert renderer.rendered.count("The new text.") == 1
    finally:
        speech.shutdown()


def test_a_slow_stop_is_reported_and_a_quick_one_is_not():
    renderer = SlowToStop(0.5)
    speech = slow_controller(renderer)
    try:
        assert not speech.stop_overdue(0.1)
        assert speech.speak("One.")
        assert renderer.rendering.wait(3)
        speech.request_stop()
        assert not speech.stop_overdue(0.3)
        time.sleep(0.35)
        assert speech.stop_overdue(0.3)
        assert speech.stop(5)
        assert not speech.stop_overdue(0.0)
    finally:
        speech.shutdown()


def test_the_window_never_waits_for_speech_to_stop():
    """The window's code asks; only quitting waits."""
    source = read("ttspython", "ui", "app_controller.py")
    assert not re.search(r"\.speech\.stop\b", source)


def test_pause_right_after_a_new_start_is_kept():
    renderer = SlowToStop(0.3)
    speech = slow_controller(renderer)
    try:
        assert speech.speak("The old text.")
        assert renderer.rendering.wait(3)
        speech.request_stop()
        assert speech.speak("The new text.")
        speech.pause()
        assert wait_until(lambda: renderer.rendered[-1] == "The new text.", 5)
        assert speech.player.paused
    finally:
        speech.resume()
        speech.shutdown()


# --- a clean end ------------------------------------------------------------------------------------
def run_exit_script(body):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=ROOT)
    return subprocess.run([sys.executable, "-c", body], env=env, capture_output=True, timeout=60).returncode


COPIED = """
from PySide6.QtCore import QMimeData
from PySide6.QtWidgets import QApplication
app = QApplication([])
data = QMimeData()
data.setText("x")
app.clipboard().setMimeData(data)
app.processEvents()
"""


@pytest.mark.skipif(sys.platform != "win32", reason="seen on Windows")
def test_quitting_with_something_copied_does_not_crash():
    assert run_exit_script(COPIED + "from ttspython.app import leave\nleave(0)\n") == 0


def test_the_exit_code_is_kept():
    assert run_exit_script("from ttspython.app import leave\nleave(7)\n") == 7


def test_exit_handlers_still_run(tmp_path):
    mark = tmp_path / "ran"
    body = (f"import atexit\nfrom ttspython.app import leave\n"
            f"atexit.register(lambda: open({str(mark)!r}, 'w').close())\nleave(0)\n")
    assert run_exit_script(body) == 0
    assert mark.exists()


class FakeClipboard:
    def __init__(self, owns):
        self.owns = owns

    def ownsClipboard(self):
        return self.owns


def test_what_we_copied_stays_after_we_quit():
    from ttspython.platform import inject

    flushed = []
    assert inject.keep_clipboard_after_exit(FakeClipboard(True), "windows", lambda: flushed.append(1))
    assert flushed == [1]
    assert not inject.keep_clipboard_after_exit(FakeClipboard(False), "windows", lambda: flushed.append(1))
    assert not inject.keep_clipboard_after_exit(FakeClipboard(True), "offscreen", lambda: flushed.append(1))
    assert flushed == [1]


def test_a_clipboard_that_will_not_flush_does_not_stop_quitting():
    from ttspython.platform import inject

    def broken():
        raise OSError("no")

    assert not inject.keep_clipboard_after_exit(FakeClipboard(True), "windows", broken)


# --- mixed line endings --------------------------------------------------------------------------------
MIXED = b"one\r\ntwo\nthree\r\nfour\rfive\nsix"


def editor_text(doc):
    return doc.text.replace("\r", "\n")


def saved(tmp_path, doc, text):
    path = tmp_path / "f.txt"
    textio.write_text_file(str(path), text, doc.encoding, doc.newline, doc.bom, doc.original)
    return path.read_bytes()


def test_a_file_with_mixed_endings_is_saved_as_it_was(tmp_path):
    doc = textio.decode_text(MIXED)
    assert saved(tmp_path, doc, editor_text(doc)) == MIXED


def test_only_the_edited_line_changes(tmp_path):
    doc = textio.decode_text(MIXED)
    out = saved(tmp_path, doc, editor_text(doc).replace("three", "THREE"))
    assert out == b"one\r\ntwo\nTHREE\r\nfour\rfive\nsix"


def test_lines_added_and_removed_keep_the_others_as_they_were(tmp_path):
    doc = textio.decode_text(MIXED)
    out = saved(tmp_path, doc, editor_text(doc).replace("three\n", "three\nnew\n"))
    assert out == b"one\r\ntwo\nthree\r\nnew\r\nfour\rfive\nsix"
    out = saved(tmp_path, doc, editor_text(doc).replace("three\n", ""))
    assert out == b"one\r\ntwo\nfour\rfive\nsix"


@pytest.mark.parametrize(("raw", "edit", "wanted"), [
    (b"a\r\nb\nc", "a\nb\nc\nd", b"a\r\nb\nc\r\nd"),
    (b"a\r\nb\n", "a\nb\n\n", b"a\r\nb\n\r\n"),
    (b"a\r\nb\nc", "a\nb", b"a\r\nb"),
    (b"a\r\nb\nc", "", b""),
    (b"a\r\nb\nc", "z\na\nb\nc", b"z\r\na\r\nb\nc"),
])
def test_lines_added_at_either_end_or_all_removed(tmp_path, raw, edit, wanted):
    doc = textio.decode_text(raw)
    assert doc.original is not None
    assert saved(tmp_path, doc, edit) == wanted


def test_even_endings_are_not_slowed_down_or_changed(tmp_path):
    doc = textio.decode_text(b"a\r\nb\r\nc")
    assert doc.original is None
    assert saved(tmp_path, doc, editor_text(doc)) == b"a\r\nb\r\nc"
    doc = textio.decode_text(b"a\nb")
    assert doc.original is None


def test_a_large_mixed_file_is_quick(tmp_path):
    raw = b"".join(b"line %d\r\n" % i if i % 2 else b"line %d\n" % i for i in range(300_000))
    doc = textio.decode_text(raw)
    text = editor_text(doc).replace("line 150000", "changed")
    started = time.perf_counter()
    out = textio.with_original_endings(text, doc.original, doc.newline)
    assert time.perf_counter() - started < 1.0
    assert out.count("\r\n") == raw.count(b"\r\n")


def test_the_app_keeps_mixed_endings_across_two_saves(qtbot, tmp_path):
    app = make_controller(qtbot, tmp_path)
    path = tmp_path / "mixed.txt"
    path.write_bytes(MIXED)
    app.open_path(str(path), confirmed=True)
    assert app.current_doc.original
    app._write(str(path))
    assert path.read_bytes() == MIXED
    cursor = app.editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.Start)
    cursor.insertText("zero ")
    app._write(str(path))
    assert path.read_bytes() == b"zero one\r\ntwo\nthree\r\nfour\rfive\nsix"
    app._write(str(path))
    assert path.read_bytes() == b"zero one\r\ntwo\nthree\r\nfour\rfive\nsix"
    app.editor.document().setModified(False)


# --- a Whisper download is checked ---------------------------------------------------------------------
def fake_download(tmp_path, content=b"model"):
    folder = tmp_path / "snapshot"
    folder.mkdir()
    (folder / "model.bin").write_bytes(content)
    (folder / "config.json").write_bytes(b"{}")
    return folder


def test_a_download_with_the_right_contents_passes(tmp_path):
    from ttspython.core.stt import service

    folder = fake_download(tmp_path)
    digests = {"model.bin": hashlib.sha256(b"model").hexdigest(), "config.json": hashlib.sha256(b"{}").hexdigest()}
    service.check_download(str(folder), digests)


def test_a_damaged_download_is_named(tmp_path):
    from ttspython.core.stt import service

    folder = fake_download(tmp_path, b"something else")
    digests = {"model.bin": hashlib.sha256(b"model").hexdigest(), "config.json": hashlib.sha256(b"{}").hexdigest()}
    with pytest.raises(service.DamagedDownload, match="model.bin"):
        service.check_download(str(folder), digests)


def test_every_pinned_model_has_its_digests():
    from ttspython.core.stt import service, whisper_digests

    assert set(whisper_digests.DIGESTS) == set(service.WHISPER_REVISIONS)
    for name, files in whisper_digests.DIGESTS.items():
        assert files.get("model.bin") and "config.json" in files and "tokenizer.json" in files
        assert any(f.startswith("vocabulary.") for f in files), name
        assert all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in files.values())


def test_a_damaged_download_is_removed_and_reported(tmp_path, monkeypatch):
    from ttspython.core.stt import service, whisper_digests

    folder = fake_download(tmp_path, b"damaged")
    removed = []
    assert whisper_digests.DIGESTS["tiny"]
    monkeypatch.setattr(service, "_digests_for", lambda _name: {"model.bin": "0" * 64})
    monkeypatch.setattr(service, "delete_model", lambda name, scan=None: removed.append(name))
    with pytest.raises(service.DamagedDownload):
        service.verify_download("tiny", str(folder))
    assert removed == ["tiny"]


def test_a_new_download_goes_through_the_check(tmp_path, monkeypatch):
    import huggingface_hub

    from ttspython.core.stt import service

    folder = fake_download(tmp_path, b"damaged")

    def fake_snapshot(*_a, **kw):
        if kw.get("local_files_only"):
            raise FileNotFoundError
        return str(folder)

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot)
    monkeypatch.setattr(service, "_digests_for", lambda _name: {"model.bin": "0" * 64})
    monkeypatch.setattr(service, "delete_model", lambda name, scan=None: None)
    with pytest.raises(service.DamagedDownload):
        service.download_whisper("tiny")


# --- the instance name cannot be taken from you --------------------------------------------------------
def test_a_copy_answering_for_another_user_is_not_trusted(qtbot, monkeypatch):
    from ttspython.platform import single_instance as si

    name = f"ttspython-squat-{os.getpid()}"
    monkeypatch.setenv("TTSPYTHON_INSTANCE", name)
    squatter = si.InstanceServer()
    assert squatter.listening
    got = []
    squatter.set_handler(got.append)
    monkeypatch.setattr(si, "_answered_by_me", lambda _sock: False)
    assert not si.send_to_running(["show"])  # was: it counted as running, and this copy quit
    qtbot.wait(100)
    assert not got
    mine = si.InstanceServer()
    assert mine.listening and mine.server.serverName() != squatter.server.serverName()
    mine.server.close()
    squatter.server.close()


def test_your_own_copy_is_recognized(qtbot, monkeypatch):
    from ttspython.platform import single_instance as si

    monkeypatch.setenv("TTSPYTHON_INSTANCE", f"ttspython-mine-{os.getpid()}")
    server = si.InstanceServer()
    assert server.listening
    code = ("import sys; from PySide6.QtCore import QCoreApplication; app = QCoreApplication(sys.argv); "
            "from ttspython.platform.single_instance import send_to_running; print(send_to_running(['show']))")
    with qtbot.waitSignal(server.received, timeout=8000) as sig:  # the real check, on a real pipe
        proc = subprocess.Popen([sys.executable, "-c", code], cwd=ROOT, stdout=subprocess.PIPE, text=True)
    assert proc.communicate(timeout=20)[0].strip() == "True"
    assert sig.args[0] == ["show"]
    server.server.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows security")
def test_the_owner_check_really_tells_people_apart(tmp_path):
    import msvcrt

    from ttspython.platform import single_instance as si

    mine = tmp_path / "mine.txt"
    mine.write_text("x")
    with open(mine, "rb") as f:
        assert si._owner_is_me(msvcrt.get_osfhandle(f.fileno()))
    # This file belongs to the system's installer service: neither this user nor an administrator.
    with open(os.path.join(os.environ["SystemRoot"], "explorer.exe"), "rb") as f:
        assert not si._owner_is_me(msvcrt.get_osfhandle(f.fileno()))


def test_a_copy_of_yours_on_a_spare_name_is_still_found(qtbot, monkeypatch):
    """Another user held the name when your copy started, and has since left it."""
    from ttspython.platform import single_instance as si

    name = f"ttspython-spare-{os.getpid()}"
    monkeypatch.setenv("TTSPYTHON_INSTANCE", name)
    server = si.InstanceServer.__new__(si.InstanceServer)
    assert si._names()[1] == f"{name}-2"
    monkeypatch.setattr(si, "_names", lambda: [f"{name}-2"])
    si.InstanceServer.__init__(server)
    assert server.listening
    monkeypatch.undo()
    monkeypatch.setenv("TTSPYTHON_INSTANCE", name)
    other = si.InstanceServer()
    assert not other.listening  # the base name is free, but your copy answers on the next
    server.server.close()


def test_a_folder_that_cannot_be_made_still_gives_a_name(monkeypatch):
    from ttspython.platform import single_instance as si

    monkeypatch.delenv("TTSPYTHON_INSTANCE", raising=False)
    monkeypatch.setattr(si.sys, "platform", "linux")
    monkeypatch.setattr(si.os, "makedirs", lambda *_a, **_k: (_ for _ in ()).throw(PermissionError("no")))
    assert si.server_name().startswith("ttspython-")


def test_with_nobody_else_on_the_name_it_is_used_as_before(qtbot, monkeypatch):
    from ttspython.platform import single_instance as si

    name = f"ttspython-plain-{os.getpid()}"
    monkeypatch.setenv("TTSPYTHON_INSTANCE", name)
    server = si.InstanceServer()
    assert server.server.serverName() == name
    server.server.close()


@pytest.mark.skipif(os.name == "nt", reason="Windows pipes have no folder")
def test_on_linux_the_name_is_in_a_private_folder(monkeypatch, tmp_path):
    from ttspython.platform import single_instance as si

    monkeypatch.delenv("TTSPYTHON_INSTANCE", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert si.server_name().startswith(str(tmp_path))


def test_the_linux_name_is_private_whatever_this_computer_is(monkeypatch, tmp_path):
    from ttspython.platform import single_instance as si

    monkeypatch.delenv("TTSPYTHON_INSTANCE", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert si.posix_socket_path().startswith(str(tmp_path))
    monkeypatch.delenv("XDG_RUNTIME_DIR")
    assert si.posix_socket_path().startswith(os.environ["TTSPYTHON_DATA"])


# --- consent comes from a microphone ---------------------------------------------------------------------
@pytest.mark.parametrize("name", ["Stereo Mix (Realtek Audio)", "What U Hear (Sound Blaster)", "CABLE Output (VB-Audio Virtual Cable)",
                                  "Voicemeeter Out B1", "Monitor of Built-in Audio", "Wave Out Mix", "BlackHole 2ch", "Loopback: PCM"])
def test_a_device_that_records_the_computers_own_sound_is_refused(name):
    from ttspython.core.audio_devices import plays_back_the_computer

    assert plays_back_the_computer(name)


@pytest.mark.parametrize("name", ["Microphone (Realtek Audio)", "Headset Microphone (Jabra)", "Blue Yeti", "MacBook Mic", "", None])
def test_a_microphone_is_not(name):
    from ttspython.core.audio_devices import plays_back_the_computer

    assert not plays_back_the_computer(name)


def test_the_consent_recording_refuses_such_a_device(qtbot):
    from test_clone import FakeRecorder, window

    class Sd:
        def query_devices(self, _device, _kind):
            return {"name": "Stereo Mix (Realtek Audio)"}

    recorder = FakeRecorder()
    recorder.sd = Sd()
    dlg = window(qtbot, recorder=recorder)
    dlg._start_recording()
    assert not dlg.recording and not recorder.running
    assert "Stereo Mix" in dlg.status.text()


# --- pace ------------------------------------------------------------------------------------------------
def test_one_babbled_sentence_does_not_move_the_pace(tmp_path):
    from ttspython.core.tts import clone

    renderer = clone.CloneRenderer()
    voice = "clone:nothing"
    renderer._native[voice] = 170.0
    words = " ".join(["word"] * 20)
    renderer._note_pace(voice, words, 20 * 60 / 80, smooth=True)  # 80 words a minute: far too slow to be real
    assert renderer._native[voice] == 170.0


def test_a_voice_that_really_is_different_is_followed(tmp_path):
    from ttspython.core.tts import clone

    renderer = clone.CloneRenderer()
    voice = "clone:nothing"
    renderer._native[voice] = 170.0
    words = " ".join(["word"] * 20)
    for _ in range(3):
        renderer._note_pace(voice, words, 20 * 60 / 110, smooth=True)
    assert renderer._native[voice] < 170.0


def test_ordinary_changes_are_smoothed_as_before(tmp_path):
    from ttspython.core.tts import clone

    renderer = clone.CloneRenderer()
    voice = "clone:nothing"
    renderer._native[voice] = 170.0
    renderer._note_pace(voice, " ".join(["word"] * 20), 20 * 60 / 190, smooth=True)
    assert renderer._native[voice] == pytest.approx(180.0, abs=0.5)


# --- releases: exact tools, exact packages -------------------------------------------------------------------
def test_the_self_test_can_stop_a_release():
    workflow = read(".github", "workflows", "build.yml")
    step = workflow.split("name: Self-test", 1)[1].split("- name:", 1)[0]
    assert "continue-on-error" not in step
    assert "timeout-minutes" in step


def test_a_machine_with_no_voices_is_told_apart_from_a_broken_build(monkeypatch):
    from ttspython.app import self_test_problems

    report = {"engine_ready": True, "voices": 0, "mp3_export_bytes": 0, "output_devices": 0}
    monkeypatch.delenv("TTSPYTHON_SELFTEST_NO_VOICES_OK", raising=False)
    assert any("voices" in p for p in self_test_problems(report))
    monkeypatch.setenv("TTSPYTHON_SELFTEST_NO_VOICES_OK", "1")
    assert not self_test_problems(report)
    assert self_test_problems({**report, "sounddevice": "ImportError: gone"})  # a missing library always counts
    assert self_test_problems({**report, "voices": 3})  # voices, but no MP3: broken


def test_the_build_installs_exactly_what_was_locked():
    workflow = read(".github", "workflows", "build.yml")
    assert '--require-hashes --no-deps -r "$lock"' in workflow
    assert "pip install --upgrade pip" not in workflow
    for lock_name, needed in (("linux", ("pynput==", "evdev==", "python-xlib==", "pyinstaller==")),
                              ("windows", ("comtypes==", "pywin32==", "pyinstaller=="))):
        lock = read("packaging", f"requirements-{lock_name}.lock")
        pins = [line for line in lock.splitlines() if re.match(r"^[a-z0-9]", line)]
        assert len(pins) > 30
        assert all("==" in line for line in pins)
        for name in needed:
            assert any(line.startswith(name) for line in pins), name
        assert lock.count("--hash=sha256:") >= len(pins)
        assert lock_name in workflow


def test_the_locks_match_the_tested_versions():
    pins = dict(line.split("==") for line in read("packaging", "constraints.txt").lower().splitlines()
                if line and not line.startswith("#"))
    for lock_name in ("linux", "windows"):
        found = re.findall(r"^([a-z0-9._-]+)==([^ ;\\]+)", read("packaging", f"requirements-{lock_name}.lock"), re.M)
        assert found
        for name, version in found:
            assert pins.get(name) == version, name


def test_a_release_waits_for_the_tests():
    workflow = read(".github", "workflows", "build.yml")
    assert "needs: [test, build]" in workflow
    assert "python -m pytest" in workflow


def test_the_constraints_cover_linux_too():
    pins = read("packaging", "constraints.txt").lower()
    for needed in ("pynput==", "evdev==", "python-xlib==", "six=="):
        assert needed in pins


def test_the_build_uses_the_inno_setup_it_was_tested_with():
    workflow = read(".github", "workflows", "build.yml")
    step = workflow.split("name: Inno Setup", 1)[1].split("- name:", 1)[0]
    assert "choco" not in step
    assert "Tools.InnoSetup/6.7.3" in step
    assert re.search(r"[0-9a-f]{64}", step, re.I)
    assert "Get-FileHash" in step


def test_settings_know_the_new_switch():
    from ttspython.core.settings import DEFAULTS, normalize

    assert DEFAULTS["stt_keep_recording"] is True
    assert normalize({"stt_keep_recording": False})["stt_keep_recording"] is False


def test_the_window_offers_and_discards_a_recording_from_a_crash(qtbot, tmp_path):
    app = make_controller(qtbot, tmp_path)
    leave_a_crashed_recording(app.stt.spool_folder, seconds=2.0)
    message = app.recover_dictation()
    assert "2 s" in message and "Try again" in message and "Discard" in message
    panel = app.window.listen_panel
    qtbot.waitUntil(lambda: not panel.retry.isHidden() and not panel.discard.isHidden(), timeout=2000)
    panel.discard.click()
    qtbot.waitUntil(lambda: panel.retry.isHidden() and panel.discard.isHidden(), timeout=2000)
    assert not spool_mod.find(app.stt.spool_folder)
    assert app.recover_dictation() is None


def test_the_switch_turns_the_file_off_and_removes_what_is_there(qtbot, tmp_path):
    app = make_controller(qtbot, tmp_path)
    assert app.stt.spool_folder
    folder = app.stt.spool_folder
    leave_a_crashed_recording(folder)
    app._apply_keep_recording(dict(app.settings.data, stt_keep_recording=False))
    assert app.stt.spool_folder is None and not spool_mod.find(folder)


def test_stop_in_the_window_does_not_wait(qtbot, tmp_path, monkeypatch):
    app = make_controller(qtbot, tmp_path)
    asked = []
    with monkeypatch.context() as m:
        m.setattr(app.speech, "stop", lambda *_a, **_k: pytest.fail("the window waited for speech to stop"))
        m.setattr(app.speech, "request_stop", lambda: asked.append(1))
        app.on_stop()
    assert asked


def test_header_sizes_are_filled_in_only_at_the_end(tmp_path):
    spool = spool_mod.Spool(str(tmp_path), 16000)
    with open(spool.path, "rb") as f:
        head = f.read(44)
    assert head[:4] == b"RIFF" and struct.unpack("<I", head[24:28])[0] == 16000
    spool.discard()
    assert wait_until(lambda: not os.path.exists(spool.path))


# --- found by reading the real window from outside, as a screen reader does -------------------------------
def test_a_new_document_is_not_unsaved(qtbot):
    from ttspython.ui.editor import SpeechTextEdit

    editor = SpeechTextEdit()
    qtbot.addWidget(editor)
    assert not editor.document().isModified()


def unnamed_controls(root):
    from PySide6.QtGui import QAccessible
    from PySide6.QtWidgets import (QAbstractButton, QAbstractSlider, QAbstractSpinBox, QComboBox, QFrame, QLineEdit, QListView,
                                   QPlainTextEdit, QScrollBar, QTextEdit)

    kinds = (QAbstractButton, QAbstractSlider, QAbstractSpinBox, QComboBox, QLineEdit, QListView, QPlainTextEdit, QTextEdit)
    missing = []
    for w in root.findChildren(object):
        if not isinstance(w, kinds) or isinstance(w, QScrollBar):
            continue
        if isinstance(w.parent(), (QComboBox, QAbstractSpinBox)) or type(w.parent()) is QFrame and isinstance(w, QListView):
            continue  # the insides of a combo box or spin box, which have their own name
        if isinstance(w.parent(), QLineEdit):
            continue  # a field's clear button, which is hidden from the Tab order
        iface = QAccessible.queryAccessibleInterface(w)
        if not (iface and (iface.text(QAccessible.Text.Name) or "").strip()):
            missing.append(f"{type(w).__name__} in {type(w.parent()).__name__}")
    return missing


def test_every_control_has_a_name_for_a_screen_reader(qtbot, tmp_path):
    app = make_controller(qtbot, tmp_path)
    assert unnamed_controls(app.window) == []
    assert unnamed_controls(app.mini) == []
    assert unnamed_controls(app.popover) == []
    assert unnamed_controls(app.caption) == []
    app.open_settings("appearance")
    dialog = next(w for w in QApplicationWidgets() if type(w).__name__ == "SettingsDialog")
    assert unnamed_controls(dialog) == []
    dialog.done(0)
    app.editor.document().setModified(False)


def QApplicationWidgets():  # noqa: N802
    from PySide6.QtWidgets import QApplication

    return QApplication.topLevelWidgets()


FALSE_ALARM = "Windows fatal exception: code 0x8001010d\n\nThread 0x1 (most recent call first):\n  File \"x.py\", line 1 in y\n"
REAL = "Windows fatal exception: access violation\n\nThread 0x2 (most recent call first):\n  File \"z.py\", line 2 in w\n"


def test_the_crash_log_keeps_only_crashes(tmp_path):
    from ttspython.core import diagnostics

    path = tmp_path / "crash.log"
    path.write_text(FALSE_ALARM + REAL + FALSE_ALARM, encoding="utf-8")
    diagnostics.tidy_crash_log(str(path))
    assert path.read_text(encoding="utf-8") == REAL


def test_no_crash_means_no_crash_log(tmp_path):
    from ttspython.core import diagnostics

    path = tmp_path / "crash.log"
    path.write_text(FALSE_ALARM, encoding="utf-8")
    diagnostics.tidy_crash_log(str(path))
    assert not path.exists()


def test_the_crash_log_does_not_grow_for_ever(tmp_path):
    from ttspython.core import diagnostics

    path = tmp_path / "crash.log"
    path.write_text(REAL * 20000, encoding="utf-8")
    diagnostics.tidy_crash_log(str(path))
    assert path.stat().st_size <= diagnostics._MAX_CRASH_BYTES
