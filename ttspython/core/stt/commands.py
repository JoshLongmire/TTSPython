"""Spoken commands in dictated text: "new line", "period", "delete that" and so on, in English.

Whisper writes what it hears and adds its own punctuation, so a command arrives as "milk, period."
or "Milk. New line." The command word and the punctuation Whisper put around it make way for what
the command means. A word that only looks like a command stays a word: "the period of time",
"a new line of shoes", "please delete that file".
"""
from __future__ import annotations

import re

# (spoken words, what they become). Longest first, so "new paragraph" wins over a word on its own.
MARKS = {
    ("full", "stop"): ".",
    ("question", "mark"): "?",
    ("exclamation", "mark"): "!",
    ("exclamation", "point"): "!",
    ("period",): ".",
    ("comma",): ",",
    ("colon",): ":",
    ("semicolon",): ";",
    ("semi", "colon"): ";",
}
BREAKS = {
    ("new", "paragraph"): "\n\n",
    ("new", "line"): "\n",
    ("next", "line"): "\n",
}
DELETE = {("delete", "that"), ("scratch", "that")}
_PHRASES = sorted([*MARKS, *BREAKS, *DELETE], key=len, reverse=True)

# After these, and with more words following, a command word is part of what is being said: "the period of time",
# "a new line of shoes", "put a comma there". At the end ("I like that period") it is still a command.
_DETERMINERS = {"a", "an", "the", "this", "that", "these", "those", "each", "every", "any", "some", "no",
                "its", "his", "her", "their", "our", "my", "your", "whole", "same", "another", "per"}
_SENTENCE_END = ".?!"
_WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")

# The examples shown in Settings and the docs.
EXAMPLES = ('"period", "comma", "question mark", "exclamation mark", "colon", "semicolon", '
            '"new line", "new paragraph", "delete that"')


def _bare(token):
    """The word in a token without the punctuation Whisper put around it, lowercased."""
    found = _WORD.search(token)
    return found.group(0).lower() if found else ""


def _ends_clause(token):
    return token[-1:] in ".,;:!?" if token else False


def _capitalize(token):
    for i, ch in enumerate(token):
        if ch.isalpha():
            return token[:i] + ch.upper() + token[i + 1:]
        if ch.isdigit():
            return token
    return token


class _Out:
    """The text so far, as pieces: words, marks and line breaks."""

    def __init__(self):
        self.pieces = []
        self.cap_next = False
        self.spoken_mark = False  # the last piece ends with a mark that was said, not one Whisper guessed

    def word(self, token):
        if self.cap_next:
            token = _capitalize(token)
            self.cap_next = False
        self.pieces.append(token)
        self.spoken_mark = False

    def _strip_trailing(self, chars):
        while self.pieces and self.pieces[-1] not in ("\n", "\n\n"):
            last = self.pieces[-1].rstrip(chars)
            if last == self.pieces[-1]:
                return
            if last:
                self.pieces[-1] = last
                return
            self.pieces.pop()

    def mark(self, mark):
        self._strip_trailing(".,;:!?")  # Whisper's own guess at the punctuation: the spoken mark replaces it
        if not self.pieces or self.pieces[-1] in ("\n", "\n\n"):
            return  # a mark with nothing before it on its line
        self.pieces[-1] += mark
        self.cap_next = mark in _SENTENCE_END
        self.spoken_mark = True

    def line_break(self, kind):
        if not self.spoken_mark:
            self._strip_trailing(",;:")  # keep a sentence end, drop a pause Whisper wrote as a comma
        while self.pieces and self.pieces[-1] in ("\n", "\n\n"):
            self.pieces.pop()
        if self.pieces:
            self.pieces.append(kind)
        self.cap_next = True

    def at_sentence_start(self):
        return not self.pieces or self.pieces[-1] in ("\n", "\n\n") or self.pieces[-1][-1:] in _SENTENCE_END

    def delete_sentence(self):
        """Back to the end of the sentence before the last one, or to the last line break."""
        while self.pieces and self.pieces[-1] in ("\n", "\n\n"):
            self.pieces.pop()
        while self.pieces:
            if self.pieces[-1] in ("\n", "\n\n"):
                break
            self.pieces.pop()
            if self.pieces and self.pieces[-1][-1:] in _SENTENCE_END:
                break
        self.cap_next = True

    def text(self):
        out = []
        for piece in self.pieces:
            if piece in ("\n", "\n\n") or (out and out[-1] in ("\n", "\n\n")) or not out:
                out.append(piece)
            else:
                out.append(" " + piece)
        return "".join(out).strip(" ")


def _starts_command(words, i):
    return any(tuple(words[i:i + len(p)]) == p for p in _PHRASES)


def _at_boundary(tokens, i):
    """Is token i at the start of a sentence (or of the text)?"""
    return i == 0 or tokens[i - 1][-1:] in _SENTENCE_END + ",;:"


def apply_commands(text):
    """text with its spoken commands carried out. Plain text without a command comes back as it was."""
    if not text:
        return text
    lines = text.split("\n")
    if len(lines) > 1:  # already broken into lines (by an earlier pass): each line on its own, breaks kept
        return "\n".join(apply_commands(line) for line in lines)
    tokens = text.split()
    words = [_bare(t) for t in tokens]
    if not any(phrase[0] in words for phrase in _PHRASES):
        return text
    out = _Out()
    i = 0
    while i < len(tokens):
        phrase = next((p for p in _PHRASES if tuple(words[i:i + len(p)]) == p), None)
        if phrase is not None:
            end = i + len(phrase)
            last = tokens[end - 1]
            before = words[i - 1] if i else ""
            is_last = end == len(tokens)
            if phrase in DELETE:
                # "Delete that." as a sentence of its own, not "please delete that file".
                ok = (_at_boundary(tokens, i) or out.at_sentence_start()) and (is_last or _ends_clause(last))
            else:
                more_words = not is_last and not _ends_clause(last) and not _starts_command(words, end)
                ok = not (before in _DETERMINERS and more_words)
            if ok:
                if phrase in DELETE:
                    out.delete_sentence()
                elif phrase in BREAKS:
                    out.line_break(BREAKS[phrase])
                else:
                    out.mark(MARKS[phrase])
                i += len(phrase)
                continue
        out.word(tokens[i])
        i += 1
    return out.text()


def for_caption(text):
    """The same, with line breaks shown as a mark (the caption bubble wraps words itself)."""
    return apply_commands(text).replace("\n\n", " ¶ ").replace("\n", " ↵ ")
