"""Tiny thread-safe event emitter used by the core services."""
from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)


class EventEmitter:
    def __init__(self):
        self._lock = threading.Lock()
        self._handlers = {}
        self._held = {}  # name -> [args], kept by emit(..., hold=True) until someone listens

    def on(self, name, callback):
        with self._lock:
            self._handlers.setdefault(name, []).append(callback)
            held = self._held.pop(name, [])
        for args in held:
            self._call(name, callback, args)
        return callback

    def emit(self, name, *args, hold=False):
        """hold: if nobody listens yet (a worker thread that starts in a constructor), keep the
        event and deliver it to the first listener."""
        with self._lock:
            handlers = list(self._handlers.get(name, []))
            if hold and not handlers:
                self._held.setdefault(name, []).append(args)
        for handler in handlers:
            self._call(name, handler, args)

    @staticmethod
    def _call(name, handler, args):
        try:
            handler(*args)
        except Exception:
            log.exception("event handler for %s failed", name)
