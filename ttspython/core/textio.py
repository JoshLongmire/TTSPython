"""Reading and writing text documents without altering their bytes."""
from __future__ import annotations

import contextlib
import os
import shutil
from dataclasses import dataclass

from .settings import atomic_replace


@dataclass
class TextDocument:
    text: str            # editor text with "\n" line endings
    encoding: str        # encoding used to decode the file
    newline: str         # "\r\n" or "\n" as found in the file
    bom: bool = False
    lossy: bool = False  # not read correctly (see _looks_misread): saving over the file would destroy it


def _detect_newline(text):
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    if crlf and crlf >= lf:
        return "\r\n"
    if lf:
        return "\n"
    return os.linesep


_UTF16_BOMS = ((b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be"))


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
    utf16 = next((enc for mark, enc in _UTF16_BOMS if raw.startswith(mark)), None)
    lossy = False
    if utf16:
        (text, lossy), enc, bom = _decode_marked(raw[2:], utf16), utf16, True
    elif raw.startswith(b"\xef\xbb\xbf"):
        (text, lossy), enc, bom = _decode_marked(raw[3:], "utf-8"), "utf-8", True
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
    newline = _detect_newline(text)
    text = text.replace("\r\n", "\n")
    return TextDocument(text=text, encoding=enc, newline=newline, bom=bom, lossy=lossy)


def read_text_file(path) -> TextDocument:
    with open(path, "rb") as f:
        return decode_text(f.read())


def read_text(path) -> str:
    return read_text_file(path).text


def encode_text(text, encoding="utf-8", newline=None, bom=False):
    """Return (bytes, encoding actually used). Falls back to UTF-8 if the text does not fit."""
    newline = newline or os.linesep
    body = text.replace("\r\n", "\n")
    if newline != "\n":
        body = body.replace("\n", newline)
    try:
        data = body.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        data = body.encode("utf-8")
        encoding = "utf-8"
    if bom:
        data = {"utf-8": b"\xef\xbb\xbf", "utf-16-le": b"\xff\xfe", "utf-16-be": b"\xfe\xff"}.get(encoding, b"") + data
    return data, encoding


def write_text_file(path, text, encoding="utf-8", newline=None, bom=False):
    """Write exactly the editor text (no extra trailing newline), atomically.

    Returns the encoding used, which is UTF-8 if the text cannot be stored in `encoding`.
    """
    data, used = encode_text(text, encoding, newline, bom)
    if os.path.exists(path) and not os.access(path, os.W_OK):
        raise PermissionError("This file is read-only. Use Save as to keep your text in another file.")
    if os.path.islink(path):
        path = os.path.realpath(path)  # save through the link, do not replace it with a file
    tmp = path + ".part"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise
    if os.path.exists(path):
        with contextlib.suppress(OSError):
            shutil.copymode(path, tmp)  # a private file stays private
    try:
        atomic_replace(tmp, path)
    except OSError:  # the editor still holds the text and says the save failed: leave nothing behind
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise
    return used
