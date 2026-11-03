"""System tray icon and menu."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .widgets import ICON_SIZES, paint_mark


def app_icon(accent=None, fg=None):
    ico = QIcon()
    for size in ICON_SIZES:
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        paint_mark(p, QRectF(0, 0, size, size), accent, fg)
        p.end()
        ico.addPixmap(pm)
    return ico


def recording_icon(icon):
    """The app icon with a red dot (dictation is recording)."""
    out = QIcon()
    for size in ICON_SIZES:
        pm = icon.pixmap(size, size)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        d = size * 0.42
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(size - d - 1, size - d - 1, d + 1, d + 1))
        p.setBrush(QColor("#e5484d"))
        p.drawEllipse(QRectF(size - d - 0.5, size - d - 0.5, d, d))
        p.end()
        out.addPixmap(pm)
    return out


class Tray(QSystemTrayIcon):
    def __init__(self, actions, parent=None):
        super().__init__(parent)
        self.setToolTip("TTSPython")
        menu = QMenu()
        # No "dictate" entry: opening the tray menu takes focus from the app the text should go to.
        for key in ("show_window", "mini_mode", None, "speak_clipboard", "pause_resume", "stop", None,
                    "settings", None, "quit"):
            if key is None:
                menu.addSeparator()
            else:
                menu.addAction(actions[key])
        self.setContextMenu(menu)
        self._menu = menu
        self.activated.connect(self._activated)
        self.show_window = actions["show_window"]

    def set_state(self, tooltip, recording=False, base_icon=None):
        """The tray is often the only thing visible: say what is happening, and mark recording."""
        self.setToolTip(f"TTSPython\n{tooltip}" if tooltip else "TTSPython")
        if base_icon is not None:
            self.setIcon(recording_icon(base_icon) if recording else base_icon)

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_window.trigger()

    @staticmethod
    def available():
        return QSystemTrayIcon.isSystemTrayAvailable()
