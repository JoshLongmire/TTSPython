"""The full application window."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMainWindow, QSplitter, QStatusBar, QVBoxLayout, QWidget,
)

from .. import __version__
from .editor import EditorCard
from .panels import ListenPanel, QueuePanel, TransportBar
from .widgets import AppMark, ElidedLabel, Segmented, Toast, ToggleSwitch, action_button


class MainWindow(QMainWindow):
    close_requested = Signal(object)  # QCloseEvent
    STATUS_TEXT_ROOM = 300  # the status bar keeps this much for its messages

    def __init__(self, actions, parent=None):
        super().__init__(parent)
        self.actions = actions
        self.setWindowTitle("TTSPython")
        self.setMinimumSize(760, 500)

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_app_bar())

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(14, 12, 14, 12)
        bl.setSpacing(12)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(12)
        self.editor_card = EditorCard(actions["paste"], actions["clear"])
        self.editor_card.setMinimumHeight(170)  # Listen mode on a small window keeps a few lines
        self.editor = self.editor_card.editor
        self.find_bar = self.editor_card.find_bar
        self.listen_panel = ListenPanel(actions["record"])
        ll.addWidget(self.editor_card, 1)
        ll.addWidget(self.listen_panel)
        self.queue_panel = QueuePanel(actions)
        self.splitter.addWidget(left)
        self.splitter.addWidget(self.queue_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([900, 300])
        bl.addWidget(self.splitter, 1)
        outer.addWidget(body, 1)

        self.transport = TransportBar(actions)
        outer.addWidget(self.transport)

        self._build_status_bar()
        self.toast = Toast(root)
        self.fit_status_bar()
        for action in actions.values():
            self.addAction(action)

    # --- construction ---------------------------------------------------------------
    def _build_app_bar(self):
        bar = QFrame()
        bar.setObjectName("AppBar")
        bar.setFixedHeight(52)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(18, 0, 14, 0)
        lay.setSpacing(10)
        self.mark = AppMark(26)
        title = QLabel("TTSPython")
        title.setObjectName("AppTitle")
        version = QLabel(f"v{__version__}")
        version.setObjectName("VersionChip")
        center = Qt.AlignVCenter
        lay.addWidget(self.mark, 0, center)
        lay.addWidget(title, 0, center)
        lay.addWidget(version, 0, center)
        lay.addStretch(1)
        self.mode_switch = Segmented([("tts", "Speak", "voices"), ("stt", "Listen", "mic")])
        self.mode_switch.setToolTip("Speak reads text aloud. Listen turns your voice into text.")
        lay.addWidget(self.mode_switch, 0, center)
        lay.addStretch(1)
        tools = QHBoxLayout()
        tools.setSpacing(2)
        a = self.actions
        for key in ("open", "save", "save_as", "export"):
            btn = action_button(a[key])
            if key == "open":
                self.open_button = btn
            tools.addWidget(btn)
        sep = QFrame()
        sep.setFixedSize(1, 22)
        sep.setObjectName("VSep")
        tools.addSpacing(6)
        tools.addWidget(sep)
        tools.addSpacing(6)
        for key in ("find", "mini_mode", "settings"):
            tools.addWidget(action_button(a[key]))
        lay.addLayout(tools)
        return bar

    def _build_status_bar(self):
        sb = QStatusBar()
        sb.setSizeGripEnabled(False)
        self.setStatusBar(sb)
        self.status_label = ElidedLabel("Ready")
        self.status_label.setObjectName("StatusText")
        sb.addWidget(self.status_label, 1)

        self.export_status = QLabel("")
        self.export_status.hide()
        self.export_cancel = action_button(self.actions["export_cancel"], size=14)
        self.export_cancel.hide()
        self.export_open = action_button(self.actions["export_open"], show_text=True, size=14)
        self.export_open.hide()
        sb.addPermanentWidget(self.export_status)
        sb.addPermanentWidget(self.export_cancel)
        sb.addPermanentWidget(self.export_open)

        group = QWidget()
        gl = QHBoxLayout(group)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(8)
        self.clip_switch = ToggleSwitch("Clipboard")
        self.clip_switch.setToolTip("Watch the clipboard and speak or queue copied text")
        self.clip_mode = Segmented([("speak", "Speak", None), ("queue", "Queue", None)])
        self.clip_mode.setObjectName("SegmentedSmall")
        self.clip_mode.setToolTip("What to do with copied text")
        self.auto_queue = ToggleSwitch("Auto-Queue")
        self.auto_queue.setToolTip("Queue copied text while speech is playing, and read the queue when reading ends")
        gl.addWidget(self.clip_switch)
        gl.addWidget(self.clip_mode)
        gl.addWidget(self.auto_queue)
        sb.addPermanentWidget(group)

        self.perf_switch = ToggleSwitch("Performance")
        self.perf_switch.setToolTip("Performance Mode: fewer animations and lighter updates for slower PCs")
        sb.addPermanentWidget(self.perf_switch)
        self.device_chip = ElidedLabel("")
        self.device_chip.setObjectName("StatusChip")
        self.device_chip.set_clickable("Change where speech plays (Settings > Speech)")
        self.device_chip.setMinimumWidth(120)
        self.device_chip.setMaximumWidth(220)
        sb.addPermanentWidget(self.device_chip)
        self.clip_switch.toggled.connect(self.fit_status_bar)

    # --- helpers ------------------------------------------------------------------------
    def set_status(self, text):
        self.status_label.setText(text)

    def show_toast(self, text, ms=2600):
        self.toast.show_message(text, ms)

    def set_mode(self, mode):
        self.mode_switch.set_value(mode)
        self.listen_panel.setVisible(mode == "stt")

    def set_queue_visible(self, visible):
        self.queue_panel.setVisible(visible)

    def refresh_icons(self):
        self.editor_card.refresh_icons()
        self.transport.refresh_icons()
        self.mark.update()

    def fit_status_bar(self, *_):
        """Speak or Queue only means something while the clipboard is watched. In a narrow window the
        output chip, then the Performance switch (both also in Settings), give way to the status text."""
        watching = self.clip_switch.isChecked()
        self.clip_mode.setVisible(watching)
        room = self.width() - self.STATUS_TEXT_ROOM - self.clip_switch.sizeHint().width()
        room -= self.auto_queue.sizeHint().width() + 8
        if watching:
            room -= self.clip_mode.minimumSizeHint().width() + 8
        room -= self.perf_switch.sizeHint().width() + 8
        self.perf_switch.setVisible(room >= 0)
        self.device_chip.setVisible(room >= self.device_chip.minimumWidth() + 8)

    def resizeEvent(self, event):  # noqa: N802
        self.fit_status_bar()
        super().resizeEvent(event)

    def closeEvent(self, event):  # noqa: N802
        self.close_requested.emit(event)
