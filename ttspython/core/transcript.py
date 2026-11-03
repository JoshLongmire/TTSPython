"""Transcript clean-up."""
from __future__ import annotations


def normalize_transcript_text(text):
    """Light-touch punctuation cleanup without changing word content."""
    cleaned = " ".join((text or "").split()).strip()
    if not cleaned:
        return ""
    for idx, ch in enumerate(cleaned):
        if ch.isalpha():
            cleaned = cleaned[:idx] + ch.upper() + cleaned[idx + 1:]
            break
    if cleaned[-1] not in ".!?。！？":
        cleaned += "."
    return cleaned
