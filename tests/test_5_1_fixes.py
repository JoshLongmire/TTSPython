"""The fixes left over from 5.0, each proved by a test that failed before the fix."""
import threading
import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from test_ui import make_controller
from ttspython.core.stt import service
from ttspython.core.stt.service import SttState
from ttspython.platform import inject
from ttspython.ui.settings_dialog import SettingsDialog

if inject.IS_WINDOWS:
    from ttspython.platform import winapi
else:  # it loads Windows libraries; its tests are skipped elsewhere
    winapi = None


@pytest.fixture
def c(qtbot, tmp_path):
    controller = make_controller(qtbot, tmp_path)
    yield controller
    controller.editor.document().setModified(False)
    controller.quit()


# --- Ctrl+numpad Enter does what Ctrl+Enter does ------------------------------------------------
def test_ctrl_numpad_enter_plays(c):
    c.settings.set("mode", "tts")
    c.window.show()
    QTest.qWaitForWindowExposed(c.window)
    c.window.activateWindow()
    c.editor.setFocus()
    calls = []
    c.actions["speak_all"].triggered.disconnect()
    c.actions["speak_all"].triggered.connect(lambda *_: calls.append(True))
    QTest.keyClick(c.editor, Qt.Key_Enter, Qt.ControlModifier | Qt.KeypadModifier)
    assert calls == [True]
    assert c.editor.toPlainText() == ""  # and no line break is typed


def test_a_numpad_enter_binding_of_another_command_is_not_taken(c):
    shortcuts = dict(c.settings["shortcuts"], stop="Ctrl+Enter")
    c.settings.set("shortcuts", shortcuts)
    c._apply_shortcuts()
    assert [s.toString() for s in c.actions["speak_all"].shortcuts()] == ["Ctrl+Return"]


# --- Settings only asks about changes that were really made ----------------------------------------
class Voice:
    def __init__(self, voice_id, name):
        self.id, self.name = voice_id, name


def open_settings(c, monkeypatch, voices, saved="piper:later"):
    c.settings.set("tts_voice_id", saved)
    monkeypatch.setattr(c, "voices", lambda: voices, raising=False)
    c.open_settings()
    dialog = c._settings_dialog
    assert isinstance(dialog, SettingsDialog)
    monkeypatch.setattr(dialog.ctx, "voices", lambda: voices, raising=False)
    dialog._load_fields(dialog.values)
    return dialog


def test_settings_opened_before_the_voices_load_has_nothing_to_save(c, monkeypatch):
    dialog = open_settings(c, monkeypatch, [Voice("sapi:one", "One")])
    assert dialog.voice.currentData() == "sapi:one"  # the saved voice is not listed yet
    assert not dialog.unsaved_changes()
    assert "tts_voice_id" not in dialog._read_fields()


def test_the_saved_voice_is_selected_once_it_loads(c, monkeypatch):
    dialog = open_settings(c, monkeypatch, [Voice("sapi:one", "One")])
    voices = [Voice("sapi:one", "One"), Voice("piper:later", "Later")]
    monkeypatch.setattr(dialog.ctx, "voices", lambda: voices, raising=False)
    dialog.refresh_voices()
    assert dialog.voice.currentData() == "piper:later"
    assert not dialog.unsaved_changes()


def test_a_voice_the_user_picks_still_counts(c, monkeypatch):
    dialog = open_settings(c, monkeypatch, [Voice("sapi:one", "One"), Voice("sapi:two", "Two")], saved="sapi:one")
    dialog.voice.setCurrentIndex(1)
    assert dialog._read_fields()["tts_voice_id"] == "sapi:two"
    dialog.refresh_voices()  # a refresh keeps the pick
    assert dialog._read_fields()["tts_voice_id"] == "sapi:two"
    assert dialog._save()
    assert not dialog.unsaved_changes()


# --- a first model download can be cancelled ----------------------------------------------------------
def fake_hub(monkeypatch, started, release):
    import huggingface_hub

    def snapshot(repo, revision=None, allow_patterns=None, local_files_only=False, tqdm_class=None):
        if local_files_only:
            raise OSError("not downloaded yet")
        started.set()
        release.wait(20)
        return "C:/hub/model"

    monkeypatch.setattr(huggingface_hub, "snapshot_download", snapshot)


def test_cancel_returns_from_a_download_at_once(monkeypatch):
    started, release, cancel = threading.Event(), threading.Event(), threading.Event()
    fake_hub(monkeypatch, started, release)
    outcome = {}

    def run():
        try:
            outcome["path"] = service.download_whisper("tiny", None, cancel)
        except service.DownloadCancelled:
            outcome["cancelled"] = time.perf_counter()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert started.wait(5)
    t0 = time.perf_counter()
    cancel.set()
    thread.join(5)
    release.set()
    assert outcome.get("cancelled") and outcome["cancelled"] - t0 < 0.5


def test_a_cancelled_download_stops_at_the_next_progress_step():
    cancel = threading.Event()
    bars = []
    progress = service._progress_class(bars, cancel)
    bar = progress(total=100, unit="B")
    bar.update(10)
    cancel.set()
    with pytest.raises(service.DownloadCancelled):
        bar.update(10)


def test_a_download_that_fails_by_itself_still_reports_its_error(monkeypatch):
    import huggingface_hub

    def snapshot(repo, revision=None, allow_patterns=None, local_files_only=False, tqdm_class=None):
        raise OSError("no network")

    monkeypatch.setattr(huggingface_hub, "snapshot_download", snapshot)
    with pytest.raises(OSError, match="no network"):
        service.download_whisper("tiny", None, threading.Event())


def blocking_service(monkeypatch):
    """A service whose first model fetch hangs until it is cancelled, as a slow download does."""
    from test_live_captions import make

    svc, _model, events = make()

    def fetch(name, progress, cancel):
        progress(1, 75, 1)
        while not cancel.wait(0.02):
            pass
        raise service.DownloadCancelled

    svc.cache._model = None
    svc.cache._name = None
    svc.cache._downloader = fetch
    return svc, events


def test_cancel_after_stop_ends_a_dictation_stuck_on_the_download(monkeypatch):
    from test_live_captions import of, wait_for

    svc, events = blocking_service(monkeypatch)
    try:
        svc.start("editor")
        assert wait_for(lambda: svc.downloading, timeout=5)
        time.sleep(0.3)
        svc.stop()
        assert svc.state is SttState.TRANSCRIBING
        t0 = time.perf_counter()
        svc.cancel()
        assert wait_for(lambda: svc.state is SttState.IDLE, timeout=5)
        assert time.perf_counter() - t0 < 1
        assert of(events, "transcript_ready") == []
        assert of(events, "error") == []
        assert not any("failed" in str(e).lower() for e in of(events, "model_status"))
    finally:
        svc.shutdown()


def test_dictation_works_again_after_a_cancelled_download(monkeypatch):
    from test_live_captions import of, wait_for

    svc, events = blocking_service(monkeypatch)
    try:
        svc.start("editor")
        assert wait_for(lambda: svc.downloading, timeout=5)
        svc.cancel()
        assert svc.state is SttState.IDLE
        assert wait_for(lambda: not svc.downloading, timeout=5)
        svc.cache._downloader = lambda name, progress, cancel: "C:/hub/model"
        svc.start("editor")
        time.sleep(0.4)
        svc.stop()
        assert wait_for(lambda: svc.state is SttState.IDLE, timeout=5)
        assert of(events, "transcript_ready")
    finally:
        svc.shutdown()


def test_the_listen_panel_offers_cancel_only_during_a_download(c):
    button = c.window.listen_panel.cancel
    assert button.isHidden()
    c._on_model_status("Downloading the small model... 12 of 480 MB (first use only)")
    assert not button.isHidden()
    called = []
    c.stt.cancel = lambda: called.append(True)
    button.click()
    assert called == [True]
    c._on_model_status("small model ready")
    assert button.isHidden()


# --- a slow app gets the dictated text, not the old clipboard ------------------------------------
class ReadableClipboard:
    """Qt's clipboard hands the injector's data object to whoever pastes."""

    def __init__(self):
        self.data = None

    def mimeData(self):
        return self.data

    def setMimeData(self, data):
        self.data = data

    def text(self):
        return self.data.text() if self.data is not None and self.data.hasText() else ""


def injector_with_a_reader(qtbot, monkeypatch, read_after_ms):
    clip = ReadableClipboard()
    old = inject.QMimeData()
    old.setText("OLD")
    clip.data = old
    monkeypatch.setattr(inject.TextInjector, "clipboard", property(lambda self: clip))
    monkeypatch.setattr(winapi, "foreground_window", lambda: 1)
    monkeypatch.setattr(winapi, "window_needs_admin", lambda hwnd: False)
    monkeypatch.setattr(winapi, "modifiers_down", lambda: False)
    monkeypatch.setattr(winapi, "send_paste", lambda keystroke: True)
    monkeypatch.setattr(winapi, "clipboard_sequence", lambda: 7)
    injector = inject.TextInjector()
    pasted = {}
    if read_after_ms is not None:
        from PySide6.QtCore import QTimer

        QTimer.singleShot(read_after_ms, lambda: pasted.setdefault("text", clip.text()))
    return injector, clip, pasted


@pytest.mark.skipif(not inject.IS_WINDOWS, reason="the Windows paste path")
def test_an_app_that_reads_the_clipboard_late_gets_the_dictated_text(qtbot, monkeypatch):
    injector, clip, pasted = injector_with_a_reader(qtbot, monkeypatch, 1000)
    with qtbot.waitSignal(injector.finished, timeout=5000) as signal:
        injector.inject("DICTATED", 1)
    assert pasted["text"] == "DICTATED"
    assert clip.text() == "OLD"  # and only then the old clipboard comes back
    assert signal.args == [True, ""]


@pytest.mark.skipif(not inject.IS_WINDOWS, reason="the Windows paste path")
def test_a_blocked_paste_says_so_right_away(qtbot, monkeypatch):
    injector, clip, _pasted = injector_with_a_reader(qtbot, monkeypatch, None)
    monkeypatch.setattr(winapi, "send_paste", lambda keystroke: False)
    t0 = time.perf_counter()
    with qtbot.waitSignal(injector.finished, timeout=5000) as signal:
        injector.inject("DICTATED", 1)
    assert time.perf_counter() - t0 < 0.3
    assert signal.args[0] is False
    assert clip.text() == "DICTATED"  # kept, or it would be lost
