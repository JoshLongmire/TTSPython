"""Regression tests for the issues found in the code review."""
import json
import queue
import random
import threading
import time

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor

from fakes import FakeSD, wait_for
from test_speech_engine import Rig
import test_ui
from test_ui import LONG, make_controller
from ttspython.core import chunking, keys, settings, textio
from ttspython.core.stt.service import ModelCache, SttService
from ttspython.core.tts import controller as controller_mod
from ttspython.core.tts.controller import State
from ttspython.core.tts.player import AudioPlayer, Marker
from ttspython.core.tts.render import Voice, pick_default_voice
from test_stt_service import FakeRecorder, FakeTimer

ctl = test_ui.ctl  # the fixture, shared with test_ui


# --- engine ---------------------------------------------------------------------------
def test_callback_survives_concurrent_flush_and_drop():
    sd = FakeSD(speed=60)
    player = AudioPlayer(queue.Queue(), sd_module=sd)
    stop = threading.Event()

    def feeder():
        i = 0
        while not stop.is_set():
            player.enqueue(np.full(64, 1000, dtype=np.int16), 22050, Marker(utt_id=1, index=i))
            i += 1

    def mutator():
        rng = random.Random(1)
        while not stop.is_set():
            player.drop_queued(1) if rng.random() < 0.5 else player.flush()

    threads = [threading.Thread(target=feeder), threading.Thread(target=mutator)]
    for t in threads:
        t.start()
    time.sleep(1.0)
    stop.set()
    for t in threads:
        t.join()
    assert player.callback_errors == 0
    assert sd.streams[-1].running  # the stream was never aborted
    player.close()


def test_audio_from_a_stopped_job_is_discarded():
    player = AudioPlayer(queue.Queue(), sd_module=FakeSD())
    player.flush(min_generation=3)
    assert player.enqueue(np.ones(100, dtype=np.int16), 22050, Marker(utt_id=1, generation=2)) is False
    assert player.pending_count() == 0
    assert player.enqueue(np.ones(100, dtype=np.int16), 22050, Marker(utt_id=1, generation=3)) is True
    player.close()


class DeadStream:
    """An output stream whose device vanished: it never calls back."""

    def __init__(self, *a, **k):
        self.active = False

    def start(self):
        pass

    def stop(self):
        pass

    def close(self):
        pass


def test_dead_device_reports_an_error_instead_of_hanging(monkeypatch):
    monkeypatch.setattr(controller_mod, "STALL_SECONDS", 0.3)
    rig = Rig()
    try:
        rig.sd.OutputStream = DeadStream
        rig.player.close()
        rig.ctl.speak("This will never be heard.")
        assert wait_for(lambda: rig.names("error"), timeout=5)
        assert "audio output stopped" in rig.names("error")[0][1]
        assert wait_for(lambda: rig.ctl.state is State.IDLE)
    finally:
        rig.close()


def test_queue_gap_is_not_reported_as_a_sentence():
    rig = Rig()
    try:
        for i in range(2):
            rig.queue.add(f"Item {i} words.", f"Item {i}")
        rig.ctl.play_queue()
        assert wait_for(lambda: rig.names("queue_finished"), timeout=5)
        assert all(e[1] > 0 for e in rig.names("chunk_started"))  # no utt_id -1 events
    finally:
        rig.close()


def test_infinity_in_settings_only_resets_that_value():
    d = settings.normalize(json.loads('{"tts_rate": 1e999, "window": {"x": Infinity, "y": 0, "w": 900, "h": 700},'
                                      ' "theme_preset": "paper"}'))
    assert d["tts_rate"] == settings.DEFAULTS["tts_rate"]
    assert d["window"] is None
    assert d["theme_preset"] == "paper"


def test_crlf_paragraphs_stay_separate_and_lone_surrogates_are_safe():
    chunks = chunking.split_chunks("Intro.\r\n\r\nTitle\r\n\r\nShort one.")
    assert [c.text for c in chunks] == ["Intro.", "Title", "Short one."]
    text = "Bad \ud800 char here. Next sentence."
    chunks = chunking.split_chunks(text)
    assert chunks and "�" in chunks[0].text
    assert chunks[1].pos16 == len("Bad \ud800 char here. ")


def test_utf16_files_round_trip(tmp_path):
    for bom, enc in ((b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be")):
        raw = bom + "Unicode text\r\nline two".encode(enc)
        path = tmp_path / f"{enc}.txt"
        path.write_bytes(raw)
        doc = textio.read_text_file(str(path))
        assert doc.text == "Unicode text\nline two"
        textio.write_text_file(str(path), doc.text, doc.encoding, doc.newline, doc.bom)
        assert path.read_bytes() == raw


def test_default_voice_prefers_english():
    voices = [Voice("de", "German (de)", language="de", gender="Female"),
              Voice("en-us", "English (en-us)", language="en-us", gender="Male")]
    assert pick_default_voice(voices, "missing-sapi-id") == "en-us"


def test_releasing_the_model_during_a_load_does_not_block():
    started, release = threading.Event(), threading.Event()

    def slow_loader(name):
        started.set()
        release.wait(5)
        return object()

    cache = ModelCache(slow_loader)
    t = threading.Thread(target=cache.get, args=("small",))
    t.start()
    assert started.wait(2)
    t0 = time.perf_counter()
    cache.release()
    assert time.perf_counter() - t0 < 0.1
    release.set()
    t.join()
    assert cache.loaded_name is None  # the release still took effect


def test_saving_unload_when_idle_frees_the_model_now():
    cache = ModelCache(lambda name: object())
    svc = SttService(recorder=FakeRecorder(), cache=cache, timer_factory=FakeTimer)
    cache.get("small")
    svc.configure(unload_when_idle=True, auto_unload=True, minutes=3)
    assert cache.loaded_name is None
    svc.shutdown()


def test_more_v4_key_names_migrate():
    assert keys.tk_to_portable("<Control-exclam>") == "Ctrl+!"
    assert keys.tk_to_portable("<KP_Add>") == "+"


# --- interface --------------------------------------------------------------------------
def test_settings_save_keeps_live_changes(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path)
    try:
        c.open_settings()
        dlg = c._settings_dialog
        c.set_mode("stt")
        c.window.transport.rate.setValue(65)  # 65% = 130 words per minute
        c.actions["queue_loop"].setChecked(True)
        c._settings_action("reset_mini")
        dlg.performance.setChecked(True)
        dlg._save()
        assert c.settings["mode"] == "stt"
        assert c.settings["tts_rate"] == 130
        assert c.settings["queue_loop"] is True
        assert c.settings["mini_pos"] is None
        assert c.settings["performance_mode"] is True
        assert c.window.listen_panel.isVisible()
    finally:
        c.quit()


def test_test_button_then_close_restores_the_engine(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path)
    try:
        c.open_settings()
        dlg = c._settings_dialog
        dlg.rate.setValue(55)  # 110 words per minute, heard right away
        assert c.speech.rate == 110
        c._settings_action("test_voice")
        assert c.speech.rate == 110
        dlg.reject()
        assert c.speech.rate == c.settings["tts_rate"] == 200
        assert c._settings_dialog is None
    finally:
        c.quit()


def test_settings_dialog_is_deleted_after_close(qtbot, tmp_path):
    from ttspython.ui.settings_dialog import SettingsDialog

    c = make_controller(qtbot, tmp_path)
    try:
        for _ in range(3):
            c.open_settings()
            c._settings_dialog.reject()
            qtbot.wait(20)
        assert len(c.window.findChildren(SettingsDialog)) == 0
    finally:
        c.quit()


def test_esc_in_find_bar_closes_it_without_stopping_speech(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path)
    try:
        c.editor.setPlainText(LONG)
        c.on_play_pause()
        qtbot.waitUntil(lambda: c.speech.state is State.PLAYING, timeout=3000)
        c.window.activateWindow()
        c.on_find()
        qtbot.wait(20)
        qtbot.keyClick(c.window.find_bar.find_edit, Qt.Key_Escape)
        assert not c.window.find_bar.isVisible()
        assert c.speech.busy
    finally:
        c.quit()


def test_shift_enter_goes_to_the_previous_match(ctl, qtbot):
    ctl.editor.setPlainText("one two one two one")
    bar = ctl.window.find_bar
    bar.open_bar()
    bar.find_edit.setText("one")
    cursor = ctl.editor.textCursor()
    cursor.setPosition(8)
    cursor.setPosition(11, QTextCursor.KeepAnchor)  # the middle "one"
    ctl.editor.setTextCursor(cursor)
    qtbot.keyClick(bar.find_edit, Qt.Key_Return, Qt.ShiftModifier)
    assert ctl.editor.textCursor().selectionStart() == 0


def test_ctrl_enter_pauses_like_the_play_button(ctl, qtbot):
    ctl.editor.setPlainText(LONG)
    ctl.actions["speak_all"].trigger()
    qtbot.waitUntil(lambda: ctl.speech.state is State.PLAYING, timeout=3000)
    ctl.actions["speak_all"].trigger()
    assert ctl.speech.state is State.PAUSED
    ctl.actions["speak_all"].trigger()
    assert ctl.speech.state is State.PLAYING
    ctl.on_stop()


def test_quit_with_unsaved_text_asks_first(ctl, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    ctl.editor.setPlainText("unsaved words")
    ctl.editor.document().setModified(True)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    ctl.request_quit()
    assert not ctl._quitting


def test_commands_sent_before_the_ui_is_ready_are_kept(qtbot):
    from ttspython.platform.single_instance import InstanceServer

    server = InstanceServer()
    server._deliver(["mini"])
    got = []
    server.set_handler(got.append)
    assert got == [["mini"]]
    server.server.close()
