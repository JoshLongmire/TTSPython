"""Render the real app's windows to PNG files (uses temporary settings and data folders).

Usage: python tools/screenshots.py --out <folder> [--themes all|studio,light] [--size 1280x800] [--extras]
Set QT_SCALE_FACTOR=2 for double-size pictures.
Set TTSPYTHON_DATA (Piper voices, live preview model) and HF_HOME (Whisper models) to folders with
downloads in them to show those; by default both are empty temporary folders, never your own.
With QT_QPA_PLATFORM=offscreen and QT_QPA_FONTDIR=C:/Windows/Fonts no window opens on the desktop.
"""
import argparse
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SAMPLE = (
    "Welcome to TTSPython. Paste an article, a chapter or your notes here and press Play.\n\n"
    "The sentence being read is highlighted, and the editor follows along as it reads. "
    "You can pause, change the voice or speed, and pick up right where you left off.\n\n"
    "Switch to Listen to dictate. Everything runs offline on this computer."
)
# The highlighted sentence: the second paragraph's first sentence.
HL_START = SAMPLE.index("The sentence being read")
HL_END = SAMPLE.index("as it reads.") + len("as it reads.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--themes", default="studio")
    parser.add_argument("--size", default="1280x800")
    parser.add_argument("--extras", action="store_true", help="also capture settings pages, mini mode, find bar")
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    os.environ["TTSPYTHON_SETTINGS"] = os.path.join(tempfile.mkdtemp(prefix="ttspy_shots_"), "settings.json")
    os.environ.setdefault("TTSPYTHON_DATA", tempfile.mkdtemp(prefix="ttspy_shots_data_"))
    os.environ.setdefault("HF_HOME", tempfile.mkdtemp(prefix="ttspy_shots_hf_"))  # Whisper models listed in Settings

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from ttspython.core.settings import SettingsStore
    from ttspython.core.theme import THEME_PRESETS
    from ttspython.ui import icons
    from ttspython.ui.app_controller import AppController

    app = QApplication(sys.argv[:1])
    store = SettingsStore(legacy="")
    ctl = AppController(app, store)
    w, h = (int(v) for v in args.size.split("x"))
    ctl.window.resize(w, h)
    ctl.window.show()
    ctl.editor.setPlainText(SAMPLE)
    for i, text in enumerate(["Chapter one of the audiobook draft.", "Meeting notes from Tuesday.",
                              "A long article copied from the browser."]):
        ctl.queue.add(text * 6, ["Chapter 1.txt", "Text: Meeting notes from Tuesday...",
                                 "Clipboard: A long article copied from..."][i], ["file", "text", "clipboard"][i])
    ctl.speech.wait_ready(10)
    themes = list(THEME_PRESETS) if args.themes == "all" else args.themes.split(",")

    def settle(ms=120):
        loop_end = __import__("time").monotonic() + ms / 1000
        while __import__("time").monotonic() < loop_end:
            app.processEvents()

    def grab(widget, name):
        settle()
        path = os.path.join(args.out, name + ".png")
        widget.grab().save(path)
        print(path)

    def run():
        try:
            capture()
        finally:
            ctl.quit()  # or a failure leaves the windows open and this program running

    def capture():
        ctl.editor.begin_tracking()
        ctl.editor.highlight_range(HL_START, HL_END)
        ctl.window.transport.set_progress(1, 4, "Sentence 2 of 4")
        # As it looks while reading: nothing is spoken, the waveform gets a speech-shaped level.
        clock = __import__("time").monotonic
        math = __import__("math")
        ctl.window.transport.set_level_source(
            lambda: 0.2 + 0.7 * abs(math.sin(clock() * 11)) * abs(math.sin(clock() * 2.7)))
        icons.apply(ctl.actions["play_pause"], "pause", "on_accent", 22)
        ctl.window.status_label.setText("Speaking...")
        ctl.actions["stop"].setEnabled(True)
        settle(1000)
        for key in themes:
            ctl.theme.apply(key)
            icons.apply(ctl.actions["play_pause"], "pause", "on_accent", 22)
            ctl.editor.begin_tracking()
            ctl.editor.highlight_range(HL_START, HL_END)
            grab(ctl.window, f"main_{key}")
        ctl.window.transport.set_level_source(None)
        icons.apply(ctl.actions["play_pause"], "play", "on_accent", 22)
        ctl.window.status_label.setText("")
        ctl.actions["stop"].setEnabled(False)
        if args.extras:
            ctl.theme.apply(themes[0])
            ctl.set_mode("stt")
            grab(ctl.window, "main_listen")
            ctl.set_mode("tts")
            ctl.window.find_bar.open_bar()
            ctl.window.find_bar.find_edit.setText("sentence")
            grab(ctl.window, "main_findbar")
            ctl.window.find_bar.close_bar()
            ctl.open_settings()
            dlg = ctl._settings_dialog
            dlg.resize(900, 640)
            for row, (page, _t, _i) in enumerate(__import__("ttspython.ui.settings_dialog", fromlist=["PAGES"]).PAGES):
                dlg.nav.setCurrentRow(row)
                grab(dlg, f"settings_{page}")
            dlg.nav.setCurrentRow(1)
            ctl.open_voice_browser()
            browser = ctl._voice_browser
            browser.resize(620, 520)
            grab(browser, "voice_browser")
            browser.close()
            dlg.close()
            ctl.mini.restore_position(None)
            ctl.mini.show()
            grab(ctl.mini, "mini_idle")
            ctl.mini.set_speaking(True)
            ctl.mini.wave.set_source(lambda: 0.35)
            settle(900)
            grab(ctl.mini, "mini_speaking")
            ctl.mini.set_speaking(False)
            ctl.mini.set_recording(True)
            ctl.mini.wave.color_role = "danger"
            settle(600)
            grab(ctl.mini, "mini_recording")
            # The live caption bubble above the recording bar, as one picture: Whisper's checked
            # words, then the instant preview's newer ones (dimmer), the newest highlighted.
            ctl.caption.set_tokens(ctl.theme.tokens)
            ctl.caption.set_words("The meeting moved to Thursday at three,",
                                  "and we will need the room", "for about an hour")
            ctl.caption.show_by(ctl.mini)
            settle(300)
            pill, cap = ctl.mini.grab(), ctl.caption.grab()
            from PySide6.QtCore import Qt as _Qt
            from PySide6.QtGui import QPainter, QPixmap

            dpr = pill.devicePixelRatio()
            gap = 4
            width = max(pill.width(), cap.width())
            sheet = QPixmap(width, cap.height() + gap + pill.height())
            sheet.setDevicePixelRatio(dpr)
            sheet.fill(_Qt.transparent)
            painter = QPainter(sheet)
            painter.drawPixmap(int((width - cap.width()) / 2 / dpr), 0, cap)
            painter.drawPixmap(int((width - pill.width()) / 2 / dpr), int((cap.height() + gap) / dpr), pill)
            painter.end()
            sheet.save(os.path.join(args.out, "mini_caption.png"))
            ctl.caption.hide()
            ctl.mini.set_recording(False)
            ctl.mini.wave.set_source(None)
            ctl.popover.set_values(ctl.voices(), ctl.speech.voice_id, 200, 0.8)
            ctl.popover.adjustSize()
            ctl.popover.move(200, 200)
            ctl.popover.show()
            grab(ctl.popover, "mini_popover")
            ctl.popover.hide()

    QTimer.singleShot(300, run)
    app.exec()


if __name__ == "__main__":
    main()
