"""Split text into speakable chunks with positions for highlighting.

Positions come in two forms: Python string indices (start, end) relative to
the given text, and UTF-16 code-unit positions (pos16, end16) that include
base16, which is what Qt text cursors use.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

FIRST_MAX = 120
CHUNK_MAX = 300
MERGE_BELOW = 20

_BOUNDARY = re.compile(r"([.!?…]+[\"'”’)\]]*)(\s+)|(\n\s*)")
_SOFT_BREAK = re.compile(r"[,;:—–]\s+|\s+")
_PARAGRAPH = re.compile(r"\r?\n[ \t]*\r?\n")
_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


@dataclass(frozen=True)
class Chunk:
    text: str
    start: int
    end: int
    pos16: int
    end16: int


def utf16_len(text):
    return len(text.encode("utf-16-le")) // 2


def _sentence_spans(text):
    spans = []
    pos = 0
    for m in _BOUNDARY.finditer(text):
        end = m.end(1) if m.group(1) else m.start(3)
        spans.append((pos, end))
        pos = m.end()
    spans.append((pos, len(text)))
    out = []
    for s, e in spans:
        while s < e and text[s].isspace():
            s += 1
        while e > s and text[e - 1].isspace():
            e -= 1
        if e > s:
            out.append((s, e))
    return out


def _split_long(text, s, e, limit):
    """Split [s, e) into pieces no longer than limit, preferring soft breaks."""
    pieces = []
    while e - s > limit:
        window_end = s + limit
        cut = None
        for m in _SOFT_BREAK.finditer(text, s + max(1, limit // 3), window_end):
            cut = m
        if cut is not None and text[cut.start()] in ",;:—–":
            piece_end, next_start = cut.start() + 1, cut.end()
        elif cut is not None:
            piece_end, next_start = cut.start(), cut.end()
        else:
            piece_end, next_start = window_end, window_end
        pieces.append((s, piece_end))
        s = next_start
        while s < e and text[s].isspace():
            s += 1
    if e > s:
        pieces.append((s, e))
    return pieces


def split_spans(text, first_max=FIRST_MAX, chunk_max=CHUNK_MAX, merge_below=MERGE_BELOW):
    spans = []
    for s, e in _sentence_spans(text):
        spans.extend(_split_long(text, s, e, chunk_max))
    if spans and spans[0][1] - spans[0][0] > first_max:
        head = _split_long(text, spans[0][0], spans[0][1], first_max)
        rest = _split_long(text, head[1][0], spans[0][1], chunk_max) if len(head) > 1 else []
        spans = [head[0]] + rest + spans[1:]
    # Merge tiny fragments into their neighbour, but never grow the first
    # chunk (it is kept short so speech starts quickly).
    merged = []
    for s, e in spans:
        if len(merged) >= 2:
            prev_s, prev_e = merged[-1]
            short = (prev_e - prev_s) < merge_below or (e - s) < merge_below
            if short and e - prev_s <= chunk_max and not _PARAGRAPH.search(text, prev_e, s):
                merged[-1] = (prev_s, e)
                continue
        merged.append((s, e))
    return merged


def split_chunks(text, base16=0, **kwargs):
    # A lone surrogate (from broken clipboard data) cannot be encoded or spoken.
    # U+FFFD is also one UTF-16 unit, so positions stay the same.
    text = _LONE_SURROGATE.sub("�", text)
    spans = split_spans(text, **kwargs)
    chunks = []
    cursor, cursor16 = 0, base16
    for s, e in spans:
        cursor16 += utf16_len(text[cursor:s])
        pos16 = cursor16
        cursor16 += utf16_len(text[s:e])
        cursor = e
        chunks.append(Chunk(text=text[s:e], start=s, end=e, pos16=pos16, end16=cursor16))
    return chunks
