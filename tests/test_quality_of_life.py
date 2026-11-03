"""Quality-of-life additions: speak from the cursor, New, recent files, drops, a kept queue..."""
import os

import numpy as np
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent, QTextCursor
from PySide6.QtWidgets import QMessageBox

from test_stt_service import FakeTimer, Segment
from test_ui import make_controller
from ttspython.core.stt.service import SILENT_MIC_MESSAGE, ModelCache, SttService, friendly_audio_error
from ttspython.core.tts.controller import State
from ttspython.ui.editor import reading_time, sentence_start


def test_speak_from_the_cursor_starts_at_its_sentence(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path)
    try:
        c.editor.setPlainText("First sentence here. Second one starts here. Third and last.")
        cursor = c.editor.textCursor()
        cursor.setPosition(30)  # inside "Second one..."
        c.editor.setTextCursor(cursor)
        c.on_speak_from_cursor()
        spoken = lambda: [r[0] for r in c.renderers[-1].rendered if r[0] != "a"]  # noqa: E731 ("a" warms the engine up)
        qtbot.waitUntil(lambda: bool(spoken()), timeout=3000)
        assert spoken()[0].startswith("Second one starts here.")
        c.on_stop()
    finally:
        c.quit()


def test_sentence_start_helper():
    text = "One. Two words here!\nThree?"
    assert sentence_start(text, 2) == 0
    assert sentence_start(text, 8) == 5
    assert sentence_start(text, len(text)) == text.index("Three")


def test_new_and_clear_forget_the_file(qtbot, tmp_path, monkeypatch):
    path = tmp_path / "notes.txt"
    path.write_text("Saved words.", encoding="utf-8")
    c = make_controller(qtbot, tmp_path)
    try:
        c.open_path(str(path))
        assert c.window.windowTitle() == "notes.txt[*] - TTSPython"
        c.editor.insertPlainText("more ")
        assert c.window.isWindowModified()
        c.on_clear()  # Ctrl+S must not now write an empty file over notes.txt
        assert c.current_file is None and c.window.windowTitle().startswith("Untitled")
        c.editor.setPlainText("Fresh text.")
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        c.on_new()
        assert c.editor.toPlainText() == "" and c.current_file is None
        assert path.read_text(encoding="utf-8") == "Saved words."
    finally:
        c.quit()


def test_recent_files_menu(qtbot, tmp_path):
    files = []
    for i in range(10):
        f = tmp_path / f"doc{i}.txt"
        f.write_text(f"Document {i}.", encoding="utf-8")
        files.append(str(f))
    c = make_controller(qtbot, tmp_path)
    try:
        for f in files:
            c.open_path(f)
        recent = c.settings["recent_files"]
        assert len(recent) == 8 and os.path.basename(recent[0]) == "doc9.txt"
        menu = c.window.open_button.menu()
        assert menu is not None and menu.actions()[0].text() == "doc9.txt"
        os.remove(files[9])
        toasts = []
        c._toast = lambda text, ms=0: toasts.append(text)
        c.open_path(files[9])  # gone: it leaves the list
        assert all(os.path.basename(p) != "doc9.txt" for p in c.settings["recent_files"])
    finally:
        c.quit()


def _drop(widget, paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
    event = QDropEvent(QPointF(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    widget.dropEvent(event)


def test_dropping_text_files_opens_or_queues_them(qtbot, tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("Dropped on the editor.", encoding="utf-8")
    b.write_text("Dropped on the queue.", encoding="utf-8")
    (tmp_path / "pic.png").write_bytes(b"png")
    c = make_controller(qtbot, tmp_path)
    try:
        _drop(c.editor, [str(a)])
        assert c.editor.toPlainText() == "Dropped on the editor." and c.current_file == str(a)
        _drop(c.window.queue_panel.list, [str(b), str(tmp_path / "pic.png")])
        assert [i.name for i in c.queue.snapshot()] == ["b.txt"]
    finally:
        c.quit()


def test_queue_is_kept_across_restarts(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path)
    c.queue.add("Chapter one text.", "Chapter 1.txt", "file")
    c.queue.add("Copied words.", "Clipboard: Copied words.", "clipboard")
    c.quit()
    again = make_controller(qtbot, tmp_path)
    try:
        items = again.queue.snapshot()
        assert [(i.name, i.kind) for i in items] == [("Chapter 1.txt", "file"), ("Clipboard: Copied words.", "clipboard")]
        again._queue_to_top(items[1].id)
        assert again.queue.snapshot()[0].name == "Clipboard: Copied words."
        again._queue_to_editor(items[0].id)
        assert again.editor.toPlainText() == "Chapter one text."
    finally:
        again.editor.document().setModified(False)
        again.quit()


def test_reading_time_follows_the_speed(qtbot, tmp_path):
    assert reading_time(50, 200) == "under 1 min"
    assert reading_time(400, 200) == "about 2 min"
    assert reading_time(400, 400) == "about 1 min"
    assert reading_time(200 * 120, 200) == "about 2.0 h"
    c = make_controller(qtbot, tmp_path)
    try:
        c.editor.setPlainText("word " * 400)
        c.window.editor_card._update_counts()
        assert "about 2 min" in c.window.editor_card.counts.text()
        c._set_rate(400)
        assert "about 1 min" in c.window.editor_card.counts.text()
        assert c.window.queue_panel.list.itemDelegate().wpm == 400
    finally:
        c.editor.document().setModified(False)
        c.quit()


def test_mini_bar_wheel_and_pause(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path, seconds=20)  # 0.5 s of real time at the fake device's speed
    try:
        c.show_mini()
        c._volume_step(-1)
        assert c.speech.volume == 0.95 and c.settings["tts_volume"] == 0.95
        c.editor.setPlainText("Some words to read for a while in the mini bar test.")
        c.on_speak_all()
        qtbot.waitUntil(lambda: c.speech.state is State.PLAYING, timeout=3000)
        assert c.popover.pause.isEnabled() and c.popover.pause.text() == "Pause"
        c.popover.pause_clicked.emit()
        qtbot.waitUntil(lambda: c.popover.pause.text() == "Resume", timeout=2000)
        c.on_stop()
    finally:
        c.editor.document().setModified(False)
        c.quit()


class FakeTray:
    def __init__(self):
        self.states = []

    def set_state(self, tip, recording=False, base_icon=None):
        self.states.append((tip, recording))

    def setIcon(self, icon):  # noqa: N802
        pass

    def showMessage(self, *args):  # noqa: N802
        pass

    def hide(self):
        pass


def test_tray_says_what_is_happening(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path)
    try:
        c.tray = FakeTray()
        c.toggle_dictation(("external", 0))
        assert c.tray.states[-1] == ("Listening...", True)
        c.stt.cancel()
        qtbot.waitUntil(lambda: c.tray.states[-1] == ("", False), timeout=3000)
    finally:
        c.tray = None
        c.quit()


def test_recording_icon_is_drawn(qapp):
    from ttspython.ui.tray import app_icon, recording_icon

    icon = recording_icon(app_icon())
    assert not icon.isNull() and len(icon.availableSizes()) >= 5


def test_a_silent_microphone_is_explained():
    class SilentRecorder:
        sample_rate = 16000
        level = 0.0
        on_limit = None

        def start(self, device=None):
            pass

        def stop(self):
            return np.zeros(16000, dtype=np.float32)

    class Model:
        def transcribe(self, audio, **kw):
            return [Segment("never", 1.0)], None

    svc = SttService(recorder=SilentRecorder(), cache=ModelCache(lambda n: Model()), timer_factory=FakeTimer)
    errors = []
    svc.events.on("error", errors.append)
    try:
        svc.start("editor")
        svc.stop()
        from fakes import wait_for

        assert wait_for(lambda: errors, timeout=5)
        assert errors[0] == SILENT_MIC_MESSAGE and "microphone" in errors[0]
    finally:
        svc.shutdown()


def test_device_errors_in_plain_words():
    assert "unplugged or in use" in friendly_audio_error(RuntimeError("Error opening InputStream: Invalid device [PaErrorCode -9996]"))
    assert "sample rate" in friendly_audio_error(RuntimeError("Invalid sample rate [PaErrorCode -9997]"))
    assert friendly_audio_error(RuntimeError("something else")) == "something else"


def test_unsaved_text_is_kept_every_30_seconds(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path)
    try:
        c.editor.setPlainText("Words typed but never saved.")
        c.editor.document().setModified(True)
        c.editor.insertPlainText(" More.")
        assert c._draft_timer.isActive() and c._draft_timer.interval() == 30_000
        c._draft_timer.timeout.emit()  # 30 s later
        assert os.path.exists(c._recovery_path())
    finally:
        c.editor.document().setModified(False)
        c.quit()


def test_export_uses_the_selection_and_remembers_the_folder(qtbot, tmp_path, monkeypatch):
    c = make_controller(qtbot, tmp_path)
    try:
        c.editor.setPlainText("Keep this out. Only this part is exported.")
        cursor = c.editor.textCursor()
        cursor.setPosition(15)
        cursor.setPosition(len(c.editor.toPlainText()), QTextCursor.KeepAnchor)
        c.editor.setTextCursor(cursor)
        out = tmp_path / "exports" / "part.wav"
        out.parent.mkdir()
        titles = []
        monkeypatch.setattr(c, "_save_dialog", lambda title, start, filters: (titles.append(title), (str(out), "wav"))[1])
        started = []
        monkeypatch.setattr(c.exporter, "start", lambda text, *a: started.append(text) or False)
        c.on_export()
        assert started == ["Only this part is exported."]
        assert titles == ["Export the selected text as audio"]
        assert c.settings["export_dir"] == str(out.parent) and c.settings["export_format"] == "wav"
    finally:
        c.editor.document().setModified(False)
        c.quit()


def test_hotkeys_taken_by_another_app_are_reported_once(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path)
    try:
        toasts = []
        c._toast = lambda text, ms=0: toasts.append(text)
        c._hotkey_errors = {"toggle_dictation": "Already used by another app", "stop_speech": None}
        c._report_hotkey_errors()
        assert toasts and "Ctrl+Alt+D (Start or stop dictation)" in toasts[0]
        assert "Ctrl+Alt+D" in c.window.status_label.text()
        c._report_hotkey_errors()  # the next start: same key still taken
        assert len(toasts) == 1  # not again: the status bar still says it
        c.settings["global_hotkeys"]["toggle_dictation"] = "Ctrl+Alt+Shift+D"
        c._report_hotkey_errors()  # a different key is taken now: that is news
        assert len(toasts) == 2
    finally:
        c.quit()


def test_busy_hotkeys_are_retried_before_telling_anyone(qtbot, tmp_path, monkeypatch):
    from ttspython.ui import app_controller

    monkeypatch.setattr(app_controller, "HOTKEY_RETRY_MS", (10, 10))
    c = make_controller(qtbot, tmp_path)
    try:
        toasts = []
        c._toast = lambda text, ms=0: toasts.append(text)
        busy = [2]  # taken for the first two tries, then free (the other copy has closed)

        def set_bindings(bindings, enabled=True):
            busy[0] -= 1
            return {a: ("Already used by another app" if busy[0] >= 0 and a == "toggle_mini" else None)
                    for a in bindings}

        c.hotkeys.set_bindings = set_bindings
        c._apply_global_hotkeys()
        c._retry_hotkeys(1)
        qtbot.wait(100)
        assert not any(c._hotkey_errors.values()) and toasts == []
    finally:
        c.quit()


def test_new_default_for_mini_mode_avoids_the_common_clash():
    from ttspython.core import keys

    assert keys.DEFAULT_GLOBAL_HOTKEYS["toggle_mini"] == "Ctrl+Alt+Shift+M"


def test_status_chips_open_their_settings(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path)
    try:
        c.window.device_chip.clicked.emit()
        dlg = c._settings_dialog
        assert dlg is not None and dlg.stack.currentIndex() == dlg._page_index["speech"]
        dlg._cancel_and_close()
    finally:
        c.quit()
