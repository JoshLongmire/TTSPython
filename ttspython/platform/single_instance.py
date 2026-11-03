"""One running copy: later launches forward their command-line actions to it."""
from __future__ import annotations

import ctypes
import getpass
import json
import os
import sys

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def server_name():
    override = os.environ.get("TTSPYTHON_INSTANCE")
    if override:  # tests use a private name so they never talk to a running copy
        return override
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    return f"ttspython-{''.join(ch for ch in user if ch.isalnum()) or 'user'}"


def _allow_foreground():
    """Let the running copy bring its window to the front (we are the foreground process)."""
    if sys.platform.startswith("win"):
        try:
            ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
        except Exception:
            pass


def send_to_running(commands, timeout_ms=800):
    """Returns True if another instance received the commands."""
    sock = QLocalSocket()
    sock.connectToServer(server_name())
    if not sock.waitForConnected(timeout_ms):
        return False
    _allow_foreground()
    sock.write(json.dumps(commands or ["show"]).encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(timeout_ms)
    sock.disconnectFromServer()
    return True


class InstanceServer(QObject):
    """Commands that arrive before a handler is attached are held and delivered later."""

    received = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        self.listening = self.server.listen(server_name())
        if not self.listening:
            # Only remove the name if nobody answers on it (a stale socket from a crash).
            probe = QLocalSocket()
            probe.connectToServer(server_name())
            if not probe.waitForConnected(300):
                QLocalServer.removeServer(server_name())
                self.listening = self.server.listen(server_name())
            else:
                probe.disconnectFromServer()
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
