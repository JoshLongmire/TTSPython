"""Marshal core events (any thread) onto the Qt GUI thread as signals."""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal


class SpeechBridge(QObject):
    state_changed = Signal(object)
    voices_ready = Signal(list, str)
    chunk_started = Signal(int, int, int, int, int, object)
    queue_item_started = Signal(str)
    queue_finished = Signal(bool)
    queue_changed = Signal()
    error = Signal(str)

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        ev = controller.events
        ev.on("state_changed", self.state_changed.emit)
        ev.on("voices_ready", self.voices_ready.emit)
        ev.on("chunk_started", self.chunk_started.emit)
        ev.on("queue_item_started", self.queue_item_started.emit)
        ev.on("queue_finished", self.queue_finished.emit)
        # Once the event loop runs (the UI has connected to error by then): an engine that
        # failed while starting holds its error until this subscribes.
        QTimer.singleShot(0, lambda: ev.on("error", self.error.emit))
        controller.queue.events.on("changed", self.queue_changed.emit)


class SttBridge(QObject):
    state_changed = Signal(object)
    partial = Signal(str, str, str)
    transcript_ready = Signal(str, object)
    model_status = Signal(str)
    preview_status = Signal(str)
    error = Signal(str)

    def __init__(self, service, parent=None):
        super().__init__(parent)
        ev = service.events
        ev.on("state_changed", self.state_changed.emit)
        ev.on("partial", self.partial.emit)
        ev.on("transcript_ready", self.transcript_ready.emit)
        ev.on("model_status", self.model_status.emit)
        ev.on("preview_status", self.preview_status.emit)
        ev.on("error", self.error.emit)


class ExportBridge(QObject):
    progress = Signal(int, int)
    finished = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, exporter, parent=None):
        super().__init__(parent)
        ev = exporter.events
        ev.on("progress", self.progress.emit)
        ev.on("finished", self.finished.emit)
        ev.on("failed", self.failed.emit)
        ev.on("cancelled", self.cancelled.emit)
