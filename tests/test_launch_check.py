"""Problems found while checking the product before showing it to people."""
import importlib.util
import os

import pytest

from test_ui import make_controller
from ttspython.core import settings as settings_module
from ttspython.core.tts import piper


def test_piper_paths_survive_a_non_english_user_name(monkeypatch, tmp_path):
    """Piper cannot open absolute paths with such a name in them: it crashed with no message. Paths
    relative to the folder it runs in hold only ASCII, whatever the user is called."""
    data = tmp_path / "José 日本語"
    monkeypatch.setenv("TTSPYTHON_DATA", str(data))
    started = {}

    class FakePopen:
        def __init__(self, args, **kwargs):
            started.update(args=args, cwd=kwargs["cwd"])

    monkeypatch.setattr(piper.subprocess, "Popen", FakePopen)
    process = piper._Process("en_US-lessac-medium", 1.0)
    try:
        args, cwd = started["args"], started["cwd"]
        assert os.path.isabs(args[0]) and cwd == piper.program_dir()  # the OS itself handles these
        for value in args[1:]:
            assert value.isascii(), value
        model = args[args.index("--model") + 1]
        assert os.path.normpath(os.path.join(cwd, model)) == os.path.normpath(piper.model_path("en_US-lessac-medium"))
        espeak = args[args.index("--espeak_data") + 1]
        assert os.path.normpath(os.path.join(cwd, espeak)) == os.path.join(piper.program_dir(), "espeak-ng-data")
    finally:
        process.proc = None
        process.close()


def load_build_script():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packaging", "build.py")
    spec = importlib.util.spec_from_file_location("ttspython_build_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_package_carries_its_licenses(tmp_path):
    build = load_build_script()
    build.add_license_files(str(tmp_path))
    assert "MIT License" in (tmp_path / "LICENSE.txt").read_text(encoding="utf-8")
    notices = (tmp_path / "THIRD_PARTY_LICENSES.txt").read_text(encoding="utf-8")
    assert "Lesser General Public License" in notices
    for name in ("pyside6-essentials", "numpy", "faster-whisper", "sherpa-onnx", "sounddevice", "lameenc", "ctranslate2"):
        assert name in notices.lower().replace("_", "-"), name
    assert "\nav " not in notices  # left out of the build, so not listed
    assert "Permission is hereby granted" in notices  # the license texts, not only their names


@pytest.mark.parametrize("content", ['{"items": 5}', '{"items": {"a": 1}}', '{"items": null}', "[]", "5"])
def test_a_damaged_queue_file_cannot_stop_the_app_from_starting(qtbot, tmp_path, content):
    (tmp_path / "queue.json").write_text(content, encoding="utf-8")
    controller = make_controller(qtbot, tmp_path)
    try:
        assert len(controller.queue) == 0
    finally:
        controller.quit()


def test_settings_saved_by_notepad_with_a_byte_order_mark_are_kept(tmp_path):
    path = tmp_path / "settings.json"
    path.write_bytes(b'\xef\xbb\xbf{"stt_auto_unload_minutes": 7}')
    settings, info = settings_module.load(str(path), legacy="")
    assert info["broken_copy"] is None
    assert settings["stt_auto_unload_minutes"] == 7
