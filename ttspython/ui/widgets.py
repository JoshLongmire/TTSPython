"""Small reusable widgets."""
from __future__ import annotations

import collections
import os

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRectF, QSize, Qt, QTimer, Property, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QAbstractButton, QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLabel, QSizePolicy, QStyle,
    QStyleOptionComboBox, QStylePainter, QToolButton, QWidget,
)

from . import icons


def tool_button(icon_name, tooltip="", variant="ghost", size=18, text="", checkable=False, role="text"):
    btn = QToolButton()
    btn.setProperty("variant", variant)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setToolTip(tooltip)
    btn.setAccessibleName(tooltip or text)
    if text:
        btn.setText(text)
        btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    icons.apply(btn, icon_name, role, size)
    btn.setCheckable(checkable)
    return btn


def action_button(action, variant="ghost", show_text=False, size=18):
    """A tool button bound to a QAction (shares its icon, tooltip and enabled state)."""
    btn = QToolButton()
    btn.setDefaultAction(action)
    btn.setProperty("variant", variant)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setIconSize(QSize(size, size))
    btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon if show_text else Qt.ToolButtonIconOnly)
    return btn


def card(name="Card"):
    frame = QFrame()
    frame.setObjectName(name)
    return frame


def label(text="", name=None, muted=False):
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    if muted:
        lab.setProperty("muted", True)
    return lab


class Segmented(QFrame):
    """A segmented switch of mutually exclusive options."""

    changed = Signal(str)

    def __init__(self, options, parent=None):
        super().__init__(parent)
        self.setObjectName("Segmented")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons = {}
        for key, text, icon_name in options:
            btn = QToolButton()
            btn.setText(text)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            if icon_name:
                icons.apply(btn, icon_name, "muted", 15)
                btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            self._group.addButton(btn)
            self._buttons[key] = btn
            # Qt's size hint for a styled tool button ignores the QSS padding, so the label
            # would be elided in narrow windows: reserve the real width (bold text + icon + padding).
            bold = QFont(btn.font())
            bold.setWeight(QFont.DemiBold)
            width = QFontMetrics(bold).horizontalAdvance(text) + (21 if icon_name else 0) + 34
            btn.setMinimumWidth(width)
            lay.addWidget(btn)
            btn.clicked.connect(lambda _=False, k=key: self.changed.emit(k))

    def set_value(self, key):
        btn = self._buttons.get(key)
        if btn:
            btn.setChecked(True)

    def value(self):
        for key, btn in self._buttons.items():
            if btn.isChecked():
                return key
        return None

    def button(self, key):
        return self._buttons[key]


class ToggleSwitch(QAbstractButton):
    """An iOS-style switch that animates its knob."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setText(text)
        self.setCursor(Qt.PointingHandCursor)
        self._pos = 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)
        self.animate = True

    def _get_knob(self):
        return self._pos

    def _set_knob(self, value):
        self._pos = value
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def _animate(self, checked):
        target = 1.0 if checked else 0.0
        if not self.animate or not self.isVisible():
            self._set_knob(target)
            return
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(target)
        self._anim.start()

    def setChecked(self, checked):  # noqa: N802
        super().setChecked(checked)
        self._set_knob(1.0 if checked else 0.0)

    def sizeHint(self):  # noqa: N802
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(self.text()) + 8 if self.text() else 0
        return QSize(34 + text_w, max(20, fm.height() + 4))

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.palette()
        track = QRectF(0, (self.height() - 18) / 2, 32, 18)
        off = QColor(icons.color("muted"))
        off.setAlpha(110)
        on = QColor(pal.color(pal.ColorRole.Accent))
        if not self.isEnabled():
            on = off = QColor(icons.color("disabled"))
        color = QColor(
            int(off.red() + (on.red() - off.red()) * self._pos),
            int(off.green() + (on.green() - off.green()) * self._pos),
            int(off.blue() + (on.blue() - off.blue()) * self._pos),
            int(off.alpha() + (on.alpha() - off.alpha()) * self._pos),
        )
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(track, 9, 9)
        knob_x = track.left() + 2 + self._pos * (track.width() - 18)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(knob_x, track.top() + 2, 14, 14))
        if self.text():
            p.setPen(pal.color(pal.ColorRole.WindowText) if self.isEnabled() else QColor(icons.color("disabled")))
            p.drawText(QRectF(40, 0, self.width() - 40, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text())
        if self.hasFocus():
            pen = p.pen()
            pen.setColor(on)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(track.adjusted(-2, -2, 2, 2), 11, 11)


class Waveform(QWidget):
    """Scrolling level bars fed by a callable returning 0..1."""

    def __init__(self, bars=24, parent=None):
        super().__init__(parent)
        self._bars = bars
        self._history = collections.deque([0.0] * bars, maxlen=bars)
        self._source = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._fps = 30
        self.color_role = "accent"
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(22)

    IDLE_MS = 250  # polling while silent (paused speech, a quiet mic): no repaints until sound

    def set_fps(self, fps):
        self._fps = fps
        if self._timer.isActive() and self._timer.interval() != self.IDLE_MS:
            self._timer.start(int(1000 / fps))

    def set_source(self, source):
        self._source = source
        if source is None:
            self._timer.stop()
            self._history = collections.deque([0.0] * self._bars, maxlen=self._bars)
            self.update()
        elif self.isVisible() and not self._timer.isActive():
            self._timer.start(int(1000 / self._fps))

    @property
    def active(self):
        return self._source is not None

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if self._source is not None and not self._timer.isActive():
            self._timer.start(int(1000 / self._fps))

    def hideEvent(self, event):  # noqa: N802
        super().hideEvent(event)
        self._timer.stop()  # a hidden window (tray, mini mode) needs no animation

    def _tick(self):
        if not self.isVisible() or self._source is None:
            return
        try:
            level = float(self._source())
        except Exception:
            level = 0.0
        level = max(0.0, min(1.0, level * 2.2))
        prev = self._history[-1]
        value = level if level > prev else prev * 0.82 + level * 0.18
        flat = value < 0.02 and max(self._history) < 0.02
        self._history.append(value)
        if flat:
            if self._timer.interval() != self.IDLE_MS:
                self._timer.start(self.IDLE_MS)  # nothing moves: stop repainting, poll slowly
            return
        if self._timer.interval() != int(1000 / self._fps):
            self._timer.start(int(1000 / self._fps))
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        n = self._bars
        gap = 3.0
        bar_w = max(2.0, (w - gap * (n - 1)) / n)
        color = QColor(icons.color(self.color_role))
        idle = QColor(icons.color("muted"))
        idle.setAlpha(90)
        p.setPen(Qt.NoPen)
        for i, value in enumerate(self._history):
            x = i * (bar_w + gap)
            if self._source is None or value < 0.02:
                d = min(bar_w, 3.0)
                p.setBrush(idle)
                p.drawEllipse(QRectF(x + (bar_w - d) / 2, h / 2 - d / 2, d, d))
                continue
            bh = max(3.0, value * (h - 2))
            c = QColor(color)
            c.setAlphaF(0.45 + 0.55 * (i + 1) / n)
            p.setBrush(c)
            p.drawRoundedRect(QRectF(x, (h - bh) / 2, bar_w, bh), bar_w / 2, bar_w / 2)


class Toast(QLabel):
    """A transient message bubble anchored to the bottom of a window."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignCenter)
        self.setMaximumWidth(460)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text, ms=2600):
        self.setText(text)
        self.adjustSize()
        parent = self.parentWidget()
        x = (parent.width() - self.width()) // 2
        y = parent.height() - self.height() - 96
        self.move(QPoint(max(8, x), max(8, y)))
        self.raise_()
        self.show()
        self._timer.start(ms)


class AppMark(QWidget):
    """The app logo: accent squircle with three bars."""

    def __init__(self, size=26, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        paint_mark(p, QRectF(0, 0, self.width(), self.height()))


class ElidingComboBox(QComboBox):
    """A combo box that shortens the shown text with "..." when it is narrower than the text
    (Qt would cut it off mid-letter). The full text stays in the list and the tooltip."""

    def __init__(self, parent=None, chars=12):
        super().__init__(parent)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(chars)
        self.currentIndexChanged.connect(lambda _i: self.setToolTip(self.currentText()))

    def paintEvent(self, _event):  # noqa: N802
        painter = QStylePainter(self)
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        painter.drawComplexControl(QStyle.CC_ComboBox, opt)
        field = self.style().subControlRect(QStyle.CC_ComboBox, opt, QStyle.SC_ComboBoxEditField, self)
        opt.currentText = self.fontMetrics().elidedText(opt.currentText, Qt.ElideRight, field.width())
        painter.drawControl(QStyle.CE_ComboBoxLabel, opt)


def voice_label(name):
    """ "Microsoft Zira Desktop - English (United States)" -> "Zira - English (United States)"."""
    short = name.replace("Microsoft ", "", 1) if name.startswith("Microsoft ") else name
    return short.replace(" Desktop - ", " - ").replace(" Desktop", "")


def dropped_text_files(mime):
    """Local text files in a drag-and-drop (other files are ignored)."""
    if not mime.hasUrls():
        return []
    paths = [os.path.normpath(u.toLocalFile()) for u in mime.urls() if u.isLocalFile()]
    return [p for p in paths if p.lower().endswith(TEXT_SUFFIXES)]


TEXT_SUFFIXES = (".txt", ".text", ".md", ".log", ".csv")


class ElidedLabel(QLabel):
    """One line of text shortened to fit ("..."); the tooltip shows all of it.
    clicked fires when it is made clickable with set_clickable()."""

    clicked = Signal()

    def __init__(self, text="", mode=Qt.ElideRight, parent=None):
        super().__init__(parent)
        self._clickable = False
        self._mode = mode
        self._full = ""
        self.setMinimumWidth(40)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setText(text)

    def setText(self, text):  # noqa: N802
        self._full = text
        if not getattr(self, "_clickable", False):
            self.setToolTip(text if self.fontMetrics().horizontalAdvance(text) > self.width() else "")
        self._elide()
        self.updateGeometry()

    def text(self):
        return self._full

    def sizeHint(self):  # noqa: N802
        # Ask for the full text's width (the layout shortens it when there is less room).
        hint = super().sizeHint()
        margins = self.contentsMargins()
        want = self.fontMetrics().horizontalAdvance(self._full) + margins.left() + margins.right() + 4
        return QSize(min(max(want, self.minimumWidth()), self.maximumWidth()), hint.height())

    def minimumSizeHint(self):  # noqa: N802
        return QSize(self.minimumWidth(), super().minimumSizeHint().height())

    def set_clickable(self, tip):
        self._clickable = True
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tip)

    def mousePressEvent(self, event):  # noqa: N802
        if self._clickable and event.button() == Qt.LeftButton:
            self.clicked.emit()
            return
        super().mousePressEvent(event)

    def _elide(self):
        super().setText(self.fontMetrics().elidedText(self._full, self._mode, max(0, self.contentsRect().width())))

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if not self._clickable:
            self.setToolTip(self._full if self.fontMetrics().horizontalAdvance(self._full) > self.width() else "")
        self._elide()


ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)  # the window/tray icon and the .ico file


def paint_mark(p, rect, accent=None, fg=None):
    accent = QColor(accent or icons.color("accent"))
    fg = QColor(fg or icons.color("on_accent"))
    path = QPainterPath()
    r = rect.width() * 0.3
    path.addRoundedRect(rect, r, r)
    p.fillPath(path, accent)
    w = rect.width()
    bar = w * 0.11
    heights = (0.34, 0.58, 0.42)
    xs = (0.27, 0.445, 0.62)
    p.setPen(Qt.NoPen)
    p.setBrush(fg)
    for x, hh in zip(xs, heights):
        bh = w * hh
        p.drawRoundedRect(QRectF(rect.left() + w * x, rect.top() + (w - bh) / 2, bar, bh), bar / 2, bar / 2)
