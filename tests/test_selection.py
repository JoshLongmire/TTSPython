"""Mini bar Play: the highlighted text in the app being used, else the clipboard."""
import os
import subprocess
import sys
import time

import pytest
from PySide6.QtGui import QGuiApplication

from fakes import FakeSelection
from test_ui import make_controller
from ttspython.core.clipboard_router import Action, ClipboardRouter
from ttspython.core.platform import IS_WINDOWS
from ttspython.platform import selection
from ttspython.platform.selection import SelectionGrabber

APP = 1001


class FakeWin:
    """The Win32 calls the grabber makes, around a pretend foreground app."""

    def __init__(self, cls="Notepad", highlighted=None, modifiers=0):
        self.cls = cls
        self.highlighted = highlighted  # what the app copies on Ctrl+C (None: nothing selected)
        self.modifier_polls = modifiers
        self.seq = 1
        self.copies = 0

    def foreground_window(self):
        return APP

    def is_own_window(self, hwnd):
        return hwnd == 7

    def window_class(self, hwnd):
        return self.cls

    def modifiers_down(self):
        if self.modifier_polls:
            self.modifier_polls -= 1
            return True
        return False

    def clipboard_sequence(self):
        return self.seq

    def send_copy(self):
        self.copies += 1
        if self.highlighted is not None:
            QGuiApplication.clipboard().setText(self.highlighted)
            self.seq += 1
        return 4


def grab(qtbot, grabber):
    got = []
    grabber.grab(got.append)
    qtbot.waitUntil(lambda: bool(got), timeout=4000)
    return got[0]


@pytest.fixture
def clip(qapp):
    QGuiApplication.clipboard().setText("What was on the clipboard.")
    return QGuiApplication.clipboard()


def test_ui_automation_answer_is_used_without_keys(qtbot, clip):
    win = FakeWin()
    assert grab(qtbot, SelectionGrabber(uia=lambda: "Highlighted words.", win=win)) == "Highlighted words."
    assert win.copies == 0 and clip.text() == "What was on the clipboard."


def test_nothing_highlighted_means_the_clipboard(qtbot, clip):
    win = FakeWin(highlighted="should not be copied")
    assert grab(qtbot, SelectionGrabber(uia=lambda: "", win=win)) is None
    assert win.copies == 0


def test_terminals_never_get_ctrl_c(qtbot, clip):
    for cls in ("ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS", "mintty"):
        win = FakeWin(cls=cls, highlighted="x")
        assert grab(qtbot, SelectionGrabber(uia=lambda: None, win=win)) is None
        assert win.copies == 0


def test_other_apps_are_copied_and_the_clipboard_put_back(qtbot, clip):
    router = ClipboardRouter()
    router.prime(clip.text())
    win = FakeWin(highlighted="Selected in an older app.")
    assert grab(qtbot, SelectionGrabber(router, uia=lambda: None, win=win)) == "Selected in an older app."
    assert win.copies == 1
    assert clip.text() == "What was on the clipboard."
    # The clipboard monitor ignores the brief copy and the restore.
    for text in ("Selected in an older app.", "What was on the clipboard."):
        assert router.decide(text, busy=False, action="speak", auto_queue=False)[0] is Action.IGNORE


def test_copy_with_nothing_selected_leaves_the_clipboard(qtbot, clip):
    win = FakeWin(highlighted=None)
    t0 = time.perf_counter()
    assert grab(qtbot, SelectionGrabber(uia=lambda: None, win=win)) is None
    assert win.copies == 1 and clip.text() == "What was on the clipboard."
    assert time.perf_counter() - t0 < 1.5


def test_waits_for_hotkey_keys_to_be_released(qtbot, clip):
    win = FakeWin(highlighted="Hotkey selection.", modifiers=5)
    assert grab(qtbot, SelectionGrabber(uia=lambda: None, win=win)) == "Hotkey selection."
    win = FakeWin(highlighted="never", modifiers=10_000)  # held the whole time: no Ctrl+Alt+C
    assert grab(qtbot, SelectionGrabber(uia=lambda: None, win=win)) is None
    assert win.copies == 0


def test_an_app_that_does_not_answer_is_skipped(qtbot, clip):
    win = FakeWin(highlighted="never")
    t0 = time.perf_counter()
    assert grab(qtbot, SelectionGrabber(uia=lambda: time.sleep(3) or "late", win=win)) is None
    assert selection.UIA_TIMEOUT_MS / 1000 - 0.1 < time.perf_counter() - t0 < 2.5
    assert win.copies == 0


def test_own_windows_are_not_asked(qtbot, clip):
    win = FakeWin()
    win.foreground_window = lambda: 7
    asked = []
    assert grab(qtbot, SelectionGrabber(uia=lambda: asked.append(1), win=win)) is None
    assert asked == []


def test_play_reads_the_highlight_else_the_clipboard(qtbot, tmp_path, clip):
    c = make_controller(qtbot, tmp_path)
    try:
        c.selection = FakeSelection("Highlighted in another app.")
        said = []
        c._status = said.append
        c.window.hide()
        c.speak_clipboard()
        qtbot.waitUntil(lambda: c.speech.busy, timeout=2000)
        assert "Speaking highlighted text..." in said
        c.speak_clipboard()  # pressed again: stop
        assert not c.speech.busy
        c.selection.text = None
        c.speak_clipboard()
        qtbot.waitUntil(lambda: c.speech.busy, timeout=2000)
        assert said[-1] == "Speaking clipboard text..." or "Speaking clipboard text..." in said
        c.on_stop()
    finally:
        c.quit()


CHILD = r'''
from PySide6.QtWidgets import QApplication, QPlainTextEdit
from PySide6.QtGui import QTextCursor
app = QApplication([])
e = QPlainTextEdit(); e.setWindowTitle("TTSPython selection test")
e.setPlainText("Intro words. Selected part here. Tail.")
c = e.textCursor(); c.setPosition(13); c.setPosition(32, QTextCursor.KeepAnchor); e.setTextCursor(c)
e.resize(300, 100); e.move(20, 20); e.show()
print(int(e.winId()), flush=True)
app.exec()
'''


@pytest.mark.desktop
@pytest.mark.skipif(not IS_WINDOWS, reason="UI Automation is Windows only")
def test_ui_automation_reads_another_apps_selection():
    env = dict(os.environ, QT_QPA_PLATFORM="windows")  # a real window, not the tests' offscreen one
    child = subprocess.Popen([sys.executable, "-c", CHILD], stdout=subprocess.PIPE, text=True, env=env)
    try:
        hwnd = int(child.stdout.readline())
        time.sleep(0.5)
        from ttspython.core.platform import com_apartment

        with com_apartment():
            assert selection.uia_selection(hwnd) == "Selected part here."
    finally:
        child.kill()
