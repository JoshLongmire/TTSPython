"""Mini mode: an always-on-top pill that never takes keyboard focus."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSlider, QToolButton, QVBoxLayout, QWidget,
)

from ..core.platform import IS_WINDOWS
from ..core.settings import RATE_MAX, RATE_MIN, percent_wpm, speed_percent
from . import icons
from .widgets import ElidingComboBox, Waveform, voice_label

PILL_W, PILL_H, MARGIN = 272, 52, 10
SNAP_DISTANCE, SNAP_GAP = 24, 8


def _pill_button(icon_name, tooltip, size=36, icon_size=18, role="text"):
    btn = QToolButton()
    btn.setObjectName("PillButton")
    btn.setFixedSize(size, size)
    btn.setFocusPolicy(Qt.NoFocus)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setToolTip(tooltip)
    btn.setAccessibleName(tooltip)
    icons.apply(btn, icon_name, role, icon_size)
    return btn


class MiniPill(QWidget):
    mic_clicked = Signal()
    play_clicked = Signal()
    expand_clicked = Signal()
    popover_requested = Signal(QPoint)
    moved = Signal()
    volume_step = Signal(int)  # mouse wheel over the bar: +1 louder, -1 quieter

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self.setWindowTitle("TTSPython mini")
        self.setFixedSize(PILL_W + 2 * MARGIN, PILL_H + 2 * MARGIN)
        self.snap = True
        self._drag_offset = None
        self._tokens = {}

        lay = QHBoxLayout(self)
        lay.setContentsMargins(MARGIN + 8, MARGIN + 8, MARGIN + 8, MARGIN + 8)
        lay.setSpacing(4)
        self.grip = QLabel()
        self.grip.setFixedSize(14, 36)
        self.grip.setCursor(Qt.SizeAllCursor)
        self.grip.setToolTip("Drag to move")
        self.mic = _pill_button("mic", "Dictate (types where your cursor is)")
        self.play = _pill_button("play", "Speak highlighted text (or the clipboard)")
        self.play.setObjectName("PillPrimary")
        self.wave = Waveform(bars=18)
        self.wave.setFixedHeight(22)
        self.wave.setMinimumWidth(80)
        self.more = _pill_button("chevron_down", "Voice, speed and volume", size=26, icon_size=14, role="muted")
        self.expand = _pill_button("expand", "Open the full window", size=30, icon_size=15, role="muted")
        lay.addWidget(self.grip)
        lay.addWidget(self.mic)
        lay.addWidget(self.play)
        lay.addSpacing(4)
        lay.addWidget(self.wave, 1)
        lay.addSpacing(2)
        lay.addWidget(self.more)
        lay.addWidget(self.expand)
        for w in (self.grip, self.wave):
            w.setFocusPolicy(Qt.NoFocus)

        self.mic.clicked.connect(self.mic_clicked)
        self.play.clicked.connect(self.play_clicked)
        self.expand.clicked.connect(self.expand_clicked)
        self.more.clicked.connect(lambda: self.popover_requested.emit(self.mapToGlobal(self.more.geometry().bottomLeft())))
        self.refresh_grip()

    # --- appearance ------------------------------------------------------------------
    def set_tokens(self, tokens):
        self._tokens = tokens
        t = tokens
        self.setStyleSheet(f"""
            QToolButton#PillButton {{ background: transparent; border: none; border-radius: 18px; padding: 0px; }}
            QToolButton#PillButton:hover {{ background: {t['hover']}; }}
            QToolButton#PillButton:pressed {{ background: {t['pressed']}; }}
            QToolButton#PillPrimary {{ background: {t['accent_fill']}; border: none; border-radius: 18px; }}
            QToolButton#PillPrimary:hover {{ background: {t['accent_hover']}; }}
            QToolButton#PillRecording {{ background: {t['danger']}; border: none; border-radius: 18px; }}
        """)
        self.refresh_grip()
        self.update()

    def refresh_grip(self):
        self.grip.setPixmap(icons.pixmap("grip", icons.color("muted"), 14, self.devicePixelRatioF() or 1.0))

    def set_recording(self, recording, transcribing=False):
        self.mic.setObjectName("PillRecording" if recording else "PillButton")
        icons.apply(self.mic, "stop" if recording else "mic", "on_accent" if recording else ("muted" if transcribing else "text"),
                    16 if recording else 18)
        self.mic.setToolTip("Stop dictating" if recording else ("Transcribing..." if transcribing else
                                                                "Dictate (types where your cursor is)"))
        self.mic.style().unpolish(self.mic)
        self.mic.style().polish(self.mic)
        self.wave.color_role = "danger" if recording else "accent"

    def set_speaking(self, speaking):
        icons.apply(self.play, "stop" if speaking else "play", "on_accent", 16 if speaking else 18)
        self.play.setToolTip("Stop speaking" if speaking else "Speak highlighted text (or the clipboard)")

    def paintEvent(self, _event):  # noqa: N802
        t = self._tokens
        if not t:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pill = QRectF(MARGIN, MARGIN, PILL_W, PILL_H)
        radius = PILL_H / 2
        shadow = QColor(0, 0, 0)
        for i in range(MARGIN, 0, -1):
            shadow.setAlpha(int(3 + (MARGIN - i) * (16 if t.get("dark") else 6) / MARGIN))
            p.setPen(Qt.NoPen)
            p.setBrush(shadow)
            p.drawRoundedRect(pill.adjusted(-i + 2, -i + 4, i - 2, i), radius + i, radius + i)
        path = QPainterPath()
        path.addRoundedRect(pill, radius, radius)
        p.fillPath(path, QColor(t["surface"]))
        pen = QPen(QColor(t["border"]))
        pen.setWidthF(1.0 * t.get("border_w", 1))
        p.setPen(pen)
        p.drawPath(path)

    # --- never take focus (Windows) -----------------------------------------------------
    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if IS_WINDOWS:
            from ..platform import winapi

            winapi.apply_noactivate(int(self.winId()))

    def nativeEvent(self, event_type, message):  # noqa: N802
        if IS_WINDOWS and event_type == b"windows_generic_MSG":
            from ..platform import winapi

            msg = winapi.MSG.from_address(int(message))
            if msg.message == winapi.WM_MOUSEACTIVATE:
                return True, winapi.MA_NOACTIVATE
        return False, 0

    def wheelEvent(self, event):  # noqa: N802
        steps = event.angleDelta().y() // 120
        if steps:
            self.volume_step.emit(1 if steps > 0 else -1)

    # --- dragging and snapping --------------------------------------------------------------
    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        elif event.button() == Qt.RightButton:
            self.popover_requested.emit(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._drag_offset is not None and event.button() == Qt.LeftButton:
            self._drag_offset = None
            if self.snap:
                self.move(self.snapped(self.pos()))
            self.moved.emit()

    def _screen_rect(self, pos=None):
        center = (pos or self.pos()) + QPoint(self.width() // 2, self.height() // 2)
        screen = QGuiApplication.screenAt(center) or QGuiApplication.primaryScreen()
        return screen, screen.availableGeometry()

    def snapped(self, pos):
        _, area = self._screen_rect(pos)
        x, y = pos.x(), pos.y()
        inner_left, inner_top = x + MARGIN, y + MARGIN
        inner_right, inner_bottom = inner_left + PILL_W, inner_top + PILL_H
        if abs(inner_left - area.left()) < SNAP_DISTANCE:
            x = area.left() + SNAP_GAP - MARGIN
        elif abs(area.right() - inner_right) < SNAP_DISTANCE:
            x = area.right() - SNAP_GAP - PILL_W - MARGIN
        if abs(inner_top - area.top()) < SNAP_DISTANCE:
            y = area.top() + SNAP_GAP - MARGIN
        elif abs(area.bottom() - inner_bottom) < SNAP_DISTANCE:
            y = area.bottom() - SNAP_GAP - PILL_H - MARGIN
        return self.clamped(QPoint(x, y), area)

    def clamped(self, pos, area=None):
        if area is None:
            _, area = self._screen_rect(pos)
        x = max(area.left() - MARGIN, min(pos.x(), area.right() - PILL_W - MARGIN))
        y = max(area.top() - MARGIN, min(pos.y(), area.bottom() - PILL_H - MARGIN))
        return QPoint(x, y)

    # --- position persistence ----------------------------------------------------------------
    def position_ref(self):
        screen, area = self._screen_rect()
        span_x = max(1, area.width() - self.width())
        span_y = max(1, area.height() - self.height())
        return {"screen": screen.name(), "rx": (self.x() - area.left()) / span_x,
                "ry": (self.y() - area.top()) / span_y}

    def restore_position(self, ref):
        screens = {s.name(): s for s in QGuiApplication.screens()}
        screen = screens.get((ref or {}).get("screen")) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        if ref:
            x = area.left() + ref["rx"] * max(1, area.width() - self.width())
            y = area.top() + ref["ry"] * max(1, area.height() - self.height())
        else:
            x = area.right() - self.width() - 24
            y = area.bottom() - self.height() - 24
        self.move(self.clamped(QPoint(int(x), int(y)), area))


class FloatingToast(QLabel):
    """A message bubble near the pill that never takes focus, drawn like the caption bubble."""

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)  # rounded corners, no square box behind them
        self.setObjectName("FloatToast")
        self.setWordWrap(True)
        self.setMaximumWidth(340)
        self.setContentsMargins(14, 9, 14, 9)
        self._tokens = {}
        self._anchor = None  # (center x, bottom y or None, top y or None): kept while the text changes
        from PySide6.QtCore import QTimer

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def set_tokens(self, tokens):
        self._tokens = tokens
        self.setStyleSheet(f"QLabel#FloatToast {{ color: {tokens['text']}; background: transparent; }}")
        self.update()

    def update_text(self, text, ms=3200):
        """New text for the notice on show (a download's next step): same place, no new pop-up."""
        if not self.isVisible() or self._anchor is None:
            return
        self._fit(text)
        cx, bottom, top = self._anchor
        self.move(cx - self.width() // 2, bottom - self.height() if bottom is not None else top)
        self._timer.start(ms)

    def _fit(self, text):
        """One line when it fits, else wrapped at the widest size (adjustSize wraps far narrower)."""
        self.setText(text)
        m = self.contentsMargins()
        width = min(self.maximumWidth(), QFontMetrics(self.font()).horizontalAdvance(text) + m.left() + m.right() + 2)
        self.resize(width, self.heightForWidth(width))

    def paintEvent(self, event):  # noqa: N802
        t = self._tokens
        if t:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
            p.fillPath(path, QColor(t["surface"]))
            pen = QPen(QColor(t["border"]))
            pen.setWidthF(1.0 * t.get("border_w", 1))
            p.setPen(pen)
            p.drawPath(path)
            p.end()
        super().paintEvent(event)

    def show_near(self, widget, text, ms=3200):
        self._fit(text)
        geo = widget.frameGeometry()
        screen = QGuiApplication.screenAt(geo.center()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(max(area.left() + 8, geo.center().x() - self.width() // 2), area.right() - self.width() - 8)
        y = geo.top() + MARGIN - self.height() - 8
        if y < area.top():
            y = geo.bottom() - MARGIN + 8
            self._anchor = (x + self.width() // 2, None, y)
        else:
            self._anchor = (x + self.width() // 2, y + self.height(), None)
        self._present(x, y, ms)

    def show_in_corner(self, text, ms=3200):
        self._fit(text)
        area = QGuiApplication.primaryScreen().availableGeometry()
        x, y = area.right() - self.width() - 24, area.bottom() - self.height() - 24
        self._anchor = (x + self.width() // 2, y + self.height(), None)
        self._present(x, y, ms)

    def _present(self, x, y, ms):
        self.move(x, y)
        self.show()
        if IS_WINDOWS:
            from ..platform import winapi

            winapi.apply_noactivate(int(self.winId()))
        self._timer.start(ms)


class LiveCaption(QWidget):
    """The words dictation has heard so far, in a bubble by the mini bar (never takes focus).

    Large text, as wide and as tall as the words need (up to MAX_WIDTH and LINES lines), the
    newest line at the bottom right above the bar. Whisper's words are in the text color, the
    instant preview's newer words a little dimmer, and the newest word in the accent color.
    Older lines scroll away a whole line at a time, so words never jump around inside a line.
    """

    cancel_clicked = Signal()
    MIN_WIDTH, MAX_WIDTH, LINES, PAD = PILL_W, 460, 3, 12
    FONT_PT = 13  # 1.3x the app's 10 pt

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self.setWindowTitle("TTSPython dictation")
        self._tokens = {}
        self._parts = ("", "", "")
        self._status = ""
        self._pulse = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(self.PAD + 4, self.PAD - 2, self.PAD - 4, self.PAD - 2)
        lay.setSpacing(6)
        self.text = QLabel()
        self.text.setObjectName("CaptionText")
        self.text.setWordWrap(False)  # lines are broken here, so finished lines never re-wrap
        self.text.setTextFormat(Qt.RichText)
        self.text.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.text.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.cancel = _pill_button("close", "Cancel dictation (Esc): nothing is typed", size=26, icon_size=14,
                                   role="muted")
        self.cancel.clicked.connect(self.cancel_clicked)
        lay.addWidget(self.text, 1)
        lay.addWidget(self.cancel, 0, Qt.AlignVCenter)
        from PySide6.QtCore import QTimer

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(550)
        self._pulse_timer.timeout.connect(self._pulse_tick)

    def set_tokens(self, tokens):
        self._tokens = tokens
        self.setStyleSheet(f"""
            QToolButton#PillButton {{ background: transparent; border: none; border-radius: 13px; padding: 0px; }}
            QToolButton#PillButton:hover {{ background: {tokens['hover']}; }}
            QLabel#CaptionText {{ font-size: {self.FONT_PT}pt; }}
        """)
        self.text.ensurePolished()
        self._render()

    def start(self):
        self._parts = ("", "", "")
        self.set_status("Listening...")

    def set_status(self, text):
        self._status = text
        listening = bool(text) and not any(self._parts)
        if listening and not self._pulse_timer.isActive():
            self._pulse_timer.start()
        elif not listening:
            self._pulse_timer.stop()
        self._render()

    def set_words(self, settled, checked, preview=""):
        self._parts = (settled, checked, preview)
        self._status = ""
        self._pulse_timer.stop()
        self._render()

    def hideEvent(self, event):  # noqa: N802
        self._pulse_timer.stop()
        super().hideEvent(event)

    def _pulse_tick(self):
        self._pulse = not self._pulse
        self._render()

    def _room(self):
        return self.MAX_WIDTH - 2 * self.PAD - self.cancel.width() - 10

    def lines(self):
        """[[(word, kind)]] for the lines on show: kind is "text", "preview" or "newest"."""
        settled, checked, preview = self._parts
        words = [(w, "text") for w in f"{settled} {checked}".split()] + [(w, "preview") for w in preview.split()]
        if not words:
            return []
        words[-1] = (words[-1][0], "newest")
        fm = QFontMetrics(self.text.font())
        room, space = self._room(), fm.horizontalAdvance(" ")
        lines, line, width = [], [], 0
        for word, kind in words:
            w = fm.horizontalAdvance(word)
            if line and width + space + w > room:
                lines.append(line)
                line, width = [], 0
            width += (space if line else 0) + w
            line.append((word, kind))
        lines.append(line)
        return lines[-self.LINES:]

    def _render(self):
        from html import escape

        t = self._tokens
        text, muted = t.get("text", "#e6e8ee"), t.get("muted", "#8b93a7")
        accent = t.get("accent", "#3b82f6")
        preview = QColor(text)
        preview.setAlphaF(0.62)
        colors = {"text": text, "preview": preview.name(QColor.HexArgb), "newest": accent}
        lines = self.lines()
        if not lines:
            dot = accent if self._pulse else muted
            status = self._status or "Listening..."
            html = (f'<span style="color:{dot}">&#9679;</span>&nbsp; '
                    f'<span style="color:{muted}">{escape(status)}</span>')
        else:
            if colors["preview"].startswith("#") and len(colors["preview"]) == 9:  # #AARRGGBB -> rgba()
                c = QColor(colors["preview"])
                colors["preview"] = f"rgba({c.red()},{c.green()},{c.blue()},{c.alphaF():.2f})"
            html = "<br>".join(
                " ".join(f'<span style="color:{colors[kind]}">{escape(word)}</span>' for word, kind in line)
                for line in lines)
        self.text.setText(html)
        fm = QFontMetrics(self.text.font())
        widest = max((fm.horizontalAdvance(" ".join(w for w, _k in line)) for line in lines),
                     default=fm.horizontalAdvance("\u25cf  " + (self._status or "Listening...")))
        extra = 2 * self.PAD + self.cancel.width() + 10
        width = max(self.MIN_WIDTH if lines else 0, min(self.MAX_WIDTH, widest + extra + 4))
        height = max(len(lines), 1) * fm.lineSpacing() + 2 * (self.PAD - 2) + 4
        self.setFixedSize(int(width), int(max(height, self.cancel.height() + 2 * (self.PAD - 2))))

    def show_by(self, pill):
        """Above the pill (below it near the top of the screen), or in the corner without one.
        The bottom edge stays put as lines are added, so the newest words stay in one place."""
        if pill is not None and pill.isVisible():
            geo = pill.frameGeometry()
            screen = QGuiApplication.screenAt(geo.center()) or QGuiApplication.primaryScreen()
            area = screen.availableGeometry()
            x = min(max(area.left() + 8, geo.center().x() - self.width() // 2), area.right() - self.width() - 8)
            y = geo.top() + MARGIN - self.height() - 6
            if y < area.top():
                y = geo.bottom() - MARGIN + 6
        else:
            area = QGuiApplication.primaryScreen().availableGeometry()
            x, y = area.right() - self.width() - 24, area.bottom() - self.height() - 24
        self.move(x, y)
        if not self.isVisible():
            self.show()

    def paintEvent(self, _event):  # noqa: N802
        t = self._tokens
        if not t:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)
        p.fillPath(path, QColor(t["surface"]))
        pen = QPen(QColor(t["border"]))
        pen.setWidthF(1.0 * t.get("border_w", 1))
        p.setPen(pen)
        p.drawPath(path)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if IS_WINDOWS:
            from ..platform import winapi

            winapi.apply_noactivate(int(self.winId()))

    def nativeEvent(self, event_type, message):  # noqa: N802
        if IS_WINDOWS and event_type == b"windows_generic_MSG":
            from ..platform import winapi

            msg = winapi.MSG.from_address(int(message))
            if msg.message == winapi.WM_MOUSEACTIVATE:
                return True, winapi.MA_NOACTIVATE  # clicking X must not take focus from the app
        return False, 0


class QuickPopover(QFrame):
    """Voice, speed and volume, opened from the pill."""

    voice_changed = Signal(str)
    rate_changed = Signal(int)
    volume_changed = Signal(float)
    pause_clicked = Signal()
    hide_mini = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("Card")
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setFixedWidth(290)
        self._previous_hwnd = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        def section(text):
            lab = QLabel(text.upper())
            lab.setObjectName("SectionLabel")
            return lab

        lay.addWidget(section("Voice"))
        self.voice = ElidingComboBox(chars=16)
        lay.addWidget(self.voice)
        lay.addWidget(section("Speed"))
        row = QHBoxLayout()
        self.rate = QSlider(Qt.Horizontal)
        self.rate.setRange(speed_percent(RATE_MIN), speed_percent(RATE_MAX))
        self.rate.setSingleStep(5)
        self.rate_label = QLabel("100%")
        self.rate_label.setObjectName("Muted")
        width = QFontMetrics(self.rate_label.font()).horizontalAdvance("200%") + 4
        self.rate_label.setMinimumWidth(width)
        row.addWidget(self.rate)
        row.addWidget(self.rate_label)
        lay.addLayout(row)
        lay.addWidget(section("Volume"))
        vrow = QHBoxLayout()
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(10, 100)
        self.volume_label = QLabel("100%")
        self.volume_label.setObjectName("Muted")
        self.volume_label.setMinimumWidth(width)
        vrow.addWidget(self.volume)
        vrow.addWidget(self.volume_label)
        lay.addLayout(vrow)
        hide = QToolButton()
        hide.setText("Hide mini mode")
        hide.setProperty("variant", "ghost")
        hide.setCursor(Qt.PointingHandCursor)
        self.pause = QToolButton()
        self.pause.setText("Pause")
        self.pause.setToolTip("Pause or resume speech")
        self.pause.setProperty("variant", "ghost")
        self.pause.setCursor(Qt.PointingHandCursor)
        self.pause.clicked.connect(self.pause_clicked)
        bottom = QHBoxLayout()
        bottom.addWidget(self.pause)
        bottom.addStretch(1)
        bottom.addWidget(hide)
        lay.addSpacing(2)
        lay.addLayout(bottom)

        self.voice.currentIndexChanged.connect(lambda _i: self.voice.currentData() and self.voice_changed.emit(self.voice.currentData()))
        self.rate.valueChanged.connect(lambda v: (self.rate_label.setText(f"{v}%"), self.rate_changed.emit(percent_wpm(v))))
        self.volume.valueChanged.connect(lambda v: (self.volume_label.setText(f"{v}%"), self.volume_changed.emit(v / 100.0)))
        hide.clicked.connect(self._hide_mini)

    def set_speech_state(self, busy, paused):
        self.pause.setEnabled(busy)
        icons.apply(self.pause, "play" if paused else "pause", "text", 14)
        self.pause.setText("Resume" if paused else "Pause")
        self.pause.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

    def _hide_mini(self):
        # The main window is about to come forward: do not hand focus back to the previous app.
        self._previous_hwnd = 0
        self.hide()
        self.hide_mini.emit()

    def set_values(self, voices, voice_id, rate, volume):
        for w in (self.voice, self.rate, self.volume):
            w.blockSignals(True)
        self.voice.clear()
        for i, v in enumerate(voices):
            self.voice.addItem(voice_label(v.name), v.id)
            self.voice.setItemData(i, v.name, Qt.ToolTipRole)
        self.voice.setCurrentIndex(max(0, self.voice.findData(voice_id)))
        self.rate.setValue(speed_percent(rate))
        self.rate_label.setText(f"{speed_percent(rate)}%")
        self.volume.setValue(int(round(volume * 100)))
        self.volume_label.setText(f"{self.volume.value()}%")
        for w in (self.voice, self.rate, self.volume):
            w.blockSignals(False)

    def open_at(self, global_pos, anchor: QRect):
        if IS_WINDOWS:
            from ..platform import winapi

            fg = winapi.foreground_window()
            self._previous_hwnd = 0 if winapi.is_own_window(fg) else fg
        self.adjustSize()
        screen = QGuiApplication.screenAt(global_pos) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(max(area.left() + 8, anchor.center().x() - self.width() // 2), area.right() - self.width() - 8)
        below = anchor.bottom() - MARGIN + 6
        y = below if below + self.height() < area.bottom() else anchor.top() + MARGIN - self.height() - 6
        self.move(x, y)
        self.show()
        self.activateWindow()

    def hideEvent(self, event):  # noqa: N802
        super().hideEvent(event)
        if IS_WINDOWS and self._previous_hwnd:
            from ..platform import winapi

            if winapi.is_own_window(winapi.foreground_window()):
                winapi.set_foreground(self._previous_hwnd)
            self._previous_hwnd = 0
