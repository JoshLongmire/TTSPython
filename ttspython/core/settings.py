"""Settings: defaults, validation, v4 migration and atomic persistence."""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime

from . import keys
from .platform import config_dir
from .theme import THEME_PRESETS, DEFAULT_THEME

SETTINGS_VERSION = 5
SETTINGS_ENV = "TTSPYTHON_SETTINGS"

WHISPER_MODELS = [
    ("tiny", "Tiny (75 MB, fastest)"),
    ("base", "Base (145 MB)"),
    ("small", "Small (480 MB, default)"),
    ("medium", "Medium (1.5 GB)"),
    ("large-v3", "Large v3 (3 GB, most accurate)"),
    ("large-v3-turbo", "Large v3 Turbo (1.6 GB)"),
    ("distil-large-v3", "Distil Large v3 (1.5 GB, English)"),
]

STT_LANGUAGES = [
    ("en", "English"),
    ("auto", "Auto-detect"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("de", "German"),
    ("it", "Italian"),
    ("pt", "Portuguese"),
    ("nl", "Dutch"),
    ("pl", "Polish"),
    ("ru", "Russian"),
    ("uk", "Ukrainian"),
    ("tr", "Turkish"),
    ("ar", "Arabic"),
    ("hi", "Hindi"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("zh", "Chinese"),
]

DEFAULTS = {
    "settings_version": SETTINGS_VERSION,
    "theme_preset": DEFAULT_THEME,
    "performance_mode": False,
    "mode": "tts",
    "clipboard_monitor": False,
    "clipboard_auto_queue": False,
    "clipboard_action": "speak",
    "stt_whisper_model": "small",
    "stt_language": "en",
    "stt_input_device": None,
    "tts_output_device": None,
    "stt_unload_model_when_idle": False,
    "stt_auto_unload_enabled": True,
    "stt_auto_unload_minutes": 3,
    "stt_live_preview": True,
    "hotkey_conflicts_seen": [],  # "action=keys" already reported as taken by another app (told once)
    "tts_voice_id": "",
    "tts_rate": 200,
    "tts_volume": 1.0,
    "sentence_highlight": True,
    "queue_loop": False,
    "queue_panel_visible": True,
    "shortcuts": dict(keys.DEFAULT_SHORTCUTS),
    "global_hotkeys_enabled": True,
    "global_hotkeys": dict(keys.DEFAULT_GLOBAL_HOTKEYS),
    "close_to_tray": False,
    "dictation_output": "paste",
    "paste_keystroke": "ctrl+v",
    "mini_snap": True,
    "mini_waveform": True,
    "mini_pos": None,
    "window": None,
    "splitter": None,
    "recent_files": [],
    "export_dir": "",
    "export_format": "wav",
}
RECENT_MAX = 8

RATE_MIN, RATE_MAX = 100, 400  # words per minute (shown as 50% to 200%)
NORMAL_WPM = 200                # shown as 100%


def speed_percent(wpm):
    """Speed as shown in the app: 200 words per minute is 100%."""
    return int(round(float(wpm) * 100 / NORMAL_WPM))


def percent_wpm(percent):
    return int(round(float(percent) * NORMAL_WPM / 100))
VOLUME_MIN, VOLUME_MAX = 0.1, 1.0

_LEGACY_KEYS = ("hotkeys", "geometry", "dark_mode", "stt_engine")


def default_path() -> str:
    override = os.environ.get(SETTINGS_ENV)
    if override:
        return override
    return os.path.join(config_dir(), "settings.json")


def legacy_path() -> str:
    """Where v4 kept its settings: next to TTSPython.py (or next to the built app)."""
    if getattr(sys, "frozen", False):
        here = os.path.dirname(os.path.abspath(sys.executable))
    else:
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(here, "tts_settings.json")


def defaults() -> dict:
    return copy.deepcopy(DEFAULTS)


def _as_bool(value, default):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    return default


def _clamp_int(value, lo, hi, default):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError, OverflowError):  # OverflowError: JSON Infinity / 1e999
        return default


def _clamp_float(value, lo, hi, default):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if f != f:  # NaN
        return default
    return max(lo, min(hi, f))


def normalize_device_ref(value):
    """Device refs are {"name", "hostapi", "index"} or None (system default).

    v4 stored a PortAudio index as a string ("3") or a device name.
    """
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        name = value.get("name") if isinstance(value.get("name"), str) else ""
        hostapi = value.get("hostapi") if isinstance(value.get("hostapi"), str) else ""
        index = value.get("index")
        index = index if isinstance(index, int) and not isinstance(index, bool) and index >= 0 else None
        if not name and index is None:
            return None
        return {"name": name, "hostapi": hostapi, "index": index}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"name": "", "hostapi": "", "index": value} if value >= 0 else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.isdigit():
            return {"name": "", "hostapi": "", "index": int(text)}
        return {"name": text, "hostapi": "", "index": None}
    return None


_GEOMETRY_RE = re.compile(r"^(\d+)x(\d+)([+-]-?\d+)([+-]-?\d+)$")


def geometry_to_window(geometry):
    """Convert a Tk geometry string "WxH+X+Y" into a window dict."""
    if not isinstance(geometry, str):
        return None
    m = _GEOMETRY_RE.match(geometry.strip())
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    x, y = int(m.group(3)), int(m.group(4))
    if w < 200 or h < 150:
        return None
    return {"x": x, "y": y, "w": w, "h": h, "maximized": False}


def _normalize_window(value):
    if not isinstance(value, dict):
        return None
    try:
        out = {k: int(value[k]) for k in ("x", "y", "w", "h")}
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if out["w"] < 200 or out["h"] < 150:
        return None
    out["maximized"] = bool(value.get("maximized", False))
    return out


def _normalize_mini_pos(value):
    if not isinstance(value, dict):
        return None
    try:
        rx = float(value["rx"])
        ry = float(value["ry"])
    except (KeyError, TypeError, ValueError):
        return None
    if rx != rx or ry != ry:  # NaN
        return None
    screen = value.get("screen") if isinstance(value.get("screen"), str) else ""
    return {"screen": screen, "rx": max(0.0, min(1.0, rx)), "ry": max(0.0, min(1.0, ry))}


def normalize(raw) -> dict:
    """Validate every known key, migrate v4 values and keep unknown keys."""
    raw = raw if isinstance(raw, dict) else {}
    out = {k: v for k, v in raw.items() if k not in DEFAULTS and k not in _LEGACY_KEYS}
    d = defaults()

    theme = raw.get("theme_preset")
    if not isinstance(theme, str) or theme not in THEME_PRESETS:
        if raw.get("dark_mode") is True:
            theme = "dark"
        elif raw.get("dark_mode") is False:
            theme = "light"
        else:
            theme = d["theme_preset"]
    out["theme_preset"] = theme

    for key in ("performance_mode", "clipboard_monitor", "clipboard_auto_queue",
                "stt_unload_model_when_idle", "stt_auto_unload_enabled", "sentence_highlight",
                "queue_loop", "queue_panel_visible", "global_hotkeys_enabled", "close_to_tray",
                "mini_snap", "mini_waveform", "stt_live_preview"):
        out[key] = _as_bool(raw.get(key, d[key]), d[key])

    out["mode"] = raw.get("mode") if raw.get("mode") in ("tts", "stt") else d["mode"]
    out["clipboard_action"] = raw.get("clipboard_action") if raw.get("clipboard_action") in ("speak", "queue") else d["clipboard_action"]

    model = raw.get("stt_whisper_model")
    out["stt_whisper_model"] = model.strip() if isinstance(model, str) and model.strip() else d["stt_whisper_model"]
    lang = raw.get("stt_language")
    valid_langs = {code for code, _ in STT_LANGUAGES}
    out["stt_language"] = lang if lang in valid_langs else d["stt_language"]

    out["stt_input_device"] = normalize_device_ref(raw.get("stt_input_device"))
    out["tts_output_device"] = normalize_device_ref(raw.get("tts_output_device"))
    out["stt_auto_unload_minutes"] = _clamp_int(raw.get("stt_auto_unload_minutes", d["stt_auto_unload_minutes"]), 1, 60, d["stt_auto_unload_minutes"])

    voice = raw.get("tts_voice_id")
    out["tts_voice_id"] = voice if isinstance(voice, str) else ""
    out["tts_rate"] = _clamp_int(raw.get("tts_rate", d["tts_rate"]), RATE_MIN, RATE_MAX, d["tts_rate"])
    out["tts_volume"] = _clamp_float(raw.get("tts_volume", d["tts_volume"]), VOLUME_MIN, VOLUME_MAX, d["tts_volume"])

    if "shortcuts" in raw:
        out["shortcuts"] = keys.merge_shortcuts(raw.get("shortcuts"), strict=False)
    else:
        out["shortcuts"] = keys.merge_shortcuts(raw.get("hotkeys"), strict=False)
    out["global_hotkeys"] = keys.merge_shortcuts(raw.get("global_hotkeys"), keys.DEFAULT_GLOBAL_HOTKEYS, strict=True)
    seen = raw.get("hotkey_conflicts_seen")
    out["hotkey_conflicts_seen"] = [x for x in seen if isinstance(x, str)][:50] if isinstance(seen, list) else []

    out["dictation_output"] = raw.get("dictation_output") if raw.get("dictation_output") in ("paste", "clipboard") else d["dictation_output"]
    out["paste_keystroke"] = raw.get("paste_keystroke") if raw.get("paste_keystroke") in ("ctrl+v", "shift+insert") else d["paste_keystroke"]

    out["mini_pos"] = _normalize_mini_pos(raw.get("mini_pos"))
    window = _normalize_window(raw.get("window"))
    if window is None:
        window = geometry_to_window(raw.get("geometry"))
    out["window"] = window
    splitter = raw.get("splitter")
    out["splitter"] = splitter if isinstance(splitter, list) and all(isinstance(v, int) for v in splitter) else None
    recent = raw.get("recent_files")
    out["recent_files"] = [p for p in recent if isinstance(p, str) and p][:RECENT_MAX] if isinstance(recent, list) else []
    out["export_dir"] = raw.get("export_dir") if isinstance(raw.get("export_dir"), str) else ""
    out["export_format"] = raw.get("export_format") if raw.get("export_format") in ("wav", "mp3") else "wav"
    out["settings_version"] = SETTINGS_VERSION
    return out


def atomic_replace(src, dst):
    """Replace dst with src, tolerating Windows lock/read-only issues."""
    try:
        os.replace(src, dst)
        return
    except OSError:
        pass
    try:
        os.chmod(dst, 0o666)
    except OSError:
        pass
    try:
        os.replace(src, dst)
        return
    except OSError:
        pass
    try:
        shutil.copyfile(src, dst)
    finally:
        try:
            os.remove(src)
        except OSError:
            pass


def write_json_atomic(path, data):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    atomic_replace(tmp, path)


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


KEEP_BROKEN_COPIES = 3


def _prune_broken_copies(folder, keep=KEEP_BROKEN_COPIES):
    """Only the newest few copies of unreadable settings files are worth keeping."""
    try:
        names = sorted(n for n in os.listdir(folder) if n.startswith("settings.broken.") and n.endswith(".json"))
    except OSError:
        return
    for name in names[:-keep]:  # timestamped names sort oldest first
        try:
            os.remove(os.path.join(folder, name))
        except OSError:
            pass


def load(path=None, legacy=None):
    """Load settings. Returns (settings, info).

    info["source"] is "file", "legacy" (imported from a v4 tts_settings.json,
    which is never modified) or "defaults". A file that fails to parse is
    copied to settings.broken.<timestamp>.json and defaults are used.
    """
    path = path or default_path()
    legacy = legacy if legacy is not None else legacy_path()
    info = {"path": path, "source": "defaults", "broken_copy": None}
    if os.path.exists(path):
        try:
            data = normalize(_read_json(path))
            info["source"] = "file"
            return data, info
        except Exception as exc:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            name = f"settings.broken.{stamp}.json"
            # Keep a copy before the next save overwrites it: next to it, else in the temp folder.
            for folder in (os.path.dirname(path), tempfile.gettempdir()):
                broken = os.path.join(folder, name)
                try:
                    shutil.copy2(path, broken)
                    info["broken_copy"] = broken
                    _prune_broken_copies(folder)
                    break
                except OSError:
                    continue
            info["error"] = str(exc)
            return defaults(), info
    if legacy and os.path.exists(legacy):
        try:
            data = normalize(_read_json(legacy))
            info["source"] = "legacy"
            info["legacy_path"] = legacy
            return data, info
        except Exception as exc:
            info["error"] = str(exc)
    return defaults(), info


class SettingsStore:
    """Holds the live settings dict and saves it atomically."""

    def __init__(self, path=None, legacy=None):
        self.data, self.info = load(path, legacy)
        self.path = self.info["path"]
        if self.info["source"] == "legacy":
            try:
                self.save()
            except OSError as exc:  # e.g. read-only profile: run with the imported values anyway
                self.info["save_error"] = str(exc)

    def __getitem__(self, key):
        return self.data[key]

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def update(self, values):
        self.data.update(values)

    def save(self):
        write_json_atomic(self.path, self.data)
