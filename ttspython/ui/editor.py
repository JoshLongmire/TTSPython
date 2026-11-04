"""Editor card: text area with sentence highlight, inline find bar, header."""
from __future__ import annotations

import re

from PySide6.QtCore import QEvent, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor, QTextFormat
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QTextEdit, QVBoxLayout, QWidget,
)

from ..core import search
from ..core.chunking import utf16_len
from . import icons
from .style import EDITOR_FONT_CANDIDATES, pick_family
from .widgets import ElidedLabel, TextFileDropMixin, action_button, mute_clear_button, tool_button


_SENTENCE_END = re.compile(r"[.!?…]+[\"'”’)\]]*\s+|\n\s*")


def sentence_start(text, index):
    """Index of the start of the sentence that contains index."""
    start = 0
    for m in _SENTENCE_END.finditer(text, 0, index):
        start = m.end()
    return start


def reading_time(words, wpm):
    """ "about 3 min" at this speed (under a minute: "under 1 min")."""
    minutes = words / max(1, wpm)
    if minutes < 1:
        return "under 1 min"
    if minutes < 90:
        return f"about {round(minutes)} min"
    return f"about {minutes / 60:.1f} h"


def py_to_u16(text, index):
    return utf16_len(text[:index])


def u16_to_py(text, pos16):
    """Python index for a UTF-16 position (clamped)."""
    if pos16 <= 0:
        return 0
    if text.isascii() or utf16_len(text) == len(text):  # no emoji or other 4-byte characters
        return min(pos16, len(text))
    count = 0
    for i, ch in enumerate(text):
        if count >= pos16:
            return i
        count += 2 if ord(ch) > 0xFFFF else 1
    return len(text)


class SpeechTextEdit(TextFileDropMixin, QPlainTextEdit):
    """Plain text editor that can highlight the sentence being spoken."""

    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.menu_actions = []  # added to the right-click menu (Speak from here, Speak selected)
        self.setObjectName("Editor")
        font = QFont(pick_family(EDITOR_FONT_CANDIDATES))
        font.setPointSizeF(12)
        self.setFont(font)
        self.setPlaceholderText("Type or paste text here, then press Play (Ctrl+Enter). Press it again to pause.")
        self.setFrameShape(QFrame.NoFrame)
        self.document().setDocumentMargin(14)
        self._sentence = None
        self._sentence_color = QColor("#333")
        self._highlight_enabled = True
        self._valid_revision = None
        self.document().contentsChanged.connect(self._on_changed)

    def contextMenuEvent(self, event):  # noqa: N802
        menu = self.createStandardContextMenu(event.pos())
        if self.menu_actions:
            first = menu.actions()[0] if menu.actions() else None
            for action in self.menu_actions:
                menu.insertAction(first, action)
            menu.insertSeparator(first)
        menu.exec(event.globalPos())
        menu.deleteLater()

    def set_highlight_color(self, color):
        self._sentence_color = QColor(color)
        if self._sentence:
            self.highlight_range(*self._sentence)

    def set_highlight_enabled(self, enabled):
        self._highlight_enabled = enabled
        if not enabled:
            self.clear_highlight()

    def begin_tracking(self):
        """Call when speech of the editor text starts; edits invalidate highlights."""
        self._valid_revision = self.document().revision()

    def stop_tracking(self):
        self._valid_revision = None
        self.clear_highlight()

    def _on_changed(self):
        if self._valid_revision is not None and self.document().revision() != self._valid_revision:
            self._valid_revision = None
            self.clear_highlight()

    def highlight_range(self, start16, end16):
        if not self._highlight_enabled or self._valid_revision is None:
            return
        doc_len = self.document().characterCount() - 1
        start16 = max(0, min(start16, doc_len))
        end16 = max(start16, min(end16, doc_len))
        self._sentence = (start16, end16)
        sel = QTextEdit.ExtraSelection()
        fmt = QTextCharFormat()
        fmt.setBackground(self._sentence_color)
        fmt.setProperty(QTextFormat.FullWidthSelection, False)
        sel.format = fmt
        cursor = QTextCursor(self.document())
        cursor.setPosition(start16)
        cursor.setPosition(end16, QTextCursor.KeepAnchor)
        sel.cursor = cursor
        self.setExtraSelections([sel])
        self._scroll_into_view(cursor)

    def _scroll_into_view(self, cursor):
        rect = self.cursorRect(cursor)
        viewport = self.viewport().rect()
        if rect.top() < 0 or rect.bottom() > viewport.height():
            bar = self.verticalScrollBar()
            bar.setValue(bar.value() + int((rect.top() - viewport.height() / 3) / max(1, self.fontMetrics().lineSpacing())))

    def clear_highlight(self):
        self._sentence = None
        self.setExtraSelections([])

    def selection_info(self):
        """(text with \\n newlines, start16) of the current selection, or ("", 0)."""
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return "", 0
        text = cursor.selectedText().replace(" ", "\n").replace(" ", "\n")
        return text, cursor.selectionStart()

    def replace_all_text(self, new_text):
        """Replace the whole document as one undoable step."""
        cursor = QTextCursor(self.document())
        cursor.beginEditBlock()
        cursor.select(QTextCursor.Document)
        cursor.insertText(new_text)
        cursor.endEditBlock()

    def clear_undoable(self):
        cursor = QTextCursor(self.document())
        cursor.select(QTextCursor.Document)
        cursor.removeSelectedText()

    def append_line(self, text):
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.End)
        current = self.toPlainText()
        prefix = "" if not current or current.endswith("\n") else "\n"
        cursor.insertText(prefix + text + "\n")
        self.setTextCursor(cursor)
        self.ensureCursorVisible()


class FindBar(QFrame):
    """Inline find and replace (case-sensitive and regex options)."""

    message = Signal(str)

    def __init__(self, editor: SpeechTextEdit, parent=None):
        super().__init__(parent)
        self.setObjectName("FindBar")
        self.editor = editor
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(6)

        row1 = QHBoxLayout()
        row1.setSpacing(6)
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Find")
        self.find_edit.setClearButtonEnabled(True)
        mute_clear_button(self.find_edit)
        self.case_btn = tool_button("case", "Match case", checkable=True)
        self.regex_btn = tool_button("regex", "Use regular expression", checkable=True)
        self.prev_btn = tool_button("chevron_up", "Previous match (Shift+Enter)")
        self.next_btn = tool_button("chevron_down", "Next match (Enter)")
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        self.status.setMinimumWidth(90)
        close_btn = tool_button("close", "Close (Esc)")
        for w in (self.find_edit, self.case_btn, self.regex_btn, self.prev_btn, self.next_btn, self.status, close_btn):
            row1.addWidget(w)
        row1.setStretch(0, 1)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        self.replace_edit = QLineEdit()
        self.replace_edit.setPlaceholderText("Replace with")
        self.replace_btn = tool_button("replace", "Replace this match", variant="ghost", text="Replace")
        self.replace_all_btn = tool_button("replace_all", "Replace every match", variant="ghost", text="Replace all")
        row2.addWidget(self.replace_edit, 1)
        row2.addWidget(self.replace_btn)
        row2.addWidget(self.replace_all_btn)
        spacer = QWidget()
        spacer.setFixedWidth(close_btn.sizeHint().width() + 96)
        row2.addWidget(spacer)

        outer.addLayout(row1)
        outer.addLayout(row2)

        self.find_edit.returnPressed.connect(lambda: self.find(False))
        self.next_btn.clicked.connect(lambda: self.find(False))
        self.prev_btn.clicked.connect(lambda: self.find(True))
        self.replace_btn.clicked.connect(self.replace_one)
        self.replace_all_btn.clicked.connect(self.replace_all)
        self.replace_edit.returnPressed.connect(self.replace_one)
        close_btn.clicked.connect(self.close_bar)
        self._count_timer = QTimer(self)
        self._count_timer.setSingleShot(True)
        self._count_timer.setInterval(200)
        self._count_timer.timeout.connect(self._show_count)
        self.find_edit.textChanged.connect(lambda _t: self._count_timer.start())
        self.case_btn.toggled.connect(lambda _c: self._count_timer.start())
        self.regex_btn.toggled.connect(lambda _c: self._count_timer.start())
        for edit in (self.find_edit, self.replace_edit):
            edit.installEventFilter(self)
        self.hide()

    def eventFilter(self, obj, event):  # noqa: N802
        etype = event.type()
        if etype == QEvent.ShortcutOverride and event.key() == Qt.Key_Escape:
            # Claim Esc before the window's Stop shortcut sees it.
            event.accept()
            return True
        if etype == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape:
                self.close_bar()
                return True
            if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ShiftModifier:
                self.find(True)  # handled here so returnPressed (find forward) does not also fire
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.close_bar()
            return
        super().keyPressEvent(event)

    def open_bar(self):
        selected, _ = self.editor.selection_info()
        if selected and "\n" not in selected:
            self.find_edit.setText(selected)
        self.show()
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def close_bar(self):
        self.hide()
        self.editor.setFocus()

    def _opts(self):
        return dict(case_sensitive=self.case_btn.isChecked(), use_regex=self.regex_btn.isChecked())

    def _show_count(self, current=None):
        """ "3 matches" while typing; "2 of 5" once on a match."""
        term = self.find_edit.text()
        if not term:
            self.status.setText("")
            return
        try:
            starts = search.match_starts(self.editor.toPlainText(), term, **self._opts())
        except search.SearchError:
            self.status.setText("Invalid")
            return
        if not starts:
            self.status.setText("No matches")
        elif current is not None and current in starts:
            self.status.setText(f"{starts.index(current) + 1} of {len(starts)}")
        else:
            self.status.setText(f"{len(starts)} match{'es' if len(starts) != 1 else ''}")

    def find(self, backwards=False):
        term = self.find_edit.text()
        text = self.editor.toPlainText()
        cursor = self.editor.textCursor()
        pos16 = cursor.selectionStart() if backwards else cursor.selectionEnd()
        start = u16_to_py(text, pos16)
        try:
            found = search.find_next(text, term, start, backwards=backwards, **self._opts())
        except search.SearchError as exc:
            self.status.setText("Invalid")
            self.message.emit(str(exc))
            return False
        if not found:
            self.status.setText("No matches")
            return False
        s, e, wrapped = found
        new = QTextCursor(self.editor.document())
        new.setPosition(py_to_u16(text, s))
        new.setPosition(py_to_u16(text, e), QTextCursor.KeepAnchor)
        self.editor.setTextCursor(new)
        self.editor.ensureCursorVisible()
        self._count_timer.stop()
        self._show_count(s)
        if wrapped:
            self.message.emit("Search wrapped around")
        return True

    def replace_one(self):
        term = self.find_edit.text()
        cursor = self.editor.textCursor()
        selected = cursor.selectedText().replace("\u2029", "\n")  # how Qt writes a line break here
        if selected:
            try:
                pattern = search.compile_pattern(term, **self._opts())
            except search.SearchError as exc:
                self.message.emit(str(exc))
                return
            if pattern.fullmatch(selected):
                try:
                    repl = search.replacement_for(selected, term, self.replace_edit.text(), **self._opts())
                except search.SearchError as exc:
                    self.message.emit(str(exc))
                    return
                cursor.insertText(repl)
        self.find(False)

    def replace_all(self):
        text = self.editor.toPlainText()
        try:
            new, count = search.replace_all(text, self.find_edit.text(), self.replace_edit.text(), **self._opts())
        except search.SearchError as exc:
            self.status.setText("Invalid")
            self.message.emit(str(exc))
            return 0
        if count:
            self.editor.replace_all_text(new)
        self.status.setText(f"{count} replaced")
        self.message.emit(f"Replaced {count} occurrence{'s' if count != 1 else ''}")
        return count


class EditorCard(QFrame):
    """Card holding the header, find bar and editor."""

    def __init__(self, paste_action, clear_action, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        header = QWidget()
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 10, 10, 6)
        hl.setSpacing(8)
        self.doc_icon = QLabel()
        self.title = ElidedLabel("Untitled", Qt.ElideMiddle)
        self.title.setObjectName("CardTitle")
        self.modified = QFrame()
        self.modified.setObjectName("Dot")
        self.modified.setFixedSize(6, 6)
        self.modified.setToolTip("Unsaved changes")
        self.modified.hide()
        self.counts = QLabel("0 words")
        self.counts.setObjectName("Muted")

        hl.addWidget(self.doc_icon)
        hl.addWidget(self.title)
        hl.addWidget(self.modified)
        hl.addStretch(1)
        hl.addWidget(self.counts)
        hl.addSpacing(6)
        hl.addWidget(action_button(paste_action, show_text=True, size=16))
        hl.addWidget(action_button(clear_action, show_text=True, size=16))

        self.editor = SpeechTextEdit()
        self.find_bar = FindBar(self.editor)
        lay.addWidget(header)
        lay.addWidget(self.find_bar)
        lay.addWidget(self.editor, 1)

        self.wpm = 200  # for the reading time
        self._words = self._chars = 0
        self._count_timer = QTimer(self)
        self._count_timer.setSingleShot(True)
        self._count_timer.timeout.connect(self._update_counts)
        self.editor.textChanged.connect(self._count_soon)
        self.editor.modificationChanged.connect(self.modified.setVisible)
        self.refresh_icons()

    def refresh_icons(self):
        self.doc_icon.setPixmap(icons.pixmap("file_text", icons.color("muted"), 16, self.devicePixelRatioF()))

    def set_title(self, title):
        self.title.setText(title)

    def _count_soon(self):
        # Big documents are counted less often while typing (a split of megabytes takes a while).
        self._count_timer.start(150 if self.editor.document().characterCount() < 200_000 else 1000)

    def set_wpm(self, wpm):
        self.wpm = max(1, int(wpm))
        if not self._count_timer.isActive():  # or its count is on the way
            self._show_counts()

    COMPACT_BELOW = 640  # narrower cards drop the character count

    def _update_counts(self):
        self._count_timer.stop()  # this is the count it was waiting to do
        text = self.editor.toPlainText()
        self._words, self._chars = len(text.split()), len(text)
        self._show_counts()

    def _show_counts(self):
        """From the last count: dragging the speed must not split the whole document at every step."""
        words = self._words
        parts = [f"{words:,} word{'s' if words != 1 else ''}"]
        if self.width() >= self.COMPACT_BELOW:
            parts.append(f"{self._chars:,} characters")
        if words:
            parts.append(reading_time(words, self.wpm))
        self.counts.setText("  ·  ".join(parts))

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if (event.oldSize().width() >= self.COMPACT_BELOW) != (event.size().width() >= self.COMPACT_BELOW):
            self._show_counts()
