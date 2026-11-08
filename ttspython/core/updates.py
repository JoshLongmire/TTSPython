"""Is there a newer TTSPython on GitHub? Only asked if the user said yes, at most once a day.

One https request to GitHub's public API for the latest release. Nothing is sent but the request itself
(a plain "TTSPython/<version>" user agent), and nothing is downloaded: the user gets a link.
"""
from __future__ import annotations

import json
import os
import re
import time

API_URL = "https://api.github.com/repos/JoshLongmire/TTSPython/releases/latest"
RELEASES_URL = "https://github.com/JoshLongmire/TTSPython/releases/latest"
EVERY_SECONDS = 24 * 3600
TIMEOUT = 5.0
MAX_BYTES = 512_000  # a release's JSON is a few KB; never read an endless answer
_VERSION = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$")
OFF_ENV = "TTSPYTHON_NO_UPDATE_CHECK"


def parse_version(text):
    """(major, minor, patch) from "v5.1.0" or "5.1", or None for anything else (pre-releases included)."""
    found = _VERSION.match(text.strip()) if isinstance(text, str) else None
    if not found:
        return None
    return tuple(int(part or 0) for part in found.groups())


def is_newer(latest, current):
    a, b = parse_version(latest), parse_version(current)
    return a is not None and b is not None and a > b


def disabled():
    """Never in tests, the self-test, benchmarks or CI."""
    return any(os.environ.get(name) for name in (OFF_ENV, "TTSPYTHON_SELFTEST", "TTSPYTHON_BENCH", "CI"))


def due(last_check, now=None):
    now = time.time() if now is None else now
    try:
        last = float(last_check or 0)
    except (TypeError, ValueError):
        last = 0.0
    return not (0 <= now - last < EVERY_SECONDS)  # a clock set back counts as due


def _get(url, user_agent):
    if not url.startswith("https://"):
        raise ValueError("https only")
    import urllib.request  # 90 ms of imports: only when a check is due, never at startup
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 (https, pinned above)
        return response.read(MAX_BYTES + 1)


def latest_release(current, get=_get):
    """(version, page url) if GitHub's latest release is newer than current, else None. Raises on a network error."""
    body = get(API_URL, f"TTSPython/{current}")
    if len(body) > MAX_BYTES:
        raise ValueError("answer too long")
    info = json.loads(body)
    if not isinstance(info, dict) or info.get("draft") or info.get("prerelease"):
        return None
    tag = info.get("tag_name")
    if not is_newer(tag, current):
        return None
    page = info.get("html_url")
    if not (isinstance(page, str) and page.startswith("https://github.com/JoshLongmire/TTSPython/")):
        page = RELEASES_URL  # only ever a link to this project's own releases
    return tag.lstrip("v"), page
