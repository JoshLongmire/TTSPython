"""The pieces the standalone build relies on."""
import importlib.util
import os
import struct
import sys

import yaml

from ttspython import app
from ttspython.core import settings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_icon_has_every_size(qapp, tmp_path):
    make_icon = _load("make_icon", os.path.join(ROOT, "packaging", "make_icon.py"))
    ico, png = make_icon.main(str(tmp_path))
    data = open(ico, "rb").read()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind, count) == (0, 1, len(make_icon.SIZES))
    for i in range(count):
        size, offset = struct.unpack("<II", data[6 + 16 * i + 8:6 + 16 * i + 16])
        assert data[offset:offset + 8] == b"\x89PNG\r\n\x1a\n" and size > 0
    assert open(png, "rb").read(8) == b"\x89PNG\r\n\x1a\n"


def test_windowed_build_gets_output_streams(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    app._console_streams([])
    assert sys.stdout is not None and sys.stderr is not None
    print("progress bars can write here", file=sys.stderr)


def test_built_app_looks_for_v4_settings_next_to_itself(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "TTSPython.exe"))
    assert settings.legacy_path() == str(tmp_path / "tts_settings.json")


def test_av_stand_in_only_fails_when_used():
    original = sys.modules.pop("av", None)
    try:
        _load("rthook_no_av", os.path.join(ROOT, "packaging", "rthook_no_av.py"))
        import av

        try:
            av.open("x.mp3")
        except RuntimeError as exc:
            assert "not included" in str(exc)
        else:
            raise AssertionError("expected RuntimeError")
    finally:
        sys.modules.pop("av", None)
        if original is not None:
            sys.modules["av"] = original


def test_build_workflow_covers_both_systems():
    with open(os.path.join(ROOT, ".github", "workflows", "build.yml"), encoding="utf-8") as f:
        flow = yaml.safe_load(f)
    systems = {entry["os"] for entry in flow["jobs"]["build"]["strategy"]["matrix"]["include"]}
    assert any(s.startswith("windows") for s in systems) and any(s.startswith("ubuntu") for s in systems)
    assert any("packaging/build.py" in (step.get("run") or "") for step in flow["jobs"]["build"]["steps"])
