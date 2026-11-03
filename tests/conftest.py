import hashlib
import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Never talk to a TTSPython the user has running: tests get their own single-instance name.
os.environ["TTSPYTHON_INSTANCE"] = f"ttspython-tests-{os.getpid()}"
# Downloaded voices and the Piper program: a scratch folder, never the user's.
os.environ["TTSPYTHON_DATA"] = tempfile.mkdtemp(prefix="ttspython-test-data-")

from ttspython.core.platform import config_dir  # noqa: E402

REAL_SETTINGS_FILES = [
    os.path.join(ROOT, "tts_settings.json"),
    os.path.join(config_dir(), "settings.json"),
]


def _fingerprint(path):
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest(), os.path.getmtime(path)


@pytest.fixture(autouse=True, scope="session")
def guard_real_settings(tmp_path_factory):
    """Fail the run if any test touches the user's real settings files."""
    tmp = tmp_path_factory.mktemp("settings")
    os.environ["TTSPYTHON_SETTINGS"] = str(tmp / "settings.json")
    before = {p: _fingerprint(p) for p in REAL_SETTINGS_FILES}
    yield
    after = {p: _fingerprint(p) for p in REAL_SETTINGS_FILES}
    assert before == after, "a test modified a real settings file"


@pytest.fixture
def settings_path(tmp_path):
    return str(tmp_path / "settings.json")


@pytest.fixture
def v4_settings_file(tmp_path):
    """A copy of a v4-format tts_settings.json (tests/data) in a temp folder."""
    src = os.path.join(ROOT, "tests", "data", "v4_tts_settings.json")
    dst = tmp_path / "tts_settings.json"
    with open(src, "rb") as f:
        dst.write_bytes(f.read())
    return str(dst)


@pytest.fixture(autouse=True)
def no_preview_download(monkeypatch):
    """The instant preview's model is never downloaded in tests (tests that use the preview
    give the service a fake one)."""
    from ttspython.core.stt import preview

    monkeypatch.setattr(preview, "installed", lambda: False)
    monkeypatch.setattr(preview, "install", lambda *a, **k: (_ for _ in ()).throw(OSError("no downloads in tests")))


@pytest.fixture(autouse=True)
def no_unexpected_prompts(monkeypatch):
    """A message box nobody answers would hang the run: fail the test instead. Tests that
    expect a prompt patch QMessageBox.question themselves (their patch wins)."""
    try:
        from PySide6.QtWidgets import QMessageBox
    except ImportError:
        return

    def unexpected(*args, **_kwargs):
        raise AssertionError(f"Unexpected prompt: {args[1:3]}")

    monkeypatch.setattr(QMessageBox, "question", unexpected)
    monkeypatch.setattr(QMessageBox, "warning", unexpected)
