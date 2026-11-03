"""Get more voices: download Piper voices, remove them, or add system voices."""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar, QPushButton,
    QVBoxLayout,
)

from ..core import platform as plat
from ..core.download import DownloadCancelled
from ..core.tts import piper

KEY_ROLE = Qt.UserRole + 1


class _Relay(QObject):
    """Carries download progress from the worker thread to the dialog."""

    progress = Signal(int, int, str)
    done = Signal(str, str)  # voice id ("" on failure), error message


class VoiceBrowser(QDialog):
    voices_changed = Signal()  # a voice was downloaded or removed
    use_voice = Signal(str)

    def __init__(self, current_voice_id="", parent=None, installer=piper.install_voice, remover=piper.remove_voice):
        super().__init__(parent)
        self.setWindowTitle("Get more voices")
        self.setMinimumSize(520, 460)
        self.resize(620, 560)
        self._install = installer
        self._remove = remover
        self._current = current_voice_id
        self._cancel = None
        self._downloading = None
        self._relay = _Relay(self)
        self._relay.progress.connect(self._on_progress)
        self._relay.done.connect(self._on_done)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(10)
        title = QLabel("Natural voices (Piper)")
        title.setObjectName("PageTitle")
        intro = QLabel(f"These voices run offline on this computer. Each one downloads once (about 60 MB); "
                       f"the first also downloads the Piper program (about {piper.PROGRAM_MB} MB).")
        intro.setObjectName("PageSubtitle")
        intro.setWordWrap(True)
        lay.addWidget(title)
        lay.addWidget(intro)

        top = QHBoxLayout()
        self.language = QComboBox()
        self.language.setToolTip("Language")
        languages = sorted({v.language for v in piper.catalog()})
        for name in languages:
            self.language.addItem(name, name)
        self.language.setCurrentIndex(max(0, self.language.findData("English")))
        self.language.currentIndexChanged.connect(self._fill)
        samples = QPushButton("Hear samples online")
        samples.setProperty("variant", "ghost")
        samples.setToolTip(piper.SAMPLES_PAGE)
        samples.clicked.connect(lambda: plat.open_uri(piper.SAMPLES_PAGE))
        top.addWidget(self.language, 1)
        top.addWidget(samples)
        lay.addLayout(top)

        self.list = QListWidget()
        self.list.setObjectName("VoiceList")
        self.list.setAlternatingRowColors(False)
        self.list.currentItemChanged.connect(lambda *_: self._update_buttons())
        self.list.itemDoubleClicked.connect(lambda _item: self._primary())
        lay.addWidget(self.list, 1)

        self.status = QLabel()
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        lay.addWidget(self.status)
        lay.addWidget(self.progress)

        buttons = QHBoxLayout()
        self.download_btn = QPushButton("Download")
        self.download_btn.setProperty("variant", "primary")
        self.use_btn = QPushButton("Use this voice")
        self.use_btn.setProperty("variant", "primary")
        self.remove_btn = QPushButton("Remove")
        self.cancel_btn = QPushButton("Cancel download")
        self.cancel_btn.hide()
        close = QPushButton("Close")
        self.download_btn.clicked.connect(self._download)
        self.use_btn.clicked.connect(self._use)
        self.remove_btn.clicked.connect(self._remove_selected)
        self.cancel_btn.clicked.connect(self._cancel_download)
        close.clicked.connect(self.close)
        for b in (self.download_btn, self.use_btn, self.remove_btn, self.cancel_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)
        buttons.addWidget(close)
        lay.addLayout(buttons)

        system = QLabel(("Windows voices: add more in Windows Settings > Time & language > Speech."
                         if plat.IS_WINDOWS else "System voices: install espeak-ng language packs with your package manager."))
        system.setObjectName("Muted")
        system.setWordWrap(True)
        lay.addWidget(system)
        if plat.IS_WINDOWS:
            add = QPushButton("Open Windows speech settings")
            add.setProperty("variant", "ghost")
            add.clicked.connect(plat.open_voice_settings)
            lay.addWidget(add, 0, Qt.AlignLeft)

        if not piper.program_available():
            self.status.setText("Piper voices are not available for this computer's processor.")
            self.list.setEnabled(False)
        self._fill()

    # --- list -----------------------------------------------------------------------------------
    def _fill(self, *_):
        keep = self.selected_key()
        installed = set(piper.installed_keys()) if piper.program_installed() else set()
        language = self.language.currentData()
        voices = [v for v in piper.catalog() if v.language == language]
        voices.sort(key=lambda v: (v.key not in installed, v.country, v.name, v.quality != "medium"))
        self.list.clear()
        for v in voices:
            mark = "Installed" + ("  ·  in use" if v.id == self._current else "") if v.key in installed \
                else f"{v.size / 1e6:.0f} MB"
            item = QListWidgetItem(f"{v.label}    {mark}")
            item.setData(KEY_ROLE, v.key)
            item.setToolTip(f"{v.key}  ·  {v.speakers} speaker{'s' if v.speakers != 1 else ''}")
            self.list.addItem(item)
            if v.key == keep:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._update_buttons()

    def selected_key(self):
        item = self.list.currentItem()
        return item.data(KEY_ROLE) if item else None

    def _installed(self, key):
        return piper.program_installed() and key in piper.installed_keys()

    def _update_buttons(self):
        key = self.selected_key()
        busy = self._downloading is not None
        have = bool(key) and self._installed(key)
        self.download_btn.setVisible(not have)
        self.download_btn.setEnabled(bool(key) and not busy)
        self.use_btn.setVisible(have)
        self.use_btn.setEnabled(have and piper.PREFIX + key != self._current)
        self.remove_btn.setEnabled(have and not busy)
        self.cancel_btn.setVisible(busy)
        self.language.setEnabled(not busy)

    def _primary(self):
        key = self.selected_key()
        if key and self._installed(key):
            self._use()
        elif key:
            self._download()

    # --- actions ----------------------------------------------------------------------------------
    def _download(self):
        key = self.selected_key()
        if not key or self._downloading is not None:
            return
        self._downloading = key
        self._cancel = threading.Event()
        self.progress.setRange(0, 0)
        self.progress.show()
        self.status.setText("Starting the download...")
        self._update_buttons()
        relay, cancel = self._relay, self._cancel

        def work():
            try:
                vid = self._install(key, lambda d, t, what: relay.progress.emit(d, t, what), cancel)
                relay.done.emit(vid, "")
            except DownloadCancelled:
                relay.done.emit("", "Download cancelled.")
            except Exception as exc:
                relay.done.emit("", f"Could not download this voice: {exc}")

        threading.Thread(target=work, name="voice-download", daemon=True).start()

    def _on_progress(self, done, total, what):
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(min(done, total))
        thing = "the Piper program" if what == "program" else "the voice"
        self.status.setText(f"Downloading {thing}... {done} of {total} MB")

    def _on_done(self, voice_id, error):
        self._downloading = None
        self._cancel = None
        self.progress.hide()
        if voice_id:
            self.status.setText("Downloaded. Press \"Use this voice\" to switch to it.")
            self.voices_changed.emit()
        else:
            self.status.setText(error)
        self._fill()

    def _cancel_download(self):
        if self._cancel is not None:
            self._cancel.set()
            self.status.setText("Cancelling...")

    def _use(self):
        key = self.selected_key()
        if key and self._installed(key):
            self._current = piper.PREFIX + key
            self.use_voice.emit(self._current)
            self.status.setText("Speech now uses this voice.")
            self._fill()

    def _remove_selected(self):
        key = self.selected_key()
        if not key:
            return
        if piper.PREFIX + key == self._current:
            self.status.setText("This voice is in use. Pick another voice first, then remove it.")
            return
        self._remove(key)
        self.status.setText("Removed.")
        self.voices_changed.emit()
        self._fill()

    def set_current(self, voice_id):
        self._current = voice_id
        self._fill()

    def closeEvent(self, event):  # noqa: N802
        self._cancel_download()
        super().closeEvent(event)
