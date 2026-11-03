import ctypes
import sys

import pytest
from PySide6.QtGui import QGuiApplication

from ttspython.core.clipboard_router import ClipboardRouter, Action
from ttspython.platform.inject import TextInjector
from ttspython.platform.single_instance import InstanceServer

windows_only = pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows only")


@windows_only
def test_input_struct_matches_win32_size():
    from ttspython.platform import winapi

    assert ctypes.sizeof(winapi.INPUT) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)


@windows_only
def test_real_hotkey_registration_and_conflict(qapp):
    from ttspython.platform.hotkeys import _WinHotkeyThread

    first = _WinHotkeyThread(lambda a: None)
    second = _WinHotkeyThread(lambda a: None)
    first.start()
    second.start()
    try:
        assert first.set_bindings({"a": "Ctrl+Alt+Shift+F22", "b": ""}) == {"a": None, "b": None}
        assert second.set_bindings({"a": "Ctrl+Alt+Shift+F22"})["a"] == "Already used by another app"
        assert first.set_bindings({}) == {}
        assert second.set_bindings({"a": "Ctrl+Alt+Shift+F22"})["a"] is None
    finally:
        first.stop()
        second.stop()
        first.join(2)
        second.join(2)


def test_copy_only_puts_text_on_clipboard_and_is_ignored_by_monitor(qtbot):
    router = ClipboardRouter()
    injector = TextInjector(router)
    with qtbot.waitSignal(injector.finished, timeout=1000) as sig:
        injector.copy_only("Dictated words here.")
    assert sig.args[0] is False
    assert QGuiApplication.clipboard().text() == "Dictated words here."
    assert router.decide("Dictated words here.", busy=False, action="speak", auto_queue=False)[0] is Action.IGNORE


def test_single_instance_forwards_commands(qtbot):
    import os
    import subprocess

    server = InstanceServer()
    assert server.listening
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = ("import sys; from PySide6.QtCore import QCoreApplication; app = QCoreApplication(sys.argv); "
            "from ttspython.platform.single_instance import send_to_running; "
            "print(send_to_running(['mini', 'toggle-dictation']))")
    with qtbot.waitSignal(server.received, timeout=8000) as sig:
        proc = subprocess.Popen([sys.executable, "-c", code], cwd=root, stdout=subprocess.PIPE, text=True)
    out, _ = proc.communicate(timeout=10)
    assert out.strip() == "True"
    assert sig.args[0] == ["mini", "toggle-dictation"]
    server.server.close()
