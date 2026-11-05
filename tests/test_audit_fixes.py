"""Regression tests for the issues found in the full-codebase audit."""
import os
import subprocess
import sys
import time

from fakes import wait_for
from test_speech_engine import Rig
from test_ui import make_controller
from ttspython.core import keys, settings, textio
from ttspython.core.tts.controller import Source, State

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --- core -------------------------------------------------------------------------------
def test_qt_only_shortcuts_survive_a_restart(settings_path):
    store = settings.SettingsStore(settings_path, legacy="")
    store.set("shortcuts", dict(store["shortcuts"], speak_all="Ctrl+Num+5", find="Help", clear="Media Play"))
    store.save()
    again = settings.SettingsStore(settings_path, legacy="")
    assert again["shortcuts"]["speak_all"] == "Ctrl+Num+5"
    assert again["shortcuts"]["find"] == "Help"
    assert again["shortcuts"]["clear"] == "Media Play"


def test_global_hotkeys_stay_strict_but_accept_the_keypad():
    merged = keys.merge_shortcuts({"toggle_dictation": "Ctrl+Num+5", "speak_clipboard": "Media Play"},
                                  keys.DEFAULT_GLOBAL_HOTKEYS, strict=True)
    assert merged["toggle_dictation"] == "Ctrl+Num+5"
    assert merged["speak_clipboard"] == keys.DEFAULT_GLOBAL_HOTKEYS["speak_clipboard"]
    assert keys.to_win_hotkey("Ctrl+Num+5")[1] == 0x65  # VK_NUMPAD5
    assert keys.find_conflicts({"a": "Ctrl+Num+5", "b": "Ctrl+5"}) == {}


def test_voice_test_never_starts_the_auto_queue():
    rig = Rig()
    try:
        rig.queue.add("Pending queue item.", "Pending")
        rig.ctl.auto_queue = True
        rig.ctl.speak("This is how speech will sound.", Source.TEST)
        assert wait_for(lambda: rig.names("utterance_finished"))
        time.sleep(0.3)
        assert rig.names("queue_item_started") == []
        rig.ctl.speak("Real reading now.", Source.EDITOR)
        assert wait_for(lambda: rig.names("queue_item_started"), timeout=5)
    finally:
        rig.close()


def test_stt_worker_does_not_keep_the_process_alive():
    code = ("import sys, threading; sys.path.insert(0, r'%s');"
            "from ttspython.core.stt.service import SttService, ModelCache;"
            "svc = SttService(cache=ModelCache(lambda n: threading.Event().wait(60)));"
            "svc._pool.submit(svc.cache.get, 'small'); print('exiting', flush=True)") % ROOT
    t0 = time.perf_counter()
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    assert out.stdout.strip() == "exiting"
    assert time.perf_counter() - t0 < 15  # did not wait for the 60 s "model load"


def test_save_reports_the_utf8_fallback(tmp_path):
    path = str(tmp_path / "doc.txt")
    used = textio.write_text_file(path, "emoji \U0001F600 here", "cp1252", "\r\n")
    assert used == "utf-8"
    assert textio.read_text(path) == "emoji \U0001F600 here"


def test_unsavable_import_does_not_crash(tmp_path, v4_settings_file):
    blocked = tmp_path / "blocked"
    blocked.write_text("a file where a folder is needed")
    store = settings.SettingsStore(str(blocked / "settings.json"), legacy=v4_settings_file)
    assert store.info["source"] == "legacy" and store.info.get("save_error")


def test_quit_flag_with_nothing_running_exits(tmp_path):
    env = dict(os.environ, TTSPYTHON_SETTINGS=str(tmp_path / "s.json"),
               TTSPYTHON_INSTANCE=f"ttspython-quit-test-{os.getpid()}")
    t0 = time.perf_counter()
    out = subprocess.run([sys.executable, os.path.join(ROOT, "TTSPython.py"), "--quit"], env=env,
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0
    assert time.perf_counter() - t0 < 15
    assert not os.path.exists(tmp_path / "s.json")  # it never built the app


# --- interface ---------------------------------------------------------------------------
def test_now_playing_marker_clears_and_paused_label_recovers(qtbot, tmp_path):
    from ttspython.ui.panels import PLAYING_ROLE

    c = make_controller(qtbot, tmp_path)
    try:
        for i in range(2):
            c.queue.add(f"Queue item {i} has a few words in it.", f"Item {i}")
        c.queue_play()
        qtbot.waitUntil(lambda: c.speech.state is State.PLAYING, timeout=3000)
        c.speech.pause()
        qtbot.waitUntil(lambda: c.window.transport.now.text() == "Paused", timeout=2000)
        c.speech.resume()
        qtbot.waitUntil(lambda: c.window.transport.now.text() != "Paused", timeout=2000)
        c.on_stop()
        qtbot.waitUntil(lambda: c.speech.state is State.IDLE, timeout=3000)
        qtbot.wait(50)
        lst = c.window.queue_panel.list
        assert not any(lst.item(i).data(PLAYING_ROLE) for i in range(lst.count()))
    finally:
        c.quit()


def test_queue_start_clears_the_editor_highlight(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path)
    try:
        c.editor.setPlainText("Editor sentence one. Editor sentence two.")
        c.editor.begin_tracking()
        c.editor.highlight_range(0, 20)
        assert c.editor.extraSelections()
        c._on_queue_item_started("x")
        assert not c.editor.extraSelections()
    finally:
        c.quit()


def test_settings_save_keeps_values_changed_elsewhere(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path)
    try:
        c.open_settings()
        dlg = c._settings_dialog
        c.window.transport.rate.setValue(75)           # 75% (150 wpm), changed live, not in the dialog
        c.window.perf_switch.setChecked(True)
        dlg.theme_cards["paper"].clicked.emit("paper")  # the dialog change
        dlg._save()
        assert c.settings["tts_rate"] == 150 and c.speech.rate == 150
        assert c.settings["performance_mode"] is True
        assert c.settings["theme_preset"] == "paper"
    finally:
        c.quit()


def test_closing_settings_without_test_leaves_live_speech_alone(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path)
    try:
        c.open_settings()
        c.window.transport.rate.setValue(140)
        calls = []
        c._apply_engine = lambda values: calls.append(values)
        c._settings_dialog.reject()
        assert calls == []
    finally:
        c.quit()


def test_window_layout_saved_when_switching_to_mini(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path)
    try:
        c.window.resize(1000, 700)
        qtbot.wait(20)
        c.show_mini()
        assert c.settings["window"]["w"] == 1000 and c.settings["window"]["h"] == 700
    finally:
        c.quit()


def test_dictation_feedback_reaches_the_user_outside_the_window(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path)
    try:
        c.show_mini()
        shown = []
        c._toast = lambda text, ms=0: shown.append(text)
        c._on_model_status("No speech detected")
        c._on_model_status("small model ready")
        assert shown == ["No speech detected"]
    finally:
        c.quit()


def test_queue_list_keeps_its_scroll_position(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path)
    try:
        c.window.resize(1000, 560)
        for i in range(40):
            c.queue.add(f"Item number {i} text.", f"Item {i}")
        bar = c.window.queue_panel.list.verticalScrollBar()
        qtbot.waitUntil(lambda: bar.maximum() > 0, timeout=2000)
        bar.setValue(bar.maximum() // 2)
        before = bar.value()
        c.queue.add("One more.", "More")
        qtbot.wait(20)
        assert bar.value() == before
    finally:
        c.quit()


# --- previously documented as not fixable -------------------------------------------------
def test_failed_model_load_is_not_retried_in_the_same_recording():
    from test_stt_service import FakeRecorder, FakeTimer
    from ttspython.core.stt.service import ModelCache, SttService

    loads = []

    def loader(name):
        loads.append(name)
        raise OSError("no network")

    svc = SttService(recorder=FakeRecorder(), cache=ModelCache(loader), timer_factory=FakeTimer)
    errors = []
    svc.events.on("error", errors.append)
    try:
        svc.start("editor")
        assert wait_for(lambda: loads)
        svc.stop()
        assert wait_for(lambda: errors)
        assert loads == ["small"]  # one load attempt, not two
        assert "failed to load" in errors[0] and "no network" in errors[0]
        svc.start("editor")  # the next recording tries again
        assert wait_for(lambda: len(loads) == 2)
        svc.stop()
    finally:
        svc.shutdown()


def test_unsaved_text_survives_logoff(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path)
    try:
        c.editor.setPlainText("Draft words that were never saved.")
        c.editor.document().setModified(True)
        c._on_commit_data(None)               # Windows asks to end the session
        assert os.path.exists(c._recovery_path())
    finally:
        c.quit()                              # the event loop ends with no prompt
    again = make_controller(qtbot, tmp_path)
    try:
        assert again.restore_recovery()
        assert again.editor.toPlainText() == "Draft words that were never saved."
        assert again.editor.document().isModified()
        assert os.path.exists(again._recovery_path())  # kept until replaced: a second crash loses nothing
        again.editor.document().setModified(False)
        again.editor.setPlainText("")
        again.quit(keep_draft=False)
        assert not os.path.exists(again._recovery_path())  # a clean end removes it
    finally:
        again.editor.document().setModified(False)
        again.quit()


def test_recovery_keeps_the_original_file_and_encoding(qtbot, tmp_path):
    path = tmp_path / "notes.txt"
    path.write_bytes("caf\xe9\r\n".encode("cp1252"))
    c = make_controller(qtbot, tmp_path)
    try:
        doc = textio.read_text_file(str(path))
        c.editor.setPlainText(doc.text + " more")
        c.current_file, c.current_doc = str(path), doc
        c.editor.document().setModified(True)
    finally:
        c.quit()
    again = make_controller(qtbot, tmp_path)
    try:
        assert again.restore_recovery()
        assert again.current_file == str(path)
        assert again.current_doc.encoding == doc.encoding and again.current_doc.newline == "\r\n"
    finally:
        again.editor.document().setModified(False)
        again.quit()


def test_choosing_discard_leaves_no_recovery(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    c = make_controller(qtbot, tmp_path)
    c.editor.setPlainText("Throw this away.")
    c.editor.document().setModified(True)
    c._on_commit_data(None)  # an earlier logoff that was cancelled
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Discard)
    c.request_quit()
    assert c._quitting
    assert not os.path.exists(c._recovery_path())


# --- first dictation looked stuck while the model downloaded ----------------------------------
def test_first_dictation_reports_the_model_download():
    import threading

    from test_stt_service import FakeModel, FakeRecorder, FakeTimer
    from ttspython.core.stt.service import ModelCache, SttService

    release, loaded_from = threading.Event(), []

    def downloader(name, progress):
        progress(120, 484, 3)
        release.wait(5)
        return "C:/models/" + name

    def loader(path):
        loaded_from.append(path)
        return FakeModel(path, [])

    svc = SttService(recorder=FakeRecorder(), cache=ModelCache(loader, downloader), timer_factory=FakeTimer)
    status = []
    svc.events.on("model_status", status.append)
    try:
        svc.start("editor")
        assert wait_for(lambda: svc.downloading)
        svc.stop()
        svc.toggle("editor")  # pressing the mic again while it downloads
        assert "Downloading the small model... 120 of 484 MB (first use only)" in status
        assert status[-1] == "Still downloading the small model (first use only)..."
        release.set()
        assert wait_for(lambda: svc.state.value == "idle")
        assert "Loading small model..." in status and not svc.downloading
        assert loaded_from == ["C:/models/small"]  # loaded from disk, no online check
    finally:
        svc.shutdown()


def test_download_progress_counts_bytes(monkeypatch):
    import huggingface_hub

    from ttspython.core.stt import service

    calls = []

    def fake_snapshot(repo, allow_patterns=None, local_files_only=False, tqdm_class=None):
        calls.append((repo, local_files_only))
        if local_files_only:
            raise FileNotFoundError("not cached")
        bar = tqdm_class(total=484_000_000, unit="B")
        bar.update(242_000_000)
        time.sleep(1.4)
        return "C:/hub/small"

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot)
    seen = []
    assert service.download_whisper("small", lambda *a: seen.append(a)) == "C:/hub/small"
    assert calls == [("Systran/faster-whisper-small", True), ("Systran/faster-whisper-small", False)]
    assert seen and seen[0][:2] == (242, 484)


def test_downloaded_model_skips_the_download(monkeypatch):
    import huggingface_hub

    from ttspython.core.stt import service

    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda repo, **k: "C:/hub/tiny")
    seen = []
    assert service.download_whisper("tiny", lambda *a: seen.append(a)) == "C:/hub/tiny"
    assert seen == []
