import json
import queue as queue_mod

import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QTextCursor
from PySide6.QtWidgets import QApplication, QMessageBox

from fakes import FakeRenderer, FakeSD, FakeSelection
from test_stt_service import FakeModel, FakeRecorder, FakeTimer
from ttspython.core import textio
from ttspython.core.queue_model import SpeechQueue
from ttspython.core.settings import SettingsStore
from ttspython.core.stt.service import ModelCache, SttService, SttState
from ttspython.core.tts.controller import SpeechController, State
from ttspython.core.tts.export import AudioExporter
from ttspython.core.tts.player import AudioPlayer
from ttspython.ui.app_controller import AppController
from ttspython.ui.editor import FindBar
from ttspython.ui.settings_dialog import SettingsDialog

LONG = " ".join(f"Sentence number {i} is here." for i in range(60))


class FakeHotkeys(QObject):
    triggered = Signal(str)

    def __init__(self):
        super().__init__()
        self.bindings = None

    def set_bindings(self, bindings, enabled=True):
        self.bindings = (dict(bindings), enabled)
        return {}

    def stop(self):
        pass


def make_controller(qtbot, tmp_path, settings_data=None, seconds=0.4):
    path = tmp_path / "settings.json"
    if settings_data is not None:
        path.write_text(json.dumps(settings_data), encoding="utf-8")
    store = SettingsStore(str(path), legacy="")
    sd = FakeSD(speed=40)
    player = AudioPlayer(queue_mod.Queue(), sd_module=sd)
    renderers = []

    def factory():
        r = FakeRenderer(seconds)
        renderers.append(r)
        return r

    speech = SpeechController(SpeechQueue(), renderer_factory=factory, player=player)
    calls = []
    stt = SttService(recorder=FakeRecorder(), cache=ModelCache(lambda name: FakeModel(name, calls)),
                     timer_factory=FakeTimer)
    exporter = AudioExporter(renderer_factory=lambda: FakeRenderer(0.05))
    hot = FakeHotkeys()
    ctl = AppController(QApplication.instance(), store, services={
        "speech": speech, "stt": stt, "exporter": exporter, "hotkeys": hot, "tray": False, "devices": [],
        "selection": FakeSelection(),  # never reads or sends keys to the real desktop
    })
    ctl.sd, ctl.renderers, ctl.fake_hotkeys = sd, renderers, hot
    # The window asks before discarding unsaved text; the test harness closes it at teardown.
    qtbot.addWidget(ctl.window, before_close_func=lambda _w: ctl.editor.document().setModified(False))
    ctl.window.show()
    qtbot.waitExposed(ctl.window)
    assert speech.wait_ready(5)
    qtbot.waitUntil(lambda: len(ctl.voices()) == 2, timeout=3000)
    return ctl


@pytest.fixture
def ctl(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path)
    yield c
    c.quit()


def activate(qtbot, ctl):
    ctl.window.activateWindow()
    ctl.editor.setFocus()
    qtbot.wait(30)


# --- feature parity -----------------------------------------------------------------
V4_COMMANDS = ["speak_all", "speak_selected", "stop", "paste", "clear", "open", "save", "save_as", "export",
               "find", "settings", "refresh_voices", "queue_add_text", "queue_add_files",
               "queue_play", "queue_remove", "queue_clear", "queue_up", "queue_down", "queue_loop",
               "toggle_mode", "record"]


def test_every_v4_command_has_an_action(ctl):
    for key in V4_COMMANDS:
        assert key in ctl.actions, key


def test_every_v4_control_exists(ctl):
    w = ctl.window
    t = w.transport
    # Speed is shown in percent now (200 wpm = 100%); it still covers v4's 100 to 250 wpm.
    assert t.rate.minimum() * 2 <= 100 and t.rate.maximum() * 2 >= 250
    assert t.volume.minimum() == 10 and t.volume.maximum() == 100
    assert len(ctl.voices()) == 2  # picked in Settings and the mini bar (no longer in the control bar)
    assert w.clip_switch and w.clip_mode.value() in ("speak", "queue") and w.auto_queue and w.perf_switch
    fb = w.find_bar
    assert fb.case_btn.isCheckable() and fb.regex_btn.isCheckable()
    assert fb.replace_btn and fb.replace_all_btn and fb.prev_btn and fb.next_btn
    assert w.mode_switch.button("tts") and w.mode_switch.button("stt")
    assert w.status_label is not None
    for key in ("speak_all", "speak_selected", "stop", "open", "save", "save_as", "paste", "clear", "find", "export"):
        assert not ctl.actions[key].shortcut().isEmpty(), key


def test_settings_dialog_has_every_v4_setting(ctl, qtbot):
    dlg = SettingsDialog(ctl, ctl.window)
    qtbot.addWidget(dlg)
    assert len(dlg.theme_cards) == 12
    assert dlg.performance and dlg.input and dlg.output and dlg.unload_idle and dlg.auto_unload
    assert dlg.auto_unload_minutes.minimum() == 1 and dlg.auto_unload_minutes.maximum() == 60
    assert set(dlg.shortcut_edits) >= {"speak_all", "speak_selected", "stop", "open", "save", "save_as",
                                       "paste", "clear", "find", "export"}
    dlg.close()


# --- bugs ----------------------------------------------------------------------------
def test_bug06a_rebind_replaces_old_key(ctl, qtbot):
    values = dict(ctl.settings.data)
    values["shortcuts"] = dict(values["shortcuts"], clear="Ctrl+K")
    ctl.apply_settings(values)
    activate(qtbot, ctl)
    ctl.editor.setPlainText("keep me")
    qtbot.keyClick(ctl.editor, Qt.Key_L, Qt.ControlModifier)
    assert ctl.editor.toPlainText() == "keep me"
    qtbot.keyClick(ctl.editor, Qt.Key_K, Qt.ControlModifier)
    assert ctl.editor.toPlainText() == ""


def test_bug06b_missing_or_blank_shortcuts_do_not_crash(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path, {"shortcuts": {"stop": "", "open": "garbage<<"}})
    try:
        assert c.actions["stop"].shortcut().isEmpty()
        assert c.actions["open"].shortcut() == QKeySequence("Ctrl+O")
        assert c.actions["save"].shortcut() == QKeySequence("Ctrl+S")
    finally:
        c.quit()


def test_bug06c_ctrl_v_pastes_once(ctl, qtbot):
    QGuiApplication.clipboard().setText("hello")
    activate(qtbot, ctl)
    ctl.editor.clear()
    qtbot.keyClick(ctl.editor, Qt.Key_V, Qt.ControlModifier)
    assert ctl.editor.toPlainText() == "hello"


def test_bug14_find_is_a_single_inline_bar(ctl):
    ctl.on_find()
    ctl.on_find()
    assert len(ctl.window.findChildren(FindBar)) == 1
    assert ctl.window.find_bar.isVisible()


def test_bug08_regex_find_selects_whole_match(ctl):
    ctl.editor.setPlainText("caaat")
    bar = ctl.window.find_bar
    bar.open_bar()
    bar.regex_btn.setChecked(True)
    bar.find_edit.setText("a+")
    bar.find()
    assert ctl.editor.textCursor().selectedText() == "aaa"


def test_bug08b_find_honours_the_case_option(ctl):
    ctl.editor.setPlainText("say hello")
    bar = ctl.window.find_bar
    bar.find_edit.setText("HELLO")
    assert bar.find()
    assert ctl.editor.textCursor().selectedText() == "hello"
    bar.case_btn.setChecked(True)
    ctl.editor.moveCursor(QTextCursor.Start)
    assert not bar.find()


def test_bug16_literal_replace_all_keeps_backslashes(ctl):
    ctl.editor.setPlainText("save to old and OLD")
    bar = ctl.window.find_bar
    bar.open_bar()
    bar.find_edit.setText("old")
    bar.replace_edit.setText(r"C:\new\1")
    assert bar.replace_all() == 2
    assert ctl.editor.toPlainText() == r"save to C:\new\1 and C:\new\1"


def test_bug18_replace_all_and_clear_are_one_undo_step(ctl):
    ctl.editor.setPlainText("one two one")
    bar = ctl.window.find_bar
    bar.find_edit.setText("one")
    bar.replace_edit.setText("1")
    bar.replace_all()
    assert ctl.editor.toPlainText() == "1 two 1"
    ctl.editor.undo()
    assert ctl.editor.toPlainText() == "one two one"
    ctl.on_clear()
    assert ctl.editor.toPlainText() == ""
    ctl.editor.undo()
    assert ctl.editor.toPlainText() == "one two one"


def test_bug05_bug21_selection_highlight_offsets_with_emoji(ctl, qtbot):
    intro = "\U0001F600 Intro words here. "
    ctl.editor.setPlainText(intro + "Selected sentence one. Selected sentence two.")
    cursor = ctl.editor.textCursor()
    start16 = len(intro.encode("utf-16-le")) // 2
    cursor.setPosition(start16)
    cursor.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
    ctl.editor.setTextCursor(cursor)
    seen = []
    ctl.speech_bridge.chunk_started.connect(
        lambda *a: seen.append([s.cursor.selectedText() for s in ctl.editor.extraSelections()]))
    ctl.on_speak_selected()
    qtbot.waitUntil(lambda: len(seen) >= 2, timeout=3000)
    assert seen[0] == ["Selected sentence one."]
    assert seen[1] == ["Selected sentence two."]
    ctl.on_stop()


def test_bug07_record_button_matches_state(ctl, qtbot):
    ctl.set_mode("stt")
    rec = ctl.actions["record"]
    assert rec.text() == "Start dictation" and rec.isEnabled()
    rec.trigger()
    qtbot.waitUntil(lambda: rec.text() == "Stop dictation", timeout=2000)
    rec.trigger()
    qtbot.waitUntil(lambda: ctl.stt.state is SttState.IDLE and rec.isEnabled(), timeout=3000)
    assert rec.text() == "Start dictation"
    qtbot.waitUntil(lambda: "Hello world." in ctl.editor.toPlainText(), timeout=2000)


def test_bug04_clipboard_monitor_toggle_has_one_listener(ctl, qtbot):
    ctl.window.clip_mode.set_value("queue")
    ctl._set_clip_action("queue")
    for _ in range(10):
        ctl.window.clip_switch.setChecked(True)
        ctl.window.clip_switch.setChecked(False)
    ctl.window.clip_switch.setChecked(True)
    QGuiApplication.clipboard().setText("copied text number one")
    qtbot.waitUntil(lambda: len(ctl.queue) >= 1, timeout=2000)
    qtbot.wait(100)
    assert len(ctl.queue) == 1


def test_bug03_clipboard_speak_never_overlaps(ctl, qtbot):
    ctl.window.clip_switch.setChecked(True)
    ctl.editor.setPlainText(LONG)
    ctl.on_speak_all()
    qtbot.waitUntil(lambda: ctl.speech.state is State.PLAYING, timeout=3000)
    QGuiApplication.clipboard().setText("first copied sentence")
    QGuiApplication.clipboard().setText("second copied sentence")
    qtbot.wait(150)
    ctl.on_stop()
    assert ctl.renderers[-1].max_active == 1
    assert ctl.sd.max_open == 1


def test_bug15_close_while_speaking_stops_threads(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path)
    c.editor.setPlainText(LONG)
    c.on_speak_all()
    qtbot.waitUntil(lambda: c.speech.state is State.PLAYING, timeout=3000)
    c.quit()
    assert c.speech.state is State.IDLE
    assert not c.speech._synth.is_alive()


def test_bug19_voice_rate_volume_persist(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path)
    t = c.window.transport
    t.rate.setValue(111)  # percent: 222 words per minute
    t.volume.setValue(40)
    c._set_voice("v-david")
    c.save_now()
    c.quit()
    saved = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert (saved["tts_rate"], saved["tts_volume"], saved["tts_voice_id"]) == (222, 0.4, "v-david")
    again = make_controller(qtbot, tmp_path)
    try:
        assert again.speech.rate == 222 and again.speech.voice_id == "v-david"
        assert again.window.transport.volume.value() == 40
    finally:
        again.quit()


def test_bug10_output_device_reaches_the_player(ctl):
    ctl._on_devices_resolved({"out_index": 3, "in_index": 1, "out_ref": None, "in_ref": None})
    assert ctl.speech.player.device == 3
    assert ctl.stt.input_device == 1


def test_bug17_save_keeps_file_bytes(ctl, tmp_path):
    path = tmp_path / "doc.txt"
    raw = b"first line\r\nsecond line\r\n"
    path.write_bytes(raw)
    doc = textio.read_text_file(str(path))
    ctl.editor.setPlainText(doc.text)
    ctl.current_file, ctl.current_doc = str(path), doc
    ctl.on_save()
    ctl.on_save()
    assert path.read_bytes() == raw


def test_bug09_export_mp3_from_ui(ctl, qtbot, tmp_path, monkeypatch):
    out = str(tmp_path / "speech.mp3")
    monkeypatch.setattr(ctl, "_save_dialog", lambda *a, **k: (out, "mp3"))
    ctl.editor.setPlainText("Export this text please.")
    ctl.on_export()
    qtbot.waitUntil(lambda: ctl.actions["export"].isEnabled(), timeout=5000)
    data = open(out, "rb").read()
    assert data[:4] != b"RIFF" and (data[:3] == b"ID3" or data[0] == 0xFF)


# --- behaviour ------------------------------------------------------------------------
def test_play_pause_resume_cycle(ctl, qtbot):
    ctl.editor.setPlainText(LONG)
    ctl.actions["play_pause"].trigger()
    qtbot.waitUntil(lambda: ctl.speech.state is State.PLAYING, timeout=3000)
    assert ctl.actions["play_pause"].text() == "Pause"
    ctl.actions["play_pause"].trigger()
    assert ctl.speech.state is State.PAUSED
    assert ctl.actions["play_pause"].text() == "Resume"
    ctl.actions["play_pause"].trigger()
    assert ctl.speech.state is State.PLAYING
    ctl.on_stop()
    qtbot.waitUntil(lambda: ctl.actions["play_pause"].text() == "Play", timeout=2000)


def test_listen_mode_disables_speak_buttons(ctl):
    ctl.set_mode("stt")
    assert not ctl.actions["speak_all"].isEnabled()
    assert not ctl.actions["speak_selected"].isEnabled()
    assert ctl.window.listen_panel.isVisible()
    ctl.set_mode("tts")
    assert ctl.actions["speak_all"].isEnabled()
    assert not ctl.window.listen_panel.isVisible()


def test_queue_controls(ctl, qtbot, monkeypatch):
    ctl.editor.setPlainText("Queue item text one.")
    ctl.queue_add_text()
    ctl.editor.setPlainText("Queue item text two.")
    ctl.queue_add_text()
    panel = ctl.window.queue_panel
    assert panel.list.count() == 2
    panel.list.setCurrentRow(1)
    panel.list.item(1).setSelected(True)
    ctl.queue_move(-1)
    assert ctl.queue.snapshot()[0].text == "Queue item text two."
    ctl.queue_play()
    qtbot.waitUntil(lambda: not ctl.speech.busy, timeout=5000)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    ctl.queue_clear()
    assert len(ctl.queue) == 0 and panel.empty.isVisible()


def test_settings_save_cancel_and_theme_preview(ctl, qtbot, monkeypatch):
    ctl.open_settings()
    dlg = ctl._settings_dialog
    dlg.rate.setValue(75)  # 75% = 150 words per minute, applied live
    assert ctl.speech.rate == 150
    dlg._cancel()
    assert dlg.rate.value() == 100 and ctl.speech.rate == 200 and ctl.settings["tts_rate"] == 200
    dlg.rate.setValue(75)
    dlg._save()
    assert ctl.settings["tts_rate"] == 150 and ctl.speech.rate == 150
    dlg.theme_cards["light"].clicked.emit("light")
    assert ctl.theme.key == "light"
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[1]) or QMessageBox.Discard)
    dlg.close()  # unsaved theme preview: asks, and Discard puts the theme back
    assert asked == ["Unsaved settings"]
    assert ctl.theme.key == "studio"


def test_global_hotkeys_follow_settings(ctl):
    values = dict(ctl.settings.data)
    values["global_hotkeys"] = dict(values["global_hotkeys"], toggle_dictation="Ctrl+Alt+J")
    ctl.apply_settings(values)
    bindings, enabled = ctl.fake_hotkeys.bindings
    assert bindings["toggle_dictation"] == "Ctrl+Alt+J" and enabled


def test_hotkey_actions_dispatch(ctl, qtbot):
    QGuiApplication.clipboard().setText("Read this clipboard text aloud.")
    ctl.fake_hotkeys.triggered.emit("speak_clipboard")
    qtbot.waitUntil(lambda: ctl.speech.busy, timeout=2000)
    ctl.fake_hotkeys.triggered.emit("stop_speech")
    assert not ctl.speech.busy
    ctl.fake_hotkeys.triggered.emit("toggle_mini")
    assert ctl.mini.isVisible() and not ctl.window.isVisible()
    ctl.fake_hotkeys.triggered.emit("toggle_mini")
    assert ctl.window.isVisible() and not ctl.mini.isVisible()


def test_mini_pill_never_takes_focus(ctl):
    pill = ctl.mini
    flags = pill.windowFlags()
    for flag in (Qt.WindowDoesNotAcceptFocus, Qt.WindowStaysOnTopHint, Qt.Tool, Qt.FramelessWindowHint):
        assert flags & flag
    assert pill.testAttribute(Qt.WA_ShowWithoutActivating)
    from PySide6.QtWidgets import QToolButton

    for btn in pill.findChildren(QToolButton):
        assert btn.focusPolicy() == Qt.NoFocus


def test_mini_play_speaks_clipboard_and_toggles_stop(ctl, qtbot):
    ctl.show_mini()
    QGuiApplication.clipboard().setText(LONG)
    ctl.mini.play.click()
    qtbot.waitUntil(lambda: ctl.speech.busy, timeout=2000)
    ctl.mini.play.click()
    assert not ctl.speech.busy


def test_dictation_target_editor_vs_clipboard_only(ctl):
    ctl._on_transcript("Into the editor.", "editor")
    assert "Into the editor." in ctl.editor.toPlainText()
    ctl.settings.set("dictation_output", "clipboard")
    ctl._on_transcript("Somewhere else.", ("external", 0))
    assert QGuiApplication.clipboard().text() == "Somewhere else."


def test_ipc_commands(ctl):
    ctl.handle_commands(["mini"])
    assert ctl.mini.isVisible()
    ctl.handle_commands(["show"])
    assert ctl.window.isVisible()


def test_every_theme_applies(ctl):
    from ttspython.core.theme import THEME_PRESETS

    for key in THEME_PRESETS:
        tokens = ctl.theme.apply(key)
        assert QApplication.instance().styleSheet()
        assert tokens["name"] == THEME_PRESETS[key]["name"]
    ctl.theme.apply("studio")
