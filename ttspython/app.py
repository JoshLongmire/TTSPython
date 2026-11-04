"""Application entry point."""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import warnings

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
warnings.filterwarnings("ignore", message="You are sending unauthenticated requests to the HF Hub.*")

from . import APP_NAME, __version__  # noqa: E402
from .core.platform import IS_WINDOWS, session_type  # noqa: E402

COMMAND_FLAGS = {
    "show": "Show the main window",
    "mini": "Show the floating mini bar",
    "toggle-dictation": "Start or stop dictation into the active app",
    "speak-clipboard": "Speak the highlighted text, or the clipboard (or stop speaking)",
    "stop": "Stop speaking",
    "pause": "Pause or resume speech",
    "quit": "Quit the running app",
}


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="TTSPython", description="Offline text-to-speech and dictation.")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument("--settings", metavar="PATH", help="Use this settings file instead of the default")
    for flag, help_text in COMMAND_FLAGS.items():
        parser.add_argument(f"--{flag}", action="store_true", help=help_text)
    return parser.parse_args(argv)


def _console_streams(argv):
    """The built Windows app has no console: sys.stdout and sys.stderr are None there.

    Libraries that print (download progress bars) would crash, so give them a sink, and
    let --version / --help print into the terminal the app was started from.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    out = None
    if IS_WINDOWS and any(a in ("--version", "--help", "-h") for a in argv):
        import ctypes

        if ctypes.windll.kernel32.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
            try:
                out = open("CONOUT$", "w", encoding="utf-8", errors="replace")
                out.write("\n")  # start below the prompt the shell already printed
            except OSError:
                out = None
    sink = out or open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = sink
    if sys.stderr is None:
        sys.stderr = sink


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    _console_streams(argv)
    args = parse_args(argv)
    if args.settings:
        os.environ["TTSPYTHON_SETTINGS"] = os.path.abspath(args.settings)
    commands = [flag for flag in COMMAND_FLAGS if getattr(args, flag.replace("-", "_"))]

    if session_type() == "wayland" and os.environ.get("DISPLAY") and not os.environ.get("QT_QPA_PLATFORM"):
        # XWayland keeps always-on-top and window positioning working for the mini bar.
        os.environ["QT_QPA_PLATFORM"] = "xcb"
    if IS_WINDOWS:
        from .platform.winapi import disable_power_throttling, set_app_user_model_id

        set_app_user_model_id("PureTech.TTSPython")
        disable_power_throttling()

    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)

    bench = os.environ.get("TTSPYTHON_BENCH")
    from .platform.single_instance import InstanceServer, send_to_running

    server = None
    if not bench:
        if send_to_running(commands or ["show"]):
            return 0
        if "quit" in commands:
            return 0  # nothing is running, so there is nothing to quit
        # Claim the name right away (before the slow UI build) so a second launch in the
        # next second finds us; commands it sends are held until the UI is ready.
        server = InstanceServer(app)
        if not server.listening and send_to_running(commands or ["show"]):
            return 0

    from .core.settings import SettingsStore
    from .ui.app_controller import AppController

    store = SettingsStore()
    controller = AppController(app, store)
    notice = None
    if store.info.get("error") and store.info.get("source") == "defaults":
        copy = store.info.get("broken_copy")
        notice = ("Your settings file could not be read, so defaults are in use."
                  + (f" A copy was kept: {copy}" if copy else ""))
    elif store.info.get("save_error"):
        notice = f"Imported your TTSPython 4 settings, but they could not be saved: {store.info['save_error']}"
    elif store.info.get("source") == "legacy":
        notice = "Imported your settings from TTSPython 4."
    if controller.restore_recovery():
        restored = "Restored the unsaved text from your last session."
        notice = f"{notice} {restored}" if notice else restored
    if notice:
        # After the window is up and the voice list has loaded (its status would replace ours).
        QTimer.singleShot(1500, lambda: (controller._toast(notice, 6000), controller._status(notice)))

    actions = [c for c in commands if c not in ("show", "mini")]
    if actions:
        # e.g. --toggle-dictation from a desktop shortcut: act on the app the user is in
        # first, then show only the mini bar (it never takes focus).
        controller.handle_commands(actions)
        controller.show_initial(mini="show" not in commands)
    else:
        controller.show_initial(mini="mini" in commands)
    if server is not None:
        server.set_handler(controller.handle_commands)
    if IS_WINDOWS:
        from .platform.selection import warm_up

        # Ready UI Automation (used to read highlighted text) once the start-up work is done.
        QTimer.singleShot(5000, lambda: threading.Thread(target=warm_up, name="uia-warm-up", daemon=True).start())
    if bench:
        _install_bench_hooks(app, controller, bench)
    self_test = os.environ.get("TTSPYTHON_SELFTEST")
    if self_test:
        QTimer.singleShot(0, lambda: _run_self_test(controller, self_test))
    return app.exec()


def _run_self_test(controller, out_path):
    """Used by the packaging checks: load every part that is imported on first use, write a
    JSON report to out_path, then quit. Plays no sound and loads no Whisper model."""
    import importlib
    import json
    import tempfile

    report = {"version": __version__, "frozen": bool(getattr(sys, "frozen", False))}
    for name in ("sounddevice", "lameenc", "numpy", "ctranslate2", "onnxruntime", "faster_whisper"):
        try:
            importlib.import_module(name)
            report[name] = "ok"
        except Exception as exc:
            report[name] = f"{type(exc).__name__}: {exc}"
    try:
        from faster_whisper.vad import get_vad_model

        get_vad_model()
        report["vad_model"] = "ok"
    except Exception as exc:
        report["vad_model"] = f"{type(exc).__name__}: {exc}"
    try:
        from .core import audio_devices

        report["output_devices"] = len(audio_devices.list_devices("output"))
        report["input_devices"] = len(audio_devices.list_devices("input"))
    except Exception as exc:
        report["output_devices"] = f"{type(exc).__name__}: {exc}"
    if IS_WINDOWS:
        try:
            from .core.platform import com_apartment
            from .platform.selection import _automation

            with com_apartment():
                _automation()
            report["ui_automation"] = "ok"
        except Exception as exc:
            report["ui_automation"] = f"{type(exc).__name__}: {exc}"
    try:
        from .core.stt import preview

        report["preview_engine"] = "ok" if preview.available() else "missing"
        report["preview_model_installed"] = preview.installed()
        if preview.installed():
            import numpy as np

            t0 = time.perf_counter()
            rec = preview.shared_recognizer()
            stream = rec.create_stream()
            stream.accept_waveform(preview.SAMPLE_RATE, np.zeros(preview.SAMPLE_RATE, dtype=np.float32))
            while rec.is_ready(stream):
                rec.decode_stream(stream)
            report["preview_load_ms"] = round((time.perf_counter() - t0) * 1000)
    except Exception as exc:
        report["preview_engine"] = f"{type(exc).__name__}: {exc}"
    try:
        from .core.tts import piper

        report["piper_catalog"] = len(piper.catalog())
        report["piper_program_available"] = piper.program_available()
    except Exception as exc:
        report["piper_catalog"] = f"{type(exc).__name__}: {exc}"
    report["engine_ready"] = controller.speech.wait_ready(20)
    report["renderer"] = controller.speech.renderer_name
    report["voices"] = len(controller.speech.voices)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "self-test.mp3")
        voice = os.environ.get("TTSPYTHON_SELFTEST_VOICE") or controller.speech.voice_id
        errors = []
        controller.exporter.events.on("failed", errors.append)
        controller.exporter.start("Self test.", path, voice, 200, 1.0)
        controller.exporter.join(60)
        report["export_voice"] = voice
        report["mp3_export_bytes"] = os.path.getsize(path) if os.path.exists(path) else 0
        if errors:
            report["export_error"] = errors[0]
    stt_model = os.environ.get("TTSPYTHON_SELFTEST_STT")
    if stt_model:
        report["dictation"] = _self_test_dictation(controller, stt_model)
    report["problems"] = self_test_problems(report)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    controller.quit()


def self_test_problems(report):
    """What a self-test report says is broken, as "part: what happened". Empty when all is well."""
    problems = []
    for key in ("sounddevice", "lameenc", "numpy", "ctranslate2", "onnxruntime", "faster_whisper", "vad_model",
                "ui_automation", "preview_engine"):
        if report.get(key, "ok") != "ok":
            problems.append(f"{key}: {report[key]}")
    for key in ("output_devices", "piper_catalog"):
        if isinstance(report.get(key), str):
            problems.append(f"{key}: {report[key]}")
    if not report.get("engine_ready"):
        problems.append("engine_ready: the speech engine did not start")
    if not report.get("voices"):
        problems.append("voices: none found")
    if report.get("export_error") or not report.get("mp3_export_bytes"):
        problems.append(f"mp3_export: {report.get('export_error') or 'no file was written'}")
    return problems


def preview_ready():
    from .core.stt import preview

    return preview.available() and preview.installed()


def _self_test_dictation(controller, model_name, timeout=900):
    """Speak a phrase with the real voice and run it through the dictation service's own
    transcription path (loads, and if needed downloads, model_name). Reports where it hangs."""
    import traceback

    import numpy as np

    from .core.platform import com_apartment
    from .core.tts.render import create_renderer

    phrase = os.environ.get("TTSPYTHON_SELFTEST_PHRASE") or "Testing one two three."
    with com_apartment():
        renderer = create_renderer()
        pcm, rate = renderer.render(phrase, controller.speech.voice_id, 170, threading.Event())
    samples = pcm.astype(np.float32) / 32768.0
    audio = np.interp(np.arange(0, len(samples), rate / 16000.0), np.arange(len(samples)), samples)
    audio = audio.astype(np.float32)

    class Playback:
        """Stands in for the microphone: "records" the spoken phrase in real time, and hands
        each block to on_block like the real recorder (the instant preview listens there)."""
        sample_rate = capture_rate = 16000
        level = 0.0
        on_limit = None
        on_block = None
        t0 = 0.0

        def start(self, device=None):
            self.t0 = time.perf_counter()
            threading.Thread(target=self._feed, daemon=True).start()

        def _feed(self):
            sent, block = 0, 1024
            while sent < audio.size:
                heard = int((time.perf_counter() - self.t0) * self.sample_rate)
                while sent + block <= min(heard, audio.size):
                    callback = self.on_block
                    if callback is not None:
                        callback(audio[sent:sent + block])
                    sent += block
                time.sleep(0.01)

        def _heard(self):
            return audio[:int((time.perf_counter() - self.t0) * self.sample_rate)]

        def snapshot(self, start=0):
            return self._heard()[start:]

        def stop(self):
            return self._heard()

    from .core.stt.service import SttState

    svc = controller.stt
    svc.model = model_name
    svc.recorder = Playback()
    svc.live = os.environ.get("TTSPYTHON_SELFTEST_LIVE", "1") != "0"
    controller.stt_bridge.blockSignals(True)  # never type the result into the user's app
    result = {"model": model_name, "phrase": phrase, "events": []}
    t0 = time.perf_counter()
    done = threading.Event()

    def log(kind, value):
        result["events"].append([round(time.perf_counter() - t0, 1), kind, value])

    svc.events.on("transcript_ready", lambda text, _target: log("text", text))
    svc.events.on("partial", lambda *parts: log("partial", " | ".join(parts)))
    result["preview_used"] = svc.preview_wanted() and preview_ready()
    svc.events.on("model_status", lambda text: log("status", text))
    svc.events.on("preview_status", lambda text: log("preview", text))
    svc.events.on("error", lambda text: log("error", text))
    svc.events.on("state_changed", lambda state: (log("state", state.value), state is SttState.IDLE and done.set()))
    svc.start("self-test")  # the same calls the mic button makes
    time.sleep(audio.size / 16000 + 0.3)  # "speaking" the whole phrase in real time
    stopped = time.perf_counter()
    svc.stop()
    done.wait(timeout)
    result["seconds"] = round(time.perf_counter() - t0, 1)
    result["stop_to_text_ms"] = round((time.perf_counter() - stopped) * 1000)
    shown = [e for e in result["events"] if e[1] == "partial"]
    result["captions"] = len(shown)
    result["first_caption_s"] = shown[0][0] if shown else None
    result["audio_seconds"] = round(audio.size / 16000, 1)
    result["state_after"] = svc.state.value
    if not done.is_set():
        frame = sys._current_frames().get(svc._pool._thread.ident)
        result["hung"] = traceback.format_stack(frame) if frame else "worker thread is gone"
    return result


def _install_bench_hooks(app, controller, mode):
    """Used by tools/bench/bench.py: report when the window is painted, speak on request."""
    from PySide6.QtCore import QObject, QTimer, Signal

    def ready():
        app.processEvents()
        print("READY", flush=True)
        if mode == "ttfa":
            threading.Thread(target=wait_go, daemon=True).start()

    class Relay(QObject):
        go = Signal()

    relay = Relay(app)
    app._bench_relay = relay

    def speak():
        controller.editor.setPlainText("Hello there. This is a quick speech test.")
        controller.speech.wait_ready(10)
        print("SPEAK", time.time_ns(), flush=True)
        controller.on_speak_all()

    relay.go.connect(speak)

    def wait_go():
        sys.stdin.readline()
        relay.go.emit()

    QTimer.singleShot(0, ready)
