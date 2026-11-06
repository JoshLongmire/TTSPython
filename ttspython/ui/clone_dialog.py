"""Your own voice: read a statement out loud and the app makes a copy of your voice from that recording."""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton,
    QVBoxLayout, QWidget,
)

from ..core.download import DownloadCancelled
from ..core.resample import resample
from ..core.stt.recorder import Recorder
from ..core.stt.service import friendly_audio_error
from ..core.tts import clone
from ..core.tts.render import Cancelled

RECORD_RATE = 48000
WHISPER_RATE = 16000


class _Stopped(Exception):
    """The person cancelled, or closed the window, while the voice was being made."""


class _Relay(QObject):
    """Carries results from the worker threads to the dialog."""

    progress = Signal(int, int)  # done MB, total MB
    download_done = Signal(str)  # error message, empty when it worked
    status = Signal(str)
    built = Signal(str, float, str)  # voice id ("" on failure), speech per second, error message


class CloneDialog(QDialog):
    voices_changed = Signal()  # a voice was made or removed, or the model came or went
    use_voice = Signal(str)
    hear_voice = Signal(str)
    recording_started = Signal()  # speech has to stop: the microphone would hear it

    def __init__(self, transcribe, current_voice_id="", parent=None, recorder=None, input_device=None, busy_reason=None,
                 installer=clone.install_model, builder=clone.build_voice, speed_check=clone.speed_check,
                 busy_speaking=None, stop_transcribe=None):
        """current_voice_id and input_device may be functions, asked each time they matter.
        busy_reason: why recording cannot start now. busy_speaking: why nothing can be removed now."""
        super().__init__(parent)
        self.setWindowTitle("Your own voice")
        self.setMinimumSize(560, 560)  # all the buttons fit in one row
        self.resize(620, 660)
        self._transcribe = transcribe
        self._recorder = recorder or Recorder(sample_rate=RECORD_RATE)
        self._input_device = input_device
        self._busy_reason = busy_reason or (lambda: "")
        self._busy_speaking = busy_speaking or (lambda: "")
        self._stop_transcribe = stop_transcribe or (lambda: None)
        self._install = installer
        self._build = builder
        self._speed_check = speed_check
        self._current = current_voice_id
        self._cancel = None
        self._stop_work = threading.Event()
        self._work_thread = None
        self._recording = False
        self._working = False
        self._consent = clone.new_consent()
        self._relay = _Relay(self)
        self._relay.progress.connect(self._on_progress)
        self._relay.download_done.connect(self._on_downloaded)
        self._relay.status.connect(self._set_status)
        self._relay.built.connect(self._on_built)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(10)
        title = QLabel("Your own voice")
        title.setObjectName("PageTitle")
        intro = QLabel("Read the statement below out loud and this computer makes a copy of your voice from that "
                       "recording. Only your own voice, read by you: a voice cannot be made from a file. "
                       "Everything stays on this computer.")
        intro.setObjectName("PageSubtitle")
        intro.setWordWrap(True)
        lay.addWidget(title)
        lay.addWidget(intro)

        self.model_box = QWidget()
        model_lay = QVBoxLayout(self.model_box)
        model_lay.setContentsMargins(0, 0, 0, 0)
        note = QLabel(f"First, the voice model has to be downloaded once ({clone.MODEL_MB} MB). While it speaks it uses "
                      f"about {clone.MEMORY_GB} GB of memory and 3 processor cores, and it needs a fairly quick computer.")
        note.setWordWrap(True)
        model_row = QHBoxLayout()
        self.download_btn = self._button("Download the voice model", primary=True)
        self.cancel_btn = self._button("Cancel download")
        self.cancel_btn.hide()
        self.download_btn.clicked.connect(self._download)
        self.cancel_btn.clicked.connect(self._cancel_download)
        model_row.addWidget(self.download_btn)
        model_row.addWidget(self.cancel_btn)
        model_row.addStretch(1)
        model_lay.addWidget(note)
        model_lay.addLayout(model_row)
        lay.addWidget(self.model_box)

        self.record_box = QWidget()
        record_lay = QVBoxLayout(self.record_box)
        record_lay.setContentsMargins(0, 0, 0, 0)
        read_title = QLabel("Read this out loud, in your normal voice:")
        read_title.setObjectName("Muted")
        self.statement = QLabel()
        self.statement.setObjectName("CloneStatement")
        self.statement.setWordWrap(True)
        self.statement.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.statement.setFocusPolicy(Qt.StrongFocus)  # a screen reader has to be able to reach it
        self.statement.setAccessibleName("The statement to read out loud")
        font = self.statement.font()
        font.setPointSizeF(font.pointSizeF() * 1.2)
        self.statement.setFont(font)
        name_row = QHBoxLayout()
        self.name_label = QLabel("&Name")
        self.name = QLineEdit("My voice")
        self.name.setMaxLength(60)
        self.name_label.setBuddy(self.name)
        name_row.addWidget(self.name_label)
        name_row.addWidget(self.name, 1)
        record_row = QHBoxLayout()
        self.record_btn = self._button("Start recording", primary=True)
        self.record_btn.clicked.connect(self._toggle_record)
        self.stop_btn = self._button("Cancel")
        self.stop_btn.setToolTip("Stop making this voice. Nothing is kept.")
        self.stop_btn.hide()
        self.stop_btn.clicked.connect(self._stop_making)
        self.level = QProgressBar()
        self.level.setRange(0, 100)
        self.level.setTextVisible(False)
        self.level.setAccessibleName("Microphone level")
        self.seconds = QLabel("")
        self.seconds.setObjectName("Muted")
        record_row.addWidget(self.record_btn)
        record_row.addWidget(self.stop_btn)
        record_row.addWidget(self.level, 1)
        record_row.addWidget(self.seconds)
        record_lay.addWidget(read_title)
        record_lay.addWidget(self.statement)
        record_lay.addLayout(name_row)
        record_lay.addLayout(record_row)
        lay.addWidget(self.record_box)

        self.status = QLabel()
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName("Progress")
        self.progress.hide()
        lay.addWidget(self.status)
        lay.addWidget(self.progress)

        self.list_label = QLabel("&Your voices")
        lay.addWidget(self.list_label)
        self.list = QListWidget()
        self.list_label.setBuddy(self.list)
        self.list.currentItemChanged.connect(lambda *_: self._update_buttons())
        lay.addWidget(self.list, 1)

        buttons = QHBoxLayout()
        self.use_btn = self._button("Use this voice", primary=True)
        self.hear_btn = self._button("Hear it")
        self.remove_btn = self._button("Remove")
        self.remove_model_btn = self._button("Delete the voice model")
        self.remove_model_btn.setToolTip("Frees the disk space. Your voices are kept, ready for when you download it again.")
        close = self._button("Close")
        self.use_btn.clicked.connect(self._use)
        self.hear_btn.clicked.connect(self._hear)
        self.remove_btn.clicked.connect(self._remove_selected)
        self.remove_model_btn.clicked.connect(self._remove_model)
        close.clicked.connect(self.close)
        for b in (self.use_btn, self.hear_btn, self.remove_btn, self.remove_model_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)
        buttons.addWidget(close)
        lay.addLayout(buttons)

        self._meter = QTimer(self)
        self._meter.setInterval(100)
        self._meter.timeout.connect(self._tick)
        self._elapsed = 0.0
        self._show_statement()
        self._fill()

    @staticmethod
    def _button(text, primary=False):
        button = QPushButton(text)
        button.setAutoDefault(False)  # Enter in the name box must not start a recording
        if primary:
            button.setProperty("variant", "primary")
        return button

    # --- what is shown --------------------------------------------------------------------------
    def _show_statement(self):
        self.statement.setText(self._consent.text)

    def _set_status(self, text):
        self.status.setText(text)
        self._announce(text)

    def _announce(self, text):
        """Say it to a screen reader, which does not follow a label changing by itself."""
        try:
            from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent
        except ImportError:  # Qt before 6.8
            return
        QAccessible.updateAccessibility(QAccessibleAnnouncementEvent(self.status, text))

    def model_status(self, text):
        """What Whisper is doing, while the recording is being checked (it may be downloading)."""
        if self._working:
            self._set_status(text)

    def selected_voice(self):
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _voice_in_use(self):
        return self._current() if callable(self._current) else self._current

    def _fill(self, select=None):
        keep = select or self.selected_voice()
        in_use = self._voice_in_use()
        self.list.clear()
        for voice_id, info in clone.saved_voices():
            label = info.get("name") or "My voice"
            if voice_id == in_use:
                label += "    in use"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, voice_id)
            self.list.addItem(item)
            if voice_id == keep:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._update_buttons()

    def _update_buttons(self):
        have_model = clone.model_installed()
        downloading = self._cancel is not None
        self.model_box.setVisible(not have_model)
        self.download_btn.setVisible(not downloading)
        self.cancel_btn.setVisible(downloading)
        self.record_box.setVisible(have_model)
        self.record_btn.setVisible(not self._working)
        self.stop_btn.setVisible(self._working)
        selected = self.selected_voice()
        self.use_btn.setEnabled(bool(selected) and have_model and selected != self._voice_in_use() and not self._working)
        self.hear_btn.setEnabled(bool(selected) and have_model and not self._working and not self._recording)
        self.remove_btn.setEnabled(bool(selected) and not self._working)
        self.remove_model_btn.setVisible(have_model)
        self.remove_model_btn.setEnabled(not self._working and not self._recording)

    # --- the download ---------------------------------------------------------------------------
    def _download(self):
        if self._cancel is not None:
            return
        self._cancel = threading.Event()
        self.progress.setRange(0, 0)
        self.progress.show()
        self._set_status("Starting the download...")
        self._update_buttons()
        relay, cancel, install = self._relay, self._cancel, self._install

        def work():
            error = ""
            try:
                install(lambda done, total: self._emit(relay.progress, done // 1_000_000, total // 1_000_000), cancel)
            except DownloadCancelled:
                error = "Download cancelled. The files that finished are kept for next time."
            except Exception as exc:
                error = f"Could not download the voice model: {exc}"
            self._emit(relay.download_done, error)

        threading.Thread(target=work, name="clone-download", daemon=True).start()

    @staticmethod
    def _emit(signal, *args):
        try:
            signal.emit(*args)
        except RuntimeError:
            pass  # the window was closed while this was running

    def _on_progress(self, done, total):
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(min(done, total))
        self.status.setText(f"Downloading the voice model... {done} of {total} MB")  # not announced: too many

    def _on_downloaded(self, error):
        self._cancel = None
        self.progress.hide()
        self._set_status(error or "Downloaded. Now read the statement out loud.")
        if not error:
            self.voices_changed.emit()
        self._update_buttons()

    def _cancel_download(self):
        if self._cancel is not None:
            self._cancel.set()
            self._set_status("Cancelling...")

    # --- the recording --------------------------------------------------------------------------
    def _toggle_record(self):
        if self._recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        reason = self._busy_reason()
        if reason:
            self._set_status(reason)
            return
        self.recording_started.emit()
        device = self._input_device() if callable(self._input_device) else self._input_device
        try:
            self._recorder.start(device)
        except Exception as exc:
            self._set_status(f"Could not start recording: {friendly_audio_error(exc)}")
            return
        self._recording = True
        self._elapsed = 0.0
        self.record_btn.setText("Stop recording")
        self._set_status("Recording. Read the whole statement, then press Stop.")
        self._meter.start()
        self._update_buttons()

    @property
    def recording(self):
        return self._recording

    def _tick(self):
        self._elapsed += self._meter.interval() / 1000
        self.level.setValue(int(self._recorder.level * 100))
        self.seconds.setText(f"{self._elapsed:.0f} of {clone.MAX_SECONDS} s")
        if self._elapsed >= clone.MAX_SECONDS:
            self._stop_recording()

    def _stop_recording(self):
        self._meter.stop()
        self._recording = False
        self.level.setValue(0)
        self.seconds.setText("")
        self.record_btn.setText("Start recording")
        audio = self._recorder.stop()
        rate = self._recorder.sample_rate
        problem = clone.check_recording(audio, rate)
        if problem:
            self._set_status(problem)
            self._update_buttons()
            return
        self._working = True
        self._stop_work = threading.Event()
        self.progress.setRange(0, 0)
        self.progress.show()
        self._set_status("Checking the recording...")
        self._update_buttons()
        relay, consent, name, stop = self._relay, self._consent, self.name.text(), self._stop_work
        transcribe, build, speed_check = self._transcribe, self._build, self._speed_check

        def check_stop():
            if stop.is_set():
                raise _Stopped()

        def work():
            voice_id, speed, error = "", 0.0, ""
            try:
                heard = transcribe(resample(audio, rate, WHISPER_RATE))
                check_stop()
                problem = clone.check_consent(consent, heard)
                if problem:
                    raise ValueError(problem)
                self._emit(relay.status, "Making your voice...")
                voice_id = build(name, consent, audio, rate, heard)
                check_stop()
                self._emit(relay.status, "Checking how quickly this computer can speak in it...")
                speed = speed_check(voice_id, stop)
                check_stop()
            except (_Stopped, Cancelled):
                pass
            except ValueError as exc:
                error = str(exc)
            except Exception as exc:
                error = "" if stop.is_set() else f"Could not make your voice: {exc}"
            if stop.is_set() and voice_id:
                clone.remove_voice(voice_id)  # nothing is kept from a voice the person walked away from
                voice_id = ""
            self._emit(relay.built, voice_id, float(speed), error)

        self._work_thread = threading.Thread(target=work, name="clone-build", daemon=True)
        self._work_thread.start()

    def _stop_making(self):
        if self._working and not self._stop_work.is_set():
            self._stop_work.set()
            self._stop_transcribe()  # a first-time Whisper download may be what it is waiting for
            self._set_status("Cancelling...")

    def _on_built(self, voice_id, speed, error):
        self._working = False
        self.progress.hide()
        # A statement is good for one try: an old recording of it must not work next time.
        self._consent = clone.new_consent()
        self._show_statement()
        if self._stop_work.is_set():
            self._set_status("Cancelled. Nothing was kept. The code words have changed.")
        elif voice_id and not error:
            self._set_status(clone.speed_message(speed))
            self.voices_changed.emit()
        elif voice_id:
            self._set_status(f"Your voice is ready, but its speed could not be checked. {error}")
            self.voices_changed.emit()
        else:
            self._set_status(f"{error} The code words have changed.")
        self._fill(select=voice_id or None)

    # --- the voices -----------------------------------------------------------------------------
    def _use(self):
        voice_id = self.selected_voice()
        if voice_id:
            if not callable(self._current):
                self._current = voice_id
            self.use_voice.emit(voice_id)
            self._set_status("Speech now uses this voice.")
            self._fill()

    def _hear(self):
        voice_id = self.selected_voice()
        if voice_id:
            self._set_status("Playing a sample. It can take a few seconds to start.")
            self.hear_voice.emit(voice_id)

    def _ask(self, title, question):
        return QMessageBox.question(self, title, question, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    def _remove_selected(self):
        voice_id = self.selected_voice()
        if not voice_id:
            return
        if voice_id == self._voice_in_use():
            self._set_status("This voice is in use. Pick another voice first, then remove it.")
            return
        busy = self._busy_speaking()
        if busy:
            self._set_status(busy)
            return
        if not self._ask("Remove voice", "Remove this voice and the recording it was made from? This cannot be undone."):
            return
        removed = clone.remove_voice(voice_id)
        self._set_status("Removed, along with its recording." if removed
                         else "Could not remove all of this voice. Close what is using it and try again.")
        self.voices_changed.emit()
        self._fill()

    def _remove_model(self):
        if (self._voice_in_use() or "").startswith(clone.PREFIX):
            self._set_status("One of your voices is in use. Pick another voice first, then delete the model.")
            return
        busy = self._busy_speaking()
        if busy:
            self._set_status(busy)
            return
        if not self._ask("Delete the voice model", f"Delete the voice model? Your voices are kept, but they cannot speak "
                         f"until it is downloaded again ({clone.MODEL_MB} MB)."):
            return
        try:
            freed = clone.remove_model()
        except OSError as exc:
            self._set_status(str(exc))
            return
        self._set_status(f"Deleted the voice model ({freed / 1e6:.0f} MB). Your voices are kept.")
        self.voices_changed.emit()
        self._fill()

    def set_current(self, voice_id):
        if not callable(self._current):
            self._current = voice_id
        self._fill()

    # --- closing --------------------------------------------------------------------------------
    def abandon(self):
        """Stop whatever is running. Nothing is kept from a recording or a voice stopped this way."""
        self._cancel_download()
        self._stop_making()
        if self._recording:
            self._meter.stop()
            self._recording = False
            self._recorder.stop()

    def _may_close(self):
        if self._cancel is not None and not self._cancel.is_set():
            return self._ask("Stop the download?", "Closing this window stops the download. Stop it?")
        return True

    def closeEvent(self, event):  # noqa: N802
        if not self._may_close():
            event.ignore()
            return
        self.abandon()
        super().closeEvent(event)

    def reject(self):  # Esc: closes without a closeEvent
        if self._may_close():
            self.abandon()
            super().reject()
