"""Win32 declarations via ctypes (imported only on Windows)."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

ULONG_PTR = ctypes.c_size_t
LONG_PTR = ctypes.c_ssize_t

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
VK_SHIFT, VK_CONTROL, VK_MENU = 0x10, 0x11, 0x12
VK_LWIN, VK_RWIN = 0x5B, 0x5C
VK_INSERT = 0x2D
VK_V = 0x56
VK_C = 0x43

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_MOUSEACTIVATE = 0x0021
MA_NOACTIVATE = 3
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
ERROR_HOTKEY_ALREADY_REGISTERED = 1409


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT), ("wParam", wintypes.WPARAM),
                ("lParam", wintypes.LPARAM), ("time", wintypes.DWORD), ("pt", wintypes.POINT),
                ("lPrivate", wintypes.DWORD)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.PeekMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = LONG_PTR
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, LONG_PTR]
user32.SetWindowLongPtrW.restype = LONG_PTR
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.GetCurrentProcessId.restype = wintypes.DWORD
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
advapi32.OpenProcessToken.restype = wintypes.BOOL


def foreground_window():
    return user32.GetForegroundWindow() or 0


def process_needs_admin(pid):
    """True if we may not look inside that program: it runs with more rights than ours."""
    PROCESS_QUERY_LIMITED_INFORMATION, TOKEN_QUERY = 0x1000, 0x0008
    process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        return True
    try:
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(process, TOKEN_QUERY, ctypes.byref(token)):
            return True
        kernel32.CloseHandle(token)
        return False
    finally:
        kernel32.CloseHandle(process)


def window_needs_admin(hwnd):
    """Windows silently drops keys sent to a program with more rights, and says nothing about it."""
    pid = window_process_id(hwnd) if hwnd else 0
    return bool(pid) and process_needs_admin(pid)


def window_process_id(hwnd):
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def is_own_window(hwnd):
    return bool(hwnd) and window_process_id(hwnd) == kernel32.GetCurrentProcessId()


def set_foreground(hwnd):
    if hwnd and user32.IsWindow(hwnd):
        user32.SetForegroundWindow(hwnd)


def clipboard_sequence():
    return user32.GetClipboardSequenceNumber()


def modifiers_down():
    return any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in (VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN))


def _key(vk, up=False, extended=False):
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if extended else 0)
    return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0))


def send_paste(keystroke="ctrl+v"):
    """Synthesize Ctrl+V (or Shift+Insert). Returns the number of events injected."""
    if keystroke == "shift+insert":
        seq = [_key(VK_SHIFT), _key(VK_INSERT, extended=True), _key(VK_INSERT, up=True, extended=True),
               _key(VK_SHIFT, up=True)]
    else:
        seq = [_key(VK_CONTROL), _key(VK_V), _key(VK_V, up=True), _key(VK_CONTROL, up=True)]
    arr = (INPUT * len(seq))(*seq)
    return user32.SendInput(len(seq), arr, ctypes.sizeof(INPUT))


def send_copy():
    """Synthesize Ctrl+C. Returns the number of events injected."""
    seq = [_key(VK_CONTROL), _key(VK_C), _key(VK_C, up=True), _key(VK_CONTROL, up=True)]
    arr = (INPUT * len(seq))(*seq)
    return user32.SendInput(len(seq), arr, ctypes.sizeof(INPUT))


def window_class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    return buf.value if hwnd and user32.GetClassNameW(hwnd, buf, 256) else ""


def apply_noactivate(hwnd):
    """Make a top-level window never take focus when clicked."""
    style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)
    return user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)


def set_app_user_model_id(app_id):
    try:
        shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(app_id))
    except Exception:
        pass


class _PowerThrottlingState(ctypes.Structure):
    _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]


def disable_power_throttling():
    """Keep full CPU speed while in the background. Windows 11 otherwise runs background apps
    in efficiency mode, and dictating into another app made each Whisper pass 2.6x slower
    (1.03 s -> 2.68 s). An idle app uses no CPU, so this costs nothing while idle."""
    try:
        kernel32.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        state = _PowerThrottlingState(1, 0x1 | 0x4, 0)  # execution speed + timer resolution: never throttled
        return bool(kernel32.SetProcessInformation(kernel32.GetCurrentProcess(), 4,  # ProcessPowerThrottling
                                                   ctypes.byref(state), ctypes.sizeof(state)))
    except Exception:
        return False  # Windows 10 before 1709 has no power throttling
