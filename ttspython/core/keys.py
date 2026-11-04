"""Shortcut definitions, v4 (Tk syntax) migration and global hotkey parsing.

Shortcuts are stored as portable key-sequence text, e.g. "Ctrl+Shift+S".
"""
from __future__ import annotations

# In-window shortcuts (v4's ten plus six new ones).
DEFAULT_SHORTCUTS = {
    "speak_all": "Ctrl+Return",
    "speak_selected": "Ctrl+Shift+Return",
    "speak_from_cursor": "Ctrl+Alt+Return",
    "new": "Ctrl+N",
    "stop": "Esc",
    "open": "Ctrl+O",
    "save": "Ctrl+S",
    "save_as": "Ctrl+Shift+S",
    "paste": "Ctrl+V",
    "clear": "Ctrl+L",
    "find": "Ctrl+F",
    "export": "Ctrl+E",
    "pause_resume": "Ctrl+Space",
    "toggle_mode": "Ctrl+M",
    "toggle_queue": "Ctrl+Q",
    "settings": "Ctrl+,",
}

SHORTCUT_LABELS = {
    "speak_all": "Speak all",
    "speak_selected": "Speak selected",
    "speak_from_cursor": "Speak from the cursor",
    "new": "New document",
    "stop": "Stop",
    "open": "Open file",
    "save": "Save",
    "save_as": "Save as",
    "paste": "Paste",
    "clear": "Clear text",
    "find": "Find and replace",
    "export": "Export audio",
    "pause_resume": "Pause or resume",
    "toggle_mode": "Switch Speak / Listen",
    "toggle_queue": "Show or hide the queue",
    "settings": "Settings",
}

# System-wide hotkeys (toggle style). Empty string means unassigned.
DEFAULT_GLOBAL_HOTKEYS = {
    "toggle_dictation": "Ctrl+Alt+D",
    "speak_clipboard": "Ctrl+Alt+S",
    "stop_speech": "Ctrl+Alt+X",
    "toggle_mini": "Ctrl+Alt+Shift+M",  # Ctrl+Alt+M is often taken by other apps
    "pause_resume": "",
    "show_window": "",
}

GLOBAL_HOTKEY_LABELS = {
    "toggle_dictation": "Start or stop dictation",
    "speak_clipboard": "Speak selection or clipboard",
    "stop_speech": "Stop speaking",
    "toggle_mini": "Show or hide mini mode",
    "pause_resume": "Pause or resume speech",
    "show_window": "Show main window",
}

_TK_MODIFIERS = {
    "control": "Ctrl", "ctrl": "Ctrl",
    "alt": "Alt", "mod1": "Alt", "option": "Alt",
    "shift": "Shift",
    "meta": "Meta", "command": "Meta", "win": "Meta", "super": "Meta",
}

_TK_KEYSYMS = {
    "return": "Return", "enter": "Return", "kp_enter": "Enter",
    "escape": "Esc", "space": "Space", "tab": "Tab",
    "prior": "PgUp", "next": "PgDown", "home": "Home", "end": "End",
    "backspace": "Backspace", "delete": "Del", "insert": "Ins",
    "minus": "-", "plus": "+", "equal": "=", "comma": ",", "period": ".",
    "slash": "/", "backslash": "\\", "semicolon": ";", "apostrophe": "'",
    "bracketleft": "[", "bracketright": "]", "grave": "`",
    "up": "Up", "down": "Down", "left": "Left", "right": "Right",
    "exclam": "!", "at": "@", "numbersign": "#", "dollar": "$", "percent": "%", "asciicircum": "^",
    "ampersand": "&", "asterisk": "*", "parenleft": "(", "parenright": ")", "underscore": "_",
    "question": "?", "colon": ":", "quotedbl": '"', "less": "<", "greater": ">", "bar": "|",
    "braceleft": "{", "braceright": "}", "asciitilde": "~", "quoteright": "'", "quoteleft": "`",
    "kp_add": "+", "kp_subtract": "-", "kp_multiply": "*", "kp_divide": "/", "kp_decimal": ".",
    "kp_0": "0", "kp_1": "1", "kp_2": "2", "kp_3": "3", "kp_4": "4",
    "kp_5": "5", "kp_6": "6", "kp_7": "7", "kp_8": "8", "kp_9": "9",
    "pause": "Pause", "print": "Print", "menu": "Menu",
}

_MOD_ORDER = ["Ctrl", "Alt", "Shift", "Meta", "Num"]


def tk_to_portable(binding):
    """Convert a Tk binding like "<Control-Shift-S>" to "Ctrl+Shift+S".

    Returns None if the binding cannot be understood.
    """
    if not isinstance(binding, str):
        return None
    raw = binding.strip()
    if not raw:
        return None
    if not (raw.startswith("<") and raw.endswith(">")):
        return None
    parts = [p for p in raw[1:-1].split("-") if p != ""]
    if raw[1:-1].endswith("-"):
        parts.append("-")
    if not parts:
        return None
    mods = []
    for part in parts[:-1]:
        name = _TK_MODIFIERS.get(part.lower())
        if name is None:
            if part.lower() in ("key", "keypress"):
                continue
            return None
        if name not in mods:
            mods.append(name)
    key = parts[-1]
    lower = key.lower()
    if lower in _TK_KEYSYMS:
        key_name = _TK_KEYSYMS[lower]
    elif len(key) == 1:
        if key.isalpha() and key.isupper() and "Shift" not in mods:
            mods.append("Shift")
        key_name = key.upper()
    elif lower.startswith("f") and lower[1:].isdigit() and 1 <= int(lower[1:]) <= 24:
        key_name = key.upper()
    else:
        return None
    mods.sort(key=_MOD_ORDER.index)
    return "+".join(mods + [key_name])


def looks_like_tk(binding):
    return isinstance(binding, str) and binding.startswith("<") and binding.endswith(">")


def looks_like_sequence(text):
    """Loose check for Qt portable key-sequence text such as "Ctrl+Num+5", "Help", "Media Play".

    In-window shortcuts are validated by Qt itself, so anything Qt can write is kept.
    """
    if not isinstance(text, str) or not text.strip():
        return False
    raw = text.strip()
    parts = raw[:-2].split("+") + ["+"] if raw.endswith("++") else raw.split("+")
    if any(p == "" for p in parts):
        return False
    for part in parts[:-1]:
        if part.lower() not in _MODIFIER_NAMES:
            return False
    key = parts[-1]
    if len(key) == 1:
        return True
    return all(ch.isalnum() or ch == " " for ch in key)


def merge_shortcuts(saved, defaults=None, strict=True):
    """Merge saved shortcuts with defaults, migrating Tk syntax.

    Missing keys get the default; "" means deliberately unassigned; unreadable
    values fall back to the default. strict=True (global hotkeys) only keeps
    combinations the OS hotkey APIs can register; strict=False (in-window
    shortcuts) keeps anything that looks like a Qt key sequence.
    """
    defaults = DEFAULT_SHORTCUTS if defaults is None else defaults
    result = dict(defaults)
    if not isinstance(saved, dict):
        return result
    valid = (lambda v: parse_combo(v) is not None) if strict else looks_like_sequence
    for action, value in saved.items():
        if action not in defaults:
            continue
        if value == "" or value is None:
            result[action] = ""
            continue
        if looks_like_tk(value):
            converted = tk_to_portable(value)
            result[action] = converted if converted else defaults[action]
        elif isinstance(value, str) and valid(value):
            result[action] = value
    return result


def find_conflicts(shortcuts):
    """Return {sequence: [actions]} for sequences bound to more than one action."""
    seen = {}
    for action, seq in shortcuts.items():
        if seq:
            seen.setdefault(normalize_combo_text(seq), []).append(action)
    return {seq: actions for seq, actions in seen.items() if len(actions) > 1}


# --- Global hotkey parsing ---------------------------------------------------
# Multi-letter key names as Qt writes them in portable key-sequence text.
KNOWN_KEY_NAMES = {
    "Return", "Enter", "Esc", "Escape", "Tab", "Backtab", "Backspace", "Ins", "Insert", "Del", "Delete",
    "Pause", "Print", "SysReq", "Home", "End", "Left", "Up", "Right", "Down", "PgUp", "PgDown", "Space",
    "Menu", "CapsLock", "NumLock", "ScrollLock",
}
_MODIFIER_NAMES = {"ctrl": "Ctrl", "control": "Ctrl", "alt": "Alt", "shift": "Shift",
                   "meta": "Meta", "win": "Meta", "super": "Meta", "num": "Num"}


# Without a modifier these would stop working for typing in every other app.
_TYPING_KEYS = {"Space", "Return", "Enter", "Tab", "Backspace", "Esc", "Del", "Delete", "Ins", "Insert",
                "Left", "Right", "Up", "Down", "Home", "End", "PgUp", "PgDown"}


def global_hotkey_problem(combo):
    """What is wrong with this combination as a global hotkey, or None."""
    parsed = parse_combo(combo)
    if parsed and not parsed[0] and (len(parsed[1]) == 1 or parsed[1] in _TYPING_KEYS):
        return "Add Ctrl, Alt or Shift"
    return None


def parse_combo(text):
    """Parse "Ctrl+Alt+D" into (frozenset({"Ctrl","Alt"}), "D"). None if invalid."""
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    parts = raw.split("+")
    if raw.endswith("++"):
        parts = parts[:-2] + ["+"]
    parts = [p.strip() for p in parts if p.strip() != ""] if not raw.endswith("++") else parts
    if not parts:
        return None
    mods = set()
    for part in parts[:-1]:
        name = _MODIFIER_NAMES.get(part.lower())
        if name is None:
            return None
        mods.add(name)
    key = parts[-1]
    if key.lower() in _MODIFIER_NAMES:
        return None
    if len(key) == 1:
        key = key.upper()
    elif not (key in KNOWN_KEY_NAMES or (key[0] == "F" and key[1:].isdigit() and 1 <= int(key[1:]) <= 35)):
        return None
    return frozenset(mods), key


def normalize_combo_text(text):
    parsed = parse_combo(text)
    if parsed is None:
        return text
    mods, key = parsed
    return "+".join([m for m in _MOD_ORDER if m in mods] + [key])


_VK_NAMED = {
    "Return": 0x0D, "Enter": 0x0D, "Esc": 0x1B, "Escape": 0x1B, "Space": 0x20, "Tab": 0x09,
    "Backspace": 0x08, "Del": 0x2E, "Delete": 0x2E, "Ins": 0x2D, "Insert": 0x2D,
    "Home": 0x24, "End": 0x23, "PgUp": 0x21, "PgDown": 0x22,
    "Left": 0x25, "Up": 0x26, "Right": 0x27, "Down": 0x28,
    "-": 0xBD, "=": 0xBB, "+": 0xBB, ",": 0xBC, ".": 0xBE, "/": 0xBF, ";": 0xBA,
    "'": 0xDE, "[": 0xDB, "]": 0xDD, "\\": 0xDC, "`": 0xC0,
    "Pause": 0x13, "Print": 0x2C,
}

_VK_NUMPAD_OPS = {"*": 0x6A, "+": 0x6B, "-": 0x6D, ".": 0x6E, "/": 0x6F, "Enter": 0x0D}

WIN_MOD_ALT = 0x0001
WIN_MOD_CONTROL = 0x0002
WIN_MOD_SHIFT = 0x0004
WIN_MOD_WIN = 0x0008
WIN_MOD_NOREPEAT = 0x4000


def to_win_hotkey(text):
    """Return (modifiers, vk) for RegisterHotKey, or None."""
    parsed = parse_combo(text)
    if parsed is None:
        return None
    mods, key = parsed
    flags = WIN_MOD_NOREPEAT
    if "Ctrl" in mods:
        flags |= WIN_MOD_CONTROL
    if "Alt" in mods:
        flags |= WIN_MOD_ALT
    if "Shift" in mods:
        flags |= WIN_MOD_SHIFT
    if "Meta" in mods:
        flags |= WIN_MOD_WIN
    if "Num" in mods and len(key) == 1 and key.isdigit():
        vk = 0x60 + int(key)  # VK_NUMPAD0..9
    elif "Num" in mods and key in _VK_NUMPAD_OPS:
        vk = _VK_NUMPAD_OPS[key]
    elif len(key) == 1 and (key.isalpha() or key.isdigit()):
        vk = ord(key.upper())
    elif key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    elif key in _VK_NAMED:
        vk = _VK_NAMED[key]
    else:
        return None
    return flags, vk


_PYNPUT_NAMED = {
    "Return": "<enter>", "Enter": "<enter>", "Esc": "<esc>", "Space": "<space>", "Tab": "<tab>",
    "Backspace": "<backspace>", "Del": "<delete>", "Ins": "<insert>", "Home": "<home>",
    "End": "<end>", "PgUp": "<page_up>", "PgDown": "<page_down>", "Left": "<left>",
    "Up": "<up>", "Right": "<right>", "Down": "<down>",
}


def to_pynput(text):
    """Return a pynput GlobalHotKeys string like "<ctrl>+<alt>+d", or None."""
    parsed = parse_combo(text)
    if parsed is None or "Num" in parsed[0]:  # pynput cannot tell keypad keys apart
        return None
    mods, key = parsed
    out = []
    for mod, name in (("Ctrl", "<ctrl>"), ("Alt", "<alt>"), ("Shift", "<shift>"), ("Meta", "<cmd>")):
        if mod in mods:
            out.append(name)
    if len(key) == 1:
        out.append(key.lower())
    elif key.startswith("F") and key[1:].isdigit():
        out.append(f"<{key.lower()}>")
    elif key in _PYNPUT_NAMED:
        out.append(_PYNPUT_NAMED[key])
    else:
        return None
    return "+".join(out)
