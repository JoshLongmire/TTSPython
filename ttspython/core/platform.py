"""Platform detection and small OS helpers."""
from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys

IS_WINDOWS = sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")
IS_DARWIN = sys.platform == "darwin"


def session_type() -> str:
    """Return "windows", "darwin", "wayland" or "x11"."""
    if IS_WINDOWS:
        return "windows"
    if IS_DARWIN:
        return "darwin"
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    return "x11"


def config_dir() -> str:
    """Per-user folder for settings."""
    if IS_WINDOWS:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "TTSPython")
    if IS_DARWIN:
        return os.path.expanduser("~/Library/Application Support/TTSPython")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "ttspython")


def data_dir() -> str:
    """Per-user folder for downloaded voices and the Piper program (TTSPYTHON_DATA overrides)."""
    override = os.environ.get("TTSPYTHON_DATA")
    if override:
        return override
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "TTSPython")
    if IS_DARWIN:
        return os.path.expanduser("~/Library/Application Support/TTSPython")
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "ttspython")


def open_uri(uri_or_path: str) -> None:
    """Open a settings URI, URL or file with the platform default handler."""
    if IS_WINDOWS:
        os.startfile(uri_or_path)  # type: ignore[attr-defined]
        return
    opener = "open" if IS_DARWIN else "xdg-open"
    subprocess.Popen([opener, uri_or_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_first_available(commands) -> bool:
    """Start the first command whose executable exists. Returns True if one started."""
    for cmd in commands:
        if shutil.which(cmd[0]) is None:
            continue
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            continue
    return False


def open_voice_settings() -> bool:
    """Open the OS place where voices are installed. Returns True if something opened."""
    if IS_WINDOWS:
        try:
            open_uri("ms-settings:speech")
            return True
        except OSError:
            return False
    if IS_LINUX:
        try:
            open_uri("https://github.com/espeak-ng/espeak-ng")
            return True
        except OSError:
            return run_first_available([["gnome-control-center", "sound"]])
    return False


def open_sound_settings() -> bool:
    """Open the OS sound output settings. Returns True if something opened."""
    if IS_WINDOWS:
        try:
            open_uri("ms-settings:sound")
            return True
        except OSError:
            return False
    if IS_LINUX:
        return run_first_available([["gnome-control-center", "sound"], ["pavucontrol"],
                                    ["xdg-open", "settings://sound"]])
    return False


@contextlib.contextmanager
def com_apartment():
    """Initialize a single-threaded COM apartment for this thread (Windows only)."""
    if not IS_WINDOWS:
        yield
        return
    initialized = False
    try:
        import comtypes

        comtypes.CoInitialize()
        initialized = True
    except Exception:
        pass
    try:
        yield
    finally:
        if initialized:
            try:
                import comtypes

                comtypes.CoUninitialize()
            except Exception:
                pass
