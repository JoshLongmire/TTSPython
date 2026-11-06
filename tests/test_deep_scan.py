"""What the deep code base scan found. Each of these failed before its fix."""
import json
import os
import queue
import re
import sys
import threading
import time
import tracemalloc

import numpy as np
import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QMessageBox

from fakes import FakeSD, wait_for
from test_ui import make_controller
from test_voice_streaming import Blocks, Rig as StreamRig, tone, voice  # noqa: F401 (fixture)
from ttspython.core import chunking, diagnostics, keys, search, textio
from ttspython.core import settings as settings_mod
from ttspython.core.stt import recorder as recorder_mod
from ttspython.core.stt import service
from ttspython.core.stt.service import ModelCache, SttService, SttState
from ttspython.core.tts import clone
from ttspython.core.tts.player import AudioPlayer, Marker
from ttspython.platform import inject
from ttspython.ui.clone_dialog import CloneDialog
from ttspython.ui.editor import FindBar, SpeechTextEdit
from ttspython.ui.settings_dialog import MicMeter
from ttspython.ui.voice_browser import VoiceBrowser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*path):
    with open(os.path.join(ROOT, *path), encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def c(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(MicMeter, "start", lambda self, device: None)
    controller = make_controller(qtbot, tmp_path)
    yield controller
    controller.quit()


# --- your own voice ------------------------------------------------------------------------------
class Encoder:
    def encode(self, audio, rate):
        return np.zeros((5, 16), dtype=np.int32)


def make_voice(name):
    return clone.build_voice(name, clone.Consent("words", ("a", "b", "c")), tone(7, 16000), 16000, "words", Encoder())


def test_a_second_voice_keeps_its_own_name(voice):  # noqa: F811
    second = make_voice("Mum")
    assert clone.voice_info(second)["name"] == "Mum"


def test_the_pace_does_not_jump_in_the_middle_of_a_sentence():
    rig = StreamRig(blocks=4, block_seconds=0.25, delay=0.01, native=200)
    try:
        rig.ctl.set_rate(200)
        rig.ctl.speak("A sentence that goes on for one second.")
        assert wait_for(lambda: bool(rig.player._segments) and rig.player._segments[0].announced, timeout=3)
        segment = rig.player._segments[0]
        rig.renderer.native = 100  # it turns out, when the chunk is made, to be much slower
        assert wait_for(lambda: rig.renderer.finished_block_at is not None, timeout=3)
        time.sleep(0.1)
        assert segment.native == 200
        assert not segment.growing
    finally:
        rig.close()


def test_the_voices_pace_is_known_from_the_first_sentence_of_the_next_session(voice):  # noqa: F811
    list(clone.CloneRenderer(lambda: Blocks((2.0, 2.0))).stream(
        "One two three four five six seven eight nine ten.", voice, 200, threading.Event()))
    assert clone.CloneRenderer(lambda: Blocks()).native_wpm(200, voice) == 150


def test_one_odd_sentence_does_not_swing_the_pace(voice):  # noqa: F811
    r = clone.CloneRenderer(lambda: Blocks((2.0, 2.0)))
    text = "One two three four five six seven eight nine ten."
    list(r.stream(text, voice, 200, threading.Event()))
    before = r.native_wpm(200, voice)
    r._engine_factory = lambda: Blocks((1.0, 1.0))
    list(r.stream(text, voice, 200, threading.Event()))
    assert r.native_wpm(200, voice) == before


def test_the_speed_check_tells_the_pace_of_a_new_voice(voice, monkeypatch):  # noqa: F811
    class Engine(Blocks):
        def speak(self, codes, text, cancel):
            return tone(5.0, self.rate)

    monkeypatch.setattr(clone, "_load_engine", lambda cancel: None)
    monkeypatch.setattr(clone, "shared_engine", Engine)
    clone.speed_check(voice)
    words = len(clone.SPEED_CHECK_TEXT.split())
    assert clone.CloneRenderer().native_wpm(200, voice) == pytest.approx(words * 60 / 5.0, abs=1)


def test_how_far_along_follows_what_the_model_says_is_left():
    player = AudioPlayer(queue.Queue(), sd_module=FakeSD(), idle_close=30)
    try:
        feed = player.open_feed(22050, Marker(utt_id=1), 200, 10.0)
        pcm = (tone(1.0) * 32767).astype(np.int16)
        feed.add(pcm, left=1.0)
        assert feed._segment.expected == pytest.approx(2 * 22050, abs=50)
    finally:
        player.close()


def test_a_voice_change_between_sentences_does_not_repeat_the_last_one():
    rig = StreamRig(blocks=1)
    try:
        text = "The first sentence goes here now. The second sentence goes here now. The third one goes here."
        chunks = chunking.split_chunks(text, 0)
        assert len(chunks) >= 3
        rig.ctl._playing_index = 0  # the first was heard to the end; the next has not started
        new_text, _base, new_chunks, heard = rig.ctl._restart_at_heard_word(1, text, 0, chunks)
        assert heard == 1
        assert new_text == text[chunks[1].start:]
        rig.ctl._playing_index = len(chunks) - 1
        new_text, _base, new_chunks, _heard = rig.ctl._restart_at_heard_word(1, text, 0, chunks)
        assert new_text == "" and new_chunks == []
    finally:
        rig.close()


def test_resuming_just_as_a_long_pause_stops_the_device_leaves_it_running():
    sd = FakeSD()
    player = AudioPlayer(queue.Queue(), sd_module=sd, idle_close=30)
    try:
        player.wait_open()
        stream = sd.streams[-1]
        stopping, go_on = threading.Event(), threading.Event()
        real_stop = stream.stop

        def slow_stop():
            stopping.set()
            go_on.wait(2)
            real_stop()

        stream.stop = slow_stop
        player.pause()
        player._paused_since = time.monotonic() - 100
        stopper = threading.Thread(target=player._stop_if_still_paused)
        stopper.start()
        assert stopping.wait(2)
        resumer = threading.Thread(target=player.resume)
        resumer.start()
        time.sleep(0.05)
        go_on.set()
        stopper.join(2)
        resumer.join(2)
        assert stream.running
        assert not player._stream_stopped
    finally:
        player.close()


def test_a_voice_change_at_the_wrong_moment_cannot_reach_the_wrong_engine():
    rig = StreamRig(blocks=2, delay=0.001)
    try:
        real = rig.renderer.streams

        def streams(voice_id):
            rig.ctl.voice_id = "plain"  # set_voice arriving right now, from another thread
            return real(voice_id)

        rig.renderer.streams = streams
        rig.ctl.speak("A sentence here.")
        assert wait_for(lambda: bool(rig.renderer.started) or bool(rig.errors), timeout=3)
        assert rig.renderer.started[0][1] == "stream-a"
        rig.ctl.stop()
    finally:
        rig.close()


def test_dead_code_is_gone():
    assert not hasattr(clone.Engine, "_speak_piece")
    from ttspython.core.tts.stretch import Stretcher
    assert not hasattr(Stretcher, "fraction")


# --- dictation ---------------------------------------------------------------------------------
class ScriptedRecorder:
    sample_rate = 16000

    def __init__(self):
        self.level = 0.0
        self.on_limit = self.on_lost = None
        self.audio = np.full(16000 * 2, 0.05, dtype=np.float32)

    def start(self, device=None):
        pass

    def stop(self):
        return self.audio


class Segment:
    def __init__(self, text):
        self.text, self.start, self.end = text, 0.0, 1.0


class Whisper:
    def __init__(self):
        self.fail = True

    def transcribe(self, audio, **kwargs):
        if self.fail:
            raise RuntimeError("out of memory")
        return [Segment("the rest")], None


def dictation():
    model = Whisper()
    svc = SttService(recorder=ScriptedRecorder(), cache=ModelCache(lambda _name: model),
                     timer_factory=lambda *_a: threading.Timer(1000, lambda: None))
    svc.live = False
    log = []
    for name in ("transcript_ready", "error", "retry_available"):
        svc.events.on(name, lambda *a, n=name: log.append((n, *a)))
    return svc, model, log


def stop_and_wait(svc):
    svc.toggle("editor")
    svc.toggle()
    assert wait_for(lambda: svc.state is SttState.IDLE)


def test_a_failed_transcription_keeps_the_recording_and_can_try_again():
    svc, model, log = dictation()
    stop_and_wait(svc)
    assert any(e[0] == "error" and "Try again" in e[1] for e in log)
    assert ("retry_available", True) in log
    model.fail = False
    assert svc.retry()
    assert wait_for(lambda: any(e[0] == "transcript_ready" for e in log))
    assert ("retry_available", False) in log
    assert [e[1] for e in log if e[0] == "transcript_ready"] == ["The rest."]
    assert not svc.retry()  # used up


def test_text_already_final_is_delivered_even_if_the_rest_fails():
    svc, model, log = dictation()
    svc.toggle("editor")
    svc._settled_text = "the first part"
    svc._settled_samples = 16000
    svc.toggle()
    assert wait_for(lambda: svc.state is SttState.IDLE)
    assert [e[1] for e in log if e[0] == "transcript_ready"] == ["The first part."]
    model.fail = False
    log.clear()
    assert svc.retry()
    assert wait_for(lambda: any(e[0] == "transcript_ready" for e in log))
    assert [e[1] for e in log if e[0] == "transcript_ready"] == ["The rest."]  # not the first part again


def test_a_model_that_could_not_load_keeps_the_recording_too():
    svc, _model, log = dictation()
    svc.toggle("editor")
    svc._load_failed = (svc.model, OSError("offline"))
    svc.toggle()
    assert wait_for(lambda: svc.state is SttState.IDLE)
    assert ("retry_available", True) in log
    assert any(e[0] == "error" and "Try again" in e[1] for e in log)


def test_a_new_dictation_lets_the_kept_recording_go():
    svc, _model, log = dictation()
    stop_and_wait(svc)
    svc.toggle("editor")
    assert ("retry_available", False) in log
    assert not svc.retry()
    svc.cancel()


class SilentInput:
    """A microphone that gives a few blocks, then is unplugged: nothing more arrives, and no error."""

    def __init__(self, callback, blocks):
        self.callback = callback
        self.blocks = blocks

    def start(self):
        block = np.full((1024, 1), 500, dtype=np.int16)
        for _ in range(self.blocks):
            self.callback(block, 1024, None, None)

    def stop(self):
        pass

    def close(self):
        pass


class InputSD:
    def __init__(self, blocks=3):
        self.blocks = blocks

    def InputStream(self, samplerate, channels, dtype, blocksize, device, callback):  # noqa: N802
        return SilentInput(callback, self.blocks)

    def query_devices(self, *_a):
        return {"default_samplerate": 16000}


def test_losing_the_microphone_is_noticed_and_keeps_what_was_said(monkeypatch):
    monkeypatch.setattr(recorder_mod, "NO_SOUND_SECONDS", 0.2)
    rec = recorder_mod.Recorder(sd_module=InputSD())
    lost = threading.Event()
    rec.on_lost = lost.set
    rec.start()
    assert lost.wait(3)
    assert rec.stop().size == 3 * 1024


def test_a_microphone_that_keeps_going_is_left_alone(monkeypatch):
    monkeypatch.setattr(recorder_mod, "NO_SOUND_SECONDS", 0.2)
    rec = recorder_mod.Recorder(sd_module=InputSD(blocks=0))
    lost = threading.Event()
    rec.on_lost = lost.set
    rec.start()
    block = np.full((1024, 1), 500, dtype=np.int16)
    for _ in range(12):
        rec._callback(block, 1024, None, None)
        time.sleep(0.05)
    assert not lost.is_set()
    rec.stop()
    time.sleep(0.5)
    assert not lost.is_set()  # and a stopped recording is not "lost" either


def test_the_service_types_what_it_has_when_the_microphone_goes():
    svc, model, log = dictation()
    model.fail = False
    statuses = []
    svc.events.on("model_status", statuses.append)
    svc.toggle("editor")
    svc.recorder.on_lost()
    assert wait_for(lambda: any(e[0] == "transcript_ready" for e in log))
    assert any("microphone stopped" in s for s in statuses)


def test_stopping_a_long_recording_at_the_devices_rate_takes_little_memory():
    rec = recorder_mod.Recorder(sd_module=InputSD(blocks=0))
    rec._capture_rate = 48000
    block = (tone(1024 / 48000, 48000) * 32767).astype(np.int16)
    rec._blocks = [block] * (48000 * 120 // 1024)  # 2 minutes
    tracemalloc.start()
    audio = rec.stop()
    _now, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert abs(audio.size - 16000 * 120) < 400
    assert peak < 40e6  # was 146 MB, about 2.2 GB for 30 minutes
    assert np.abs(audio[1000:-1000]).max() > 0.4


def test_recording_failure_while_converting_does_not_lose_the_audio(monkeypatch):
    rec = recorder_mod.Recorder(sd_module=InputSD(blocks=0))
    rec._blocks = [np.zeros(1024, dtype=np.int16)]

    def broken(_blocks):
        raise MemoryError

    monkeypatch.setattr(rec, "_to_float", broken)
    with pytest.raises(MemoryError):
        rec.stop()
    assert rec._blocks


def test_a_superscript_digit_does_not_stop_the_captions():
    assert service._plain("10²") == "10²"
    assert service._same_word("10²", "10²")


def test_a_long_silence_is_not_converted_again_on_every_pass():
    svc, _model, _log = dictation()
    rate = 16000
    silent = np.zeros(rate * 60, dtype=np.float32)
    assert svc._settle([], silent) == ""
    assert svc._settled_samples == rate * 60 - rate  # keeps the last second: a word may be starting
    assert svc._settled_text == ""


def test_a_short_silence_is_left_alone():
    svc, _model, _log = dictation()
    svc._settle([], np.zeros(16000 * 2, dtype=np.float32))
    assert svc._settled_samples == 0


def test_a_model_without_its_vocabulary_is_not_complete(tmp_path):
    for name in service.REQUIRED_FILES:
        (tmp_path / name).write_bytes(b"x")
    assert not service.model_complete(str(tmp_path))
    (tmp_path / "vocabulary.json").write_bytes(b"x")
    assert service.model_complete(str(tmp_path))


# --- settings ---------------------------------------------------------------------------------
def write_settings(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return str(path)


def test_a_huge_window_size_cannot_stop_the_app_starting(tmp_path):
    path = write_settings(tmp_path / "s.json", {"window": {"x": 0, "y": 0, "w": 2147483648, "h": 600}, "splitter": [2**40, 1]})
    data, _info = settings_mod.load(path, legacy="")
    assert data["window"] is None and data["splitter"] is None
    data, _info = settings_mod.load(write_settings(tmp_path / "t.json", {"window": {"x": -2**40, "y": 0, "w": 800, "h": 600}}), legacy="")
    assert data["window"] is None


def test_a_normal_window_survives(tmp_path):
    data, _info = settings_mod.load(write_settings(
        tmp_path / "s.json", {"window": {"x": -1920, "y": 40, "w": 1280, "h": 800}, "splitter": [600, 200]}), legacy="")
    assert data["window"]["x"] == -1920 and data["splitter"] == [600, 200]
    QRect(data["window"]["x"], data["window"]["y"], data["window"]["w"], data["window"]["h"])


ODD_VALUES = [None, True, 0, -1, 10**400, 1.5, float("inf"), "", "x", "²", "٣", "Ctrl+F²", [], ["en"], [None], {}, {"a": 1},
              {"x": "y"}, {"w": 10**400}, [[1]], {"rx": 10**400, "ry": 0}, {"F2": "Ctrl+F²"}]


@pytest.mark.parametrize("key", sorted(settings_mod.DEFAULTS))
def test_one_bad_value_never_costs_the_rest_of_the_settings(key):
    for value in ODD_VALUES:
        out = settings_mod.normalize({key: value, "tts_rate": 321})
        assert out["tts_rate"] == (321 if key != "tts_rate" else out["tts_rate"]), (key, value)
        json.dumps(out)


def test_odd_shortcuts_are_refused_not_fatal():
    assert keys.parse_combo("Ctrl+F²") is None
    assert settings_mod.normalize_device_ref("²") == {"name": "²", "hostapi": "", "index": None}


def test_a_file_held_by_another_program_is_not_overwritten_with_defaults(tmp_path, monkeypatch):
    path = write_settings(tmp_path / "settings.json", {"tts_rate": 123})
    monkeypatch.setattr(settings_mod, "_read_json", lambda _p: (_ for _ in ()).throw(PermissionError("held")))
    monkeypatch.setattr(settings_mod.shutil, "copy2", lambda *_a: (_ for _ in ()).throw(PermissionError("held")))
    store = settings_mod.SettingsStore(path, legacy="")
    assert store.info["read_failed"]
    store.save()
    assert json.loads(open(path, encoding="utf-8").read()) == {"tts_rate": 123}


def test_saving_works_again_once_the_file_can_be_read(tmp_path, monkeypatch):
    path = write_settings(tmp_path / "settings.json", {"tts_rate": 123})
    real = settings_mod._read_json
    monkeypatch.setattr(settings_mod, "_read_json", lambda _p: (_ for _ in ()).throw(PermissionError("held")))
    store = settings_mod.SettingsStore(path, legacy="")
    monkeypatch.setattr(settings_mod, "_read_json", real)
    store.save()
    # Saved now: what was there is merged in, and what was changed this session stays changed.
    assert json.loads(open(path, encoding="utf-8").read())["tts_rate"] == 123


@pytest.mark.parametrize("content", ["[]", "null", "3", "\"text\""])
def test_a_file_that_is_not_settings_counts_as_broken_and_a_copy_is_kept(tmp_path, content):
    path = tmp_path / "settings.json"
    path.write_text(content, encoding="utf-8")
    _data, info = settings_mod.load(str(path), legacy="")
    assert info["broken_copy"] and os.path.exists(info["broken_copy"])


# --- saving documents ---------------------------------------------------------------------------
def test_a_held_document_is_never_copied_over(tmp_path, monkeypatch):
    path = tmp_path / "doc.txt"
    path.write_bytes(b"the original")
    copied = []
    monkeypatch.setattr(os, "replace", lambda *_a: (_ for _ in ()).throw(PermissionError("held")))
    monkeypatch.setattr(settings_mod.shutil, "copyfile", lambda *a: copied.append(a))
    with pytest.raises(OSError):
        textio.write_text_file(str(path), "new text")
    assert not copied
    assert path.read_bytes() == b"the original"
    assert os.listdir(tmp_path) == ["doc.txt"]


def test_a_moment_of_holding_does_not_fail_the_save(tmp_path, monkeypatch):
    path = tmp_path / "doc.txt"
    path.write_bytes(b"the original")
    real = os.replace
    tries = []

    def held_once(a, b):
        tries.append(1)
        if len(tries) == 1:
            raise PermissionError("held")
        real(a, b)

    monkeypatch.setattr(os, "replace", held_once)
    textio.write_text_file(str(path), "new text", newline="\n")
    assert path.read_bytes() == b"new text"


def test_saving_does_not_touch_a_file_of_the_same_name_as_its_scratch_file(tmp_path):
    path = tmp_path / "doc.txt"
    theirs = tmp_path / "doc.txt.part"
    theirs.write_bytes(b"mine")
    textio.write_text_file(str(path), "text")
    assert theirs.read_bytes() == b"mine"
    assert sorted(os.listdir(tmp_path)) == ["doc.txt", "doc.txt.part"]


def test_utf16_without_a_mark_is_not_saved_over():
    assert textio.decode_text("hello there".encode("utf-16-le")).lossy
    assert textio.decode_text("hello there".encode("utf-16-be")).lossy
    assert textio.decode_text(b"a\x00b").lossy
    assert not textio.decode_text(b"plain text").lossy


def test_utf32_is_read_as_utf32_and_written_back_the_same():
    for raw, encoding in (("﻿hi there".encode("utf-32-le"), "utf-32-le"), ("﻿hi there".encode("utf-32-be"), "utf-32-be")):
        doc = textio.decode_text(raw)
        assert doc.text == "hi there" and doc.encoding == encoding and doc.bom and not doc.lossy
        data, used = textio.encode_text(doc.text, doc.encoding, "\n", doc.bom)
        assert data == raw and used == encoding


def test_a_broken_character_does_not_stop_the_save(tmp_path):
    path = tmp_path / "doc.txt"
    assert textio.write_text_file(str(path), "good \ud83d bad", newline="\n") == "utf-8"
    assert path.read_text(encoding="utf-8") == "good � bad"


def test_replace_works_with_a_lookahead(qtbot):
    editor = SpeechTextEdit()
    qtbot.addWidget(editor)
    bar = FindBar(editor)
    qtbot.addWidget(bar)
    editor.setPlainText("one, two")
    bar.regex_btn.setChecked(True)
    bar.find_edit.setText(r"(\w+)(?=,)")
    bar.replace_edit.setText(r"[\1]")
    assert bar.find(False)
    bar.replace_one()
    assert editor.toPlainText() == "[one], two"


def test_replacing_a_match_uses_its_place_in_the_text():
    text = "a one, a two"
    assert search.replacement_at(text, 7, 12, r"(\w) two", r"\1!", use_regex=True) == "a!"
    assert search.replacement_at(text, 2, 5, "one", r"\1") == r"\1"  # plain text is taken as it is


def test_a_long_run_of_dots_is_quick():
    start = time.perf_counter()
    chunking.split_chunks("." * 64000 + " end.", 0)
    assert time.perf_counter() - start < 0.5  # 16,000 dots took 2.3 s


def test_sentences_still_split_the_same():
    spans = [c.text for c in chunking.split_chunks("Wait... what? Yes!) Fine. And the rest goes on here without a stop", 0, )]
    assert "".join(spans).replace(" ", "") == "Wait...what?Yes!)Fine.Andtherestgoesonherewithoutastop"


# --- diagnostics -----------------------------------------------------------------------------------
def test_an_error_nobody_catches_is_written_down(tmp_path):
    previous = (sys.excepthook, threading.excepthook)
    folder = str(tmp_path / "logs")
    try:
        sys.excepthook = lambda *_a: None  # pytest-qt fails the test for any error that reaches the hook
        handler = diagnostics.start(folder, crashes=False)
        try:
            raise ValueError("something broke")
        except ValueError as exc:
            sys.excepthook(ValueError, exc, exc.__traceback__)
        handler.flush()
        with open(os.path.join(folder, diagnostics.LOG_NAME), encoding="utf-8") as f:
            text = f.read()
        assert "something broke" in text and "Traceback" in text
    finally:
        diagnostics.stop()
        sys.excepthook, threading.excepthook = previous


# --- the window: dictation --------------------------------------------------------------------------
def test_the_last_dictation_can_be_copied_again(c, monkeypatch):
    action = c.actions["copy_last_dictation"]
    assert not action.isEnabled()
    copied = []
    monkeypatch.setattr(c.injector, "copy_only", lambda text, message="": copied.append(text))
    monkeypatch.setattr(c.injector, "inject", lambda text, target=None: None)
    c._on_transcript("words that went nowhere", ("external", 0))
    assert action.isEnabled()
    action.trigger()
    assert copied == ["words that went nowhere"]


def test_the_tray_offers_the_last_dictation():
    assert "copy_last_dictation" in read("ttspython", "ui", "tray.py")


def test_dictating_stops_speech_wherever_the_text_goes(c, monkeypatch):
    stopped = []
    monkeypatch.setattr(type(c.speech), "busy", property(lambda _self: True))
    monkeypatch.setattr(c.speech, "request_stop", lambda *a, **k: stopped.append(1))
    monkeypatch.setattr(c.stt, "toggle", lambda target=None: None)
    c.toggle_dictation(("external", 5))
    assert stopped  # the microphone would hear the speakers and type what they say


def test_the_hidden_editor_is_never_the_target(c, monkeypatch):
    from ttspython.core import platform as plat
    if plat.IS_WINDOWS:
        from ttspython.platform import winapi
        monkeypatch.setattr(winapi, "foreground_window", lambda: 5)
        monkeypatch.setattr(winapi, "is_own_window", lambda _h: True)
    monkeypatch.setattr(c.window, "isVisible", lambda: False)
    monkeypatch.setattr(c.window, "isActiveWindow", lambda: False)
    assert c.capture_target() != "editor"


def test_the_visible_editor_still_is(c, monkeypatch):
    from ttspython.core import platform as plat
    if plat.IS_WINDOWS:
        from ttspython.platform import winapi
        monkeypatch.setattr(winapi, "foreground_window", lambda: 5)
        monkeypatch.setattr(winapi, "is_own_window", lambda _h: True)
    monkeypatch.setattr(c.window, "isVisible", lambda: True)
    monkeypatch.setattr(c.window, "isActiveWindow", lambda: True)
    assert c.capture_target() == "editor"


def test_a_kept_recording_shows_try_again(c, qtbot):
    panel = c.window.listen_panel
    assert panel.retry.isHidden()
    c.stt.events.emit("retry_available", True)
    qtbot.waitUntil(lambda: not panel.retry.isHidden(), timeout=2000)
    called = []
    c.stt.retry = lambda: called.append(1) or True
    panel.retry.click()
    assert called
    c.stt.events.emit("retry_available", False)
    qtbot.waitUntil(panel.retry.isHidden, timeout=2000)


def test_dictated_text_goes_in_at_the_cursor(qtbot):
    editor = SpeechTextEdit()
    qtbot.addWidget(editor)
    editor.setPlainText("first last")
    cursor = editor.textCursor()
    cursor.setPosition(5)
    editor.setTextCursor(cursor)
    editor.add_dictation("middle")
    assert editor.toPlainText() == "first middle last"
    editor.add_dictation("more")
    assert editor.toPlainText() == "first middle more last"


def test_dictated_text_at_the_end_goes_on_its_own_line(qtbot):
    editor = SpeechTextEdit()
    qtbot.addWidget(editor)
    editor.setPlainText("first")
    cursor = editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    editor.setTextCursor(cursor)
    editor.add_dictation("second")
    assert editor.toPlainText() == "first\nsecond\n"


def test_wayland_paste_that_fails_keeps_the_text(qtbot, monkeypatch):
    from PySide6.QtWidgets import QApplication

    class Failed:
        def __init__(self, *_a, **_k):
            pass

        def poll(self):
            return 1

    monkeypatch.setattr(inject.shutil, "which", lambda _t: "wtype")
    monkeypatch.setattr(inject.subprocess, "Popen", Failed)
    monkeypatch.setattr(inject, "RESTORE_DELAY_MS", 1)
    clipboard_text = []

    class Clip:
        def text(self):
            return clipboard_text[-1] if clipboard_text else "old"

        def setText(self, text):  # noqa: N802
            clipboard_text.append(text)

        def setMimeData(self, _data):  # noqa: N802
            clipboard_text.append("restored")

        def mimeData(self):  # noqa: N802
            return None

    assert QApplication.instance()
    monkeypatch.setattr(inject.TextInjector, "clipboard", Clip())
    injector = inject.TextInjector()
    done = []
    injector.finished.connect(lambda pasted, message: done.append((pasted, message)))
    injector._inject_wayland("hello")
    qtbot.waitUntil(lambda: bool(done), timeout=2000)
    assert done[0][0] is False and "clipboard" in done[0][1]
    assert clipboard_text[-1] == "hello"


# --- the window: other --------------------------------------------------------------------------
def test_the_microphone_meter_stops_when_settings_is_hidden(c, monkeypatch):
    c.open_settings("shortcuts")
    dialog = c._settings_dialog
    stopped, started = [], []
    monkeypatch.setattr(dialog.meter, "stop", lambda: stopped.append(1))
    monkeypatch.setattr(dialog, "_restart_meter", lambda *_a: started.append(1))
    dialog.hide()
    assert stopped
    dialog.show()
    assert started
    dialog.close()


def test_a_device_found_at_a_new_number_is_not_an_unsaved_change(c):
    c.open_settings("shortcuts")
    dialog = c._settings_dialog
    dialog.saved_values["tts_output_device"] = {"name": "Headset", "hostapi": "WASAPI", "index": 3}
    dialog.form_values = lambda: {"tts_output_device": {"name": "Headset", "hostapi": "WASAPI", "index": 7}}
    assert dialog._read_fields() == {}
    dialog.form_values = lambda: {"tts_output_device": {"name": "Speakers", "hostapi": "WASAPI", "index": 7}}
    assert "tts_output_device" in dialog._read_fields()
    del dialog.form_values
    dialog.done(0)


def test_a_window_saved_on_a_bigger_monitor_fits_this_one(c, monkeypatch):
    from PySide6.QtGui import QGuiApplication
    area = QGuiApplication.primaryScreen().availableGeometry()
    c.settings.set("window", {"x": area.x() + 10, "y": area.y() + 10, "w": area.width() + 900, "h": area.height() + 900,
                              "maximized": False})
    c._restore_geometry()
    assert c.window.width() <= area.width()
    assert c.window.height() <= area.height()


def test_every_part_of_the_window_fits_a_small_laptop_at_150_percent(c):
    assert c.window.minimumHeight() <= 450
    assert c.window.minimumSizeHint().height() <= 450


def test_a_voice_dialog_on_a_short_screen_can_still_reach_its_buttons(qtbot):
    dialog = CloneDialog(lambda *_a: "", recorder=object())
    qtbot.addWidget(dialog)
    assert dialog.minimumHeight() <= 450


def test_quitting_during_a_download_asks_first(c, monkeypatch):
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or QMessageBox.No)
    c.open_voice_browser()
    c._voice_browser._cancel = threading.Event()
    c._voice_browser._downloading = "en_US-x"
    assert not c._confirm_quit()
    assert "download" in asked[0]
    c._voice_browser._cancel = None
    c._voice_browser._downloading = None


def test_closing_get_more_voices_during_a_download_asks_first(qtbot, monkeypatch):
    dialog = VoiceBrowser()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._cancel = threading.Event()
    dialog._downloading = "en_US-x"
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    dialog.close()
    assert dialog.isVisible() and not dialog._cancel.is_set()
    dialog.reject()
    assert dialog.isVisible() and not dialog._cancel.is_set()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    dialog.close()
    assert dialog._cancel is None or dialog._cancel.is_set()
    dialog._cancel, dialog._downloading = None, None


def test_a_download_finishing_after_the_window_is_gone_is_harmless():
    assert "_emit" in read("ttspython", "ui", "voice_browser.py")
    assert "relay.done.emit" not in read("ttspython", "ui", "voice_browser.py")


def test_no_download_button_where_piper_cannot_run(qtbot, monkeypatch):
    from ttspython.core.tts import piper
    monkeypatch.setattr(piper, "program_available", lambda: False)
    dialog = VoiceBrowser()
    qtbot.addWidget(dialog)
    assert not dialog.download_btn.isEnabled()


def test_a_hotkey_that_cannot_work_here_does_not_blame_another_app(c, monkeypatch):
    monkeypatch.setattr(c.hotkeys, "available", False, raising=False)
    monkeypatch.setattr(c.hotkeys, "reason", "This desktop has no global hotkeys.", raising=False)
    c._hotkey_errors = {"toggle_dictation": "This desktop has no global hotkeys."}
    c._report_hotkey_errors()
    assert "Another app" not in c.window.status_label.text()
    assert "no global hotkeys" in c.window.status_label.text()


def test_the_tray_notice_shows_once(c, monkeypatch):
    toasts = []
    monkeypatch.setattr(c, "_toast", lambda text, *_a: toasts.append(text))
    monkeypatch.setattr(c.settings, "data", dict(c.settings.data, close_to_tray=True))
    c.tray = c.tray or object()
    monkeypatch.setattr(c, "_quitting", False, raising=False)

    class Event:
        def ignore(self):
            pass

        def accept(self):
            pass

    c._on_close_requested(Event())
    c._on_close_requested(Event())
    assert len(toasts) == 1
    assert c.settings["tray_notice_shown"] is True
    c.tray = None


def test_removing_from_the_queue_selects_the_next_one(c, monkeypatch):
    for text in ("one", "two", "three"):
        c.queue.add(text, text)
    c._refresh_queue()
    panel = c.window.queue_panel
    panel.list.setCurrentRow(1)
    c.queue_remove()
    c._refresh_queue()
    assert panel.selected_id() == c.queue.snapshot()[1].id
    panel.list.setCurrentRow(1)
    c.queue_remove()
    c._refresh_queue()
    assert panel.selected_id() == c.queue.snapshot()[0].id  # the last one went: the one before it


def test_the_editor_hint_shows_the_key_in_use(c):
    shortcuts = dict(c.settings["shortcuts"])
    key = next(k for k in shortcuts if shortcuts[k] == "Ctrl+Return")
    shortcuts[key] = "Ctrl+Shift+P"
    c.settings.set("shortcuts", shortcuts)
    c._apply_shortcuts()
    assert "Ctrl+Shift+P" in c.editor.placeholderText()
    assert "Ctrl+Enter" not in c.editor.placeholderText()


def test_a_stop_that_takes_long_is_reported(c, monkeypatch):
    monkeypatch.setattr(c.speech, "stop_overdue", lambda _s: True)
    c._report_slow_stop()
    assert "Still stopping" in c.window.status_label.text()


def test_a_stop_that_was_quick_is_not_mentioned(c, monkeypatch):
    monkeypatch.setattr(c.speech, "stop_overdue", lambda _s: False)
    c._report_slow_stop()
    assert "Still stopping" not in c.window.status_label.text()


def test_distil_says_it_only_knows_english(c):
    c.open_settings("shortcuts")
    dialog = c._settings_dialog
    dialog.model.setCurrentIndex(dialog.model.findData("distil-large-v3"))
    dialog.language.setCurrentIndex(dialog.language.findData("fr"))
    assert not dialog.model_note.isHidden() and "English" in dialog.model_note.text()
    dialog.language.setCurrentIndex(dialog.language.findData("en"))
    assert dialog.model_note.isHidden()
    dialog.done(0)


# --- keyboard and screen readers -------------------------------------------------------------------
def test_the_pill_says_what_it_does_now(c):
    c.mini.set_recording(True)
    assert "Stop" in c.mini.mic.accessibleName()
    c.mini.set_recording(False)
    assert "Dictate" in c.mini.mic.accessibleName()
    c.mini.set_speaking(True)
    assert "Stop" in c.mini.play.accessibleName()
    c.mini.set_speaking(False)


def test_settings_rows_name_their_number_boxes(c):
    from PySide6.QtWidgets import QAbstractSpinBox
    c.open_settings("shortcuts")
    for box in c._settings_dialog.findChildren(QAbstractSpinBox):
        assert box.accessibleName(), box
    c._settings_dialog.close()


def test_control_tab_leaves_the_editor(qtbot):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLineEdit, QVBoxLayout, QWidget

    holder = QWidget()
    qtbot.addWidget(holder)
    lay = QVBoxLayout(holder)
    editor, other = SpeechTextEdit(), QLineEdit()
    lay.addWidget(editor)
    lay.addWidget(other)
    moved = []
    editor.focusNextPrevChild = lambda forward: moved.append(forward) or True
    QTest.keyClick(editor, Qt.Key_Tab, Qt.ControlModifier)
    assert moved == [True]
    assert "\t" not in editor.toPlainText()
    del editor.focusNextPrevChild
    QTest.keyClick(editor, Qt.Key_Tab)
    assert "\t" in editor.toPlainText()  # plain Tab still types a tab


def test_the_status_chips_work_from_the_keyboard(qtbot):
    from PySide6.QtTest import QTest

    from ttspython.ui.widgets import ElidedLabel
    chip = ElidedLabel("Mic: Headset")
    qtbot.addWidget(chip)
    clicked = []
    chip.clicked.connect(lambda: clicked.append(1))
    chip.set_clickable("Open the settings")
    assert chip.focusPolicy() == Qt.TabFocus
    assert "Mic: Headset" in chip.accessibleName() and "Open the settings" in chip.accessibleName()
    QTest.keyClick(chip, Qt.Key_Return)
    QTest.keyClick(chip, Qt.Key_Space)
    assert len(clicked) == 2


def test_status_changes_are_said_to_a_screen_reader_but_not_every_download_step(c, monkeypatch):
    said = []
    monkeypatch.setattr(c.window, "announce", said.append)
    c._status("Queue finished")
    c._status("Downloading the small model... 3 of 480 MB (first use only)")
    assert said == ["Queue finished"]


def test_get_more_voices_names_its_controls(qtbot):
    dialog = VoiceBrowser()
    qtbot.addWidget(dialog)
    assert dialog.language.accessibleName() and dialog.filter.accessibleName() and dialog.list.accessibleName()


# --- docs and packaging -----------------------------------------------------------------------------
def test_uninstall_on_linux_finds_data_where_the_app_put_it():
    script = read("packaging", "linux", "uninstall.sh")
    assert "${XDG_CONFIG_HOME:-$HOME/.config}" in script and "${XDG_DATA_HOME:-$HOME/.local/share}" in script


def test_install_on_linux_reports_the_library_the_readme_promises():
    assert "libxcb-cursor" in read("packaging", "linux", "install.sh")


def test_the_uninstallers_say_which_models_stay():
    for text in (read("packaging", "linux", "uninstall.sh"), read("packaging", "windows", "TTSPython.iss")):
        assert "Whisper" in text and "voice model" in text
        assert "Speech recognition models" not in text


def test_every_build_input_is_pinned():
    pins = read("packaging", "constraints.txt").lower()
    for name in ("altgraph", "pefile", "pywin32-ctypes", "setuptools"):
        assert re.search(rf"^{name}==", pins, re.M), name


def test_what_the_code_imports_is_declared():
    req = read("requirements.txt").lower()
    assert "onnxruntime" in req and "huggingface_hub" in req


def test_gitignore_covers_what_the_app_and_rules_need():
    ignore = read(".gitignore").split()
    for entry in ("out/", "node_modules/", "*.json.tmp"):
        assert entry in ignore, entry
    for stale in (".eggs/", "*.egg", "settings.json.tmp"):
        assert stale not in ignore, stale


def test_the_wayland_banner_names_the_right_command(c, monkeypatch):
    source = read("ttspython", "ui", "settings_dialog.py")
    assert '"TTSPython.py --toggle-dictation' not in source
    from ttspython.ui import settings_dialog
    assert settings_dialog.command_name() == "python TTSPython.py"
    monkeypatch.setattr(settings_dialog.sys, "frozen", True, raising=False)
    assert settings_dialog.command_name() == "ttspython"


def test_the_docs_tell_the_new_things():
    readme = read("README.md")
    assert "Try again" in readme and "Copy last dictation" in readme and "logs" in readme
    assert "fraction of a second" not in readme or "system and Piper voices" in readme
    assert "stays selected" not in readme or "in use" in readme
    assert "keeps\n  your settings, voices and models when you upgrade or uninstall" not in read("CHANGELOG.md")


def test_speech_in_your_voice_uses_only_what_is_needed_for_speech():
    assert "5 to 10 seconds" not in read("ttspython", "core", "tts", "clone.py")
