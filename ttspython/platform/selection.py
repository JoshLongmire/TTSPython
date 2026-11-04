"""Find the text the user has highlighted in the app they are using.

Windows: UI Automation asks the focused control for its selection (no keystrokes, the
clipboard is untouched). Apps that do not answer get a Ctrl+C, and the clipboard is put
back right after; terminals never do, because Ctrl+C there stops the running program.
Linux: the X11 primary selection (what middle-click would paste).
"""
from __future__ import annotations

import itertools
import threading

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QClipboard, QGuiApplication

from ..core.platform import IS_WINDOWS, com_apartment
from .inject import snapshot_clipboard

# Terminals: Ctrl+C with nothing selected interrupts the program running in them.
TERMINAL_CLASSES = {
    "ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS", "PseudoConsoleWindow", "mintty", "PuTTY",
    "KiTTY", "VirtualConsoleClass", "org.wezfurlong.wezterm", "Alacritty",
}
UIA_TIMEOUT_MS = 1500   # an app that does not answer by then is treated as having no selection
MODIFIER_WAIT_MS = 600  # after a hotkey, wait for its keys to be released before sending Ctrl+C
COPY_WAIT_MS = 400      # how long an app gets to put its selection on the clipboard
LATE_COPY_MS = 1500     # after that, a copy that still arrives is undone (the clipboard put back)
POLL_MS = 20

_uia_lock = threading.Lock()
_uia = []


def _automation():
    """The UI Automation module and client for this thread's COM apartment."""
    import comtypes.client

    with _uia_lock:  # the first call generates the comtypes wrapper module
        if not _uia:
            comtypes.client.GetModule("UIAutomationCore.dll")
            from comtypes.gen import UIAutomationClient

            _uia.append(UIAutomationClient)
    mod = _uia[0]
    return mod, comtypes.client.CreateObject(mod.CUIAutomation, interface=mod.IUIAutomation)


def uia_selection(hwnd=None):
    """Selected text of the focused control, or of the first text control inside hwnd.

    Returns the text ("" when the control says nothing is selected), or None when the app
    does not expose its text to UI Automation.
    """
    uia, auto = _automation()
    if hwnd:
        root = auto.ElementFromHandle(hwnd)
        if not root.GetCurrentPropertyValue(uia.UIA_IsTextPatternAvailablePropertyId):
            cond = auto.CreatePropertyCondition(uia.UIA_IsTextPatternAvailablePropertyId, True)
            root = root.FindFirst(uia.TreeScope_Descendants, cond)
        candidates = [root] if root else []
    else:
        element = auto.GetFocusedElement()
        walker = auto.ControlViewWalker
        candidates = []
        for _ in range(4):  # the focused part may sit inside the control that has the text
            if not element:
                break
            candidates.append(element)
            try:
                element = walker.GetParentElement(element)
            except Exception:
                break
    for element in candidates:
        if not element.GetCurrentPropertyValue(uia.UIA_IsTextPatternAvailablePropertyId):
            continue
        pattern = element.GetCurrentPattern(uia.UIA_TextPatternId).QueryInterface(uia.IUIAutomationTextPattern)
        ranges = pattern.GetSelection()
        parts = [ranges.GetElement(i).GetText(-1) for i in range(ranges.Length if ranges else 0)]
        return "\n".join(p for p in parts if p)
    return None


def warm_up():
    """Generate the UI Automation wrapper ahead of the first Play (it takes a moment once)."""
    if not IS_WINDOWS:
        return
    try:
        with com_apartment():
            _automation()
    except Exception:
        pass


class SelectionGrabber(QObject):
    """grab(callback) calls callback(text) with the highlighted text, or callback(None)."""

    _uia_done = Signal(int, object)

    def __init__(self, router=None, parent=None, uia=uia_selection, win=None):
        super().__init__(parent)
        self.router = router
        self._uia = uia
        self._win = win
        self._token = itertools.count(1)
        self._pending = None  # (token, hwnd, callback)
        self._uia_done.connect(self._on_uia)

    @property
    def win(self):
        if self._win is None:
            from . import winapi

            self._win = winapi
        return self._win

    def grab(self, callback):
        if self._pending is not None:
            return False
        if not IS_WINDOWS and self._win is None:
            clip = QGuiApplication.clipboard()
            text = clip.text(QClipboard.Selection) if clip.supportsSelection() else ""
            callback(text if text.strip() else None)
            return True
        hwnd = self.win.foreground_window()
        if not hwnd or self.win.is_own_window(hwnd):
            callback(None)
            return True
        token = next(self._token)
        self._pending = (token, hwnd, callback)
        threading.Thread(target=self._ask_uia, args=(token,), name="selection-uia", daemon=True).start()
        QTimer.singleShot(UIA_TIMEOUT_MS, lambda: self._finish(token, None))
        return True

    def _ask_uia(self, token):
        try:
            with com_apartment():
                result = self._uia()
        except Exception:
            result = None
        self._uia_done.emit(token, result)

    def _on_uia(self, token, text):
        if self._pending is None or self._pending[0] != token:
            return  # timed out already
        if text:
            self._finish(token, text)
        elif text == "":
            self._finish(token, None)  # the app says nothing is highlighted
        elif self.win.window_class(self._pending[1]) in TERMINAL_CLASSES:
            self._finish(token, None)
        else:
            self._copy_fallback(token)

    def _finish(self, token, text):
        if self._pending is None or self._pending[0] != token:
            return
        callback = self._pending[2]
        self._pending = None
        callback(text if text and text.strip() else None)

    # --- Ctrl+C for apps that do not answer UI Automation ----------------------------------
    def _copy_fallback(self, token):
        _old, hwnd, callback = self._pending
        token = next(self._token)  # a new token: the UI Automation timeout no longer applies
        self._pending = (token, hwnd, callback)
        waited = [0]

        def finish(text):
            self._finish(token, text)

        def send():
            if self.win.foreground_window() != hwnd:
                finish(None)  # the user moved on
                return
            if self.win.modifiers_down():
                if waited[0] < MODIFIER_WAIT_MS:
                    waited[0] += POLL_MS
                    QTimer.singleShot(POLL_MS, send)
                else:
                    finish(None)  # Ctrl+C with Alt or Shift still held would be another command
                return
            clipboard = QGuiApplication.clipboard()
            snapshot = snapshot_clipboard(clipboard)
            before = self.win.clipboard_sequence()
            if self.router is not None:
                self.router.pause(2.0)
            if not self.win.send_copy():
                finish(None)
                return
            polled = [0]

            def poll():
                if self.win.clipboard_sequence() == before:
                    if polled[0] < COPY_WAIT_MS:
                        polled[0] += POLL_MS
                        QTimer.singleShot(POLL_MS, poll)
                    else:
                        finish(None)  # nothing was copied: nothing is highlighted
                        QTimer.singleShot(POLL_MS, late)
                    return
                QTimer.singleShot(POLL_MS, read)  # let the app finish writing every format

            def put_back():
                if snapshot is not None:
                    if self.router is not None:
                        self.router.pause(1.0)
                    clipboard.setMimeData(snapshot)

            def read():
                text = clipboard.text()
                put_back()
                finish(text)

            def late():
                # A slow app (remote desktop, a large spreadsheet range) may still copy after we
                # gave up: put the user's clipboard back then too.
                if self.win.clipboard_sequence() != before:
                    QTimer.singleShot(POLL_MS, put_back)
                elif polled[0] < LATE_COPY_MS:
                    polled[0] += POLL_MS * 5
                    QTimer.singleShot(POLL_MS * 5, late)

            QTimer.singleShot(POLL_MS, poll)

        send()
