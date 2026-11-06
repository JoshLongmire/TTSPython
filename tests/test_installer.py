"""The Windows installer's rules. Building and running it for real is done by packaging/build.py and CI."""
import os
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packaging"))

import build  # noqa: E402

SCRIPT = (ROOT / "packaging" / "windows" / "TTSPython.iss").read_text(encoding="utf-8")


def test_it_installs_without_administrator_rights():
    assert "PrivilegesRequired=lowest" in SCRIPT
    assert "{autopf}" in SCRIPT


def test_it_never_touches_settings_voices_or_models():
    # Only the one procedure that runs when the person says yes while uninstalling may name them.
    start = SCRIPT.index("procedure DeleteUserData;")
    outside = SCRIPT[:start] + SCRIPT[SCRIPT.index("end;", SCRIPT.index("#endif", start)):]
    for folder in ("{userappdata}", "{localappdata}", "{commonappdata}", "{userdocs}"):
        assert folder not in outside
    assert "DeleteUserData" not in SCRIPT[:start]
    assert "{commonappdata}" not in SCRIPT and "{userdocs}" not in SCRIPT
    deleted = re.findall(r'^Type: \w+; Name: "([^"]+)"', SCRIPT, re.M)
    assert deleted == ["{app}\\_internal"]


def test_the_version_comes_from_the_app():
    assert re.search(r"^AppVersion=\{#AppVersion\}$", SCRIPT, re.M)
    assert not re.search(r"\d+\.\d+\.\d+", SCRIPT.replace("10.0", ""))


def test_a_running_copy_is_asked_to_quit_before_files_change():
    assert "'--quit'" in SCRIPT
    assert "function PrepareToInstall" in SCRIPT and "function InitializeUninstall" in SCRIPT
    assert len(re.findall(r"^ +QuitRunningApp;", SCRIPT, re.M)) == 2  # once for upgrades, once for uninstalling


def test_the_public_name_is_used():
    assert "AppPublisher=Pure Tech" in SCRIPT


def test_the_compiler_gets_what_the_script_needs(tmp_path):
    command = build.installer_command("ISCC.exe", "C:/app", "C:/icon.ico", "C:/out", "1.2.3")
    assert command[0] == "ISCC.exe" and command[-1].endswith("TTSPython.iss") and os.path.isfile(command[-1])
    for define in ("/DAppVersion=1.2.3", "/DAppDir=C:/app", "/DIconFile=C:/icon.ico", "/DOutDir=C:/out"):
        assert define in command
    for name in re.findall(r"\{#(\w+)\}", SCRIPT):
        assert any(part.startswith(f"/D{name}=") for part in command)


def test_a_missing_compiler_is_reported_not_skipped(monkeypatch):
    monkeypatch.setattr(build, "find_iscc", lambda: None)
    with pytest.raises(SystemExit, match="Inno Setup"):
        build.make_installer("C:/app", "C:/icon.ico", "C:/out")


def test_the_iscc_setting_wins(monkeypatch, tmp_path):
    tool = tmp_path / "ISCC.exe"
    tool.write_bytes(b"")
    monkeypatch.setenv("ISCC", str(tool))
    assert build.find_iscc() == str(tool)
