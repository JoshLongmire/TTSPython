"""What the two pre-launch code reviews found, each proved by a test that failed before the fix."""
import ast
import os
import threading

import numpy as np
import pytest
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMessageBox

from test_ui import make_controller
from ttspython.core import platform as plat
from ttspython.core import settings as settings_module
from ttspython.core import textio
from ttspython.core.stt.service import SttState
from ttspython.core.tts import piper
from ttspython.core.tts.controller import Source
from ttspython.platform import inject
from ttspython.ui.voice_browser import VoiceBrowser


@pytest.fixture
def c(qtbot, tmp_path):
    controller = make_controller(qtbot, tmp_path)
    yield controller
    controller.editor.document().setModified(False)
    controller.quit()


def status(c):
    return c.window.status_label.text()


# --- saving must never damage a file ----------------------------------------------------------
GBK = "丂你好，世界。".encode("gbk")  # the first character has a byte cp1252 lacks


def test_a_file_that_cannot_be_decoded_is_marked_and_kept_safe(c, tmp_path, monkeypatch):
    path = tmp_path / "legacy.txt"
    path.write_bytes(GBK)
    assert textio.read_text_file(str(path)).lossy
    c.open_path(str(path))
    asked = []
    monkeypatch.setattr(c, "on_save_as", lambda: asked.append(True))
    c.editor.insertPlainText("x")
    c.on_save()
    assert asked == [True]  # Save asks for a new name
    assert path.read_bytes() == GBK


@pytest.mark.parametrize("raw", [b"\xef\xbb\xbfgood \x81 bad", b"\xff\xfe\x00\xd8"])
def test_a_byte_order_mark_with_bad_bytes_is_marked_too(raw):
    assert textio.decode_text(raw).lossy


@pytest.mark.parametrize("raw", [b"plain", "café".encode(), "café".encode("cp1252"), b"\xff\xfeh\x00"])
def test_files_read_exactly_are_not_marked(raw):
    assert not textio.decode_text(raw).lossy


def test_saving_keeps_no_break_spaces(c, tmp_path):
    path = tmp_path / "doc.txt"
    path.write_bytes("one two\nthree".encode())
    c.open_path(str(path))
    c.editor.document().setModified(True)
    c.on_save()
    assert path.read_bytes().replace(b"\r\n", b"\n") == "one two\nthree".encode()


def test_shift_enter_is_saved_as_a_line_break(c, tmp_path):
    path = tmp_path / "doc.txt"
    path.write_bytes(b"caf\xe9 au lait")  # Windows-1252: it must stay that way
    c.open_path(str(path))
    c.editor.moveCursor(c.editor.textCursor().MoveOperation.End)
    c.editor.textCursor().insertText("\u2028more")
    c.on_save()
    assert path.read_bytes().replace(b"\r\n", b"\n") == b"caf\xe9 au lait\nmore"


def test_text_in_another_encoding_read_as_windows_1252_is_marked(c, tmp_path, monkeypatch):
    for raw in ("\u4f60\u597d\uff0c\u4e16\u754c\u3002".encode("gbk"), "\u3053\u3093\u306b\u3061\u306f".encode("shift-jis"),
                "\u041f\u0440\u0438\u0432\u0435\u0442 \u043c\u0438\u0440".encode("cp1251")):
        doc = textio.decode_text(raw)
        assert doc.encoding == "cp1252" and doc.lossy, raw
    assert not textio.decode_text("Cr\u00e8me br\u00fbl\u00e9e \u00e0 la fran\u00e7aise".encode("cp1252")).lossy


def test_text_that_cannot_be_written_shows_the_save_failed_message(c, tmp_path, monkeypatch):
    boxes = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: boxes.append(a[1]))
    monkeypatch.setattr(textio, "write_text_file", lambda *a, **k: "\ud800".encode())
    c._write(str(tmp_path / "doc.txt"))
    assert boxes == ["Save failed"]


def test_a_failed_copy_keeps_the_only_whole_copy(tmp_path, monkeypatch):
    src, dst = tmp_path / "new.part", tmp_path / "doc.txt"
    src.write_text("new", encoding="utf-8")
    dst.write_text("old", encoding="utf-8")

    def refuse(*_a):
        raise OSError("locked")

    monkeypatch.setattr(settings_module.os, "replace", refuse)
    monkeypatch.setattr(settings_module.time, "sleep", lambda _s: None)
    monkeypatch.setattr(settings_module.shutil, "copyfile", refuse)
    with pytest.raises(OSError):
        settings_module.atomic_replace(str(src), str(dst))
    assert src.read_text(encoding="utf-8") == "new"


def test_saving_follows_a_link_and_keeps_permissions(tmp_path, monkeypatch):
    real, link = tmp_path / "real.txt", tmp_path / "link.txt"
    real.write_text("old", encoding="utf-8")
    monkeypatch.setattr(textio.os.path, "islink", lambda p: p == str(link))
    monkeypatch.setattr(textio.os.path, "realpath", lambda p: str(real))
    copied = []
    monkeypatch.setattr(textio.shutil, "copymode", lambda a, b: copied.append((a, b)))
    textio.write_text_file(str(link), "new")
    assert real.read_text(encoding="utf-8") == "new" and not link.exists()
    assert copied == [(str(real), str(real) + ".part")]


def test_a_locked_file_leaves_no_part_file_beside_it(tmp_path, monkeypatch):
    path = tmp_path / "doc.txt"
    path.write_text("old", encoding="utf-8")

    def refuse(*_a):
        raise OSError("locked")

    monkeypatch.setattr(settings_module.os, "replace", refuse)
    monkeypatch.setattr(settings_module.time, "sleep", lambda _s: None)
    monkeypatch.setattr(settings_module.shutil, "copyfile", refuse)
    with pytest.raises(OSError):
        textio.write_text_file(str(path), "new")
    assert [f.name for f in tmp_path.iterdir()] == ["doc.txt"]
    assert path.read_text(encoding="utf-8") == "old"


def test_a_write_that_fails_leaves_no_part_file(tmp_path, monkeypatch):
    path = tmp_path / "doc.txt"

    def refuse(_fd):
        raise OSError("disk full")

    monkeypatch.setattr(textio.os, "fsync", refuse)
    with pytest.raises(OSError):
        textio.write_text_file(str(path), "words")
    assert list(tmp_path.iterdir()) == []


def test_a_settings_file_held_for_a_moment_is_not_called_broken(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text('{"stt_auto_unload_minutes": 7}', encoding="utf-8")
    real = settings_module._read_json
    tries = []

    def held_once(p):
        tries.append(p)
        if len(tries) == 1:
            raise PermissionError("held by a sync tool")
        return real(p)

    monkeypatch.setattr(settings_module, "_read_json", held_once)
    monkeypatch.setattr(settings_module.time, "sleep", lambda _s: None)
    data, info = settings_module.load(str(path), legacy="")
    assert info["broken_copy"] is None and data["stt_auto_unload_minutes"] == 7


# --- the editor's file and prompts --------------------------------------------------------------
def test_copying_a_queue_item_to_the_editor_detaches_the_open_file(c, tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("my notes", encoding="utf-8")
    c.open_path(str(path))
    c.queue.add("Queue words", "Item", "text")
    c._queue_to_editor(c.queue.snapshot()[0].id)
    assert c.editor.toPlainText() == "Queue words" and c.current_file is None
    assert c.editor.document().isModified()
    assert path.read_text(encoding="utf-8") == "my notes"


def unsaved(c):
    c.editor.setPlainText("unsaved words")
    c.editor.document().setModified(True)


def test_the_unsaved_prompt_defaults_to_save_not_to_losing_the_text(c, monkeypatch):
    unsaved(c)
    seen = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: seen.append(a) or QMessageBox.Cancel)
    assert c._confirm_discard() is False
    buttons, default = seen[0][3], seen[0][4]
    assert default == QMessageBox.Save
    assert buttons == QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel


def test_choosing_save_saves_and_continues(c, tmp_path, monkeypatch):
    path = tmp_path / "doc.txt"
    path.write_text("old", encoding="utf-8")
    c.open_path(str(path))
    c.editor.setPlainText("new")
    c.editor.document().setModified(True)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Save)
    assert c._confirm_discard() is True
    assert path.read_text(encoding="utf-8") == "new"


def test_choosing_save_then_cancelling_the_file_dialog_keeps_the_text(c, monkeypatch):
    unsaved(c)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Save)
    monkeypatch.setattr(c, "on_save_as", lambda: None)
    assert c._confirm_discard() is False


def test_choosing_discard_leaves_nothing_to_come_back_after_a_crash(c, monkeypatch):
    unsaved(c)
    c._on_commit_data(None)
    assert os.path.exists(c._recovery_path())
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Discard)
    assert c._confirm_discard() is True
    assert not os.path.exists(c._recovery_path())


def test_clearing_the_queue_defaults_to_no(c, monkeypatch):
    c.queue.add("Some words", "Item", "text")
    seen = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: seen.append(a) or QMessageBox.No)
    c.queue_clear()
    assert seen[0][4] == QMessageBox.No and len(c.queue) == 1


def test_recovered_text_stays_safe_until_it_is_written_again(c, tmp_path):
    unsaved(c)
    c._on_commit_data(None)
    c.editor.setPlainText("")
    assert c.restore_recovery()
    assert os.path.exists(c._recovery_path())  # a second crash right now loses nothing


def test_dropping_several_files_on_the_editor_says_what_happened(c, tmp_path, monkeypatch):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("first", encoding="utf-8")
    b.write_text("second", encoding="utf-8")
    toasts = []
    monkeypatch.setattr(c, "_toast", lambda text, *_a: toasts.append(text))
    c.editor.files_dropped.emit([str(a), str(b)])
    assert c.editor.toPlainText() == "first"
    assert "queue" in toasts[0]


def test_no_notice_about_several_files_if_none_was_opened(c, tmp_path, monkeypatch):
    unsaved(c)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Cancel)
    toasts = []
    monkeypatch.setattr(c, "_toast", lambda text, *_a: toasts.append(text))
    c.editor.files_dropped.emit([str(tmp_path / "a.txt"), str(tmp_path / "b.txt")])
    assert toasts == [] and c.editor.toPlainText() == "unsaved words"


# --- speech and quitting ----------------------------------------------------------------------
def test_opening_a_file_stops_reading_the_old_one(c, tmp_path, monkeypatch):
    path = tmp_path / "other.txt"
    path.write_text("Other text.", encoding="utf-8")
    stopped = []
    with monkeypatch.context() as m:
        m.setattr(type(c.speech), "busy", property(lambda _s: True))
        m.setattr(type(c.speech), "current_source", property(lambda _s: Source.EDITOR))
        m.setattr(c.speech, "stop", lambda: stopped.append(True))
        c.open_path(str(path), confirmed=True)
    assert stopped == [True]


def test_opening_a_file_does_not_stop_the_queue(c, qtbot, tmp_path, monkeypatch):
    path = tmp_path / "other.txt"
    path.write_text("Other text.", encoding="utf-8")
    stopped = []
    with monkeypatch.context() as m:
        m.setattr(type(c.speech), "busy", property(lambda _s: True))
        m.setattr(type(c.speech), "current_source", property(lambda _s: Source.QUEUE))
        m.setattr(c.speech, "stop", lambda: stopped.append(True))
        c.open_path(str(path), confirmed=True)
    assert stopped == []


@pytest.mark.parametrize("work", ["export", "dictation"])
def test_quitting_asks_first_while_work_is_running(c, monkeypatch, work):
    seen = []
    with monkeypatch.context() as m:
        if work == "export":
            m.setattr(type(c.exporter), "running", property(lambda _s: True))
        else:
            c.stt._state = SttState.TRANSCRIBING
        m.setattr(QMessageBox, "question", lambda *a, **k: seen.append(a) or QMessageBox.No)
        c.request_quit()
    c.stt._state = SttState.IDLE  # the test's window is closed before the fixture ends
    assert not c._quitting
    assert seen[0][1] == "Quit TTSPython" and seen[0][4] == QMessageBox.No


def test_the_pause_shortcut_works_in_listen_mode_while_speech_plays(c, monkeypatch):
    c.settings.set("mode", "stt")
    with monkeypatch.context() as m:
        m.setattr(type(c.speech), "busy", property(lambda _s: True))
        c._apply_mode_enabled()
        assert c.actions["speak_all"].isEnabled()


# --- settings ---------------------------------------------------------------------------------
def test_closing_settings_keeps_a_speed_changed_in_the_main_window(c):
    c.open_settings()
    dialog = c._settings_dialog
    c.window.transport.rate.setValue(150)
    assert dialog.rate.value() == 150 and dialog.rate_label.text() == "150%"
    c.window.transport.volume.setValue(55)
    assert dialog.volume.value() == 55
    rate, volume = c.settings["tts_rate"], c.settings["tts_volume"]
    dialog._cancel()
    assert (c.settings["tts_rate"], c.settings["tts_volume"]) == (rate, volume)
    assert c.window.transport.rate.value() == 150


def test_cancel_still_undoes_what_was_moved_in_settings(c):
    before = c.settings["tts_rate"], c.settings["tts_volume"]
    c.open_settings()
    dialog = c._settings_dialog
    dialog.rate.setValue(75)
    dialog.volume.setValue(40)
    dialog._cancel()
    assert (c.settings["tts_rate"], c.settings["tts_volume"]) == before


def test_reset_then_cancel_puts_speed_and_volume_back(c):
    c.window.transport.rate.setValue(150)
    c.window.transport.volume.setValue(55)
    before = c.settings["tts_rate"], c.settings["tts_volume"]
    c.open_settings()
    dialog = c._settings_dialog
    dialog._reset()
    assert c.settings["tts_rate"] != before[0]
    dialog._cancel()
    assert (c.settings["tts_rate"], c.settings["tts_volume"]) == before
    assert c.window.transport.rate.value() == 150


def test_saving_a_hotkey_another_app_holds_says_so(c, monkeypatch):
    monkeypatch.setattr(c.hotkeys, "set_bindings", lambda bindings, enabled: {"toggle_dictation": "taken"})
    c.open_settings("shortcuts")
    c._settings_dialog._save()
    assert "Another app uses" in status(c)


def test_refresh_on_the_listen_page_shows_why_it_could_not(c, monkeypatch):
    c.open_settings("speech")
    dialog = c._settings_dialog
    monkeypatch.setattr(dialog.ctx, "rescan_devices", lambda: False)
    dialog.refresh_devices()
    assert "Stop speech" in dialog.input_note.text() and not dialog.input_note.isHidden()
    assert not dialog.device_note.isHidden()


def test_deleting_a_model_asks_first(c, monkeypatch):
    c.open_settings("speech")
    dialog = c._settings_dialog
    deleted = []
    monkeypatch.setattr(dialog.ctx, "delete_model", lambda name: deleted.append(name) or "")
    seen = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: seen.append(a) or QMessageBox.No)
    dialog._delete_model("small")
    assert deleted == [] and seen[0][4] == QMessageBox.No
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    dialog._delete_model("small")
    assert deleted == ["small"]


# --- voices -----------------------------------------------------------------------------------
def test_esc_in_get_more_voices_cancels_the_download(qtbot):
    dialog = VoiceBrowser()
    qtbot.addWidget(dialog)
    dialog._cancel = threading.Event()
    dialog.reject()
    assert dialog._cancel.is_set()


def test_a_voice_that_could_not_be_removed_is_not_called_removed(qtbot, monkeypatch):
    dialog = VoiceBrowser()
    qtbot.addWidget(dialog)
    monkeypatch.setattr(dialog, "selected_key", lambda: "en_US-lessac-medium")
    monkeypatch.setattr(dialog, "_remove", lambda _key: None)
    monkeypatch.setattr(piper, "installed_keys", lambda: ["en_US-lessac-medium"])
    dialog._remove_selected()
    assert "Could not remove" in dialog.status.text()


def test_a_process_that_cannot_start_leaves_no_temp_folder(monkeypatch, tmp_path):
    made = tmp_path / "out"

    def refuse(*_a, **_k):
        raise OSError("cannot start")

    monkeypatch.setattr(piper.tempfile, "mkdtemp", lambda prefix: (made.mkdir(), str(made))[1])
    monkeypatch.setattr(piper.subprocess, "Popen", refuse)
    with pytest.raises(OSError):
        piper._Process("en_US-lessac-medium", 1.0)
    assert not made.exists()


# --- dictation --------------------------------------------------------------------------------
def test_no_mic_error_is_reported_outside_the_lock(qtbot, tmp_path):
    """The message box runs its own event loop: a hotkey pressed there would wait on the lock forever."""
    from test_stt_service import FakeTimer
    from ttspython.core.stt.service import ModelCache, SttService

    class NoMic:
        sample_rate = 16000

        def start(self, device=None):
            raise OSError("no microphone")

    svc = SttService(recorder=NoMic(), cache=ModelCache(lambda name: object()), timer_factory=FakeTimer)
    free = []
    svc.events.on("error", lambda _text: free.append(svc._lock.acquire(blocking=False)))
    assert svc.start() is False
    assert free == [True]
    svc._lock.release()


def test_a_late_pass_of_an_old_dictation_cannot_be_typed_later():
    """Dictate, cancel, dictate again and stop: the first one's late text must not be reused."""
    from test_live_captions import make

    svc = make()[0]
    svc._session, svc._recording, svc._state = 5, 5, SttState.RECORDING
    svc.recorder.t0 = 0.0
    svc.recorder.snapshot = lambda _start=0: np.full(16000, 0.2, dtype=np.float32)
    svc.model = svc.cache.loaded_name  # counts as loaded
    svc._get_model = lambda: object()

    def late(_model, _audio, words=False):
        svc._session = svc._recording = 7  # cancelled, and a new dictation started during this pass
        return [(0.0, 1.0, "words from the old dictation")]

    svc._whisper = late
    svc._live_loop(5)
    assert svc._last_pass is None


def test_a_pass_running_when_you_press_stop_is_still_reused():
    """It saves a whole second at stop: the final text does not need a pass of its own."""
    from test_live_captions import make

    svc = make()[0]
    svc._session, svc._recording, svc._state = 5, 5, SttState.RECORDING
    svc.recorder.t0 = 0.0
    svc.recorder.snapshot = lambda _start=0: np.full(16000, 0.2, dtype=np.float32)
    svc.model = svc.cache.loaded_name
    svc._get_model = lambda: object()

    def stopped_meanwhile(_model, _audio, words=False):
        svc._session = 6  # stop() moves the session on, and the recording is still this one
        return [(0.0, 1.0, "the last words")]

    svc._whisper = stopped_meanwhile
    svc._live_loop(5)
    assert svc._last_pass == (0, 16000, "the last words")


# --- pasting into other apps ------------------------------------------------------------------
windows_only = pytest.mark.skipif(not plat.IS_WINDOWS, reason="Windows only")


@windows_only
def test_a_blocked_paste_leaves_the_dictation_on_the_clipboard(qtbot, monkeypatch):
    from ttspython.platform import winapi

    QGuiApplication.clipboard().setText("older clipboard text")
    monkeypatch.setattr(winapi, "foreground_window", lambda: 42)
    monkeypatch.setattr(winapi, "modifiers_down", lambda: False)
    monkeypatch.setattr(winapi, "send_paste", lambda _keys: 0)
    monkeypatch.setattr(inject, "RESTORE_DELAY_MS", 10)
    injector = inject.TextInjector()
    with qtbot.waitSignal(injector.finished, timeout=3000) as sig:
        injector.inject("a long dictation", 42)
    assert sig.args[0] is False
    assert QGuiApplication.clipboard().text() == "a long dictation"


@windows_only
def test_a_window_running_as_administrator_gets_the_text_on_the_clipboard(qtbot, monkeypatch):
    from ttspython.platform import winapi

    sent = []
    monkeypatch.setattr(winapi, "foreground_window", lambda: 42)
    monkeypatch.setattr(winapi, "window_needs_admin", lambda _hwnd: True)
    monkeypatch.setattr(winapi, "send_paste", lambda keys: sent.append(keys) or 4)
    injector = inject.TextInjector()
    with qtbot.waitSignal(injector.finished, timeout=3000) as sig:
        injector.inject("dictated words", 42)
    assert sent == [] and "administrator" in sig.args[1]
    assert QGuiApplication.clipboard().text() == "dictated words"


@windows_only
def test_rights_check_on_real_processes():
    from ttspython.platform import winapi

    assert winapi.process_needs_admin(os.getpid()) is False
    assert winapi.process_needs_admin(4) is True  # the System process, always out of reach
    assert winapi.window_needs_admin(0) is False


# --- other programs on Linux ------------------------------------------------------------------
def test_other_programs_get_the_systems_library_path_in_a_packaged_build(monkeypatch):
    monkeypatch.setattr(plat.sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/bundle")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/local/lib")
    assert plat.child_env()["LD_LIBRARY_PATH"] == "/usr/local/lib"
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG")
    assert "LD_LIBRARY_PATH" not in plat.child_env()


def test_nothing_starts_a_program_with_the_inherited_environment():
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ttspython")
    found, missing = 0, []
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if not name.endswith(".py"):
                continue
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess"
                        and node.func.attr in ("Popen", "run")):
                    found += 1
                    if not any(k.arg == "env" for k in node.keywords):
                        missing.append((name, node.lineno))
    assert found >= 5 and missing == []
