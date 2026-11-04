"""Reading and writing text documents without altering their bytes."""
from __future__ import annotations

import os
from dataclasses import dataclass

from .settings import atomic_replace


@dataclass
class TextDocument:
    text: str            # editor text with "\n" line endings
    encoding: str        # encoding used to decode the file
    newline: str         # "\r\n" or "\n" as found in the file
    bom: bool = False


def _detect_newline(text):
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    if crlf and crlf >= lf:
        return "\r\n"
    if lf:
        return "\n"
    return os.linesep


_UTF16_BOMS = ((b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be"))


def decode_text(raw: bytes) -> TextDocument:
    """Decode tolerantly (BOM / UTF-16 BOM / UTF-8 / cp1252 / replace)."""
    utf16 = next((enc for mark, enc in _UTF16_BOMS if raw.startswith(mark)), None)
    if utf16:
        text, enc, bom = raw[2:].decode(utf16, errors="replace"), utf16, True
    elif raw.startswith(b"\xef\xbb\xbf"):
        text, enc, bom = raw[3:].decode("utf-8", errors="replace"), "utf-8", True
    else:
        bom = False
        for enc in ("utf-8", "cp1252"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text, enc = raw.decode("utf-8", errors="replace"), "utf-8"
    newline = _detect_newline(text)
    text = text.replace("\r\n", "\n")
    return TextDocument(text=text, encoding=enc, newline=newline, bom=bom)


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
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    atomic_replace(tmp, path)
    return used
