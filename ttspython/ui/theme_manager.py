"""Applies a theme preset to the whole application."""
from __future__ import annotations

import os
import tempfile

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from ..core.theme import THEME_PRESETS, DEFAULT_THEME, derive_tokens
from . import icons
from .style import build_palette, build_qss, ui_font


def _asset_dir():
    """A folder for the SVG files the style sheet points at, owned by this user.

    /tmp is shared on Linux: a folder another user created first cannot be written to.
    """
    user = str(os.getuid()) if hasattr(os, "getuid") else ""
    path = os.path.join(tempfile.gettempdir(), "ttspython-ui" + (f"-{user}" if user else ""))
    try:
        os.makedirs(path, exist_ok=True)
        if os.access(path, os.W_OK):
            return path
    except OSError:
        pass
    return tempfile.mkdtemp(prefix="ttspython-ui-")


class ThemeManager(QObject):
    changed = Signal(dict)

    def __init__(self, app: QApplication, key=DEFAULT_THEME):
        super().__init__(app)
        self.app = app
        self.key = key
        self.tokens = {}
        self._asset_dir = _asset_dir()
        app.setStyle("Fusion")
        app.setFont(ui_font(10))
        self.apply(key)

    def _asset(self, name, color, width=2.2):
        path = os.path.join(self._asset_dir, f"{name}_{color.lstrip('#')}.svg")
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(icons.svg(name, color, width))
        return path

    def apply(self, key):
        if key not in THEME_PRESETS:
            key = DEFAULT_THEME
        if key == self.key and self.tokens:
            return self.tokens  # already on: restyling every window costs about 50 ms
        self.key = key
        t = derive_tokens(THEME_PRESETS[key])
        self.tokens = t
        icons.set_palette(t)
        self.app.setPalette(build_palette(t))
        qss = build_qss(t, self._asset("chevron_down", t["muted"]))
        self.app.setStyleSheet(qss)
        self.changed.emit(t)
        return t
