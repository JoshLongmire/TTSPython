"""Decides what a clipboard change should do (v4 rules, minus the races)."""
from __future__ import annotations

import time
from enum import Enum

MIN_LENGTH = 6  # v4 ignored text of 5 characters or fewer


class Action(Enum):
    IGNORE = "ignore"
    SPEAK = "speak"
    ENQUEUE = "enqueue"


class ClipboardRouter:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self.last_text = ""
        self._suppress = {}
        self._paused_until = 0.0

    def prime(self, text):
        """Remember the current clipboard so it does not trigger on enable."""
        self.last_text = text or ""

    def suppress(self, text, seconds=1.5):
        """Ignore our own clipboard writes (dictation paste and restore)."""
        if text:
            self._suppress[text] = self._clock() + seconds

    def pause(self, seconds=1.5):
        """Ignore every change for a while (reading a selection briefly uses the clipboard)."""
        self._paused_until = max(self._paused_until, self._clock() + seconds)

    def decide(self, text, *, busy, action, auto_queue):
        """Return (Action, label) where label names the queue entry or reason."""
        now = self._clock()
        self._suppress = {t: until for t, until in self._suppress.items() if until > now}
        if not text or not text.strip():
            return Action.IGNORE, "empty"
        if text == self.last_text:
            return Action.IGNORE, "unchanged"
        if now < self._paused_until:  # last_text is kept, so the restored clipboard reads as unchanged
            return Action.IGNORE, "own write"
        self.last_text = text
        if text in self._suppress:
            return Action.IGNORE, "own write"
        if len(text.strip()) < MIN_LENGTH:
            return Action.IGNORE, "too short"
        if action == "queue":
            return Action.ENQUEUE, "Clipboard"
        if not busy:
            return Action.SPEAK, "speak"
        if auto_queue:
            return Action.ENQUEUE, "Auto-Queued"
        return Action.IGNORE, "busy"
