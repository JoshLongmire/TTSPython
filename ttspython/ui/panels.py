"""Queue side panel, transport bar and the Listen (dictation) panel."""
from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar,
    QSizePolicy, QStyle, QStyledItemDelegate, QToolButton, QVBoxLayout, QWidget,
)

from ..core.settings import RATE_MAX, RATE_MIN, percent_wpm, speed_percent
from . import icons
from .editor import reading_time
from .widgets import ElidedLabel, Slider, TextFileDropMixin, Waveform, action_button, dropped_text_files

KIND_ICONS = {"text": "file_text", "file": "file_text", "clipboard": "clipboard"}


ID_ROLE = Qt.UserRole + 1
KIND_ROLE = Qt.UserRole + 2
WORDS_ROLE = Qt.UserRole + 3
PLAYING_ROLE = Qt.UserRole + 4


class QueueDelegate(QStyledItemDelegate):
    wpm = 200  # for the listening time shown under each item

    def sizeHint(self, option, index):  # noqa: N802
        return QSize(option.rect.width(), 46)

    def paint(self, p, option, index):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(option.rect).adjusted(2, 2, -2, -2)
        playing = bool(index.data(PLAYING_ROLE))
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        if selected or playing:
            bg = QColor(icons.color("accent"))
            bg.setAlpha(46 if selected else 30)
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(rect, 8, 8)
        elif hovered:
            bg = QColor(icons.color("text"))
            bg.setAlpha(14)
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(rect, 8, 8)
        if playing:
            p.setBrush(QColor(icons.color("accent")))
            p.drawRoundedRect(QRectF(rect.left() + 1, rect.top() + 9, 3, rect.height() - 18), 1.5, 1.5)
        kind = index.data(KIND_ROLE) or "text"
        icon_name = "play" if playing else KIND_ICONS.get(kind, "file_text")
        role = "accent" if playing else "muted"
        pm = icons.pixmap(icon_name, icons.color(role), 16, p.device().devicePixelRatioF())
        p.drawPixmap(int(rect.left() + 12), int(rect.center().y() - 8), pm)
        text_rect = QRect(int(rect.left() + 38), int(rect.top() + 5), int(rect.width() - 46), 18)
        sub_rect = QRect(int(rect.left() + 38), int(rect.top() + 23), int(rect.width() - 46), 16)
        font = option.font
        if playing:
            font.setWeight(font.Weight.DemiBold)
        p.setFont(font)
        p.setPen(QColor(icons.color("text")))
        name = QFontMetrics(font).elidedText(index.data(Qt.DisplayRole) or "", Qt.ElideRight, text_rect.width())
        p.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, name)
        small = option.font
        small.setPointSizeF(max(7.0, small.pointSizeF() - 1.2))
        small.setWeight(small.Weight.Normal)
        p.setFont(small)
        p.setPen(QColor(icons.color("muted")))
        words = index.data(WORDS_ROLE) or 0
        label = {"file": "File", "clipboard": "Clipboard"}.get(kind, "Text")
        status = "  ·  Now playing" if playing else ""
        line = f"{label}  ·  {words:,} words  ·  {reading_time(words, self.wpm)}{status}"
        p.drawText(sub_rect, Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(small).elidedText(line, Qt.ElideRight, sub_rect.width()))
        p.restore()


class QueueList(TextFileDropMixin, QListWidget):
    reordered = Signal(list)
    delete_pressed = Signal()
    files_dropped = Signal(list)
    menu_requested = Signal(str, object)  # item id, global position

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemDelegate(QueueDelegate(self))
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setAcceptDrops(True)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # long names are shortened instead
        self.setSpacing(1)

    def dropEvent(self, event):  # noqa: N802
        files = dropped_text_files(event.mimeData())
        super().dropEvent(event)  # files are added; items dragged inside are reordered
        if not files:
            self.reordered.emit([self.item(i).data(ID_ROLE) for i in range(self.count())])

    def contextMenuEvent(self, event):  # noqa: N802
        item = self.itemAt(event.pos())
        if item is not None:
            self.setCurrentItem(item)
            self.menu_requested.emit(item.data(ID_ROLE), event.globalPos())

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Delete:
            self.delete_pressed.emit()
            return
        super().keyPressEvent(event)


class QueuePanel(TextFileDropMixin, QFrame):
    files_dropped = Signal(list)  # also when the empty queue's message is showing instead of the list

    def __init__(self, actions, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setMinimumWidth(250)
        self.setAcceptDrops(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(6, 0, 0, 0)
        title = QLabel("Speech Queue")
        title.setObjectName("CardTitle")
        self.badge = QLabel("0")
        self.badge.setObjectName("Badge")
        self.badge.setAlignment(Qt.AlignCenter)
        header.addWidget(title)
        header.addWidget(self.badge, 0, Qt.AlignVCenter)
        header.addStretch(1)
        self.loop_btn = action_button(actions["queue_loop"], size=16)
        header.addWidget(self.loop_btn)
        header.addWidget(action_button(actions["queue_clear"], size=16))
        lay.addLayout(header)

        self.list = QueueList()
        self.files_dropped.connect(self.list.files_dropped)
        lay.addWidget(self.list, 1)

        self.empty = QLabel("Add the editor text, files or clipboard items to read them back to back, "
                            "or drop text files here.")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setObjectName("Muted")
        self.empty.setWordWrap(True)
        lay.addWidget(self.empty, 1)

        add_row = QHBoxLayout()
        add_row.setSpacing(6)
        for key in ("queue_add_text", "queue_add_files"):
            add = action_button(actions[key], show_text=True, size=16)
            add.setProperty("variant", None)
            add.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            add_row.addWidget(add, 1)
        play_row = QHBoxLayout()
        play_row.setSpacing(2)
        play = action_button(actions["queue_play"], variant="primary", show_text=True, size=16)
        play.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        play_row.addWidget(play, 1)
        play_row.addSpacing(4)
        for key in ("queue_up", "queue_down", "queue_remove"):
            play_row.addWidget(action_button(actions[key], size=16))
        lay.addLayout(add_row)
        lay.addLayout(play_row)
        self._pending = None
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.setInterval(150)
        self._retry.timeout.connect(lambda: self._pending and self.set_items(*self._pending))

    def set_items(self, items, playing_id, selected_id=None):
        if self.list.state() == QAbstractItemView.DraggingState:
            # Rebuilding mid-drag would cancel the drag: try again once it ends, with the
            # newest list (later calls replace the pending one).
            self._pending = (items, playing_id, selected_id)
            if not self._retry.isActive():
                self._retry.start()
            return
        self._pending = None
        selected_id = selected_id or self.selected_id()
        scroll = self.list.verticalScrollBar().value()
        self.list.blockSignals(True)
        self.list.clear()
        for item in items:
            li = QListWidgetItem(item.name)
            li.setData(ID_ROLE, item.id)
            li.setData(KIND_ROLE, item.kind)
            li.setData(WORDS_ROLE, item.words)
            li.setData(PLAYING_ROLE, item.id == playing_id)
            li.setToolTip(item.text[:400])
            self.list.addItem(li)
            if item.id == selected_id:
                li.setSelected(True)
                self.list.setCurrentItem(li)
        self.list.blockSignals(False)
        self.list.verticalScrollBar().setValue(scroll)
        self.badge.setText(str(len(items)))
        has = bool(items)
        self.badge.setVisible(has)
        self.list.setVisible(has)
        self.empty.setVisible(not has)

    def set_playing(self, playing_id):
        for i in range(self.list.count()):
            li = self.list.item(i)
            li.setData(PLAYING_ROLE, li.data(ID_ROLE) == playing_id)
        self.list.viewport().update()

    def selected_id(self):
        items = self.list.selectedItems()
        return items[0].data(ID_ROLE) if items else None

    def set_wpm(self, wpm):
        self.list.itemDelegate().wpm = max(1, int(wpm))
        self.list.viewport().update()


class TransportBar(QFrame):
    """Media-player style controls for speech."""

    WAVE_WIDTH = 860  # narrower windows keep the room for the progress text
    rate_changed = Signal(int)
    volume_changed = Signal(float)

    def __init__(self, actions, parent=None):
        super().__init__(parent)
        self.setObjectName("Transport")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(10)

        self.play_btn = QToolButton()
        self.play_btn.setDefaultAction(actions["play_pause"])
        self.play_btn.setProperty("variant", "round_primary")
        self.play_btn.setFixedSize(48, 48)
        self.play_btn.setIconSize(QSize(22, 22))
        self.play_btn.setCursor(Qt.PointingHandCursor)
        stop = action_button(actions["stop"], size=18)
        stop.setFixedSize(38, 38)
        selected = action_button(actions["speak_selected"], size=18)
        selected.setFixedSize(38, 38)
        lay.addWidget(self.play_btn)
        lay.addWidget(stop)
        lay.addWidget(selected)
        lay.addSpacing(8)

        center = QVBoxLayout()
        center.setSpacing(5)
        top = QHBoxLayout()
        self.now = QLabel("Ready")
        self.now.setObjectName("NowPlaying")
        self.wave = Waveform(bars=24)
        self.wave.setFixedSize(120, 16)
        self.wave.hide()
        top.addWidget(self.now, 1)
        top.addWidget(self.wave)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        center.addLayout(top)
        center.addWidget(self.progress)
        center_w = QWidget()
        center_w.setLayout(center)
        center_w.setMinimumWidth(40)
        lay.addWidget(center_w, 1)
        lay.addSpacing(8)

        speed_icon = QLabel()
        speed_icon.setPixmap(icons.pixmap("gauge", icons.color("muted"), 16, 2.0))
        self._speed_icon = speed_icon
        self.rate = Slider()
        self.rate.setAccessibleName("Speed")
        self.rate.setRange(speed_percent(RATE_MIN), speed_percent(RATE_MAX))
        self.rate.setSingleStep(5)
        self.rate.setPageStep(10)
        self.rate.setMinimumWidth(70)
        self.rate.setMaximumWidth(120)
        self.rate.setToolTip("Speed (100% is normal; changes are heard right away)")
        self.rate_label = QLabel("100%")
        self.rate_label.setObjectName("Muted")
        percent_width = QFontMetrics(self.rate_label.font()).horizontalAdvance("200%") + 4
        self.rate_label.setMinimumWidth(percent_width)
        self.rate.valueChanged.connect(self._rate_moved)
        lay.addWidget(speed_icon)
        lay.addWidget(self.rate)
        lay.addWidget(self.rate_label)
        lay.addSpacing(6)

        vol_icon = QLabel()
        self._vol_icon = vol_icon
        self.volume = Slider()
        self.volume.setAccessibleName("Volume")
        self.volume.setRange(10, 100)
        self.volume.setMinimumWidth(60)
        self.volume.setMaximumWidth(110)
        self.volume.setToolTip("Volume")
        self.volume_label = QLabel("100%")
        self.volume_label.setObjectName("Muted")
        self.volume_label.setMinimumWidth(percent_width)
        self.volume.valueChanged.connect(self._volume_moved)
        lay.addWidget(vol_icon)
        lay.addWidget(self.volume)
        lay.addWidget(self.volume_label)
        lay.addSpacing(6)
        lay.addWidget(action_button(actions["toggle_queue"], size=18))
        self.refresh_icons()

    def set_level_source(self, source):
        """The waveform shows while speech plays, next to the progress text."""
        self.wave.set_source(source)
        self._fit_wave()

    def _fit_wave(self):
        self.wave.setVisible(self.wave.active and self.width() >= self.WAVE_WIDTH)

    def resizeEvent(self, event):  # noqa: N802
        self._fit_wave()
        super().resizeEvent(event)

    def refresh_icons(self):
        dpr = self.devicePixelRatioF() or 1.0
        self._speed_icon.setPixmap(icons.pixmap("gauge", icons.color("muted"), 16, dpr))
        name = "volume" if self.volume.value() >= 50 else "volume_low"
        self._vol_icon.setPixmap(icons.pixmap(name, icons.color("muted"), 16, dpr))

    def _rate_moved(self, percent):
        self.rate_label.setText(f"{percent}%")
        self.rate_changed.emit(percent_wpm(percent))

    def _volume_moved(self, value):
        self.volume_label.setText(f"{value}%")
        self.refresh_icons()
        self.volume_changed.emit(value / 100.0)

    def set_values(self, rate, volume):
        self.rate.blockSignals(True)
        self.volume.blockSignals(True)
        self.rate.setValue(speed_percent(rate))
        self.rate_label.setText(f"{speed_percent(rate)}%")
        self.volume.setValue(int(round(volume * 100)))
        self.volume_label.setText(f"{self.volume.value()}%")
        self.rate.blockSignals(False)
        self.volume.blockSignals(False)
        self.refresh_icons()

    def set_progress(self, index, total, label):
        self.progress.setValue(int(1000 * (index + 1) / total) if total else 0)
        self.now.setText(label)

    def reset_progress(self, label="Ready"):
        self.progress.setValue(0)
        self.now.setText(label)


class ListenPanel(QFrame):
    """Dictation controls shown in Listen mode."""

    def __init__(self, record_action, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(14)
        self.record = QToolButton()
        self.record.setDefaultAction(record_action)
        self.record.setProperty("variant", "record")
        self.record.setFixedSize(48, 48)
        self.record.setIconSize(QSize(22, 22))
        self.record.setCursor(Qt.PointingHandCursor)
        lay.addWidget(self.record)

        col = QVBoxLayout()
        col.setSpacing(1)
        self.title = QLabel("Ready to dictate")
        self.title.setObjectName("CardTitle")
        self.status = QLabel("Press the button or Ctrl+Alt+D, speak, then press again. Text appears in the editor.")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        col.addWidget(self.title)
        col.addWidget(self.status)
        lay.addLayout(col, 1)
        self.wave = Waveform(bars=32)
        self.wave.color_role = "danger"
        self.wave.setFixedSize(150, 32)
        lay.addWidget(self.wave)

        chips = QVBoxLayout()
        chips.setSpacing(2)
        self.model_chip = ElidedLabel("Model: small")
        self.model_chip.setObjectName("Muted")
        self.mic_chip = ElidedLabel("Mic: System default")
        self.mic_chip.setObjectName("Muted")
        self.model_chip.set_clickable("Change the dictation model (Settings > Listen)")
        self.mic_chip.set_clickable("Change the microphone (Settings > Listen)")
        for chip in (self.model_chip, self.mic_chip):
            chip.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            chip.setMinimumWidth(110)
            chip.setMaximumWidth(200)
        chips.addWidget(self.model_chip)
        chips.addWidget(self.mic_chip)
        self._chips = QWidget()
        self._chips.setLayout(chips)
        chips.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._chips)

    def resizeEvent(self, event):  # noqa: N802
        # Small windows: the help text keeps its width; the waveform, then the chips, give way.
        width = event.size().width()
        self.wave.setVisible(width >= 700)
        self._chips.setVisible(width >= 520)
        super().resizeEvent(event)
