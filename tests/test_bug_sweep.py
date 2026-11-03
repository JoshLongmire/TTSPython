"""Regression tests for the second audit's correctness findings (one per bug)."""
import os
import time
import wave

import numpy as np
import pytest
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QAbstractItemView, QMessageBox

from fakes import FakeRenderer
from test_selection import FakeWin, grab
from test_ui import make_controller
from ttspython.core.platform import IS_WINDOWS
from ttspython.core.tts.controller import State

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --- E1: a half-downloaded Whisper model -------------------------------------------------------
def _fake_hub(monkeypatch, folder):
    import huggingface_hub

    calls = []

    def snapshot(repo, allow_patterns=None, local_files_only=False, tqdm_class=None):
        calls.append(local_files_only)
        if not local_files_only:  # the online call finishes the download
            (folder / "model.bin").write_bytes(b"weights")
        return str(folder)

    monkeypatch.setattr(huggingface_hub, "snapshot_download", snapshot)
    return calls


def test_interrupted_model_download_is_resumed(tmp_path, monkeypatch):
    from ttspython.core.stt import service

    folder = tmp_path / "snap"
    folder.mkdir()
    (folder / "config.json").write_text("{}")
    (folder / "tokenizer.json").write_text("{}")  # model.bin never arrived
    calls = _fake_hub(monkeypatch, folder)
    assert service.download_whisper("small") == str(folder)
    assert calls == [True, False]  # the local copy was not trusted
    assert (folder / "model.bin").exists()


def test_complete_model_is_used_offline(tmp_path, monkeypatch):
    from ttspython.core.stt import service

    folder = tmp_path / "snap"
    folder.mkdir()
    for name in ("config.json", "tokenizer.json", "model.bin"):
        (folder / name).write_text("x")
    calls = _fake_hub(monkeypatch, folder)
    assert service.download_whisper("small") == str(folder)
    assert calls == [True]


def test_model_folder_on_disk_is_loaded_directly(tmp_path, monkeypatch):
    from ttspython.core.stt import service

    calls = _fake_hub(monkeypatch, tmp_path)
    assert service.download_whisper(str(tmp_path)) == str(tmp_path)
    assert calls == []


# --- E2: microphones that only run at their own rate -------------------------------------------
class FussyInputSD:
    """A WASAPI-like mic: refuses 16 kHz, runs at 48 kHz."""

    def __init__(self):
        self.opened = []

    def InputStream(self, samplerate, channels, dtype, blocksize, device, callback):  # noqa: N802
        if samplerate != 48000:
            raise RuntimeError("Invalid sample rate")
        self.opened.append(samplerate)
        self.callback = callback

        class Stream:
            def start(self):
                pass

            def stop(self):
                pass

            def close(self):
                pass

        return Stream()

    def query_devices(self, device=None, kind=None):
        return {"default_samplerate": 48000.0}


def test_recording_works_on_a_mic_that_rejects_16khz():
    from ttspython.core.stt.recorder import Recorder

    sd = FussyInputSD()
    rec = Recorder(sd_module=sd)
    rec.start(device=3)
    assert sd.opened == [48000]
    block = (np.sin(np.arange(4800) / 10.0) * 10000).astype(np.int16).reshape(-1, 1)
    for _ in range(10):  # one second at 48 kHz
        sd.callback(block, block.shape[0], None, None)
    assert abs(rec.snapshot().size - 16000) <= 2
    assert abs(rec.snapshot(8000).size - 8000) <= 2
    audio = rec.stop()
    assert abs(audio.size - 16000) <= 2  # handed to Whisper at 16 kHz
    assert audio.dtype == np.float32 and float(np.abs(audio).max()) <= 1.0


# --- E3: Settings Test, then Save --------------------------------------------------------------
def test_save_after_test_puts_speech_back_on_the_saved_device(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path)
    try:
        a, b = {"name": "Speakers A", "hostapi": "", "index": 1}, {"name": "Headset B", "hostapi": "", "index": 2}
        c.settings.set("tts_output_device", a)
        c.resolve_device = lambda ref, kind: ref["index"] if ref else None
        c.open_settings()
        dlg = c._settings_dialog
        form = dlg.form_values()
        dlg.form_values = lambda: dict(form, tts_output_device=b)  # B picked, then Test
        c._settings_action("test_voice")
        assert c.speech.player.device == 2
        c.speech.stop()
        c.apply_settings({})  # back on A in the form, Save with nothing else changed
        assert c.speech.player.device == 1
    finally:
        c.quit()


# --- E4: a shared temp folder owned by someone else -------------------------------------------
def test_style_assets_fall_back_when_the_shared_folder_is_not_writable(tmp_path, monkeypatch):
    import tempfile

    from ttspython.ui import theme_manager

    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    user = f"-{os.getuid()}" if hasattr(os, "getuid") else ""
    (tmp_path / f"ttspython-ui{user}").write_text("not a folder (as good as another user's)")
    path = theme_manager._asset_dir()
    assert os.path.isdir(path) and os.access(path, os.W_OK)


# --- E5: a saved voice that was uninstalled -----------------------------------------------------
def test_uninstalled_voice_is_replaced_by_the_voice_in_use(qtbot, tmp_path):
    from ttspython.core.settings import defaults

    c = make_controller(qtbot, tmp_path, dict(defaults(), tts_voice_id="v-uninstalled"))
    try:
        assert c.speech.voice_id in ("v-david", "v-zira")
        assert c.settings["tts_voice_id"] == c.speech.voice_id
        c.open_settings()
        assert c._settings_dialog.voice.currentData() == c.speech.voice_id
        assert "tts_voice_id" not in c._settings_dialog._read_fields()
    finally:
        c.quit()


# --- E6: recording a new global hotkey --------------------------------------------------------
def test_global_hotkeys_pause_while_a_shortcut_box_is_focused(qtbot, tmp_path):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QFocusEvent

    c = make_controller(qtbot, tmp_path)
    try:
        c.open_settings("shortcuts")
        dlg = c._settings_dialog
        edit = next(iter(dlg.global_edits.values()))[0]
        dlg.eventFilter(edit, QFocusEvent(QEvent.FocusIn))
        assert c.fake_hotkeys.bindings == ({}, False)
        dlg.eventFilter(edit, QFocusEvent(QEvent.FocusOut))
        assert c.fake_hotkeys.bindings[1] is True and c.fake_hotkeys.bindings[0]
        dlg.eventFilter(edit, QFocusEvent(QEvent.FocusIn))
        dlg.reject()  # closing while recording also puts them back
        assert c.fake_hotkeys.bindings[1] is True
    finally:
        c.quit()


# --- E7: the speech engine fails before the window listens ------------------------------------
def test_engine_start_failure_reaches_the_window(qtbot):
    from ttspython.core.queue_model import SpeechQueue
    from ttspython.core.tts.controller import SpeechController
    from ttspython.ui.bridge import SpeechBridge

    def broken():
        raise OSError("espeak-ng is not installed")

    ctl = SpeechController(SpeechQueue(), renderer_factory=broken)
    try:
        assert ctl.wait_ready(5)
        time.sleep(0.1)  # the error was emitted before anything subscribed
        bridge = SpeechBridge(ctl)
        got = []
        bridge.error.connect(got.append)  # connected after the bridge, like the controller does
        qtbot.waitUntil(lambda: bool(got), timeout=2000)
        assert "espeak-ng is not installed" in got[0]
    finally:
        ctl.shutdown()


# --- E8: large-v3-turbo needs faster-whisper 1.1 -------------------------------------------------
def test_requirements_allow_every_offered_model():
    with open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8") as f:
        assert "faster-whisper>=1.1.0" in f.read()


# --- E9: devices plugged in later --------------------------------------------------------------
def test_devices_rescan_only_while_audio_is_idle(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path)
    try:
        assert c.rescan_devices() is True
        c.editor.setPlainText("Some words to read for a little while.")
        c.on_speak_all()
        qtbot.waitUntil(lambda: c.speech.busy, timeout=2000)
        assert c.rescan_devices() is False  # never under an open stream
        c.on_stop()
    finally:
        c.quit()


# --- E10: replaying the queue while it plays ---------------------------------------------------
def test_restarting_the_queue_does_not_say_stopped(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path)
    try:
        ids = [c.queue.add(f"Queue item {i} with a few words.", f"Item {i}").id for i in range(2)]
        said = []
        c._status = said.append
        c.queue_play(ids[0])
        qtbot.waitUntil(lambda: c.speech.state is State.PLAYING, timeout=3000)
        said.clear()
        c.queue_play(ids[1])
        qtbot.waitUntil(lambda: c.speech.state is State.PLAYING, timeout=3000)
        qtbot.wait(100)
        assert "Queue stopped" not in said
        c.on_stop()
    finally:
        c.quit()


# --- E11 / E12: pasting dictation --------------------------------------------------------------
@pytest.mark.skipif(not IS_WINDOWS, reason="Windows paste path")
def test_paste_is_not_sent_while_keys_are_still_held(qtbot, monkeypatch):
    from ttspython.platform import inject, winapi

    sent = []
    monkeypatch.setattr(winapi, "foreground_window", lambda: 42)
    monkeypatch.setattr(winapi, "modifiers_down", lambda: True)
    monkeypatch.setattr(winapi, "send_paste", lambda keys: sent.append(keys) or 4)
    monkeypatch.setattr(inject, "MODIFIER_WAIT_MS", 100)
    injector = inject.TextInjector()
    with qtbot.waitSignal(injector.finished, timeout=3000) as sig:
        injector.inject("dictated words", 42)
    assert sent == []
    assert sig.args[0] is False and "held" in sig.args[1]
    assert QGuiApplication.clipboard().text() == "dictated words"


def test_wayland_paste_uses_the_chosen_keystroke():
    from ttspython.platform.inject import wtype_command

    assert wtype_command("wtype", "ctrl+v") == ["wtype", "-M", "ctrl", "v", "-m", "ctrl"]
    assert wtype_command("wtype", "shift+insert") == ["wtype", "-M", "shift", "-k", "Insert", "-m", "shift"]


# --- E13: an app that copies late ---------------------------------------------------------------
class LateWin(FakeWin):
    def send_copy(self):
        from PySide6.QtCore import QTimer

        self.copies += 1

        def arrive():
            QGuiApplication.clipboard().setText("selection that arrived late")
            self.seq += 1

        QTimer.singleShot(700, arrive)
        return 4


def test_a_late_copy_does_not_keep_the_selection_on_the_clipboard(qtbot):
    from ttspython.platform.selection import SelectionGrabber

    QGuiApplication.clipboard().setText("What was on the clipboard.")
    win = LateWin()
    assert grab(qtbot, SelectionGrabber(uia=lambda: None, win=win)) is None
    qtbot.waitUntil(lambda: win.seq == 2, timeout=3000)  # the copy arrived after we gave up
    qtbot.waitUntil(lambda: QGuiApplication.clipboard().text() == "What was on the clipboard.", timeout=3000)


# --- E14: export renders and writes chunk by chunk ----------------------------------------------
def test_export_streams_every_chunk_to_the_file(tmp_path):
    from ttspython.core.tts.export import AudioExporter

    text = " ".join(f"Sentence number {i} is here." for i in range(40))
    exporter = AudioExporter(renderer_factory=lambda: FakeRenderer(0.05))
    done = []
    exporter.events.on("finished", done.append)
    path = str(tmp_path / "out.wav")
    assert exporter.start(text, path, "", 200, 0.5)
    exporter.join(20)
    assert done == [path] and not os.path.exists(path + ".part")
    with wave.open(path) as w:
        assert w.getframerate() == 22050 and w.getnframes() > 22050 * 0.05


def test_cancelled_export_leaves_nothing(tmp_path):
    from ttspython.core.tts.export import AudioExporter

    exporter = AudioExporter(renderer_factory=lambda: FakeRenderer(0.05, render_delay=0.05))
    cancelled = []
    exporter.events.on("cancelled", lambda: cancelled.append(1))
    path = str(tmp_path / "out.wav")
    exporter.start(" ".join(f"Sentence {i}." for i in range(200)), path, "", 200, 1.0)
    time.sleep(0.2)
    exporter.cancel()
    exporter.join(10)
    assert cancelled and not os.path.exists(path) and not os.path.exists(path + ".part")


# --- E15: the queue list after a drag -----------------------------------------------------------
def test_queue_list_shows_the_newest_items_after_a_drag(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path)
    try:
        panel = c.window.queue_panel
        panel.list.state = lambda: QAbstractItemView.DraggingState
        c.queue.add("First item text.", "First")
        c.queue.add("Second item text.", "Second")  # two updates while dragging
        del panel.list.state
        qtbot.waitUntil(lambda: panel.list.count() == 2, timeout=2000)
        assert panel.badge.text() == "2"
    finally:
        c.quit()


# --- E16: export failure while working in another app --------------------------------------------
def test_export_failure_does_not_open_a_dialog_over_other_apps(qtbot, tmp_path, monkeypatch):
    c = make_controller(qtbot, tmp_path)
    try:
        boxes, toasts = [], []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: boxes.append(a))
        c._toast = lambda text, ms=0: toasts.append(text)
        c.show_mini()
        c._on_export_failed("disk full")
        assert boxes == [] and toasts and "disk full" in toasts[0]
    finally:
        c.quit()


# --- cleanup: unreadable settings copies do not pile up -----------------------------------------
def test_only_the_newest_broken_settings_copies_are_kept(tmp_path):
    from ttspython.core import settings

    for day in range(1, 6):
        (tmp_path / f"settings.broken.2026010{day}_120000.json").write_text("{")
    path = tmp_path / "settings.json"
    path.write_text("{ not json")
    _data, info = settings.load(str(path), legacy="")
    kept = sorted(p.name for p in tmp_path.glob("settings.broken.*.json"))
    assert len(kept) == settings.KEEP_BROKEN_COPIES
    assert os.path.basename(info["broken_copy"]) in kept
    assert "settings.broken.20260101_120000.json" not in kept


# --- cleanup: downloaded Whisper models can be deleted from Settings ---------------------------------
class _Rev:
    def __init__(self, commit):
        self.commit_hash = commit


class _Repo:
    def __init__(self, repo_id, size):
        self.repo_id, self.size_on_disk, self.revisions = repo_id, size, [_Rev(repo_id + "@1")]


class _Cache:
    def __init__(self, repos):
        self.repos, self.deleted = repos, []

    def delete_revisions(self, *hashes):
        cache = self

        class Strategy:
            expected_freed_size = sum(r.size_on_disk for r in cache.repos if r.revisions[0].commit_hash in hashes)

            def execute(self):
                cache.deleted.extend(hashes)
                cache.repos = [r for r in cache.repos if r.revisions[0].commit_hash not in hashes]

        return Strategy()


def test_downloaded_models_are_listed_and_deleted(qtbot, tmp_path, monkeypatch):
    from ttspython.core.stt import service

    cache = _Cache([_Repo("Systran/faster-whisper-small", 484_000_000), _Repo("someone/other-model", 5),
                    _Repo("mobiuslabsgmbh/faster-whisper-large-v3-turbo", 1_620_000_000)])
    assert service.downloaded_models(lambda: cache) == [("large-v3-turbo", 1_620_000_000), ("small", 484_000_000)]
    monkeypatch.setattr(service, "downloaded_models", lambda scan=None: service.__dict__["_listed"](cache))
    service._listed = lambda c: sorted((n, r.size_on_disk) for r in c.repos
                                       for n, repo in service.WHISPER_REPOS.items() if repo == r.repo_id)
    real_delete = service.delete_model
    monkeypatch.setattr(service, "delete_model", lambda name, scan=None: real_delete(name, lambda: cache))
    c = make_controller(qtbot, tmp_path)
    try:
        c.open_settings("speech")  # not the Listen page: its level meter would open the real microphone
        dlg = c._settings_dialog
        dlg.refresh_models()
        assert dlg.models_box.count() == 2
        assert c.delete_model("small") == ""
        assert cache.deleted == ["Systran/faster-whisper-small@1"]
        assert [r.repo_id for r in cache.repos] == ["someone/other-model", "mobiuslabsgmbh/faster-whisper-large-v3-turbo"]
        c.stt.start("editor")
        assert "Finish dictating" in c.delete_model("large-v3-turbo")  # never under a running dictation
        c.stt.stop()
    finally:
        del service._listed
        c.quit()


# --- performance: the level waveform rests while silent or hidden ----------------------------------
def test_waveform_does_not_repaint_while_silent_or_hidden(qtbot):
    from ttspython.ui.widgets import Waveform

    paints = []

    class Counting(Waveform):
        def paintEvent(self, event):  # noqa: N802
            paints.append(1)
            super().paintEvent(event)

    wave = Counting(bars=20)
    qtbot.addWidget(wave)
    wave.show()
    qtbot.waitExposed(wave)
    level = [0.0]
    wave.set_source(lambda: level[0])
    qtbot.wait(300)
    paints.clear()
    qtbot.wait(1000)  # a silent second (paused speech)
    assert len(paints) <= 2
    level[0] = 0.4
    qtbot.waitUntil(lambda: len(paints) > 5, timeout=2000)  # sound: it animates again
    wave.hide()
    assert not wave._timer.isActive()
    wave.show()
    assert wave._timer.isActive()
