"""System-wide hotkeys.

Windows: RegisterHotKey on a dedicated message-loop thread.
Linux X11: pynput GlobalHotKeys.
Wayland: not possible for normal apps; use the --toggle-dictation style
command-line flags with a desktop shortcut instead.
"""
from __future__ import annotations

import ctypes
import threading
import time

from PySide6.QtCore import QObject, Signal

from ..core import keys
from ..core.platform import IS_WINDOWS, session_type

DEBOUNCE_SECONDS = 0.25


def availability():
    """(available, reason)."""
    if IS_WINDOWS:
        return True, ""
    if session_type() == "wayland":
        return False, "Wayland does not allow apps to register global hotkeys."
    try:
        import pynput  # noqa: F401
    except Exception:
        return False, "Install the pynput package to enable global hotkeys."
    return True, ""


class _WinHotkeyThread(threading.Thread):
    _WM_SET = 0x8000 + 1

    def __init__(self, on_trigger):
        super().__init__(name="global-hotkeys", daemon=True)
        from . import winapi

        self.w = winapi
        self.on_trigger = on_trigger
        self.tid = 0
        self.ready = threading.Event()
        self.applied = threading.Event()
        self.pending = {}
        self.results = {}
        self.ids = {}

    def run(self):
        w = self.w
        self.tid = w.kernel32.GetCurrentThreadId()
        msg = w.MSG()
        w.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        self.ready.set()
        while w.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == w.WM_HOTKEY:
                action = self.ids.get(int(msg.wParam))
                if action:
                    self.on_trigger(action)
            elif msg.message == self._WM_SET:
                self._apply(self.pending)
                self.applied.set()
        self._unregister_all()

    def _unregister_all(self):
        for hid in list(self.ids):
            self.w.user32.UnregisterHotKey(None, hid)
        self.ids.clear()

    def _apply(self, bindings):
        self._unregister_all()
        results = {}
        next_id = 1
        for action, combo in bindings.items():
            if not combo:
                results[action] = None
                continue
            parsed = keys.to_win_hotkey(combo)
            if parsed is None:
                results[action] = "This key cannot be used as a global hotkey"
                continue
            mods, vk = parsed
            if self.w.user32.RegisterHotKey(None, next_id, mods, vk):
                self.ids[next_id] = action
                results[action] = None
            else:
                err = ctypes.get_last_error()
                results[action] = ("Already used by another app" if err == self.w.ERROR_HOTKEY_ALREADY_REGISTERED
                                   else f"Could not register (error {err})")
            next_id += 1
        self.results = results

    def set_bindings(self, bindings):
        self.ready.wait(2)
        self.pending = dict(bindings)
        self.applied.clear()
        self.w.user32.PostThreadMessageW(self.tid, self._WM_SET, 0, 0)
        self.applied.wait(2)
        return dict(self.results)

    def stop(self):
        if self.tid:
            self.w.user32.PostThreadMessageW(self.tid, self.w.WM_QUIT, 0, 0)


class _X11Hotkeys:
    def __init__(self, on_trigger):
        self.on_trigger = on_trigger
        self.listener = None

    def set_bindings(self, bindings):
        from pynput import keyboard

        self.stop()
        mapping, results = {}, {}
        for action, combo in bindings.items():
            if not combo:
                results[action] = None
                continue
            spec = keys.to_pynput(combo)
            if spec is None:
                results[action] = "This key cannot be used as a global hotkey"
                continue
            mapping[spec] = (lambda a=action: self.on_trigger(a))
            results[action] = None
        if mapping:
            try:
                self.listener = keyboard.GlobalHotKeys(mapping)
                self.listener.daemon = True
                self.listener.start()
            except Exception as exc:
                return {a: f"Could not listen: {exc}" for a in bindings}
        return results

    def stop(self):
        if self.listener is not None:
            self.listener.stop()
            self.listener = None


class GlobalHotkeys(QObject):
    triggered = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.available, self.reason = availability()
        self._last = {}
        self._backend = None
        if not self.available:
            return
        if IS_WINDOWS:
            self._backend = _WinHotkeyThread(self._fire)
            self._backend.start()
        else:
            self._backend = _X11Hotkeys(self._fire)

    def _fire(self, action):
        now = time.monotonic()
        if now - self._last.get(action, 0.0) < DEBOUNCE_SECONDS:
            return
        self._last[action] = now
        self.triggered.emit(action)

    def set_bindings(self, bindings, enabled=True):
        """Register bindings. Returns {action: error message or None}."""
        if not self.available:
            return {a: self.reason for a, combo in bindings.items() if combo}
        if not enabled:
            self._backend.set_bindings({})
            return {a: None for a in bindings}
        return self._backend.set_bindings(bindings)

    def stop(self):
        if self._backend is not None:
            self._backend.stop()
