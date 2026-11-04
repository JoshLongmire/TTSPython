"""Find and replace over plain strings."""
from __future__ import annotations

import re


class SearchError(ValueError):
    pass


def compile_pattern(term, case_sensitive=False, use_regex=False):
    if not term:
        raise SearchError("Enter something to find.")
    flags = 0 if case_sensitive else re.IGNORECASE
    source = term if use_regex else re.escape(term)
    try:
        return re.compile(source, flags | re.MULTILINE)
    except re.error as exc:
        raise SearchError(f"Invalid regular expression: {exc}") from exc


def find_next(text, term, start=0, case_sensitive=False, use_regex=False, backwards=False):
    """Return (start, end, wrapped) of the next match, or None.

    Searching wraps around the end (or start when going backwards).
    """
    pattern = compile_pattern(term, case_sensitive, use_regex)
    start = max(0, min(len(text), start))
    if not backwards:
        m = _first_nonempty(pattern, text, start)
        if m:
            return m.start(), m.end(), False
        m = _first_nonempty(pattern, text, 0)
        if m and m.start() < start:
            return m.start(), m.end(), True
        return None
    matches = [m for m in pattern.finditer(text) if m.end() > m.start()]
    before = [m for m in matches if m.end() <= start]
    if before:
        return before[-1].start(), before[-1].end(), False
    if matches:
        return matches[-1].start(), matches[-1].end(), True
    return None


def match_starts(text, term, case_sensitive=False, use_regex=False):
    """Start index of every non-empty match (for "2 of 5")."""
    pattern = compile_pattern(term, case_sensitive, use_regex)
    return [m.start() for m in pattern.finditer(text) if m.end() > m.start()]


def _first_nonempty(pattern, text, pos):
    while pos <= len(text):
        m = pattern.search(text, pos)
        if not m:
            return None
        if m.end() > m.start():
            return m
        pos = m.start() + 1
    return None


def replacement_for(match_text, term, replacement, case_sensitive=False, use_regex=False):
    """Expand the replacement for one match (regex groups only in regex mode)."""
    if not use_regex:
        return replacement
    pattern = compile_pattern(term, case_sensitive, use_regex)
    m = pattern.fullmatch(match_text)
    if not m:
        return replacement
    try:
        return m.expand(replacement)
    except (re.error, IndexError) as exc:
        raise SearchError(f"Invalid replacement: {exc}") from exc


def replace_all(text, term, replacement, case_sensitive=False, use_regex=False):
    """Return (new_text, count). Literal mode never interprets backslashes."""
    pattern = compile_pattern(term, case_sensitive, use_regex)
    if use_regex:
        count = 0

        def expanded(m):  # like Find, an empty match does not count: "x*" must not fill the gaps
            nonlocal count
            if not m.group(0):
                return ""
            count += 1
            return m.expand(replacement)

        try:
            pattern.sub(replacement, "")  # a bad replacement is reported even when nothing matches
            return pattern.sub(expanded, text), count
        except (re.error, IndexError) as exc:
            raise SearchError(f"Invalid replacement: {exc}") from exc
    return pattern.subn(lambda _m: replacement, text)
