"""Put dictated text into whatever app the user was typing in.

The text goes onto the clipboard, a paste keystroke is synthesized, and the
previous clipboard is restored afterwards unless something else changed it.
"""
from __future__ import annotations

import shutil
import subprocess

from PySide6.QtCore import QMimeData, QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication

from ..core.platform import IS_WINDOWS, session_type

MAX_SNAPSHOT_BYTES = 256 * 1024 * 1024
RESTORE_DELAY_MS = 400
MODIFIER_WAIT_MS = 600
WIN_PRIVATE_FORMATS = {
    'application/x-qt-windows-mime;value="ExcludeClipboardContentFromMonitorProcessing"': b"\x00\x00\x00\x00",
    'application/x-qt-windows-mime;value="CanIncludeInClipboardHistory"': b"\x00\x00\x00\x00",
    'application/x-qt-windows-mime;value="CanUploadToCloudClipboard"': b"\x00\x00\x00\x00",
}


def snapshot_clipboard(clipboard):
    """Copy every format on the clipboard (None if too large to copy)."""
    source = clipboard.mimeData()
    copy = QMimeData()
    if source is None:
        return copy
    total = 0
    if source.hasImage():
        # Images come back as a QImage; the raw "application/x-qt-image" bytes are empty.
        copy.setImageData(source.imageData())
    for fmt in source.formats():
        if fmt == "application/x-qt-image":
            continue
        data = source.data(fmt)
        total += data.size()
        if total > MAX_SNAPSHOT_BYTES:
            return None
        copy.setData(fmt, data)
    return copy


class TextInjector(QObject):
    """Emits finished(pasted: bool, message: str)."""

    finished = Signal(bool, str)

    def __init__(self, router=None, parent=None):
        super().__init__(parent)
        self.router = router
        self.keystroke = "ctrl+v"
        self._busy = False

    @property
    def clipboard(self):
        return QGuiApplication.clipboard()

    def _suppress(self, text):
        if self.router is not None and text:
            self.router.suppress(text)

    def copy_only(self, text, reason=""):
        self._suppress(text)
        self.clipboard.setText(text)
        self.finished.emit(False, reason or "Copied to clipboard. Press Ctrl+V to paste.")

    def inject(self, text, target=None):
        if self._busy:
            self.copy_only(text, "Copied to clipboard (still pasting the last dictation).")
            return
        try:
            if IS_WINDOWS:
                self._inject_windows(text, target)
            elif session_type() == "wayland":
                self._inject_wayland(text)
            else:
                self._inject_x11(text)
        except Exception as exc:  # never stay "busy": every later dictation would only be copied
            self._busy = False
            self.copy_only(text, f"Could not paste ({exc}), so the text was copied. Press Ctrl+V to paste.")

    # --- Windows ----------------------------------------------------------------------
    def _inject_windows(self, text, target):
        from . import winapi

        if target and winapi.foreground_window() != target:
            self.copy_only(text, "The window changed, so the text was copied. Press Ctrl+V to paste.")
            return
        self._busy = True
        snapshot = snapshot_clipboard(self.clipboard)
        previous_text = self.clipboard.text()
        data = QMimeData()
        data.setText(text)
        for fmt, value in WIN_PRIVATE_FORMATS.items():
            data.setData(fmt, value)
        self._suppress(text)
        self.clipboard.setMimeData(data)
        ours = winapi.clipboard_sequence()
        waited = [0]

        def wait_modifiers():
            if winapi.modifiers_down():
                if waited[0] < MODIFIER_WAIT_MS:
                    waited[0] += 20
                    QTimer.singleShot(20, wait_modifiers)
                    return
                # Ctrl+V with Alt or Shift still held is another command (Paste Special).
                self._busy = False
                self.finished.emit(False, "Keys were still held, so the text was copied. Press Ctrl+V to paste.")
                return
            try:
                sent = winapi.send_paste(self.keystroke)
            except OSError:
                sent = False
            QTimer.singleShot(RESTORE_DELAY_MS, lambda: restore(sent))

        def restore(sent):
            if snapshot is not None and winapi.clipboard_sequence() == ours:
                self._suppress(previous_text)
                self.clipboard.setMimeData(snapshot)
            self._busy = False
            if sent:
                self.finished.emit(True, "")
            else:
                self.finished.emit(False, "Windows blocked the paste (the app may be running as administrator). "
                                          "The text is on the clipboard.")

        QTimer.singleShot(0, wait_modifiers)

    # --- Linux -------------------------------------------------------------------------
    def _inject_x11(self, text):
        try:
            from pynput.keyboard import Controller, Key
        except Exception:
            self.copy_only(text)
            return
        self._busy = True
        snapshot = snapshot_clipboard(self.clipboard)
        previous_text = self.clipboard.text()
        self._suppress(text)
        self.clipboard.setText(text)

        def paste():
            kb = Controller()
            # A stop hotkey may still be held: Ctrl+Alt+V would be another command.
            held = (Key.alt, Key.alt_gr, Key.cmd) + (() if self.keystroke == "shift+insert" else (Key.shift,))
            for key in held:
                try:
                    kb.release(key)
                except Exception:
                    pass
            if self.keystroke == "shift+insert":
                with kb.pressed(Key.shift):
                    kb.tap(Key.insert)
            else:
                with kb.pressed(Key.ctrl):
                    kb.tap("v")
            QTimer.singleShot(RESTORE_DELAY_MS, restore)

        def restore():
            if snapshot is not None and self.clipboard.text() == text:
                self._suppress(previous_text)
                self.clipboard.setMimeData(snapshot)
            self._busy = False
            self.finished.emit(True, "")

        QTimer.singleShot(150, paste)

    def _inject_wayland(self, text):
        tool = shutil.which("wtype")
        snapshot = snapshot_clipboard(self.clipboard) if tool else None
        previous_text = self.clipboard.text()
        self._suppress(text)
        self.clipboard.setText(text)
        if not tool:
            self.finished.emit(False, "Copied to clipboard. Press Ctrl+V to paste (install wtype to paste automatically).")
            return
        try:
            subprocess.Popen(wtype_command(tool, self.keystroke))
        except OSError:
            self.finished.emit(False, "Copied to clipboard. Press Ctrl+V to paste.")
            return
        self._busy = True

        def restore():
            if snapshot is not None and self.clipboard.text() == text:
                self._suppress(previous_text)
                self.clipboard.setMimeData(snapshot)
            self._busy = False
            self.finished.emit(True, "")

        QTimer.singleShot(RESTORE_DELAY_MS, restore)


def wtype_command(tool, keystroke):
    """wtype arguments for the paste keystroke chosen in Settings."""
    if keystroke == "shift+insert":
        return [tool, "-M", "shift", "-k", "Insert", "-m", "shift"]
    return [tool, "-M", "ctrl", "v", "-m", "ctrl"]
