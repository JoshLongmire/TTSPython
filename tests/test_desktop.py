"""Opt-in checks on the real Windows desktop (no mouse or keyboard input is sent).

Run with: python -m pytest -m desktop
"""
import json
import os
import subprocess
import sys

import pytest

pytestmark = [pytest.mark.desktop,
              pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows only")]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PROBE = r"""
import ctypes, json, sys
from ctypes import wintypes
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
from ttspython.platform import winapi
from ttspython.ui.mini import MiniPill
from ttspython.ui.theme_manager import ThemeManager
theme = ThemeManager(app, "studio")
before = winapi.foreground_window()
pill = MiniPill()
pill.set_tokens(theme.tokens)
pill.restore_position(None)
pill.show()
for _ in range(20):
    app.processEvents()
hwnd = int(pill.winId())
after_show = winapi.foreground_window()
exstyle = winapi.user32.GetWindowLongPtrW(hwnd, winapi.GWL_EXSTYLE)
SendMessageW = winapi.user32.SendMessageW
SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
SendMessageW.restype = ctypes.c_ssize_t
# What Windows asks a window when it is clicked: activate or not?
mouse_activate = SendMessageW(hwnd, winapi.WM_MOUSEACTIVATE, before or 0, 1 | (0x0201 << 16))
for _ in range(10):
    app.processEvents()
after_click_query = winapi.foreground_window()
pill.close()
print(json.dumps({"before": before, "after_show": after_show, "after_click_query": after_click_query,
                  "noactivate": bool(exstyle & winapi.WS_EX_NOACTIVATE),
                  "topmost": bool(exstyle & winapi.WS_EX_TOPMOST),
                  "mouse_activate": mouse_activate, "pill_is_foreground": after_show == hwnd}))
"""


def test_pill_does_not_take_focus_on_the_real_desktop():
    env = dict(os.environ, QT_QPA_PLATFORM="windows")
    out = subprocess.run([sys.executable, "-c", PROBE], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout.strip().splitlines()[-1])
    print(r)
    assert r["noactivate"] and r["topmost"]
    assert r["mouse_activate"] == 3  # MA_NOACTIVATE
    assert not r["pill_is_foreground"]
    assert r["after_show"] == r["before"]
    assert r["after_click_query"] == r["before"]
