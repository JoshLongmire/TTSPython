"""Download a file with progress and a checksum check (voices and the Piper program)."""
from __future__ import annotations

import hashlib
import os
import time

from .settings import atomic_replace

CHUNK = 256 * 1024


class DownloadCancelled(Exception):
    pass


class ChecksumError(OSError):
    pass


def _urlopen(url, timeout):
    import urllib.request

    return urllib.request.urlopen(url, timeout=timeout)  # noqa: S310 (https URLs pinned in the code)


def fetch(url, dest, progress=None, md5=None, sha256=None, cancel=None, opener=_urlopen):
    """Download url to dest (through dest.part). progress(done_bytes, total_bytes) about
    5 times a second. md5/sha256: expected hex digest; a mismatch deletes the file."""
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    part = dest + ".part"
    digest = hashlib.md5() if md5 else (hashlib.sha256() if sha256 else None)  # noqa: S324 (file checksum)
    expected = (md5 or sha256 or "").lower()
    try:
        with opener(url, timeout=30) as resp, open(part, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done, last = 0, 0.0
            while True:
                if cancel is not None and cancel.is_set():
                    raise DownloadCancelled()
                block = resp.read(CHUNK)
                if not block:
                    break
                out.write(block)
                if digest is not None:
                    digest.update(block)
                done += len(block)
                now = time.monotonic()
                if progress is not None and now - last >= 0.2:
                    last = now
                    progress(done, total)
        if progress is not None:
            progress(done, total or done)
        if digest is not None and digest.hexdigest() != expected:
            raise ChecksumError(f"The download of {os.path.basename(dest)} was damaged (checksum mismatch). Try again.")
        atomic_replace(part, dest)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    return dest
