"""Settings: side navigation with one page per area."""
from __future__ import annotations

import copy

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QKeySequenceEdit, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QRadioButton, QScrollArea,
    QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from ..core import keys, settings as settings_mod
from ..core.stt import preview as preview_mod
from ..core.theme import THEME_PRESETS, derive_tokens
from . import icons
from .widgets import (
    ElidedLabel, ElidingComboBox, Segmented, Slider, ToggleSwitch, Waveform, mute_clear_button, tool_button, voice_label,
)


def _shrinkable(chars=22):
    """A combo box that shortens long names ("...") instead of widening the page."""
    combo = ElidingComboBox(chars=chars)
    combo.setMaximumWidth(340)
    return combo


PAGES = [
    ("appearance", "Appearance", "palette"),
    ("speech", "Speech", "voices"),
    ("listen", "Listen", "mic"),
    ("clipboard", "Clipboard", "clipboard"),
    ("shortcuts", "Shortcuts", "keyboard"),
    ("mini", "Mini mode", "mini"),
    ("general", "General", "settings"),
]


class ThemeCard(QFrame):
    clicked = Signal(str)

    def __init__(self, key, parent=None):
        super().__init__(parent)
        self.key = key
        self.setObjectName("ThemeCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(118, 100)
        self.tokens = derive_tokens(THEME_PRESETS[key])
        self.setToolTip(self.tokens["name"])
        self.setAccessibleName(f"{self.tokens['name']} theme")
        self.setFocusPolicy(Qt.StrongFocus)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.clicked.emit(self.key)
            return
        super().keyPressEvent(event)

    def set_selected(self, selected):
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, _event):  # noqa: N802
        self.clicked.emit(self.key)

    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)
        t = self.tokens
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(6, 6, self.width() - 12, 62)
        p.setPen(QColor(t["border"]))
        p.setBrush(QColor(t["window"]))
        p.drawRoundedRect(r, 8, 8)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(t["surface"]))
        p.drawRoundedRect(QRectF(r.left() + 8, r.top() + 8, r.width() * 0.62, r.height() - 16), 5, 5)
        p.setBrush(QColor(t["muted"]))
        for i, w in enumerate((0.42, 0.34, 0.38)):
            p.drawRoundedRect(QRectF(r.left() + 14, r.top() + 15 + i * 9, r.width() * w, 3), 1.5, 1.5)
        p.setBrush(QColor(t["accent_fill"]))
        p.drawEllipse(QRectF(r.right() - 30, r.center().y() - 11, 22, 22))
        p.setPen(QColor(icons.color("text")))
        p.drawText(QRectF(6, 72, self.width() - 12, 24), Qt.AlignCenter, t["name"])


class SettingRow(QFrame):
    """A setting: its name and help on the left, the control on the right. When the
    page is too narrow for both, the control moves under the text instead of being cut off."""

    STACK_BELOW = 560

    def __init__(self, title, control, help_text="", parent=None, compact=False):
        super().__init__(parent)
        self.setObjectName("SettingRow")
        self._grid = QGridLayout(self)
        margin = 2 if compact else 10
        self._grid.setContentsMargins(0, margin, 0, margin)
        self._grid.setHorizontalSpacing(16)
        self._grid.setVerticalSpacing(8)
        text = QWidget()
        col = QVBoxLayout(text)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        col.addWidget(QLabel(title))
        if help_text:
            h = QLabel(help_text)
            h.setObjectName("Muted")
            h.setWordWrap(True)
            col.addWidget(h)
        if not isinstance(control, QWidget):  # a layout of several controls
            holder = QWidget()
            control.setContentsMargins(0, 0, 0, 0)
            holder.setLayout(control)
            control = holder
        self.text, self.control = text, control
        for widget in (control, *control.findChildren(QWidget)):  # what a screen reader calls it
            if not widget.accessibleName() and not getattr(widget, "text", str)():
                widget.setAccessibleName(title)
        self._stacked = None
        self._place(False)

    def _place(self, stacked):
        if stacked == self._stacked:
            return
        self._stacked = stacked
        self._grid.removeWidget(self.text)
        self._grid.removeWidget(self.control)
        if stacked:
            self._grid.addWidget(self.text, 0, 0)
            self._grid.addWidget(self.control, 1, 0, Qt.AlignLeft)
            self._grid.setColumnStretch(1, 0)
        else:
            self._grid.addWidget(self.text, 0, 0)
            self._grid.addWidget(self.control, 0, 1, Qt.AlignRight | Qt.AlignVCenter)
        self._grid.setColumnStretch(0, 1)

    def resizeEvent(self, event):  # noqa: N802
        self._place(event.size().width() < max(self.STACK_BELOW, self.control.sizeHint().width() + 260))
        super().resizeEvent(event)


class ThemeGrid(QWidget):
    """Theme cards in as many columns as fit."""

    def __init__(self, cards, parent=None):
        super().__init__(parent)
        self.cards = cards
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(10)
        self._columns = 0
        self._arrange(4)

    def _arrange(self, columns):
        if columns == self._columns:
            return
        self._columns = columns
        for card in self.cards:
            self._grid.removeWidget(card)
        for i, card in enumerate(self.cards):
            self._grid.addWidget(card, i // columns, i % columns, Qt.AlignLeft)
        for c in range(8):
            self._grid.setColumnStretch(c, 0)
        self._grid.setColumnStretch(columns, 1)

    def minimumSizeHint(self):  # noqa: N802
        card = self.cards[0].sizeHint() if self.cards else QSize(118, 100)
        return QSize(card.width(), card.height())

    def resizeEvent(self, event):  # noqa: N802
        card_w = (self.cards[0].width() if self.cards else 118) + self._grid.spacing()
        self._arrange(max(1, min(6, (event.size().width() + self._grid.spacing()) // card_w)))
        super().resizeEvent(event)


class MicMeter(Waveform):
    """Live input level from the selected mic while visible."""

    def __init__(self, parent=None):
        super().__init__(bars=26, parent=parent)
        self.setFixedHeight(26)
        self.setMinimumWidth(160)
        self.color_role = "accent"
        self.device = None
        self._stream = None
        self._level = 0.0

    def _cb(self, indata, frames, _t, _s):
        import numpy as np

        self._level = min(1.0, float(np.sqrt(np.mean(np.square(indata[:, 0])))) * 6.0)

    def start(self, device):
        self.stop()
        self.device = device
        try:
            import sounddevice as sd

            from ..core.stt.recorder import open_input_stream

            self._stream, _rate = open_input_stream(sd, device, 16000, self._cb, dtype="float32", blocksize=512)
            self._stream.start()
            self.set_source(lambda: self._level)
        except Exception:
            self._stream = None
            self.set_source(None)

    def stop(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
        self._stream = None
        self.set_source(None)


class SettingsDialog(QDialog):
    """Edits a working copy; Save hands it to the app controller."""

    saved = Signal(dict)
    preview_theme = Signal(str)
    action_requested = Signal(str)  # "unload_model", "test_voice", "reset_mini", "open_sound", "add_voices", ...

    def __init__(self, ctx, parent=None, initial_page="appearance"):
        super().__init__(parent)
        self.ctx = ctx  # AppController: provides settings, voices, devices, hotkey status
        self.setWindowTitle("Settings")
        self.setMinimumSize(660, 440)
        self.resize(920, 640)
        self.saved_values = copy.deepcopy(ctx.settings.data)
        self.values = copy.deepcopy(self.saved_values)
        self._hotkeys_paused = False
        self._closing_handled = False
        self._clear_lines = []  # the shortcut boxes' inner text boxes, kept for their themed clear icons
        self._devices_ready = False  # the device lists are filled when Speech or Listen is first shown

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setFixedWidth(172)
        self.nav.setIconSize(QSize(18, 18))
        self.stack = QStackedWidget()
        self._page_index = {}
        builders = {
            "appearance": self._page_appearance, "speech": self._page_speech, "listen": self._page_listen,
            "clipboard": self._page_clipboard, "shortcuts": self._page_shortcuts, "mini": self._page_mini,
            "general": self._page_general,
        }
        for key, title, icon_name in PAGES:
            item = QListWidgetItem(icons.icon(icon_name, "muted"), title)
            self.nav.addItem(item)
            self._page_index[key] = self.stack.count()
            self.stack.addWidget(self._scroll(builders[key]()))
        self.nav.currentRowChanged.connect(self._page_changed)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addWidget(self.stack, 1)
        buttons = QFrame()
        buttons.setObjectName("Transport")
        bl = QHBoxLayout(buttons)
        bl.setContentsMargins(20, 12, 20, 12)
        reset = QPushButton("Reset to Defaults")
        reset.setProperty("variant", "ghost")
        reset.setToolTip("Put every setting on these pages back to its default (Save to keep)")
        cancel = QPushButton("Cancel")
        cancel.setToolTip("Close without saving (undoes previews)")
        save = QPushButton("Save")
        save.setProperty("variant", "primary")
        save.setToolTip("Save and close")
        save.setDefault(True)
        bl.addWidget(reset)
        bl.addStretch(1)
        bl.addWidget(cancel)
        bl.addWidget(save)
        right.addWidget(buttons)
        root.addWidget(self.nav)
        root.addLayout(right, 1)

        reset.clicked.connect(self._reset)
        cancel.clicked.connect(self._cancel_and_close)
        save.clicked.connect(self._save_and_close)

        self._load_fields(self.values)
        self.nav.setCurrentRow(self._page_index.get(initial_page, 0))

    # --- layout helpers ----------------------------------------------------------------
    def _scroll(self, widget):
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # rows reflow instead
        area.setWidget(widget)
        return area

    def _page(self, title, subtitle):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(4)
        t = QLabel(title)
        t.setObjectName("PageTitle")
        s = QLabel(subtitle)
        s.setObjectName("PageSubtitle")
        s.setWordWrap(True)
        lay.addWidget(t)
        lay.addWidget(s)
        lay.addSpacing(14)
        return page, lay

    def _row(self, lay, title, control, help_text="", compact=False):
        row = SettingRow(title, control, help_text, compact=compact)
        lay.addWidget(row)
        return row

    @staticmethod
    def _percent_label():
        """The value beside a slider, flush with the right edge the other controls line up on."""
        label = QLabel()
        label.setObjectName("Muted")
        label.setFixedWidth(40)
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return label

    def _section(self, lay, text):
        lab = QLabel(text.upper())
        lab.setObjectName("SectionLabel")
        lay.addSpacing(14)
        lay.addWidget(lab)

    # --- pages ----------------------------------------------------------------------
    def _page_appearance(self):
        page, lay = self._page("Appearance", "Pick a theme. It previews right away; Save keeps it.")
        self.theme_cards = {}
        for key in THEME_PRESETS:
            card = ThemeCard(key)
            card.clicked.connect(self._theme_clicked)
            self.theme_cards[key] = card
        lay.addWidget(ThemeGrid(list(self.theme_cards.values())))
        self._section(lay, "Performance")
        self.performance = ToggleSwitch()
        self._row(lay, "Performance Mode", self.performance,
                  "Fewer animations and lighter updates for slower PCs.")
        lay.addStretch(1)
        return page

    def _page_speech(self):
        page, lay = self._page("Speech", "Voice, speed, volume and where speech plays.")
        self.voice = _shrinkable(26)
        voices_row = QHBoxLayout()
        refresh = tool_button("refresh", "Refresh the voice list")
        add = QPushButton("Get more voices")
        refresh.clicked.connect(lambda: self.action_requested.emit("refresh_voices"))
        add.clicked.connect(lambda: self.action_requested.emit("add_voices"))
        voices_row.addWidget(self.voice)
        voices_row.addWidget(refresh)
        voices_row.addWidget(add)
        self._row(lay, "Voice", voices_row, "This computer's voices and the natural voices you downloaded.")
        self.rate = Slider()
        self.rate.setRange(settings_mod.speed_percent(settings_mod.RATE_MIN), settings_mod.speed_percent(settings_mod.RATE_MAX))
        self.rate.setSingleStep(5)
        self.rate.setPageStep(10)
        self.rate.setMinimumWidth(140)
        self.rate.setMaximumWidth(240)
        self.rate_label = self._percent_label()
        self.rate.valueChanged.connect(self._rate_moved)
        rr = QHBoxLayout()
        rr.addWidget(self.rate)
        rr.addWidget(self.rate_label)
        self._row(lay, "Speed", rr, "100% is normal. Changes are heard right away, even mid-sentence.")
        self.volume = Slider()
        self.volume.setRange(10, 100)
        self.volume.setMinimumWidth(140)
        self.volume.setMaximumWidth(240)
        self.volume_label = self._percent_label()
        self.volume.valueChanged.connect(self._volume_moved)
        vr = QHBoxLayout()
        vr.addWidget(self.volume)
        vr.addWidget(self.volume_label)
        self._row(lay, "Volume", vr)
        self.highlight = ToggleSwitch()
        self._row(lay, "Highlight the sentence being spoken", self.highlight,
                  "The editor follows along while it reads.")
        self._section(lay, "Output")
        self.output = _shrinkable()
        test = QPushButton("Test")
        test.clicked.connect(lambda: self.action_requested.emit("test_voice"))
        sound = QPushButton("Sound settings")
        sound.clicked.connect(lambda: self.action_requested.emit("open_sound"))
        orow = QHBoxLayout()
        orow.addWidget(self.output)
        orow.addWidget(self._refresh_devices_button())
        orow.addWidget(test)
        orow.addWidget(sound)
        self._row(lay, "Output device", orow, "Speech plays here. Test uses the device picked here.")
        self.device_note = QLabel()
        self.device_note.setObjectName("ErrorText")
        self.device_note.hide()  # shown only with a message (an empty label still takes a row)
        lay.addWidget(self.device_note)
        lay.addStretch(1)
        return page

    def _page_listen(self):
        page, lay = self._page("Listen", "Offline dictation with faster-whisper. Nothing leaves this computer.")
        self.input = _shrinkable()
        self.input.currentIndexChanged.connect(self._restart_meter)
        irow = QHBoxLayout()
        irow.addWidget(self.input)
        irow.addWidget(self._refresh_devices_button())
        self._row(lay, "Microphone", irow)
        self.meter = MicMeter()
        self._row(lay, "Input level", self.meter, "Speak to check the microphone is picking you up.")
        self.model = _shrinkable(18)
        for name, label in settings_mod.WHISPER_MODELS:
            self.model.addItem(label, name)
        self.model_status = QLabel()
        self.model_status.setObjectName("Muted")
        unload = QPushButton("Unload now")
        unload.clicked.connect(lambda: self.action_requested.emit("unload_model"))
        mrow = QHBoxLayout()
        mrow.addWidget(self.model_status)
        mrow.addWidget(self.model)
        mrow.addWidget(unload)
        self._row(lay, "Whisper model", mrow, "Bigger models are more accurate but slower. "
                                              "A model downloads the first time it is used.")
        self.model_note = QLabel()
        self.model_note.setObjectName("ErrorText")
        self.model_note.setWordWrap(True)
        self.model_note.hide()  # shown only with a message (an empty label still takes a row)
        lay.addWidget(self.model_note)
        self.models_box = QVBoxLayout()
        self.models_box.setSpacing(2)
        self._models_loaded = False
        self._row(lay, "Downloaded models", self.models_box, "Delete models you no longer use to free disk space. "
                                                             "A deleted model downloads again when it is needed.")
        self.language = QComboBox()
        for code, label in settings_mod.STT_LANGUAGES:
            self.language.addItem(label, code)
        self._row(lay, "Language", self.language, "English is fastest. Auto-detect works for any language.")
        self.live_preview = ToggleSwitch()
        self._row(lay, "Instant live preview", self.live_preview,
                  "While you dictate into another app, each word shows about half a second after you say it, "
                  f"and Whisper corrects it. English only. Downloads {preview_mod.DOWNLOAD_MB} MB the first time.")
        self._section(lay, "Memory")
        self.unload_idle = ToggleSwitch()
        self._row(lay, "Unload the model after each dictation", self.unload_idle, "Frees RAM right away.")
        self.auto_unload = ToggleSwitch()
        self.auto_unload.toggled.connect(self._sync_dependents)
        self.auto_unload_minutes = QSpinBox()
        self.auto_unload_minutes.setRange(1, 60)
        self.auto_unload_minutes.setSuffix(" min")
        arow = QHBoxLayout()
        arow.addWidget(self.auto_unload_minutes)
        arow.addWidget(self.auto_unload)
        self._row(lay, "Unload when idle", arow, "Unload the model after this many minutes without dictation.")
        self._section(lay, "Dictating into other apps")
        out = QVBoxLayout()
        self.out_paste = QRadioButton("Type it where my cursor is")
        self.out_clip = QRadioButton("Copy it to the clipboard only")
        self.out_paste.toggled.connect(self._sync_dependents)
        group = QButtonGroup(self)
        group.addButton(self.out_paste)
        group.addButton(self.out_clip)
        out.addWidget(self.out_paste)
        out.addWidget(self.out_clip)
        self._row(lay, "When dictating from mini mode or a global hotkey", out)
        self.keystroke = QComboBox()
        self.keystroke.addItem("Ctrl+V", "ctrl+v")
        self.keystroke.addItem("Shift+Insert (terminals)", "shift+insert")
        self._row(lay, "Paste using", self.keystroke)
        lay.addStretch(1)
        return page

    def _page_clipboard(self):
        page, lay = self._page("Clipboard", "Read copied text aloud or collect it in the queue.")
        self.clip_monitor = ToggleSwitch()
        self.clip_monitor.toggled.connect(self._sync_dependents)
        self._row(lay, "Watch the clipboard", self.clip_monitor, "Copied text of 6 characters or more is used.")
        self.clip_action = Segmented([("speak", "Speak it", None), ("queue", "Add to queue", None)])
        self._row(lay, "When text is copied", self.clip_action)
        self.clip_auto_queue = ToggleSwitch()
        self._row(lay, "Auto-Queue", self.clip_auto_queue,
                  "While speech is playing, queue copied text instead of ignoring it. When reading ends, the queue is read next.")
        lay.addStretch(1)
        return page

    def _shortcut_rows(self, lay, labels, edits):
        for action, label_text in labels.items():
            row = QHBoxLayout()
            edit = QKeySequenceEdit()
            edit.setMaximumSequenceLength(1)
            edit.setClearButtonEnabled(True)
            self._clear_lines.append(edit.findChild(QLineEdit))
            mute_clear_button(self._clear_lines[-1])
            edit.setMinimumWidth(150)
            edit.setMaximumWidth(220)
            edit.keySequenceChanged.connect(self._check_conflicts)
            edit.installEventFilter(self)
            status = QLabel()
            status.setObjectName("ErrorText")
            row.addWidget(status)
            row.addWidget(edit)
            edits[action] = (edit, status)
            self._row(lay, label_text, row, compact=True)

    def _page_shortcuts(self):
        page, lay = self._page("Shortcuts", "Click a box and press the new key combination.")
        self._section(lay, "In the app window")
        self.shortcut_edits = {}
        self._shortcut_rows(lay, keys.SHORTCUT_LABELS, self.shortcut_edits)
        self._section(lay, "Anywhere (global hotkeys)")
        available, reason = self.ctx.hotkey_availability()
        self._global_available = available
        if not available:
            banner = QLabel(reason + " You can bind these commands in your desktop's keyboard settings instead:\n"
                            "TTSPython.py --toggle-dictation, --speak-clipboard, --stop, --pause, --mini, --show")
            banner.setObjectName("Banner")
            banner.setWordWrap(True)
            banner.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lay.addWidget(banner)
        self.global_enabled = ToggleSwitch()
        self.global_enabled.setEnabled(available)
        self.global_enabled.toggled.connect(self._sync_dependents)
        self._row(lay, "Enable global hotkeys", self.global_enabled, "They work even when TTSPython is in the background.")
        self.global_edits = {}
        self._shortcut_rows(lay, keys.GLOBAL_HOTKEY_LABELS, self.global_edits)
        lay.addStretch(1)
        return page

    def _page_mini(self):
        page, lay = self._page("Mini mode", "A small bar that floats over other apps.")
        self.mini_snap = ToggleSwitch()
        self._row(lay, "Snap to screen edges", self.mini_snap)
        self.mini_wave = ToggleSwitch()
        self._row(lay, "Show the live waveform", self.mini_wave)
        reset = QPushButton("Reset position")
        reset.clicked.connect(lambda: self.action_requested.emit("reset_mini"))
        self._row(lay, "Position", reset, "Move the bar back to the bottom-right corner.")
        lay.addStretch(1)
        return page

    def _page_general(self):
        page, lay = self._page("General", "Window behavior and where settings are stored.")
        self.close_to_tray = ToggleSwitch()
        tray_ok = self.ctx.tray_available()
        self.close_to_tray.setEnabled(tray_ok)
        self._row(lay, "Closing the window keeps TTSPython running in the tray", self.close_to_tray,
                  "Quit from the tray icon menu." if tray_ok else "No system tray was found on this desktop.")
        path = ElidedLabel(self.ctx.settings.path, Qt.ElideMiddle)
        path.setObjectName("Muted")
        open_btn = QPushButton("Open folder")
        open_btn.clicked.connect(lambda: self.action_requested.emit("open_settings_folder"))
        prow = QHBoxLayout()
        prow.addWidget(path, 1)
        prow.addWidget(open_btn)
        self._row(lay, "Settings file", prow)
        lay.addStretch(1)
        return page

    def _refresh_devices_button(self):
        btn = tool_button("refresh", "Look for newly connected speakers and microphones")
        btn.clicked.connect(self.refresh_devices)
        return btn

    def refresh_devices(self):
        self.meter.stop()
        ok = self.ctx.rescan_devices()
        self.device_note.setText("" if ok else "Stop speech and dictation first, then refresh.")
        self.device_note.setVisible(not ok)
        self._fill_devices(self.output, "output", self.output.currentData())
        self._fill_devices(self.input, "input", self.input.currentData())
        self._restart_meter()

    # --- data binding ------------------------------------------------------------------
    def _fill_devices(self, combo, kind, ref):
        from ..core import audio_devices

        combo.blockSignals(True)
        combo.clear()
        combo.addItem("System default", None)
        default_api = self.ctx.default_hostapi()
        for dev in self.ctx.list_devices(kind):
            combo.addItem(audio_devices.label(dev, default_api), dev.ref())
        idx = 0
        if ref:
            exact = loose = None
            for i in range(1, combo.count()):
                data = combo.itemData(i)
                if data and data["name"] == ref.get("name"):
                    if data["hostapi"] == ref.get("hostapi") and exact is None:
                        exact = i
                    if loose is None:
                        loose = i
            # Same rule as audio_devices.resolve: same name and host API, else same name.
            match = exact if exact is not None else loose
            if match is not None:
                idx = match
            else:
                combo.addItem(f"{ref.get('name') or 'Device ' + str(ref.get('index'))} (not connected)", ref)
                idx = combo.count() - 1
        combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def _load_fields(self, v):
        self._select_theme_card(v["theme_preset"])
        self.performance.setChecked(v["performance_mode"])
        self._fill_voices()
        idx = self.voice.findData(v["tts_voice_id"])
        if idx < 0:  # not saved yet, or no longer installed: show the voice in use
            idx = self.voice.findData(self.ctx.current_voice_id())
        self.voice.setCurrentIndex(max(0, idx))
        for slider in (self.rate, self.volume):
            slider.blockSignals(True)
        self.rate.setValue(settings_mod.speed_percent(v["tts_rate"]))
        self.rate_label.setText(f"{self.rate.value()}%")
        self.volume.setValue(int(round(v["tts_volume"] * 100)))
        self.volume_label.setText(f"{self.volume.value()}%")
        for slider in (self.rate, self.volume):
            slider.blockSignals(False)
        if self._devices_ready:
            self._fill_devices(self.output, "output", v["tts_output_device"])
            self._fill_devices(self.input, "input", v["stt_input_device"])
        self.highlight.setChecked(v["sentence_highlight"])
        idx = self.model.findData(v["stt_whisper_model"])
        if idx < 0:
            self.model.addItem(v["stt_whisper_model"], v["stt_whisper_model"])
            idx = self.model.count() - 1
        self.model.setCurrentIndex(idx)
        self.update_model_status()
        self.language.setCurrentIndex(max(0, self.language.findData(v["stt_language"])))
        self.live_preview.setChecked(v["stt_live_preview"])
        self.unload_idle.setChecked(v["stt_unload_model_when_idle"])
        self.auto_unload.setChecked(v["stt_auto_unload_enabled"])
        self.auto_unload_minutes.setValue(v["stt_auto_unload_minutes"])
        (self.out_paste if v["dictation_output"] == "paste" else self.out_clip).setChecked(True)
        self.keystroke.setCurrentIndex(max(0, self.keystroke.findData(v["paste_keystroke"])))
        self.clip_monitor.setChecked(v["clipboard_monitor"])
        self.clip_action.set_value(v["clipboard_action"])
        self.clip_auto_queue.setChecked(v["clipboard_auto_queue"])
        for action, (edit, _status) in self.shortcut_edits.items():
            edit.setKeySequence(QKeySequence(v["shortcuts"].get(action, "")))
        self.global_enabled.setChecked(v["global_hotkeys_enabled"])
        for action, (edit, _status) in self.global_edits.items():
            edit.setKeySequence(QKeySequence(v["global_hotkeys"].get(action, "")))
        self.mini_snap.setChecked(v["mini_snap"])
        self.mini_wave.setChecked(v["mini_waveform"])
        self.close_to_tray.setChecked(v["close_to_tray"] and self.ctx.tray_available())
        self._check_conflicts()
        self._sync_dependents()
        self._restart_meter()  # the mic list was refilled with signals blocked

    def _fill_voices(self):
        self.voice.clear()
        for voice in self.ctx.voices():
            self.voice.addItem(voice_label(voice.name), voice.id)
            self.voice.setItemData(self.voice.count() - 1, voice.name, Qt.ToolTipRole)

    def _sync_dependents(self, *_):
        """Grey out what a switch above it has turned off (the values are kept)."""
        self.clip_action.setEnabled(self.clip_monitor.isChecked())
        self.auto_unload_minutes.setEnabled(self.auto_unload.isChecked())
        self.keystroke.setEnabled(self.out_paste.isChecked())
        for edit, _status in self.global_edits.values():
            edit.setEnabled(self._global_available and self.global_enabled.isChecked())

    def _read_fields(self):
        """The settings to save: only fields changed in this dialog.

        Voice, clipboard and Performance Mode can also change from the main window
        while this non-modal dialog is open; untouched fields must not overwrite those
        live values. Speed and volume are not here: they apply (and save) as they move.
        """
        form = self.form_values()
        changed = {}
        for key, value in form.items():
            before = self.saved_values.get(key)
            if before != value:
                changed[key] = value
        return changed

    def form_values(self):
        """Every setting shown in this dialog, as currently entered."""
        v = {"theme_preset": self.values["theme_preset"]}
        v["performance_mode"] = self.performance.isChecked()
        v["tts_voice_id"] = self.voice.currentData() or self.values["tts_voice_id"]
        v["tts_output_device"] = self.output.currentData() if self._devices_ready else self.values["tts_output_device"]
        v["sentence_highlight"] = self.highlight.isChecked()
        v["stt_input_device"] = self.input.currentData() if self._devices_ready else self.values["stt_input_device"]
        v["stt_whisper_model"] = self.model.currentData()
        v["stt_language"] = self.language.currentData()
        v["stt_live_preview"] = self.live_preview.isChecked()
        v["stt_unload_model_when_idle"] = self.unload_idle.isChecked()
        v["stt_auto_unload_enabled"] = self.auto_unload.isChecked()
        v["stt_auto_unload_minutes"] = self.auto_unload_minutes.value()
        v["dictation_output"] = "paste" if self.out_paste.isChecked() else "clipboard"
        v["paste_keystroke"] = self.keystroke.currentData()
        v["clipboard_monitor"] = self.clip_monitor.isChecked()
        v["clipboard_action"] = self.clip_action.value() or "speak"
        v["clipboard_auto_queue"] = self.clip_auto_queue.isChecked()
        v["shortcuts"] = {a: e.keySequence().toString(QKeySequence.PortableText) for a, (e, _s) in self.shortcut_edits.items()}
        v["global_hotkeys_enabled"] = self.global_enabled.isChecked()
        v["global_hotkeys"] = {a: e.keySequence().toString(QKeySequence.PortableText) for a, (e, _s) in self.global_edits.items()}
        v["mini_snap"] = self.mini_snap.isChecked()
        v["mini_waveform"] = self.mini_wave.isChecked()
        # Without a tray the switch is disabled; keep the user's saved preference.
        v["close_to_tray"] = self.close_to_tray.isChecked() if self.ctx.tray_available() else self.values["close_to_tray"]
        return v

    def _check_conflicts(self):
        local = {a: e.keySequence().toString(QKeySequence.PortableText) for a, (e, _s) in self.shortcut_edits.items()}
        glob = {"global:" + a: e.keySequence().toString(QKeySequence.PortableText) for a, (e, _s) in self.global_edits.items()}
        # In-window shortcuts must be unique, global ones must be unique, and a global
        # hotkey must not shadow an in-window shortcut (the OS would take it first).
        conflicts = keys.find_conflicts({**local, **glob})
        clashing = {a for actions in conflicts.values() for a in actions}
        for action, (_edit, status) in self.shortcut_edits.items():
            status.setText("Used twice" if action in clashing else "")
        errors = self.ctx.hotkey_errors()
        registered = self.saved_values.get("global_hotkeys", {})
        refused = False
        for action, (_edit, status) in self.global_edits.items():
            # A registration error belongs to the saved combo; hide it once the box is edited.
            error = errors.get(action) if glob["global:" + action] == registered.get(action, "") else None
            problem = keys.global_hotkey_problem(glob["global:" + action])
            refused = refused or bool(problem)
            status.setText("Used twice" if "global:" + action in clashing else (problem or error or ""))
        return not conflicts and not refused

    def refresh_models(self):
        """List the downloaded Whisper models with their size and a Delete button."""
        self._models_loaded = True
        while self.models_box.count():
            item = self.models_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        models = self.ctx.downloaded_models()
        if not models:
            none = QLabel("None yet")
            none.setObjectName("Muted")
            self.models_box.addWidget(none)
            return
        for name, size in models:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            label = QLabel(f"{name}  ·  {size / 1e6:,.0f} MB")
            delete = QPushButton("Delete")
            delete.clicked.connect(lambda _=False, n=name: self._delete_model(n))
            rl.addWidget(label, 1)
            rl.addWidget(delete)
            self.models_box.addWidget(row)

    def _delete_model(self, name):
        message = self.ctx.delete_model(name)
        if message:
            self.model_note.setText(message)
        self.model_note.setVisible(bool(message))
        self.refresh_models()
        self.update_model_status()

    def update_model_status(self):
        loaded = self.ctx.loaded_model()
        self.model_status.setText(f"Loaded: {loaded}" if loaded else "Not loaded")

    # --- events --------------------------------------------------------------------------
    def eventFilter(self, obj, event):  # noqa: N802
        # While a shortcut box is being filled in, the current global hotkeys must not fire
        # (on Windows they would also swallow the keys, so the box could never record them).
        if isinstance(obj, QKeySequenceEdit):
            if event.type() == QEvent.FocusIn:
                self._set_hotkeys_paused(True)
            elif event.type() == QEvent.FocusOut:
                self._set_hotkeys_paused(False)
        return super().eventFilter(obj, event)

    def _set_hotkeys_paused(self, paused):
        if paused != self._hotkeys_paused:
            self._hotkeys_paused = paused
            self.action_requested.emit("pause_hotkeys" if paused else "resume_hotkeys")

    def _select_theme_card(self, key):
        self.values["theme_preset"] = key
        for k, card in self.theme_cards.items():
            card.set_selected(k == key)

    def _theme_clicked(self, key):
        self._select_theme_card(key)
        self.preview_theme.emit(key)

    def show_page(self, key):
        self.nav.setCurrentRow(self._page_index.get(key, 0))

    def current_page(self):
        return PAGES[self.nav.currentRow()][0]

    def _page_changed(self, row):
        self.stack.setCurrentIndex(row)
        if row in (self._page_index["speech"], self._page_index["listen"]) and not self._devices_ready:
            self.ctx.rescan_devices()  # list a headset plugged in since start (skipped while audio is in use)
            self._devices_ready = True
            self._fill_devices(self.output, "output", self.values["tts_output_device"])
            self._fill_devices(self.input, "input", self.values["stt_input_device"])
        if row == self._page_index["listen"]:
            self._restart_meter()
            if not self._models_loaded:
                self.refresh_models()
        else:
            self.meter.stop()

    def _restart_meter(self, *_):
        if self.stack.currentIndex() != self._page_index["listen"]:
            return
        self.meter.start(self.ctx.resolve_device(self.input.currentData(), "input"))

    def _save(self):
        if not self._check_conflicts():
            self.nav.setCurrentRow(self._page_index["shortcuts"])
            return False
        values = self._read_fields()
        # Speed and volume were applied (and saved) as they moved: keep them from now on.
        for key in ("tts_rate", "tts_volume"):
            values.pop(key, None)
            self.saved_values[key] = self.ctx.settings[key]
        self.saved_values.update(copy.deepcopy(values))
        self.values.update(copy.deepcopy(values))
        self.saved.emit(values)
        self._check_conflicts()
        return True

    def _rate_moved(self, percent):
        self.rate_label.setText(f"{percent}%")
        self.ctx.set_speech_rate(settings_mod.percent_wpm(percent))

    def _volume_moved(self, value):
        self.volume_label.setText(f"{value}%")
        self.ctx.set_speech_volume(value / 100.0)

    def _restore_live_values(self):
        """Speed and volume moved here are live; Cancel (or closing unsaved) puts them back."""
        self.ctx.set_speech_rate(self.saved_values["tts_rate"])
        self.ctx.set_speech_volume(self.saved_values["tts_volume"])

    def unsaved_changes(self):
        return bool(self._read_fields())

    def _save_and_close(self):
        if self._save():
            self._closing_handled = True
            self.accept()

    def _cancel_and_close(self):
        self._cancel()
        self._closing_handled = True
        self.reject()

    def _cancel(self):
        self._restore_live_values()
        self.values = copy.deepcopy(self.saved_values)
        self._load_fields(self.values)
        self.preview_theme.emit(self.values["theme_preset"])
        self.action_requested.emit("sync_engine")

    def _reset(self):
        fresh = settings_mod.defaults()
        self.values.update({k: fresh[k] for k in self.form_values()})
        self.values.update(tts_rate=fresh["tts_rate"], tts_volume=fresh["tts_volume"])
        self.ctx.set_speech_rate(fresh["tts_rate"])  # these two apply as they move, here as well
        self.ctx.set_speech_volume(fresh["tts_volume"])
        self._load_fields(self.values)
        self.preview_theme.emit(self.values["theme_preset"])

    def refresh_icons(self):
        for row, (_key, _title, icon_name) in enumerate(PAGES):
            self.nav.item(row).setIcon(icons.icon(icon_name, "muted"))
        for card in self.theme_cards.values():
            card.update()

    def refresh_voices(self):
        current = self.voice.currentData()
        self.voice.blockSignals(True)
        self._fill_voices()
        self.voice.setCurrentIndex(max(0, self.voice.findData(current)))
        self.voice.blockSignals(False)

    def select_voice(self, voice_id):
        """The voice was switched elsewhere (the voice browser): show it, and keep it on Save."""
        self.saved_values["tts_voice_id"] = voice_id
        self.values["tts_voice_id"] = voice_id
        if self.voice.findData(voice_id) < 0:
            self.voice.addItem(voice_id, voice_id)  # listed properly once the voices refresh
        self.voice.setCurrentIndex(self.voice.findData(voice_id))

    def reject(self):
        """Esc or the title bar: ask before dropping changes made on these pages."""
        if not self._closing_handled and self.unsaved_changes():
            answer = QMessageBox.question(
                self, "Unsaved settings", "Save the changes you made in Settings?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
            if answer == QMessageBox.Cancel:
                return
            if answer == QMessageBox.Save:
                self._save_and_close()
                return
        super().reject()

    def done(self, result):  # noqa: D401
        """Every way of closing ends here: drop unsaved previews."""
        self.meter.stop()
        self._set_hotkeys_paused(False)
        if (self.ctx.settings["tts_rate"], self.ctx.settings["tts_volume"]) != (
                self.saved_values["tts_rate"], self.saved_values["tts_volume"]):
            self._restore_live_values()  # moved here but never saved
        if self.values.get("theme_preset") != self.saved_values.get("theme_preset"):
            self.preview_theme.emit(self.saved_values["theme_preset"])
        self.action_requested.emit("sync_engine")
        super().done(result)
