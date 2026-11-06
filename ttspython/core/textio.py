"""Reading and writing text documents without altering their bytes."""
from __future__ import annotations

import contextlib
import os
import re
import uuid
from dataclasses import dataclass

from .settings import atomic_replace


@dataclass
class TextDocument:
    text: str            # editor text with "\n" line endings
    encoding: str        # encoding used to decode the file
    newline: str         # "\r\n" or "\n" as found in the file
    bom: bool = False
    lossy: bool = False  # not read correctly (see _looks_misread): saving over the file would destroy it
    original: str | None = None  # the file's text with its line endings, when they are not all the same


_LINE_END = re.compile(r"\r\n|\n|\r")


def with_original_endings(text, original, newline):
    """text ("\\n" endings) with the line endings of original wherever a line is unchanged. Only the
    lines between the first and the last change get newline, so a file with mixed endings does not
    become a change to every line of it."""
    old = _LINE_END.split(original)
    ends = _LINE_END.findall(original)
    new = text.split("\n")
    if len(old) == len(new):  # no line was added or removed: each keeps its own, edited or not
        return "".join(part for pair in zip(new, [*ends, ""]) for part in pair)
    limit = min(len(old), len(new))
    head = 0
    while head < limit and old[head] == new[head]:
        head += 1
    tail = 0
    while tail < limit - head and old[-1 - tail] == new[-1 - tail]:
        tail += 1
    shift = len(old) - len(new)
    parts = []
    for i, line in enumerate(new[:-1]):
        parts.append(line)
        if i < head and i < len(ends):
            parts.append(ends[i])
        elif i >= len(new) - tail:
            parts.append(ends[i + shift])
        else:
            parts.append(newline)
    parts.append(new[-1])
    return "".join(parts)


def _detect_newline(text):
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    if crlf and crlf >= lf:
        return "\r\n"
    if lf:
        return "\n"
    return os.linesep


# UTF-32 first: its little-endian mark starts with UTF-16's.
_BOMS = ((b"\xff\xfe\x00\x00", "utf-32-le"), (b"\x00\x00\xfe\xff", "utf-32-be"),
         (b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be"), (b"\xef\xbb\xbf", "utf-8"))
_BOM_BY_ENCODING = {encoding: mark for mark, encoding in _BOMS}
_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


def _decode_marked(raw, encoding):
    """(text, lossy) for bytes whose encoding a byte order mark announced."""
    try:
        return raw.decode(encoding), False
    except UnicodeDecodeError:
        return raw.decode(encoding, errors="replace"), True


def _looks_misread(text):
    """Windows-1252 accepts almost any bytes. Western text is mostly plain letters, so mostly other
    characters means another encoding (GBK, Shift-JIS, Windows-1251...) shown as nonsense."""
    visible = [c for c in text if not c.isspace()]
    return len(visible) >= 4 and sum(ord(c) > 127 for c in visible) / len(visible) > 0.3


def decode_text(raw: bytes) -> TextDocument:
    """Decode tolerantly (BOM / UTF-16 BOM / UTF-8 / cp1252 / replace)."""
    marked = next(((mark, enc) for mark, enc in _BOMS if raw.startswith(mark)), None)
    lossy = False
    if marked:
        (text, lossy), enc, bom = _decode_marked(raw[len(marked[0]):], marked[1]), marked[1], True
    else:
        bom = False
        for enc in ("utf-8", "cp1252"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text, enc, lossy = raw.decode("utf-8", errors="replace"), "utf-8", True
    if enc == "cp1252" and _looks_misread(text):
        lossy = True
    if not bom and b"\x00" in raw:  # text has no such byte: UTF-16 or UTF-32 without a mark, or not text at all
        lossy = True
    newline = _detect_newline(text)
    original = text if len(set(_LINE_END.findall(text))) > 1 else None
    text = text.replace("\r\n", "\n")
    return TextDocument(text=text, encoding=enc, newline=newline, bom=bom, lossy=lossy, original=original)


def read_text_file(path) -> TextDocument:
    with open(path, "rb") as f:
        return decode_text(f.read())


def read_text(path) -> str:
    return read_text_file(path).text


def encode_text(text, encoding="utf-8", newline=None, bom=False, original=None):
    """Return (bytes, encoding actually used). Falls back to UTF-8 if the text does not fit.
    original: the file's text, when its line endings were mixed (see with_original_endings)."""
    newline = newline or os.linesep
    # A broken character (half of a pair, from damaged clipboard data) cannot be stored in any encoding.
    body = _LONE_SURROGATE.sub("\ufffd", text).replace("\r\n", "\n")
    if original is not None:
        body = with_original_endings(body, original, newline)
    elif newline != "\n":
        body = body.replace("\n", newline)
    try:
        data = body.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        data = body.encode("utf-8")
        encoding = "utf-8"
    if bom:
        data = _BOM_BY_ENCODING.get(encoding, b"") + data
    return data, encoding


def write_text_file(path, text, encoding="utf-8", newline=None, bom=False, original=None):
    """Write exactly the editor text (no extra trailing newline), atomically.

    Returns the encoding used, which is UTF-8 if the text cannot be stored in `encoding`.
    """
    data, used = encode_text(text, encoding, newline, bom, original)
    if os.path.exists(path) and not os.access(path, os.W_OK):
        raise PermissionError("This file is read-only. Use Save as to keep your text in another file.")
    if os.path.islink(path):
        path = os.path.realpath(path)  # save through the link, do not replace it with a file
    # A name of its own, never someone's file. Private from the start if the file is private.
    tmp = f"{path}.{uuid.uuid4().hex[:8]}.part"
    try:
        mode = os.stat(path).st_mode & 0o777
    except OSError:
        mode = 0o666  # a new file: the user's umask applies
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), mode)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise
    try:
        atomic_replace(tmp, path, may_copy=False)
    except OSError:  # the editor still holds the text and says the save failed: leave nothing behind
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise
    return used
