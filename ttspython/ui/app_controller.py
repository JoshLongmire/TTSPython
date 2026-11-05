"""Wires services, windows, tray, hotkeys and settings together."""
from __future__ import annotations

import json
import os
import re
import threading

from PySide6.QtCore import QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from ..core import audio_devices, keys, textio
from ..core import platform as plat
from ..core.clipboard_router import Action, ClipboardRouter
from ..core.queue_model import SpeechQueue, preview
from ..core.settings import RECENT_MAX, speed_percent, write_json_atomic
from ..core.stt import preview as stt_preview
from ..core.stt import service as stt_models
from ..core.stt.service import SttService, SttState
from ..core.tts.controller import Source, SpeechController, State
from ..core.tts.export import AudioExporter, mp3_available
from ..core.tts.render import pick_default_voice
from ..platform.hotkeys import GlobalHotkeys, availability as hotkey_availability
from ..platform.inject import TextInjector
from ..platform.selection import SelectionGrabber
from . import icons
from .bridge import ExportBridge, SpeechBridge, SttBridge
from .editor import py_to_u16, sentence_start, u16_to_py
from .main_window import MainWindow
from .mini import FloatingToast, LiveCaption, MiniPill, QuickPopover
from .panels import ID_ROLE as QUEUE_ID_ROLE
from .settings_dialog import SettingsDialog
from .theme_manager import ThemeManager
from .tray import Tray, app_icon

SHORTCUT_ACTIONS = tuple(keys.DEFAULT_SHORTCUTS)
TEXT_FILTER = "Text files (*.txt);;All files (*)"


HOTKEY_RETRY_MS = (3000, 7000)  # retry busy hotkeys 3 s after start, then 10 s
PREVIEW_MODEL_LABEL = "live preview"  # its row in Settings > Listen > Downloaded models


def _progress_key(text):
    """Every step of one download ("Downloading the small model... 12 of 480 MB") gets the same key."""
    return re.sub(r"\d+", "#", text) if text.startswith(("Downloading", "Still downloading")) else None


def _saved_text(editor):
    """The text for a file. Raw: toPlainText would turn every no-break space into a plain one."""
    return editor.document().toRawText().replace("\u2029", "\n").replace("\u2028", "\n")


class AppController(QObject):
    devices_resolved = Signal(object)

    def __init__(self, app: QApplication, settings_store, services=None):
        """services may override "speech", "stt", "exporter", "hotkeys", "tray", "selection" (tests)."""
        super().__init__(app)
        services = services or {}
        self.app = app
        self.settings = settings_store
        s = settings_store.data
        self.theme = ThemeManager(app, s["theme_preset"])
        self.current_file = None
        self.current_doc = None
        self._refresh_requested = False
        self._settings_dialog = None
        self._settings_page = "appearance"
        self._last_progress = None  # the download a model_status progress line belongs to
        self._voice_browser = None
        self._hotkey_errors = {}
        self._quitting = False
        self._voices = []
        self._progress_label = "Ready"
        self._tested_voice = False
        self._last_export = None
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.setInterval(30_000)  # unsaved text is kept every 30 s (survives a crash)
        self._draft_timer.timeout.connect(self._write_recovery)
        self._export_open_timer = QTimer(self)
        self._export_open_timer.setSingleShot(True)
        self._export_open_timer.setInterval(20_000)
        self._queue_save_timer = QTimer(self)
        self._queue_save_timer.setSingleShot(True)
        self._queue_save_timer.setInterval(1000)
        self._queue_save_timer.timeout.connect(self._save_queue)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self.save_now)

        # Services
        self.speech = services.get("speech") or SpeechController(
            SpeechQueue(), voice_id=s["tts_voice_id"], rate=s["tts_rate"], volume=s["tts_volume"])
        self.queue = self.speech.queue
        if s["tts_voice_id"]:
            self.speech.set_voice(s["tts_voice_id"])
        self.speech.set_rate(s["tts_rate"])
        self.speech.set_volume(s["tts_volume"])
        self.speech.loop = s["queue_loop"]
        self.speech.auto_queue = s["clipboard_auto_queue"]
        self.stt = services.get("stt") or SttService(
            model=s["stt_whisper_model"], language=s["stt_language"], unload_when_idle=s["stt_unload_model_when_idle"],
            auto_unload=s["stt_auto_unload_enabled"], auto_unload_minutes=s["stt_auto_unload_minutes"])
        if not services.get("stt"):
            self.stt.preview_enabled = s["stt_live_preview"]
        self.exporter = services.get("exporter") or AudioExporter()
        self.speech_bridge = SpeechBridge(self.speech, self)
        self.stt_bridge = SttBridge(self.stt, self)
        self.export_bridge = ExportBridge(self.exporter, self)
        self.router = ClipboardRouter()
        self.selection = services.get("selection") or SelectionGrabber(self.router, self)
        self.injector = TextInjector(self.router, self)
        self.injector.keystroke = s["paste_keystroke"]
        self.hotkeys = services.get("hotkeys") or GlobalHotkeys(self)

        # UI
        self.actions = self._build_actions()
        self.window = MainWindow(self.actions)
        self.editor = self.window.editor
        self.mini = MiniPill()
        self.mini.snap = s["mini_snap"]
        self.popover = QuickPopover()
        self.float_toast = FloatingToast()
        self.caption = LiveCaption()
        self._dictation_target = None
        self._esc_registered = False
        use_tray = services.get("tray", True)
        self.tray = Tray(self.actions, self) if use_tray and Tray.available() else None

        self._connect()
        if self.speech.voices:  # the engine may have loaded before we connected
            self._on_voices(list(self.speech.voices), self.speech.renderer_name)
        self._apply_theme_tokens(self.theme.tokens)  # also sets the window and tray icons
        self.app.setWindowIcon(self.window.windowIcon())  # once: it is copied to every open window
        if self.tray:
            self.tray.show()
        self._apply_settings_to_ui()
        self._apply_shortcuts()
        self._apply_global_hotkeys()
        self._restore_geometry()
        self._device_preset = services.get("devices")  # tests: a fixed device list, PortAudio untouched
        self._resolve_devices_async(self._device_preset)
        self._load_queue()
        self._refresh_queue()  # not saved: nothing has changed since the last save
        self._on_speech_state(State.IDLE)
        self._on_stt_state(SttState.IDLE)
        self._update_title()
        self._update_recent_menu()
        self._sync_reading_speed()
        if self._hotkey_errors and any(self._hotkey_errors.values()):
            QTimer.singleShot(HOTKEY_RETRY_MS[0], lambda: self._retry_hotkeys(1))

    # ======================================================================
    # Actions
    # ======================================================================
    def _act(self, key, text, icon_name, handler, tip=None, checkable=False, role="text"):
        action = QAction(text, self)
        action.setObjectName(key)
        action.setToolTip(tip or text)
        action.setCheckable(checkable)
        if icon_name:
            icons.apply(action, icon_name, role)
        if checkable:
            action.toggled.connect(handler)
        else:
            action.triggered.connect(lambda _=False: handler())
        self.actions[key] = action
        return action

    def _build_actions(self):
        self.actions = {}
        a = self._act
        a("play_pause", "Play", "play", self.on_play_pause, "Play", role="on_accent")
        # Ctrl+Enter behaves like the Play button: play, pause, resume.
        a("speak_all", "Speak all", "play", self.on_play_pause, "Speak all text (again to pause)")
        a("pause_resume", "Pause or resume", "pause", self.on_pause_resume)
        a("stop", "Stop", "stop", self.on_stop, "Stop speaking")
        a("speak_selected", "Speak selected", "speak_selected", self.on_speak_selected, "Speak the selected text")
        a("speak_from_cursor", "Speak from here", "play", self.on_speak_from_cursor,
          "Speak from the sentence where the cursor is")
        a("new", "New", "file_text", self.on_new, "Start a new, empty document")
        a("open", "Open", "folder_open", self.on_open, "Open a text file")
        a("save", "Save", "save", self.on_save, "Save")
        a("save_as", "Save as", "save_as", self.on_save_as, "Save as")
        a("export", "Export audio", "export", self.on_export, "Export audio to WAV or MP3")
        a("export_cancel", "Cancel export", "close", self.exporter.cancel, "Cancel the export")
        a("export_open", "Open folder", "folder_open", self.open_export_folder, "Show the exported file's folder")
        a("find", "Find and replace", "search", self.on_find, "Find and replace")
        a("paste", "Paste", "paste", self.on_paste, "Paste clipboard text into the editor")
        a("clear", "Clear", "eraser", self.on_clear, "Clear the editor (undo with Ctrl+Z)")
        a("toggle_mode", "Switch Speak / Listen", None, self.on_toggle_mode)
        a("toggle_queue", "Speech queue", "panel_right", self.on_toggle_queue, "Show or hide the speech queue", checkable=True)
        a("settings", "Settings", "settings", self.open_settings, "Settings")
        a("mini_mode", "Mini mode", "mini", self.toggle_mini, "Switch to the floating mini bar")
        a("queue_add_text", "Add text", "plus", self.queue_add_text, "Add the editor text to the queue")
        a("queue_add_files", "Add files", "file_plus", self.queue_add_files, "Add text files to the queue")
        a("queue_play", "Play queue", "play", self.queue_play, "Play the queue from the selected item", role="on_accent")
        a("queue_remove", "Remove", "minus", self.queue_remove, "Remove the selected item (Delete)")
        a("queue_clear", "Clear queue", "trash", self.queue_clear, "Remove every item")
        a("queue_up", "Move up", "arrow_up", lambda: self.queue_move(-1), "Move the selected item up")
        a("queue_down", "Move down", "arrow_down", lambda: self.queue_move(1), "Move the selected item down")
        a("queue_loop", "Loop queue", "repeat", self.on_queue_loop, "Loop the queue", checkable=True)
        a("refresh_voices", "Refresh voices", "refresh", self.on_refresh_voices, "Refresh the voice list")
        a("record", "Start dictation", "mic", lambda: self.toggle_dictation("editor"), "Start dictation", role="#ffffff")
        a("speak_clipboard", "Speak selection or clipboard", "clipboard", self.speak_clipboard)
        a("show_window", "Show window", "monitor", self.show_window)
        a("quit", "Quit", "power", self.request_quit)
        return self.actions

    def _apply_shortcuts(self):
        shortcuts = self.settings["shortcuts"]
        for key in SHORTCUT_ACTIONS:
            action = self.actions[key]
            seq = shortcuts.get(key, "")
            action.setShortcut(QKeySequence(seq) if seq else QKeySequence())
            base = action.toolTip().split("  (")[0]
            action.setToolTip(f"{base}  ({QKeySequence(seq).toString(QKeySequence.NativeText)})" if seq else base)
        self._update_play_tip()

    def _update_play_tip(self):
        """The Play button's tooltip says what pressing it will do now."""
        state = self.speech.state
        if self.settings["mode"] != "tts" and state is State.IDLE:
            tip = "Switch to Speak to read text aloud"
        else:
            word = "Resume" if state is State.PAUSED else ("Play" if state is State.IDLE else "Pause")
            seq = self.settings["shortcuts"].get("speak_all", "")
            tip = word + (f"  ({QKeySequence(seq).toString(QKeySequence.NativeText)})" if seq else "")
        self.actions["play_pause"].setToolTip(tip)

    def _apply_global_hotkeys(self):
        s = self.settings
        bindings = dict(s["global_hotkeys"]) if s["global_hotkeys_enabled"] else {}
        if self.stt.state is SttState.RECORDING and self._dictation_target != "editor":
            bindings["cancel_dictation"] = "Esc"  # only while dictating into another app
        errors = self.hotkeys.set_bindings(bindings, bool(bindings))
        errors.pop("cancel_dictation", None)
        self._hotkey_errors = errors
        combo = s["global_hotkeys"].get("toggle_dictation") if s["global_hotkeys_enabled"] else ""
        hint = f" or {combo}" if combo and not self._hotkey_errors.get("toggle_dictation") else ""
        self.window.listen_panel.status.setText(
            f"Press the button{hint}, speak, then press again. The text appears in the editor.")

    # ======================================================================
    # Wiring
    # ======================================================================
    def _connect(self):
        w = self.window
        sb, st = self.speech_bridge, self.stt_bridge
        sb.state_changed.connect(self._on_speech_state)
        sb.voices_ready.connect(self._on_voices)
        sb.chunk_started.connect(self._on_chunk)
        sb.queue_item_started.connect(self._on_queue_item_started)
        sb.queue_changed.connect(self._on_queue_changed)
        sb.queue_finished.connect(self._on_queue_finished)
        sb.error.connect(lambda msg: self._error("Speech", msg))
        st.state_changed.connect(self._on_stt_state)
        st.partial.connect(self._on_partial)
        st.transcript_ready.connect(self._on_transcript)
        st.model_status.connect(self._on_model_status)
        st.preview_status.connect(self._on_preview_status)
        st.error.connect(lambda msg: self._error("Dictation", msg))
        eb = self.export_bridge
        eb.progress.connect(lambda d, t: w.export_status.setText(f"Exporting {d} of {t}"))
        eb.finished.connect(self._on_export_finished)
        eb.failed.connect(self._on_export_failed)
        eb.cancelled.connect(lambda: self._export_done("Export cancelled"))
        self.injector.finished.connect(self._on_injected)
        self.hotkeys.triggered.connect(self._on_global_hotkey)
        QGuiApplication.clipboard().dataChanged.connect(self._on_clipboard)
        self._clip_poll = QTimer(self)
        self._clip_poll.timeout.connect(self._on_clipboard)

        w.close_requested.connect(self._on_close_requested)
        w.destroyed.connect(lambda *_: (self._draft_timer.stop(), self._queue_save_timer.stop()))
        w.mode_switch.changed.connect(self.set_mode)
        w.find_bar.message.connect(self._status)
        w.transport.rate_changed.connect(self._set_rate)
        w.transport.volume_changed.connect(self._set_volume)
        w.queue_panel.list.reordered.connect(self.queue.reorder)
        w.queue_panel.list.delete_pressed.connect(self.queue_remove)
        w.queue_panel.list.itemActivated.connect(lambda item: self.queue_play(item.data(QUEUE_ID_ROLE)))
        w.queue_panel.list.files_dropped.connect(self.queue_add_paths)
        w.queue_panel.list.menu_requested.connect(self._queue_menu)
        self.editor.files_dropped.connect(self._files_dropped_on_editor)
        self.editor.menu_actions = [self.actions["speak_from_cursor"], self.actions["speak_selected"]]
        self.editor.document().modificationChanged.connect(lambda _m: self._update_title())
        self.editor.document().contentsChanged.connect(self._draft_changed)
        w.device_chip.clicked.connect(lambda: self.open_settings("speech"))
        w.listen_panel.model_chip.clicked.connect(lambda: self.open_settings("listen"))
        w.listen_panel.mic_chip.clicked.connect(lambda: self.open_settings("listen"))
        w.clip_switch.toggled.connect(self._set_clip_monitor)
        w.clip_mode.changed.connect(self._set_clip_action)
        w.auto_queue.toggled.connect(self._set_auto_queue)
        w.perf_switch.toggled.connect(self._set_performance)
        w.splitter.splitterMoved.connect(lambda *_: self._remember_layout())
        self._export_open_timer.timeout.connect(w.export_open.hide)

        self.mini.mic_clicked.connect(self.dictate_external)
        self.mini.play_clicked.connect(self.speak_clipboard)
        self.mini.expand_clicked.connect(self.show_window)
        self.mini.popover_requested.connect(self._open_popover)
        self.mini.volume_step.connect(self._volume_step)
        self.popover.pause_clicked.connect(self.on_pause_resume)
        self.caption.cancel_clicked.connect(self.cancel_dictation)
        self.mini.moved.connect(self._remember_mini)
        self.popover.voice_changed.connect(self._set_voice)
        self.popover.rate_changed.connect(self._set_rate)
        self.popover.volume_changed.connect(self._set_volume)
        self.popover.hide_mini.connect(self.show_window)
        self.theme.changed.connect(self._apply_theme_tokens)
        self.devices_resolved.connect(self._on_devices_resolved)
        # Windows logoff/shutdown ends the event loop without closing windows: still save,
        # and keep unsaved editor text in a recovery file (no prompt is possible there).
        self.app.commitDataRequest.connect(self._on_commit_data)
        self.app.aboutToQuit.connect(self.quit)

    def _apply_settings_to_ui(self):
        s = self.settings
        w = self.window
        w.set_mode(s["mode"])
        w.transport.set_values(s["tts_rate"], s["tts_volume"])
        self.actions["queue_loop"].setChecked(s["queue_loop"])
        self.actions["toggle_queue"].setChecked(s["queue_panel_visible"])
        w.set_queue_visible(s["queue_panel_visible"])
        for widget, value in ((w.clip_switch, s["clipboard_monitor"]), (w.auto_queue, s["clipboard_auto_queue"]),
                              (w.perf_switch, s["performance_mode"])):
            widget.blockSignals(True)
            widget.setChecked(value)
            widget.blockSignals(False)
        w.fit_status_bar()  # the switches above were set without their signals
        w.clip_mode.set_value(s["clipboard_action"])
        self.editor.set_highlight_enabled(s["sentence_highlight"])
        self.mini.snap = s["mini_snap"]
        self.mini.wave.setVisible(s["mini_waveform"])
        self.injector.keystroke = s["paste_keystroke"]
        self._apply_performance(s["performance_mode"])
        self._apply_mode_enabled()
        if s["clipboard_monitor"]:
            self._start_clip_monitor()
        w.listen_panel.model_chip.setText(f"Model: {s['stt_whisper_model']}")

    def _apply_theme_tokens(self, tokens):
        self.editor.set_highlight_color(tokens["sentence_bg"])
        self.window.refresh_icons()
        self.mini.set_tokens(tokens)
        self.caption.set_tokens(tokens)
        self.float_toast.set_tokens(tokens)
        icon = app_icon(tokens["accent_fill"], tokens["on_accent"])
        self.window.setWindowIcon(icon)
        if self.tray:
            self.tray.setIcon(icon)
        if self._settings_dialog is not None:
            self._settings_dialog.refresh_icons()
        self._on_speech_state(self.speech.state)

    # ======================================================================
    # Speech
    # ======================================================================
    def _status(self, text):
        self.window.set_status(text)

    def _window_in_front(self):
        return self.window.isVisible() and not self.window.isMinimized() and self.window.isActiveWindow()

    def _toast(self, text, ms=2600):
        """Show a message where the user is looking: our window, the mini bar, the tray, or a corner bubble."""
        if self._window_in_front():
            self.window.show_toast(text, ms)
        elif self.caption.isVisible():
            self.float_toast.show_near(self.caption, text, ms)
        elif self.mini.isVisible():
            self.float_toast.show_near(self.mini, text, ms)
        elif self.tray:
            self.tray.showMessage("TTSPython", text, self.window.windowIcon(), ms)
        elif self.window.isVisible() and not self.window.isMinimized():
            self.window.show_toast(text, ms)
        else:
            self.float_toast.show_in_corner(text, ms)

    def _error(self, title, message):
        # A modal box would steal focus from the app the user is working in.
        if self._window_in_front():
            QMessageBox.warning(self.window, title, message)
        else:
            self._toast(message, 6000)
        self._status(message)

    def on_speak_all(self):
        if self.settings["mode"] != "tts":
            self._status("Switch to Speak mode to read text aloud")
            return
        if self.speech.state is State.PAUSED:
            self.speech.resume()
            return
        if self.speech.busy:
            return
        text = self.editor.toPlainText()
        if not text.strip():
            self._toast("Type or paste some text first.")
            return
        self.editor.begin_tracking()
        if self.speech.speak(text, Source.EDITOR, 0):
            self._status("Speaking...")

    def on_play_pause(self):
        state = self.speech.state
        if state is State.PAUSED:
            self.speech.resume()
        elif state in (State.PLAYING, State.STARTING):
            self.speech.pause()
        elif state is State.IDLE:
            self.on_speak_all()

    def on_speak_from_cursor(self):
        """Speak from the start of the sentence the cursor is in to the end."""
        if self.settings["mode"] != "tts":
            self._status("Switch to Speak mode to read text aloud")
            return
        text = self.editor.toPlainText()
        if not text.strip():
            self._toast("Type or paste some text first.")
            return
        start = sentence_start(text, u16_to_py(text, self.editor.textCursor().position()))
        if not text[start:].strip():
            start = 0
        self.speech.stop()
        self.editor.begin_tracking()
        if self.speech.speak(text[start:], Source.EDITOR, py_to_u16(text, start)):
            self._status("Speaking from the cursor...")

    def on_pause_resume(self):
        if self.speech.busy:
            self.speech.toggle_pause()

    def on_speak_selected(self):
        if self.settings["mode"] != "tts":
            self._status("Switch to Speak mode to read text aloud")
            return
        text, base16 = self.editor.selection_info()
        if not text.strip():
            self._toast("Select some text first.")
            return
        self.editor.begin_tracking()
        if self.speech.speak(text, Source.SELECTION, base16, replace=True):
            self._status("Speaking selected text...")
        else:
            self._status("Still stopping the previous speech. Try again in a moment.")

    def on_stop(self):
        self.speech.stop()
        self.editor.stop_tracking()
        self._status("Stopped")

    def speak_clipboard(self):
        """Mini bar Play, the global hotkey, the tray and --speak-clipboard: read the text
        highlighted in the app you are using, or the clipboard when nothing is highlighted.
        Pressed while speaking, it stops."""
        if self.speech.busy:
            self.on_stop()
            return
        if self.window.isActiveWindow() and self.editor.textCursor().hasSelection():
            self.on_speak_selected()
            return
        self.selection.grab(self._speak_grabbed)

    def _speak_grabbed(self, text):
        source = "highlighted text"
        if not text:
            text = QGuiApplication.clipboard().text()
            source = "clipboard text"
        if not text.strip():
            self._toast("Nothing is highlighted and the clipboard has no text to read.")
            return
        if self.speech.busy:  # something else started meanwhile
            return
        if self.speech.speak(text, Source.CLIPBOARD):
            self._status(f"Speaking {source}...")

    def _on_speech_state(self, _state=None):
        # Signals from worker threads are queued while those from the GUI thread
        # are direct, so they can arrive out of order: always show the live state.
        state = self.speech.state
        busy = state is not State.IDLE
        playing = state in (State.PLAYING, State.STARTING)
        pp = self.actions["play_pause"]
        icons.apply(pp, "pause" if playing else "play", "on_accent", 22)
        pp.setText("Pause" if playing else ("Resume" if state is State.PAUSED else "Play"))
        self._update_play_tip()
        self.actions["stop"].setEnabled(busy)
        self.actions["pause_resume"].setEnabled(busy)
        self.mini.set_speaking(busy)
        self.popover.set_speech_state(busy, state is State.PAUSED)
        self._update_tray()
        wave_src = self.speech.output_level if busy else None
        self.window.transport.set_level_source(wave_src)
        if self.stt.state is not SttState.RECORDING:
            self.mini.wave.set_source(wave_src)
        now = self.window.transport.now
        if state is State.IDLE:
            self.editor.stop_tracking()
            self.window.transport.reset_progress("Ready")
            self.window.queue_panel.set_playing(None)
            self._progress_label = "Ready"
            if self.window.status_label.text().startswith("Speaking"):
                self._status("Ready")
        elif state is State.PAUSED:
            now.setText("Paused")
        elif state is State.PLAYING and now.text() == "Paused":
            now.setText(self._progress_label)  # resumed: show the sentence again, not "Paused"
        self._apply_mode_enabled()

    def _on_queue_finished(self, stopped):
        self.window.queue_panel.set_playing(None)
        if stopped and self.speech.busy:
            return  # the old run, stopped to start a new one: keep the "Playing queue" status
        self._status("Queue stopped" if stopped else "Queue finished")

    def _on_chunk(self, utt, pos16, end16, index, total, source):
        if source in (Source.EDITOR, Source.SELECTION):
            self.editor.highlight_range(pos16, end16)
        name = ""
        if source is Source.QUEUE and self.speech.playing_item_id:
            item = self.queue.get(self.speech.playing_item_id)
            name = f"{item.name}  ·  " if item else ""
        elif source is Source.CLIPBOARD:
            name = "Clipboard  ·  "
        self._progress_label = f"{name}Sentence {index + 1} of {total}"
        if self.speech.state is not State.PAUSED:
            self.window.transport.set_progress(index, total, self._progress_label)
        self._update_tray()

    def _on_voices(self, voices, renderer):
        self._voices = voices
        if voices and self.speech.voice_id not in {v.id for v in voices}:
            # The saved voice was uninstalled (or came from another system): use a real one.
            self.speech.set_voice(pick_default_voice(voices, ""))
        vid = self.speech.voice_id
        saved = self.settings["tts_voice_id"]
        if vid and (not saved or saved not in {v.id for v in voices}):
            # No voice saved yet, or the saved one was uninstalled: keep the one in use.
            self.settings.set("tts_voice_id", vid)
            self.save_soon()
        if self._settings_dialog is not None:
            self._settings_dialog.refresh_voices()
        if self._refresh_requested:
            self._refresh_requested = False
            where = ("Windows Settings > Time & language > Speech" if plat.IS_WINDOWS
                     else "your package manager (espeak-ng voices)")
            self._toast(f"Found {len(voices)} voice{'s' if len(voices) != 1 else ''}. Add more in {where}.", 4000)
        self._status(f"{len(voices)} voice{'s' if len(voices) != 1 else ''} ready")
        if self._voice_browser is not None:
            self._voice_browser.set_current(self.speech.voice_id)

    def on_refresh_voices(self):
        self._refresh_requested = True
        self.speech.refresh_voices()

    def open_voice_browser(self):
        if self._voice_browser is not None:
            self._voice_browser.raise_()
            self._voice_browser.activateWindow()
            return
        from .voice_browser import VoiceBrowser  # loaded on first use (downloads code is not needed at start)

        # Not a child of Settings: closing that would destroy this window in the middle of a download.
        dlg = VoiceBrowser(self.speech.voice_id, self.window)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.voices_changed.connect(self.speech.refresh_voices)
        dlg.use_voice.connect(self._use_voice_from_browser)
        dlg.destroyed.connect(lambda *_: setattr(self, "_voice_browser", None))
        self._voice_browser = dlg
        dlg.show()

    def _use_voice_from_browser(self, vid):
        self._set_voice(vid)
        if self._settings_dialog is not None:
            self._settings_dialog.select_voice(vid)  # its list and saved value follow
        self.speech.refresh_voices()
        self._status("Voice changed")

    def _sync_reading_speed(self):
        self.window.editor_card.set_wpm(self.speech.rate)
        self.window.queue_panel.set_wpm(self.speech.rate)

    def _volume_step(self, direction):
        volume = max(0.1, min(1.0, round(self.speech.volume + 0.05 * direction, 2)))
        self._set_volume(volume)
        self.float_toast.show_near(self.mini, f"Volume {int(round(volume * 100))}%", 900)

    def _set_rate(self, wpm):
        self.speech.set_rate(wpm)
        self.settings.set("tts_rate", int(wpm))
        self._sync_reading_speed()
        if self.window.transport.rate.value() != speed_percent(wpm):
            self.window.transport.set_values(wpm, self.speech.volume)
        if self._settings_dialog is not None:
            self._settings_dialog.sync_live_value("tts_rate", int(wpm))
        self.save_soon()

    # Speed and volume sliders in the settings dialog apply live, like the bar's.
    def set_speech_rate(self, wpm):
        self._set_rate(wpm)

    def set_speech_volume(self, volume):
        self._set_volume(volume)

    def _set_volume(self, volume):
        self.speech.set_volume(volume)
        self.settings.set("tts_volume", round(float(volume), 2))
        if self.window.transport.volume.value() != int(round(volume * 100)):
            self.window.transport.set_values(self.speech.rate, volume)
        if self._settings_dialog is not None:
            self._settings_dialog.sync_live_value("tts_volume", round(float(volume), 2))
        self.save_soon()

    def _set_voice(self, vid):
        if not vid:
            return
        self.speech.set_voice(vid)
        self.settings.set("tts_voice_id", vid)
        self.save_soon()

    def _open_popover(self, pos):
        self.popover.set_values(self._voices, self.speech.voice_id, self.speech.rate, self.speech.volume)
        self.popover.open_at(pos, self.mini.frameGeometry())

    # ======================================================================
    # Output device
    # ======================================================================
    def _resolve_devices_async(self, devices=None):
        out_ref = self.settings["tts_output_device"]
        in_ref = self.settings["stt_input_device"]
        preset = devices

        def work():
            devices = preset if preset is not None else audio_devices.query_devices()
            out_ref2 = audio_devices.complete_ref(out_ref, "output", devices) if out_ref else None
            in_ref2 = audio_devices.complete_ref(in_ref, "input", devices) if in_ref else None
            result = {
                "out_index": audio_devices.resolve(out_ref2, "output", devices),
                "in_index": audio_devices.resolve(in_ref2, "input", devices),
                "out_ref": out_ref2, "in_ref": in_ref2,
            }
            self.devices_resolved.emit(result)

        threading.Thread(target=work, name="device-resolve", daemon=True).start()

    def rescan_devices(self):
        """Pick up devices plugged in after start. Skipped while audio is in use (an open
        stream must not outlive PortAudio). Returns True if the list was refreshed."""
        if self.speech.busy or self.stt.state is not SttState.IDLE or self.exporter.running:
            return False
        if self._device_preset is None:
            self.speech.player.close()  # idle: it reopens on the next Speak
            if not audio_devices.rescan():
                return False
        self._resolve_devices_async(self._device_preset)  # indexes may have moved
        return True

    def _on_devices_resolved(self, r):
        self.speech.set_output_device(r["out_index"])
        self.stt.input_device = r["in_index"]
        changed = False
        if r["out_ref"] != self.settings["tts_output_device"] and r["out_ref"]:
            self.settings.set("tts_output_device", r["out_ref"])
            changed = True
        if r["in_ref"] != self.settings["stt_input_device"] and r["in_ref"]:
            self.settings.set("stt_input_device", r["in_ref"])
            changed = True
        if changed:  # e.g. a v4 device index now stored with its name
            self.save_soon()
        out_name = audio_devices.describe(self.settings["tts_output_device"]) if r["out_index"] is not None else "System default"
        in_name = audio_devices.describe(self.settings["stt_input_device"]) if r["in_index"] is not None else "System default"
        self.window.device_chip.setText(f"Output: {out_name}")
        self.window.device_chip.set_clickable(f"Speech plays on: {out_name}. Click to change.")
        self.window.listen_panel.mic_chip.setText(f"Mic: {in_name}")

    # ======================================================================
    # Queue
    # ======================================================================
    def _on_queue_changed(self):
        self._refresh_queue()
        self._queue_save_timer.start()

    def _refresh_queue(self):
        self.window.queue_panel.set_items(self.queue.snapshot(), self.speech.playing_item_id)
        has = len(self.queue) > 0
        for key in ("queue_play", "queue_clear", "queue_remove", "queue_up", "queue_down"):
            self.actions[key].setEnabled(has)

    def _on_queue_item_started(self, item_id):
        self.editor.stop_tracking()  # the editor sentence is no longer the one being read
        self.window.queue_panel.set_playing(item_id)

    def queue_add_text(self):
        text = self.editor.toPlainText().strip()
        if not text:
            self._toast("There is no text to add.")
            return
        self.queue.add(text, f"Text: {preview(text)}", "text")
        self._status(f"Added to queue ({len(self.queue)} items)")

    def queue_add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self.window, "Add files to the queue", "", TEXT_FILTER)
        self.queue_add_paths(paths)

    def queue_add_paths(self, paths):
        entries, failures = [], []
        for path in paths:
            try:
                content = textio.read_text(path).strip()
            except OSError as exc:
                failures.append(f"{os.path.basename(path)}: {exc}")
                continue
            if content:
                entries.append((content, os.path.basename(path), "file"))
        if entries:
            self.queue.add_many(entries)
        if failures:
            self._error("Queue", "Could not read " + "\n".join(failures))
        if paths:
            added = len(entries)
            self._status(f"Added {added} file{'s' if added != 1 else ''} to the queue ({len(self.queue)} items)")

    def queue_play(self, item_id=None):
        if not len(self.queue):
            self._toast("The queue is empty. Add some text first.")
            return
        start = item_id or self.window.queue_panel.selected_id() or ""
        self.speech.stop()
        if self.speech.play_queue(start):
            self._status(f"Playing queue ({len(self.queue)} items)")
        else:
            self._status("Still stopping the previous speech. Try again in a moment.")

    def _queue_menu(self, item_id, pos):
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self.window)
        menu.addAction("Play from here", lambda: self.queue_play(item_id))
        menu.addAction("Move to top", lambda: self._queue_to_top(item_id))
        menu.addAction("Copy to the editor", lambda: self._queue_to_editor(item_id))
        menu.addSeparator()
        menu.addAction("Remove", lambda: (self.queue.remove(item_id), self._status(f"Removed from queue ({len(self.queue)} items)")))
        menu.exec(pos)
        menu.deleteLater()

    def _queue_to_top(self, item_id):
        index = self.queue.index_of(item_id)
        if index > 0:
            self.queue.move(item_id, -index)

    def _queue_to_editor(self, item_id):
        item = self.queue.get(item_id)
        if item is None or not self._confirm_discard():
            return
        self._stop_reading_editor()
        self.editor.setPlainText(item.text)
        self._forget_document()  # Ctrl+S must not write this over the file that was open
        self.editor.document().setModified(True)
        self._status(f"Copied \"{item.name}\" to the editor")

    def _queue_path(self):
        return os.path.join(os.path.dirname(os.path.abspath(self.settings.path)), "queue.json")

    def _load_queue(self):
        """Put back the queue from the last session."""
        try:
            with open(self._queue_path(), "r", encoding="utf-8") as f:
                items = json.load(f).get("items", [])
        except (OSError, ValueError, AttributeError):
            return
        if not isinstance(items, list):
            return
        self.queue.add_many(((item["text"], str(item.get("name") or preview(item["text"])), str(item.get("kind") or "text"))
                             for item in items
                             if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip()),
                            announce=False)

    def _save_queue(self):
        items = [{"text": i.text, "name": i.name, "kind": i.kind} for i in self.queue.snapshot()]
        try:
            if items:
                write_json_atomic(self._queue_path(), {"items": items})
            elif os.path.exists(self._queue_path()):
                os.remove(self._queue_path())
        except OSError:
            pass

    def queue_remove(self):
        item_id = self.window.queue_panel.selected_id()
        if not item_id:
            self._toast("Select an item in the queue first.")
            return
        self.queue.remove(item_id)
        self._status(f"Removed from queue ({len(self.queue)} items)")

    def queue_clear(self):
        n = len(self.queue)
        if not n:
            return
        answer = QMessageBox.question(self.window, "Clear queue", f"Remove all {n} items from the queue?",
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            if self.speech.playing_item_id:
                self.speech.stop()
            self.queue.clear()
            self._status("Queue cleared")

    def queue_move(self, delta):
        item_id = self.window.queue_panel.selected_id()
        if not item_id:
            self._toast("Select an item in the queue first.")
            return
        self.queue.move(item_id, delta)

    def on_queue_loop(self, checked):
        self.speech.loop = checked
        self.settings.set("queue_loop", checked)
        self.save_soon()

    def on_toggle_queue(self, checked):
        self.window.set_queue_visible(checked)
        self.settings.set("queue_panel_visible", checked)
        self.save_soon()

    # ======================================================================
    # Clipboard monitor
    # ======================================================================
    def _start_clip_monitor(self):
        self.router.prime(QGuiApplication.clipboard().text())
        if plat.session_type() == "wayland":
            self._clip_poll.start(2000 if self.settings["performance_mode"] else 1000)

    def _set_clip_monitor(self, enabled):
        self.settings.set("clipboard_monitor", enabled)
        if enabled:
            self._start_clip_monitor()
            self._status("Clipboard monitoring on")
        else:
            self._clip_poll.stop()
            self._status("Clipboard monitoring off")
        self.save_soon()

    def _set_clip_action(self, action):
        self.settings.set("clipboard_action", action)
        self.save_soon()

    def _set_auto_queue(self, enabled):
        self.settings.set("clipboard_auto_queue", enabled)
        self.speech.auto_queue = enabled
        self._status("Auto-Queue on: copied text is queued while speaking" if enabled
                     else "Auto-Queue off: copied text is only spoken when idle")
        self.save_soon()

    def _on_clipboard(self):
        if not self.settings["clipboard_monitor"]:
            return
        text = QGuiApplication.clipboard().text()
        action, label = self.router.decide(text, busy=self.speech.busy, action=self.settings["clipboard_action"],
                                           auto_queue=self.settings["clipboard_auto_queue"])
        if action is Action.SPEAK:
            if self.speech.speak(text, Source.CLIPBOARD):
                self._status("Speaking clipboard text...")
            elif self.settings["clipboard_auto_queue"]:
                self.queue.add(text, f"Auto-Queued: {preview(text)}", "clipboard")
        elif action is Action.ENQUEUE:
            self.queue.add(text, f"{label}: {preview(text)}", "clipboard")
            self._status(f"Clipboard text queued ({len(self.queue)} items)")
        elif label == "busy":
            self._status("Clipboard ignored while speaking (turn on Auto-Queue to queue it)")

    # ======================================================================
    # Dictation
    # ======================================================================
    def capture_target(self):
        if plat.IS_WINDOWS:
            from ..platform import winapi

            hwnd = winapi.foreground_window()
            if winapi.is_own_window(hwnd):
                return "editor"
            return ("external", hwnd)
        if self.window.isActiveWindow():
            return "editor"
        return ("external", 0)

    def dictate_external(self):
        if self.stt.state is SttState.RECORDING:
            self.stt.stop()
            return
        self.toggle_dictation(self.capture_target())

    def toggle_dictation(self, target):
        if self.stt.state is SttState.TRANSCRIBING:
            self._toast(self.stt.busy_message())
            return
        if self.stt.state is SttState.IDLE:
            self._dictation_target = target
            if target == "editor" and self.speech.busy:
                self.speech.stop()
        self.stt.toggle(target)

    def cancel_dictation(self):
        """The caption's X or Esc: throw the recording away, nothing is typed."""
        self.stt.cancel()
        self.caption.hide()

    def _caption_wanted(self):
        """The bubble is for dictating into other apps; the editor shows its own text."""
        return self._dictation_target not in (None, "editor")

    def _on_partial(self, settled, checked, preview):
        if self.stt.state is SttState.RECORDING and self._caption_wanted():
            self.caption.set_words(settled, checked, preview)
            self.caption.show_by(self.mini)

    def _on_stt_state(self, _state=None):
        state = self.stt.state
        rec = self.actions["record"]
        recording = state is SttState.RECORDING
        transcribing = state is SttState.TRANSCRIBING
        icons.apply(rec, "stop" if recording else "mic", "#ffffff", 22 if not recording else 20)
        rec.setText("Stop dictation" if recording else "Start dictation")
        rec.setToolTip(rec.text())
        rec.setEnabled(not transcribing)
        panel = self.window.listen_panel
        panel.title.setText(self._stt_title())
        panel.wave.set_source(self.stt.level if recording else None)
        self.mini.set_recording(recording, transcribing)
        self._update_tray()
        if recording:
            self.mini.wave.set_source(self.stt.level)
        else:
            self.mini.wave.set_source(self.speech.output_level if self.speech.busy else None)
        if recording:
            self._status("Listening... press again to stop")
        elif transcribing:
            self._status("Transcribing...")
        if recording and self._caption_wanted():
            if not self.caption.isVisible():
                self.caption.start()
            self.caption.show_by(self.mini)
        elif transcribing and self.caption.isVisible():
            self.caption.set_status("Typing it in...")
        elif not recording and not transcribing:
            self.caption.hide()
        hotkeys_follow = recording != self._esc_registered
        if hotkeys_follow:
            self._esc_registered = recording and self._caption_wanted()
            self._apply_global_hotkeys()

    def _on_transcript(self, text, target):
        if target == "editor":
            self.editor.append_line(text)
            self._status("Transcript inserted")
            return
        hwnd = target[1] if isinstance(target, tuple) else 0
        if self.settings["dictation_output"] == "clipboard":
            self.injector.copy_only(text, "Copied to clipboard. Press Ctrl+V to paste.")
        else:
            self.injector.inject(text, hwnd)

    def _on_injected(self, pasted, message):
        if message:
            self._toast(message, 4000)
        self._status("Dictation typed into the active app" if pasted else (message or "Copied"))

    def _stt_title(self):
        state = self.stt.state
        if state is SttState.RECORDING:
            return "Listening..."
        return "Transcribing..." if state is SttState.TRANSCRIBING else "Ready to dictate"

    def _on_model_status(self, text):
        self._status(text)
        if self.stt.state is not SttState.RECORDING:
            # A model message while it lasts ("Loading small model..."), then back to the state.
            self.window.listen_panel.title.setText(text if "..." in text else self._stt_title())
        in_bubble = self.caption.isVisible() and text.startswith(("Downloading", "Loading"))
        if in_bubble:
            self.caption.set_status(text)  # the bubble already sits where the user is looking
            self.caption.show_by(self.mini)
        # Dictating from mini mode or a hotkey: the status bar is not visible, so say it where the user is.
        quiet = in_bubble or text == "Model unloaded to free memory" or text.endswith("model ready")
        progress = _progress_key(text)
        if progress and progress == self._last_progress:
            # The next step of the same download: update a notice on show in place, never pop a new one.
            if self.float_toast.isVisible():
                self.float_toast.update_text(text, 3500)
            elif self._window_in_front():
                self.window.show_toast(text, 3500)
        elif not self._window_in_front() and not quiet:
            self._toast(text, 3500)
        self._last_progress = progress
        if self._settings_dialog is not None:
            self._settings_dialog.update_model_status()

    def _settings_closed(self, dialog):
        self._settings_page = dialog.current_page()
        self._settings_dialog = None

    def _on_preview_status(self, text):
        """The instant preview downloads in the background and nothing waits on it: the status bar
        says how far it got, and only a failure is worth a notice."""
        self._status(text)
        if "failed" in text:
            self._toast(text, 6000)
        elif self._settings_dialog is not None and text == "Live preview ready":
            self._settings_dialog.refresh_models()

    # ======================================================================
    # Mode, files, export, find
    # ======================================================================
    def set_mode(self, mode):
        if mode == self.settings["mode"]:
            self.window.set_mode(mode)
            return
        if mode == "tts" and self.stt.state is SttState.RECORDING:
            self.stt.stop()
        if mode == "tts":
            self.stt.went_idle()
        self.settings.set("mode", mode)
        self.window.set_mode(mode)
        self._apply_mode_enabled()
        self._status("Listen mode: dictation goes into the editor" if mode == "stt" else "Speak mode")
        self.save_soon()

    def on_toggle_mode(self):
        self.set_mode("stt" if self.settings["mode"] == "tts" else "tts")

    def _apply_mode_enabled(self):
        tts = self.settings["mode"] == "tts"
        self.actions["speak_all"].setEnabled(tts or self.speech.busy)  # it also pauses
        self.actions["speak_selected"].setEnabled(tts)
        self.actions["play_pause"].setEnabled(tts or self.speech.busy)
        self._update_play_tip()

    def _confirm_discard(self):
        if not self.editor.document().isModified() or not self.editor.toPlainText():
            return True
        answer = QMessageBox.question(self.window, "Unsaved changes", "Save the changes in the editor?",
                                      QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if answer == QMessageBox.Save:
            self.on_save()
            return not self.editor.document().isModified()  # still modified: cancelled or could not save
        if answer == QMessageBox.Discard:
            self._clear_recovery()  # a crash in the next moments must not bring it back
            return True
        return False

    def _confirm_quit(self):
        """Ask first if quitting would lose editor text or work still running."""
        if not self._confirm_discard():
            return False
        running = []
        if self.exporter.running:
            running.append("An audio export is still running.")
        if self.stt.state is not SttState.IDLE:
            running.append("A dictation is still in progress.")
        if not running:
            return True
        answer = QMessageBox.question(self.window, "Quit TTSPython", " ".join(running) + " Quit anyway?",
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return answer == QMessageBox.Yes

    def _stop_reading_editor(self):
        """Speech from the editor would go on over text that has been replaced."""
        if self.speech.busy and self.speech.current_source not in (Source.QUEUE, Source.CLIPBOARD):
            self.speech.stop()

    def on_open(self):
        if not self._confirm_discard():
            return
        start = os.path.dirname(self.current_file) if self.current_file else ""
        path, _ = QFileDialog.getOpenFileName(self.window, "Open a text file", start, TEXT_FILTER)
        if path:
            self.open_path(path, confirmed=True)

    def open_path(self, path, confirmed=False):
        """Open a text file (from the dialog, the recent list or a drop on the editor)."""
        if not confirmed and not self._confirm_discard():
            return
        try:
            doc = textio.read_text_file(path)
        except OSError as exc:
            self._error("Open failed", f"Could not read {os.path.basename(path)}: {exc}")
            self._forget_recent(path)
            return
        self._stop_reading_editor()
        self.editor.setPlainText(doc.text)
        self.editor.document().setModified(False)
        self.current_file, self.current_doc = path, doc
        self.window.editor_card.set_title(os.path.basename(path))
        self._remember_recent(path)
        self._update_title()
        self._status(f"Opened {os.path.basename(path)}")
        if doc.lossy:
            self._toast("This file may use an encoding TTSPython cannot read, so some characters can look wrong. "
                        "Save will ask where to save, so the original stays as it is.", 7000)

    def _files_dropped_on_editor(self, paths):
        self.open_path(paths[0])
        opened = self.current_file == paths[0]
        if len(paths) > 1 and opened and not self.current_doc.lossy:  # that notice matters more
            self._toast("The editor holds one file. To read several, drop them on the queue.")

    def on_new(self):
        if not self._confirm_discard():
            return
        self.speech.stop()
        self.editor.setPlainText("")
        self._forget_document()
        self._status("New document")

    def _forget_document(self):
        """The editor no longer belongs to a file: Save asks where to save."""
        self.current_file = self.current_doc = None
        self.editor.document().setModified(False)
        self.window.editor_card.set_title("Untitled")
        self._update_title()

    def _update_title(self):
        name = os.path.basename(self.current_file) if self.current_file else "Untitled"
        self.window.setWindowTitle(f"{name}[*] - TTSPython")
        self.window.setWindowModified(self.editor.document().isModified())

    def _remember_recent(self, path):
        path = os.path.abspath(path)
        recent = [p for p in self.settings["recent_files"] if os.path.normcase(p) != os.path.normcase(path)]
        self.settings.set("recent_files", ([path] + recent)[:RECENT_MAX])
        self.save_soon()
        self._update_recent_menu()

    def _forget_recent(self, path):
        recent = [p for p in self.settings["recent_files"] if p != path]
        if len(recent) != len(self.settings["recent_files"]):
            self.settings.set("recent_files", recent)
            self.save_soon()
            self._update_recent_menu()

    def _update_recent_menu(self):
        from PySide6.QtWidgets import QMenu, QToolButton

        button = self.window.open_button
        recent = self.settings["recent_files"]
        if not recent:
            button.setMenu(None)
            button.setPopupMode(QToolButton.DelayedPopup)
            return
        menu = button.menu() or QMenu(button)
        menu.clear()
        for path in recent:
            action = menu.addAction(os.path.basename(path), lambda p=path: self.open_path(p))
            action.setToolTip(path)
        menu.setToolTipsVisible(True)
        menu.addSeparator()
        menu.addAction("Clear recent files", lambda: (self.settings.set("recent_files", []), self.save_soon(),
                                                     self._update_recent_menu()))
        button.setMenu(menu)
        button.setPopupMode(QToolButton.MenuButtonPopup)

    def on_save(self):
        if not self.current_file or (self.current_doc and self.current_doc.lossy):
            self.on_save_as()
            return
        self._write(self.current_file)

    def _save_dialog(self, title, start, filters):
        """Save dialog whose default extension follows the chosen filter.

        filters: [(label, suffix)]. The extension is added by the dialog itself, so its
        "replace existing file?" check sees the final name. Returns (path, suffix) or (None, None).
        """
        dlg = QFileDialog(self.window, title, start)
        dlg.setAcceptMode(QFileDialog.AcceptSave)
        names = [f"{label} (*.{suffix})" for label, suffix in filters]
        dlg.setNameFilters(names)
        dlg.setDefaultSuffix(filters[0][1])
        by_name = dict(zip(names, (suffix for _label, suffix in filters)))
        dlg.filterSelected.connect(lambda name: dlg.setDefaultSuffix(by_name.get(name, filters[0][1])))
        if not dlg.exec() or not dlg.selectedFiles():
            return None, None
        path = dlg.selectedFiles()[0]
        suffix = os.path.splitext(path)[1].lstrip(".").lower() or by_name.get(dlg.selectedNameFilter(), filters[0][1])
        return path, suffix

    def on_save_as(self):
        start = self.current_file or "untitled.txt"
        path, _suffix = self._save_dialog("Save text", start, [("Text files", "txt")])
        if path:
            self._write(path)

    def _write(self, path):
        doc = self.current_doc if self.current_file == path else None
        wanted = doc.encoding if doc else "utf-8"
        try:
            used = textio.write_text_file(path, _saved_text(self.editor), wanted,
                                          doc.newline if doc else None, doc.bom if doc else False)
        except (OSError, UnicodeError) as exc:
            QMessageBox.warning(self.window, "Save failed", f"Could not save this file:\n{exc}")
            return
        if doc is None:
            self.current_doc = textio.TextDocument(self.editor.toPlainText(), used, os.linesep)
        else:
            doc.encoding = used
            doc.lossy = False  # the user chose to replace this file
        self.current_file = path
        self.editor.document().setModified(False)
        self.window.editor_card.set_title(os.path.basename(path))
        self._remember_recent(path)
        self._update_title()
        self._clear_recovery()
        if used != wanted:
            self._toast(f"Saved as UTF-8: some characters could not be stored as {wanted}.", 5000)
        self._status(f"Saved {os.path.basename(path)}")

    def on_export(self):
        selected, _base16 = self.editor.selection_info()
        text = selected if selected.strip() else self.editor.toPlainText()
        if not text.strip():
            self._toast("There is no text to export.")
            return
        if self.exporter.running:
            return
        filters = [("WAV audio", "wav")]
        if mp3_available():
            filters.append(("MP3 audio", "mp3"))
        fmt = self.settings["export_format"]
        filters.sort(key=lambda f: f[1] != fmt)  # last used format first
        name = os.path.splitext(os.path.basename(self.current_file))[0] if self.current_file else "speech"
        folder = self.settings["export_dir"] or (os.path.dirname(self.current_file) if self.current_file else "")
        start = os.path.join(folder, f"{name}.{filters[0][1]}") if folder else f"{name}.{filters[0][1]}"
        title = "Export the selected text as audio" if selected.strip() else "Export audio"
        path, suffix = self._save_dialog(title, start, filters)
        if not path:
            return
        self.settings.set("export_dir", os.path.dirname(path))
        self.settings.set("export_format", "mp3" if suffix == "mp3" else "wav")
        self.save_soon()
        self.window.export_open.hide()
        if self.exporter.start(text, path, self.speech.voice_id, self.speech.rate, self.speech.volume):
            self.actions["export"].setEnabled(False)
            self.window.export_status.setText("Exporting...")
            self.window.export_status.show()
            self.window.export_cancel.show()
            self._status("Exporting audio...")

    def _export_done(self, message):
        self.actions["export"].setEnabled(True)
        self.window.export_status.hide()
        self.window.export_cancel.hide()
        self._status(message)

    def _on_export_finished(self, path):
        self._export_done(f"Audio exported: {os.path.basename(path)}")
        self._toast(f"Saved {os.path.basename(path)}")
        self._last_export = path
        self.window.export_open.show()
        self._export_open_timer.start()  # starts over: the last export's time must not hide this one's

    def open_export_folder(self):
        if self._last_export:
            try:
                plat.open_uri(os.path.dirname(self._last_export))
            except OSError:
                self._toast("Could not open the folder.")

    def _on_export_failed(self, message):
        self._export_done("Export failed")
        self._error("Export failed", f"Could not export audio: {message}")

    def on_find(self):
        self.show_window()
        self.window.find_bar.open_bar()

    def on_paste(self):
        text = QGuiApplication.clipboard().text()
        if not text:
            self._toast("The clipboard is empty.")
            return
        self.editor.insertPlainText(text)
        self._status("Text pasted")

    def on_clear(self):
        self.editor.clear_undoable()
        if self.current_file:
            # Ctrl+S must not write the empty editor over the file it came from.
            self.current_file = self.current_doc = None
            self.window.editor_card.set_title("Untitled")
            self._update_title()
        self._status("Text cleared (Ctrl+Z to undo)")

    # ======================================================================
    # Performance
    # ======================================================================
    def _set_performance(self, enabled):
        self.settings.set("performance_mode", enabled)
        self._apply_performance(enabled)
        self._status("Performance mode on" if enabled else "Performance mode off")
        self.save_soon()

    def _apply_performance(self, enabled):
        fps = 15 if enabled else 30
        for wave in (self.window.transport.wave, self.window.listen_panel.wave, self.mini.wave):
            wave.set_fps(fps)
        for switch in (self.window.clip_switch, self.window.auto_queue, self.window.perf_switch):
            switch.animate = not enabled

    # ======================================================================
    # Windows: main, mini, tray, settings
    # ======================================================================
    def show_window(self):
        self.mini.hide()
        self.popover.hide()
        window = self.window
        saved = self.settings["window"] or {}
        if window.isMinimized():
            window.showNormal()
        elif not window.isVisible() and saved.get("maximized"):
            window.showMaximized()
        else:
            window.show()
        window.raise_()
        window.activateWindow()

    def show_mini(self):
        self._remember_layout()  # the window hides now; keep its size and place for next time
        self.mini.restore_position(self.settings["mini_pos"])
        self.mini.show()
        self.mini.raise_()
        self.window.hide()
        if self.speech.busy or self.stt.state is SttState.RECORDING:
            self._on_stt_state(self.stt.state)

    def toggle_mini(self):
        if self.mini.isVisible():
            self.show_window()
        else:
            self.show_mini()

    def _remember_mini(self):
        self.settings.set("mini_pos", self.mini.position_ref())
        self.save_soon()

    def open_settings(self, page=None):
        """On the page asked for, else the one last used (while the app runs)."""
        if self._settings_dialog is not None:
            self.show_window()  # it stays hidden with a hidden main window
            if page:
                self._settings_dialog.show_page(page)
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        self.show_window()
        dlg = SettingsDialog(self, self.window, page or self._settings_page)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.saved.connect(self.apply_settings)
        dlg.preview_theme.connect(self.theme.apply)
        dlg.action_requested.connect(self._settings_action)
        dlg.finished.connect(lambda _r: self._settings_closed(dlg))
        self._settings_dialog = dlg
        dlg.show()

    def _settings_action(self, name):
        dlg = self._settings_dialog
        if name == "refresh_voices":
            self.on_refresh_voices()
        elif name == "add_voices":
            self.open_voice_browser()
        elif name == "unload_model":
            self.stt.unload()
            if dlg:
                dlg.update_model_status()
        elif name == "test_voice":
            # Uses the unsaved dialog values; Cancel/Close put the engine back (sync_engine).
            values = dict(self.settings.data, **dlg.form_values()) if dlg else self.settings.data
            self.speech.stop()
            self._apply_engine(values)
            self._tested_voice = True
            self.speech.speak("This is how speech will sound.", Source.TEST)
        elif name == "sync_engine":
            if self._tested_voice:  # only a Test changed the engine; otherwise leave speech alone
                self._tested_voice = False
                self._apply_engine(self.settings.data)
        elif name == "pause_hotkeys":
            self.hotkeys.set_bindings({}, False)
        elif name == "resume_hotkeys":
            self._apply_global_hotkeys()
        elif name == "open_sound":
            self.on_sound_settings()
        elif name == "reset_mini":
            self.settings.set("mini_pos", None)
            self.mini.restore_position(None)
            self.save_soon()
        elif name == "open_settings_folder":
            try:
                plat.open_uri(os.path.dirname(self.settings.path))
            except OSError:
                pass

    def _apply_engine(self, values):
        """Point the speech engine at these voice/speed/volume/device values."""
        self.speech.set_output_device(self.resolve_device(values["tts_output_device"], "output"))
        if values["tts_voice_id"]:
            self.speech.set_voice(values["tts_voice_id"])
        self.speech.set_rate(values["tts_rate"])
        self.speech.set_volume(values["tts_volume"])

    def on_sound_settings(self):
        if not plat.open_sound_settings():
            if plat.IS_WINDOWS:
                self._toast("Open Windows Settings and go to System > Sound.", 5000)
            else:
                self._toast("Open your desktop sound settings (or pavucontrol) to choose the playback device.", 5000)

    def apply_settings(self, values):
        old = dict(self.settings.data)
        self.settings.update(values)
        tested, self._tested_voice = self._tested_voice, False  # the engine is set from the saved values below
        s = self.settings
        if tested:  # Test may have moved speech to a device the form no longer shows
            self.speech.set_output_device(self.resolve_device(s["tts_output_device"], "output"))
        if s["theme_preset"] != self.theme.key:
            self.theme.apply(s["theme_preset"])
        self.speech.set_voice(s["tts_voice_id"])
        self.speech.set_rate(s["tts_rate"])
        self.speech.set_volume(s["tts_volume"])
        self.window.transport.set_values(s["tts_rate"], s["tts_volume"])
        self._set_voice(s["tts_voice_id"])
        self.speech.auto_queue = s["clipboard_auto_queue"]
        self.stt.set_model(s["stt_whisper_model"])
        self.stt.language = s["stt_language"]
        self.stt.preview_enabled = s["stt_live_preview"]
        self.stt.configure(unload_when_idle=s["stt_unload_model_when_idle"], auto_unload=s["stt_auto_unload_enabled"],
                           minutes=s["stt_auto_unload_minutes"])
        if old["tts_output_device"] != s["tts_output_device"] or old["stt_input_device"] != s["stt_input_device"]:
            self._resolve_devices_async(self._device_preset)
        if not old["clipboard_monitor"] and s["clipboard_monitor"]:
            self._start_clip_monitor()
        elif not s["clipboard_monitor"]:
            self._clip_poll.stop()
        self._apply_settings_to_ui()
        self._apply_shortcuts()
        self._apply_global_hotkeys()
        self.save_now()
        self._status("Settings saved")
        self._report_hotkey_errors()

    # --- context for the settings dialog ---
    def voices(self):
        return list(self._voices)

    def current_voice_id(self):
        return self.speech.voice_id

    def list_devices(self, kind):
        return audio_devices.list_devices(kind)

    def default_hostapi(self):
        return audio_devices.default_hostapi_name()

    def resolve_device(self, ref, kind):
        return audio_devices.resolve(ref, kind)

    def loaded_model(self):
        return self.stt.cache.loaded_name

    def downloaded_models(self):
        models = stt_models.downloaded_models()
        if stt_preview.installed():
            models.append((PREVIEW_MODEL_LABEL, stt_preview.size_on_disk()))
        return models

    def delete_model(self, name):
        """Delete a downloaded Whisper model (or the live preview's). Returns a message if it
        could not be deleted."""
        if self.stt.state is not SttState.IDLE:
            return "Finish dictating first, then delete the model."
        if name == PREVIEW_MODEL_LABEL:
            stt_preview.release()
            freed = stt_preview.remove()
            self._status(f"Deleted the live preview model ({freed / 1e6:,.0f} MB freed)")
            return ""
        if self.stt.cache.loaded_name == name:
            self.stt.unload()
        try:
            freed = stt_models.delete_model(name)
        except Exception as exc:
            return f"Could not delete the {name} model: {exc}"
        self._status(f"Deleted the {name} model ({freed / 1e6:,.0f} MB freed)")
        return ""

    def hotkey_availability(self):
        return hotkey_availability()

    def hotkey_errors(self):
        return dict(self._hotkey_errors)

    def tray_available(self):
        return self.tray is not None

    # ======================================================================
    # Global hotkeys and IPC
    # ======================================================================
    def _update_tray(self):
        if not self.tray:
            return
        stt_state = self.stt.state
        if stt_state is SttState.RECORDING:
            tip = "Listening..."
        elif stt_state is SttState.TRANSCRIBING:
            tip = "Transcribing..."
        elif self.speech.state is State.PAUSED:
            tip = "Paused"
        elif self.speech.busy:
            tip = f"Speaking: {self._progress_label}" if self._progress_label != "Ready" else "Speaking..."
        else:
            tip = ""
        self.tray.set_state(tip, stt_state is SttState.RECORDING, self.window.windowIcon())

    def _retry_hotkeys(self, attempt):
        """A hotkey can be busy for a moment (a previous copy still closing): try again before
        telling the user."""
        if self._quitting:
            return
        self._apply_global_hotkeys()
        if not any(self._hotkey_errors.values()):
            return
        if attempt < len(HOTKEY_RETRY_MS):
            QTimer.singleShot(HOTKEY_RETRY_MS[attempt], lambda: self._retry_hotkeys(attempt + 1))
        else:
            self._report_hotkey_errors()

    def _report_hotkey_errors(self):
        """Say which keys another app has: in the status bar each time, in a pop-up only the
        first time that key is found taken (not on every start)."""
        taken = {a: self.settings["global_hotkeys"].get(a, "") for a, err in self._hotkey_errors.items() if err}
        if not taken:
            return
        names = ", ".join(f"{combo or '?'} ({keys.GLOBAL_HOTKEY_LABELS.get(a, a)})" for a, combo in taken.items())
        text = f"Another app uses {names}. Pick other keys in Settings > Shortcuts."
        self._status(text)
        seen = set(self.settings["hotkey_conflicts_seen"])
        found = {f"{a}={combo}" for a, combo in taken.items()}
        if found - seen:
            self._toast(text, 7000)
            self.settings.set("hotkey_conflicts_seen", sorted(seen | found))
            self.save_soon()

    def _on_global_hotkey(self, action):
        handlers = {
            "toggle_dictation": self.dictate_external,
            "speak_clipboard": self.speak_clipboard,
            "stop_speech": self.on_stop,
            "toggle_mini": self.toggle_mini,
            "pause_resume": self.on_pause_resume,
            "show_window": self.show_window,
            "cancel_dictation": self.cancel_dictation,
        }
        handler = handlers.get(action)
        if handler:
            handler()

    def handle_commands(self, commands):
        mapping = {
            "show": self.show_window, "mini": self.show_mini, "toggle-dictation": self.dictate_external,
            "speak-clipboard": self.speak_clipboard, "stop": self.on_stop, "pause": self.on_pause_resume,
            "quit": self.request_quit,
        }
        for cmd in commands:
            handler = mapping.get(cmd)
            if handler:
                handler()

    # ======================================================================
    # Geometry, persistence, shutdown
    # ======================================================================
    def _restore_geometry(self):
        s = self.settings
        geo = s["window"]
        placed = False
        if geo:
            rect = QRect(geo["x"], geo["y"], geo["w"], geo["h"])
            # The title bar must be reachable: a point near its left end has to be on a screen
            # (the window may have lived on a monitor that is now unplugged).
            grab = QPoint(rect.left() + min(120, rect.width() // 2), rect.top() + 12)
            for screen in QGuiApplication.screens():
                if screen.availableGeometry().contains(grab):
                    self.window.setGeometry(rect)
                    placed = True
                    break
        if not placed:
            area = QGuiApplication.primaryScreen().availableGeometry()
            w, h = min(1280, int(area.width() * 0.8)), min(820, int(area.height() * 0.8))
            self.window.resize(w, h)
            self.window.move(area.center().x() - w // 2, area.center().y() - h // 2)
        if s["splitter"] and len(s["splitter"]) == 2:
            self.window.splitter.setSizes(s["splitter"])
        self._restore_maximized = bool(geo and geo.get("maximized"))

    def _remember_layout(self):
        w = self.window
        if not w.isVisible():
            return
        maximized = w.isMaximized()
        g = w.normalGeometry() if maximized else w.geometry()
        self.settings.set("window", {"x": g.x(), "y": g.y(), "w": g.width(), "h": g.height(), "maximized": maximized})
        if w.queue_panel.isVisible():
            self.settings.set("splitter", [int(v) for v in w.splitter.sizes()])
        self.save_soon()

    def save_soon(self):
        self._save_timer.start()

    def save_now(self):
        self._save_timer.stop()
        try:
            self.settings.save()
        except OSError as exc:
            self._status(f"Could not save settings: {exc}")

    def show_initial(self, mini=False):
        if mini:
            self.show_mini()
        elif self._restore_maximized:
            self.window.showMaximized()
        else:
            self.window.show()

    def _on_close_requested(self, event):
        self._remember_layout()
        if self._quitting:
            event.accept()
            return
        if self.settings["close_to_tray"] and self.tray is not None:
            event.ignore()
            self.window.hide()
            self._toast("TTSPython is still running in the tray.")
            return
        if not self._confirm_quit():
            event.ignore()
            return
        event.accept()
        self.quit(keep_draft=False)

    def request_quit(self):
        """Quit from the tray or the command line: ask first if the editor has unsaved text."""
        modified = self.editor.document().isModified() and self.editor.toPlainText()
        if modified or self.exporter.running or self.stt.state is not SttState.IDLE:
            self.show_window()
            if not self._confirm_quit():
                return
        self.quit(keep_draft=False)

    # --- recovery of unsaved text --------------------------------------------------------------
    def _recovery_path(self):
        return os.path.join(os.path.dirname(os.path.abspath(self.settings.path)), "recovery.json")

    def _draft_changed(self):
        if self.editor.document().isModified() and not self._draft_timer.isActive():
            self._draft_timer.start()

    def _on_commit_data(self, _manager=None):
        """The session is ending (logoff, shutdown): keep unsaved text for the next start."""
        self._write_recovery()

    def _write_recovery(self):
        if not (self.editor.document().isModified() and self.editor.toPlainText()):
            self._clear_recovery()
            return
        doc = self.current_doc
        data = {"text": self.editor.toPlainText(), "file": self.current_file,
                "encoding": doc.encoding if doc else None, "newline": doc.newline if doc else None,
                "bom": bool(doc.bom) if doc else False, "lossy": bool(doc.lossy) if doc else False}
        try:
            write_json_atomic(self._recovery_path(), data)
        except OSError:
            pass

    def _clear_recovery(self):
        try:
            os.remove(self._recovery_path())
        except OSError:
            pass

    def restore_recovery(self):
        """Put back text kept at the end of the last session. Returns True if any was restored."""
        path = self._recovery_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return False
        text = data.get("text") if isinstance(data, dict) else None
        if not isinstance(text, str) or not text:
            self._clear_recovery()
            return False
        # The file stays until the next draft or a clean quit replaces it: a second crash must not lose the text.
        self.editor.setPlainText(text)
        file = data.get("file")
        if isinstance(file, str) and file:
            self.current_file = file
            self.current_doc = textio.TextDocument(text, data.get("encoding") or "utf-8",
                                                   data.get("newline") or os.linesep, bool(data.get("bom")),
                                                   bool(data.get("lossy")))
            self.window.editor_card.set_title(os.path.basename(file))
        self.editor.document().setModified(True)
        return True

    def quit(self, keep_draft=True):
        """keep_draft: save unsaved editor text for the next start (False once the user chose to discard)."""
        if self._quitting:
            return
        self._quitting = True
        if keep_draft:
            self._write_recovery()
        else:
            self._clear_recovery()
        if self.window.isVisible():
            self._remember_layout()
        try:
            QGuiApplication.clipboard().dataChanged.disconnect(self._on_clipboard)
        except (RuntimeError, TypeError):
            pass
        self._clip_poll.stop()
        self._draft_timer.stop()
        if self._queue_save_timer.isActive():
            self._queue_save_timer.stop()
            self._save_queue()
        for bridge in (self.speech_bridge, self.stt_bridge, self.export_bridge):
            bridge.blockSignals(True)
        self.exporter.cancel()
        self.speech.shutdown()
        self.stt.shutdown()
        self.hotkeys.stop()
        self.save_now()
        self.mini.close()
        self.popover.close()
        self.float_toast.close()
        self.caption.close()
        if self.tray:
            self.tray.hide()
        self.app.quit()
