"""One running copy: later launches forward their command-line actions to it."""
from __future__ import annotations

import contextlib
import ctypes
import getpass
import json
import os
import sys

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_MAX_SOCKET_PATH = 100  # a Unix socket's path has to fit in about 108 bytes
_SPARE_NAMES = 3  # names to try, when another user holds this one


def posix_socket_path():
    """A place only this user can write to. Qt's default is the shared temporary folder, where
    anybody could take the name first."""
    from ..core.platform import data_dir

    folder = os.environ.get("XDG_RUNTIME_DIR") or data_dir()
    return os.path.join(folder, "ttspython.sock")


def server_name():
    override = os.environ.get("TTSPYTHON_INSTANCE")
    if override:  # tests use a private name so they never talk to a running copy
        return override
    if not sys.platform.startswith("win"):
        path = posix_socket_path()
        if len(path) <= _MAX_SOCKET_PATH:
            try:
                os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
                return path
            except OSError:
                pass  # a folder that cannot be made: the plain name below still works
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    return f"ttspython-{''.join(ch for ch in user if ch.isalnum()) or 'user'}"


def _names():
    """Windows has one set of pipe names for everybody signed in to the computer, so another user
    can hold ours. Then the next one is used. A Unix socket is in this user's own folder."""
    name = server_name()
    return [name, *(f"{name}-{i}" for i in range(2, _SPARE_NAMES + 2))] if not os.path.isabs(name) else [name]


def _owner_is_me(handle):
    """Was this pipe made by this user (or by an administrator, who could do anything anyway)?
    True if it cannot be told: a check that fails must not stop the app from working."""
    import ctypes.wintypes as wt

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wt.HANDLE
    kernel32.LocalFree.argtypes = (wt.HANDLE,)
    kernel32.CloseHandle.argtypes = (wt.HANDLE,)
    advapi32.GetSecurityInfo.argtypes = (wt.HANDLE, ctypes.c_int, wt.DWORD, ctypes.POINTER(ctypes.c_void_p),
                                         ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
    advapi32.OpenProcessToken.argtypes = (wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE))
    advapi32.GetTokenInformation.argtypes = (wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD))
    advapi32.EqualSid.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    advapi32.IsWellKnownSid.argtypes = (ctypes.c_void_p, ctypes.c_int)
    SE_KERNEL_OBJECT, OWNER_SECURITY_INFORMATION, TOKEN_QUERY, TOKEN_USER = 6, 1, 8, 1
    WIN_LOCAL_SYSTEM_SID, WIN_BUILTIN_ADMINISTRATORS_SID = 22, 26

    owner, descriptor = ctypes.c_void_p(), ctypes.c_void_p()
    if advapi32.GetSecurityInfo(handle, SE_KERNEL_OBJECT, OWNER_SECURITY_INFORMATION, ctypes.byref(owner),
                                None, None, None, ctypes.byref(descriptor)) != 0:
        return True
    token = wt.HANDLE()
    try:
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)):
            return True
        try:
            buffer = ctypes.create_string_buffer(256)
            needed = wt.DWORD()
            if not advapi32.GetTokenInformation(token, TOKEN_USER, buffer, len(buffer), ctypes.byref(needed)):
                return True
            me = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]  # TOKEN_USER starts with the SID's address
            return bool(advapi32.EqualSid(owner, me)
                        or advapi32.IsWellKnownSid(owner, WIN_BUILTIN_ADMINISTRATORS_SID)
                        or advapi32.IsWellKnownSid(owner, WIN_LOCAL_SYSTEM_SID))
        finally:
            kernel32.CloseHandle(token)
    finally:
        kernel32.LocalFree(descriptor)


def _answered_by_me(sock):
    """Is the copy on the other end of this connected socket really this user's?"""
    if not sys.platform.startswith("win"):
        return True
    try:
        return _owner_is_me(int(sock.socketDescriptor()))
    except (OSError, ValueError, AttributeError):
        return True


def _allow_foreground():
    """Let the running copy bring its window to the front (we are the foreground process)."""
    if sys.platform.startswith("win"):
        with contextlib.suppress(Exception):
            ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY


def send_to_running(commands, timeout_ms=800):
    """Returns True if another instance of this user's received the commands."""
    for name in _names():
        sock = QLocalSocket()
        sock.connectToServer(name)
        if not sock.waitForConnected(timeout_ms):
            continue  # another user's name may have come free since a copy of ours took the next one
        if not _answered_by_me(sock):
            sock.abort()
            continue
        _allow_foreground()
        sock.write(json.dumps(commands or ["show"]).encode("utf-8"))
        sock.flush()
        sock.waitForBytesWritten(timeout_ms)
        sock.disconnectFromServer()
        return True
    return False


class InstanceServer(QObject):
    """Commands that arrive before a handler is attached are held and delivered later."""

    received = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        self.listening = False
        # Asked first: on Windows, listening works even when somebody already answers on the name.
        free = []
        for name in _names():
            probe = QLocalSocket()
            probe.connectToServer(name)
            if not probe.waitForConnected(300):
                free.append(name)
                continue
            mine = _answered_by_me(probe)
            probe.abort()
            if mine:  # this user's own copy is running: the caller sends it the commands
                free = []
                break
        for name in free:
            self.listening = self.server.listen(name)
            if not self.listening:  # nobody answers, so this may be a stale socket from a crash
                QLocalServer.removeServer(name)
                self.listening = self.server.listen(name)
            if self.listening:
                break
        self.server.newConnection.connect(self._accept)
        self._held = []
        self._handler = None

    def set_handler(self, handler):
        self._handler = handler
        held, self._held = self._held, []
        for commands in held:
            handler(commands)

    def _deliver(self, commands):
        self.received.emit(commands)
        if self._handler is not None:
            self._handler(commands)
        else:
            self._held.append(commands)

    def _accept(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            state = {"buffer": b"", "done": False}
            sock.readyRead.connect(lambda s=sock, st=state: self._read(s, st))
            sock.disconnected.connect(lambda s=sock, st=state: self._read(s, st))
            # Sockets stay children of the server (one tiny object per later launch);
            # deleting them from their own disconnected signal aborts Qt.
            # Data can arrive before readyRead is connected.
            self._read(sock, state)

    def _read(self, sock, state):
        if state["done"]:
            return
        state["buffer"] += bytes(sock.readAll())
        if not state["buffer"]:
            return
        try:
            commands = json.loads(state["buffer"].decode("utf-8"))
        except ValueError:
            return  # incomplete; wait for more data
        state["done"] = True
        sock.disconnectFromServer()
        if isinstance(commands, list):
            self._deliver([str(c) for c in commands])
