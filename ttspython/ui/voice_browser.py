"""Get more voices: download Piper voices, remove them, or add system voices."""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QProgressBar, QPushButton,
    QStyle, QStyledItemDelegate, QVBoxLayout,
)

from ..core import platform as plat
from ..core.download import DownloadCancelled
from ..core.tts import piper
from . import icons
from .widgets import mute_clear_button

KEY_ROLE = Qt.UserRole + 1
NAME_ROLE = Qt.UserRole + 2
DETAILS_ROLE = Qt.UserRole + 3
MARK_ROLE = Qt.UserRole + 4
INSTALLED_ROLE = Qt.UserRole + 5


class VoiceDelegate(QStyledItemDelegate):
    """A voice's name and details on the left; its size, or "Installed", lined up on the right."""

    def sizeHint(self, option, _index):  # noqa: N802
        return QSize(option.rect.width(), 34)

    def paint(self, p, option, index):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        selected = bool(option.state & QStyle.State_Selected)
        if selected or option.state & QStyle.State_MouseOver:
            bg = QColor(icons.color("line" if selected else "text"))
            bg.setAlpha(46 if selected else 14)
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(QRectF(option.rect).adjusted(1, 1, -1, -1), 8, 8)
        rect = option.rect.adjusted(10, 0, -10, 0)
        fm = QFontMetrics(option.font)
        mark = index.data(MARK_ROLE) or ""
        mark_w = fm.horizontalAdvance(mark)
        p.setFont(option.font)
        p.setPen(QColor(icons.color("accent" if index.data(INSTALLED_ROLE) else "muted")))
        p.drawText(rect, Qt.AlignRight | Qt.AlignVCenter, mark)
        left = QRect(rect.left(), rect.top(), rect.width() - mark_w - 12, rect.height())
        name = index.data(NAME_ROLE) or ""
        p.setPen(QColor(icons.color("text")))
        p.drawText(left, Qt.AlignLeft | Qt.AlignVCenter, fm.elidedText(name, Qt.ElideRight, left.width()))
        name_w = fm.horizontalAdvance(name) + 8
        p.setPen(QColor(icons.color("muted")))
        p.drawText(left.adjusted(name_w, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(index.data(DETAILS_ROLE) or "", Qt.ElideRight, max(0, left.width() - name_w)))
        p.restore()


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
        intro = QLabel(f"These voices run offline on this computer. Each one downloads once (its size is listed); "
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
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter by name, country or quality")
        self.filter.setClearButtonEnabled(True)
        mute_clear_button(self.filter)
        self.filter.textChanged.connect(self._fill)
        samples = QPushButton("Hear samples online")
        samples.setToolTip(piper.SAMPLES_PAGE)
        samples.clicked.connect(lambda: plat.open_uri(piper.SAMPLES_PAGE))
        top.addWidget(self.language)
        top.addWidget(self.filter, 1)
        top.addWidget(samples)
        lay.addLayout(top)

        self.list = QListWidget()
        self.list.setItemDelegate(VoiceDelegate(self.list))
        self.list.setMouseTracking(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # long names are shortened instead
        self.list.currentItemChanged.connect(lambda *_: self._update_buttons())
        self.list.itemActivated.connect(lambda _item: self._primary())  # double-click or Enter
        lay.addWidget(self.list, 1)

        self.status = QLabel()
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        lay.addWidget(self.status)
        lay.addWidget(self.progress)

        system = QLabel("This computer's own voices are added in Windows Settings."
                        if plat.IS_WINDOWS else "System voices: install espeak-ng language packs with your package manager.")
        system.setObjectName("Muted")
        system.setWordWrap(True)
        system_row = QHBoxLayout()
        system_row.addWidget(system, 1)
        if plat.IS_WINDOWS:
            add = QPushButton("Open speech settings")
            add.clicked.connect(plat.open_voice_settings)
            system_row.addWidget(add)
        lay.addLayout(system_row)

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

        if not piper.program_available():
            self.status.setText("Piper voices are not available for this computer's processor.")
            self.list.setEnabled(False)
        self._fill()

    # --- list -----------------------------------------------------------------------------------
    def _fill(self, *_):
        keep = self.selected_key()
        installed = set(piper.installed_keys()) if piper.program_installed() else set()
        language = self.language.currentData()
        wanted = self.filter.text().lower().split()
        voices = [v for v in piper.catalog() if v.language == language
                  and all(word in f"{v.title} {v.details}".lower() for word in wanted)]
        voices.sort(key=lambda v: (v.key not in installed, v.country, v.name, v.quality != "medium"))
        self.list.clear()
        for v in voices:
            mark = "Installed" + ("  ·  in use" if v.id == self._current else "") if v.key in installed \
                else f"{v.size / 1e6:.0f} MB"
            item = QListWidgetItem(f"{v.label}    {mark}")  # what a screen reader says
            item.setData(KEY_ROLE, v.key)
            item.setData(NAME_ROLE, v.title)
            item.setData(DETAILS_ROLE, v.details)
            item.setData(MARK_ROLE, mark)
            item.setData(INSTALLED_ROLE, v.key in installed)
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
