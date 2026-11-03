"""Line icons drawn as SVG and tinted per theme.

All icons share one 24x24 grid, 1.8px round strokes, so they read as a set.
"""
from __future__ import annotations

import weakref

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_P = {
    "play": '<path d="M7 5.5v13a1 1 0 0 0 1.5.86l10.5-6.5a1 1 0 0 0 0-1.72L8.5 4.64A1 1 0 0 0 7 5.5z" fill="currentColor" stroke="none"/>',
    "pause": '<rect x="6.5" y="5" width="4" height="14" rx="1.2" fill="currentColor" stroke="none"/><rect x="13.5" y="5" width="4" height="14" rx="1.2" fill="currentColor" stroke="none"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none"/>',
    "speak_selected": '<path d="M4 7h10M4 12h7M4 17h9"/><path d="M17 9.5v5l3.5-2.5z" fill="currentColor"/>',
    "mic": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7"/>',
    "record": '<circle cx="12" cy="12" r="6" fill="currentColor" stroke="none"/>',
    "folder_open": '<path d="M3.5 18.5V6a1.5 1.5 0 0 1 1.5-1.5h4l2 2.5h7.5A1.5 1.5 0 0 1 20 8.5V10"/><path d="M3.5 18.5l2.6-7.2A1.5 1.5 0 0 1 7.5 10.3H21l-2.8 7.4a1.5 1.5 0 0 1-1.4 1H3.5z"/>',
    "save": '<path d="M5 3.5h11l3.5 3.5v12A1.5 1.5 0 0 1 18 20.5H6A1.5 1.5 0 0 1 4.5 19V5A1.5 1.5 0 0 1 5 3.5z"/><path d="M8 3.5v5h7v-5M8 20.5v-6h8v6"/>',
    "save_as": '<path d="M12.5 20.5H6A1.5 1.5 0 0 1 4.5 19V5A1.5 1.5 0 0 1 6 3.5h10l3.5 3.5v4"/><path d="M8 3.5v5h7v-5"/><path d="M15 21l1-3.5 4.2-4.2a1.4 1.4 0 0 1 2 2L18 19.5z"/>',
    "export": '<path d="M12 4v11M7.5 10.5L12 15l4.5-4.5"/><path d="M4.5 16v2.5A1.5 1.5 0 0 0 6 20h12a1.5 1.5 0 0 0 1.5-1.5V16"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
    "settings": '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2.2"/><circle cx="9" cy="17" r="2.2"/>',
    "mini": '<rect x="3" y="5" width="18" height="14" rx="2"/><rect x="11.5" y="11.5" width="7" height="5" rx="1.2" fill="currentColor"/>',
    "expand": '<path d="M14 4h6v6M10 20H4v-6M20 4l-6.5 6.5M4 20l6.5-6.5"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "file_plus": '<path d="M14 3.5H7A1.5 1.5 0 0 0 5.5 5v14A1.5 1.5 0 0 0 7 20.5h10a1.5 1.5 0 0 0 1.5-1.5V8z"/><path d="M14 3.5V8h4.5M12 11v6M9 14h6"/>',
    "file_text": '<path d="M14 3.5H7A1.5 1.5 0 0 0 5.5 5v14A1.5 1.5 0 0 0 7 20.5h10a1.5 1.5 0 0 0 1.5-1.5V8z"/><path d="M14 3.5V8h4.5M9 13h6M9 16.5h6"/>',
    "trash": '<path d="M4.5 7h15M10 11v6M14 11v6"/><path d="M6.5 7l.8 11.6A1.5 1.5 0 0 0 8.8 20h6.4a1.5 1.5 0 0 0 1.5-1.4L17.5 7M9.5 7V5a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1v2"/>',
    "minus": '<path d="M5 12h14"/>',
    "arrow_up": '<path d="M12 19V5M6 11l6-6 6 6"/>',
    "arrow_down": '<path d="M12 5v14M6 13l6 6 6-6"/>',
    "chevron_up": '<path d="M6 15l6-6 6 6"/>',
    "chevron_down": '<path d="M6 9l6 6 6-6"/>',
    "repeat": '<path d="M17 3.5l3 3-3 3"/><path d="M4 11.5V10a3.5 3.5 0 0 1 3.5-3.5H20M7 20.5l-3-3 3-3"/><path d="M20 12.5V14a3.5 3.5 0 0 1-3.5 3.5H4"/>',
    "queue": '<path d="M4 6h11M4 12h11M4 18h7"/><path d="M17 15v6l4.5-3z" fill="currentColor"/>',
    "refresh": '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 4v4.5H15"/>',
    "voices": '<circle cx="9" cy="8" r="3.5"/><path d="M3 20a6 6 0 0 1 12 0"/><path d="M17.5 7.5a4 4 0 0 1 0 5M20 5a7.5 7.5 0 0 1 0 10"/>',
    "clipboard": '<rect x="5.5" y="4.5" width="13" height="16" rx="2"/><path d="M9 4.5V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v.5a1 1 0 0 1-1 1h-4a1 1 0 0 1-1-1z"/>',
    "paste": '<rect x="5.5" y="4.5" width="13" height="16" rx="2"/><path d="M9 4.5V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v.5a1 1 0 0 1-1 1h-4a1 1 0 0 1-1-1zM9 11h6M9 14.5h6M9 18h3.5"/>',
    "eraser": '<path d="M8.5 20.5h11"/><path d="M4.6 14.6l9.2-9.2a2 2 0 0 1 2.8 0l2.4 2.4a2 2 0 0 1 0 2.8l-8.3 8.3a2 2 0 0 1-1.4.6H7.8a2 2 0 0 1-1.4-.6l-1.8-1.8a1.8 1.8 0 0 1 0-2.5z"/><path d="M9.5 9.5l5.5 5.5"/>',
    "gauge": '<path d="M4.5 17a8.5 8.5 0 1 1 15 0"/><path d="M12 13l4-4"/><circle cx="12" cy="13" r="1.3" fill="currentColor"/>',
    "volume": '<path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5z" fill="currentColor" stroke-linejoin="round"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>',
    "volume_low": '<path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5z" fill="currentColor" stroke-linejoin="round"/><path d="M15.5 9a4 4 0 0 1 0 6"/>',
    "grip": '<circle cx="9" cy="6" r="1.4" fill="currentColor" stroke="none"/><circle cx="15" cy="6" r="1.4" fill="currentColor" stroke="none"/><circle cx="9" cy="12" r="1.4" fill="currentColor" stroke="none"/><circle cx="15" cy="12" r="1.4" fill="currentColor" stroke="none"/><circle cx="9" cy="18" r="1.4" fill="currentColor" stroke="none"/><circle cx="15" cy="18" r="1.4" fill="currentColor" stroke="none"/>',
    "keyboard": '<rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M6 14h.01M18 14h.01M9 14h6"/>',
    "palette": '<path d="M12 3.5a8.5 8.5 0 0 0 0 17c1.2 0 1.8-.8 1.8-1.7 0-.5-.2-.8-.5-1.2-.3-.3-.5-.7-.5-1.1 0-.9.7-1.6 1.6-1.6H16a4.5 4.5 0 0 0 4.5-4.5C20.5 6.9 16.7 3.5 12 3.5z"/><circle cx="7.5" cy="11" r="1" fill="currentColor"/><circle cx="10" cy="7.5" r="1" fill="currentColor"/><circle cx="14.5" cy="7.5" r="1" fill="currentColor"/>',
    "monitor": '<rect x="3" y="4.5" width="18" height="12" rx="2"/><path d="M9 20h6M12 16.5V20"/>',
    "case": '<path d="M3.5 17L7 7l3.5 10M4.8 13.5h4.4"/><path d="M14 13.6a2.6 2.6 0 1 0 5.2 0 2.6 2.6 0 1 0-5.2 0zM19.2 11v6"/>',
    "regex": '<path d="M17 4v8M13.5 6l7 4M13.5 10l7-4"/><rect x="4" y="15" width="5" height="5" rx="1" fill="currentColor"/>',
    "replace": '<path d="M4 7h11l-3-3M20 17H9l3 3"/>',
    "replace_all": '<path d="M4 6h11l-3-3M4 11h11M20 18H9l3 3M20 13H9"/>',
    "power": '<path d="M12 3.5V12"/><path d="M7 6.5a7.5 7.5 0 1 0 10 0"/>',
}

_TEMPLATE = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
             'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round" color="{color}">{body}</svg>')

_cache = {}
_registry = []
_palette = {"text": "#e6e8ee", "muted": "#8b93a7", "accent": "#7c8cff", "on_accent": "#ffffff",
            "danger": "#f87171", "disabled": "#555"}


def svg(name, color, width=1.8):
    body = _P[name].replace("currentColor", color)
    return _TEMPLATE.format(color=color, width=width, body=body)


def pixmap(name, color, size=18, dpr=1.0, width=1.8):
    key = (name, color, size, round(dpr, 2), width)
    pm = _cache.get(key)
    if pm is None:
        renderer = QSvgRenderer(QByteArray(svg(name, color, width).encode("utf-8")))
        px = max(1, int(round(size * dpr)))
        pm = QPixmap(px, px)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        renderer.render(painter)
        painter.end()
        pm.setDevicePixelRatio(dpr)
        _cache[key] = pm
    return pm


def icon(name, role="text", size=18, dpr=2.0):
    """A themed icon with a dimmed disabled state."""
    ico = QIcon()
    ico.addPixmap(pixmap(name, _palette.get(role, role), size, dpr), QIcon.Normal)
    ico.addPixmap(pixmap(name, _palette["disabled"], size, dpr), QIcon.Disabled)
    return ico


def set_palette(tokens):
    _palette.update({
        "text": tokens["text"], "muted": tokens["muted"], "accent": tokens["accent_text"],
        "on_accent": tokens["on_accent"], "danger": tokens["danger"], "disabled": tokens["disabled_text"],
    })
    _cache.clear()
    alive = []
    for ref, name, role, size in _registry:
        widget = ref()
        if widget is None:
            continue
        try:
            widget.setIcon(icon(name, role, size))
        except RuntimeError:  # widget deleted on the C++ side
            continue
        alive.append((ref, name, role, size))
    _registry[:] = alive


def apply(widget, name, role="text", size=18):
    """Set a themed icon on a button/action and re-tint it when the theme changes."""
    widget.setIcon(icon(name, role, size))
    if hasattr(widget, "setIconSize"):
        widget.setIconSize(QSize(size, size))
    for i, (ref, *_rest) in enumerate(_registry):
        if ref() is widget:
            _registry[i] = (weakref.ref(widget), name, role, size)
            return
    _registry.append((weakref.ref(widget), name, role, size))


def color(role):
    return _palette.get(role, role)
