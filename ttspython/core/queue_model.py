"""Speech queue with stable item ids, safe to mutate while it plays."""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field

from .events import EventEmitter

KINDS = ("text", "file", "clipboard")


def preview(text, length=50):
    flat = " ".join(text.split())
    return flat[:length] + "..." if len(flat) > length else flat


@dataclass
class QueueItem:
    text: str
    name: str
    kind: str = "text"
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    pending: bool = True
    words: int = field(default=0, compare=False)

    def __post_init__(self):
        self.words = len(self.text.split())  # counted once, not on every list refresh


class SpeechQueue:
    """Ordered items; emits "changed" after every change to the list."""

    def __init__(self):
        self._lock = threading.RLock()
        self._items = []
        self._removed_successor = {}
        self.events = EventEmitter()

    def _changed(self):
        self.events.emit("changed")

    def __len__(self):
        with self._lock:
            return len(self._items)

    def snapshot(self):
        with self._lock:
            return list(self._items)

    def get(self, item_id):
        with self._lock:
            for item in self._items:
                if item.id == item_id:
                    return item
        return None

    def index_of(self, item_id):
        with self._lock:
            for i, item in enumerate(self._items):
                if item.id == item_id:
                    return i
        return -1

    def add(self, text, name, kind="text"):
        item = QueueItem(text=text, name=name, kind=kind if kind in KINDS else "text")
        with self._lock:
            self._items.append(item)
        self._changed()
        return item

    def remove(self, item_id):
        with self._lock:
            idx = self.index_of(item_id)
            if idx < 0:
                return False
            del self._items[idx]
            self._removed_successor[item_id] = self._items[idx].id if idx < len(self._items) else None
            self._trim_removed()
        self._changed()
        return True

    def move(self, item_id, delta):
        with self._lock:
            idx = self.index_of(item_id)
            new = idx + delta
            if idx < 0 or new < 0 or new >= len(self._items):
                return False
            item = self._items.pop(idx)
            self._items.insert(new, item)
        self._changed()
        return True

    def _trim_removed(self, keep=500):
        """Only the most recent removals matter (the playing item); keep the map bounded."""
        while len(self._removed_successor) > keep:
            self._removed_successor.pop(next(iter(self._removed_successor)))

    def reorder(self, ids):
        """Apply a new order (from drag and drop). Unknown ids are ignored."""
        with self._lock:
            by_id = {item.id: item for item in self._items}
            ordered = [by_id.pop(i) for i in ids if i in by_id]
            self._items = ordered + [item for item in self._items if item.id in by_id]
        self._changed()

    def clear(self):
        with self._lock:
            for item in self._items:
                self._removed_successor[item.id] = None
            self._items.clear()
            self._trim_removed()
        self._changed()

    # Played/pending marks are playback bookkeeping, not shown in the list: no "changed".
    def mark_all_pending(self):
        with self._lock:
            for item in self._items:
                item.pending = True

    def mark_played(self, item_id):
        with self._lock:
            item = self.get(item_id)
            if item:
                item.pending = False

    def first(self):
        with self._lock:
            return self._items[0] if self._items else None

    def first_pending(self):
        with self._lock:
            for item in self._items:
                if item.pending:
                    return item
        return None

    def next_after(self, item_id, loop=False):
        """The item to play after item_id, which may have been moved or removed."""
        with self._lock:
            idx = self.index_of(item_id)
            if idx >= 0:
                if idx + 1 < len(self._items):
                    return self._items[idx + 1]
            elif item_id in self._removed_successor:
                successor = self._removed_successor[item_id]
                seen = set()
                while successor is not None and successor not in seen:
                    seen.add(successor)
                    found = self.get(successor)
                    if found is not None:
                        return found
                    successor = self._removed_successor.get(successor)
            else:
                return None
            if loop and self._items:
                return self._items[0]
            return None
