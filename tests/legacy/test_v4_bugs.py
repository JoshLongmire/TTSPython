"""The v5 bug specs, run against the real v4.1.0 code.

Each test asserts the correct behaviour, so it fails on v4. They are strict
xfails: a bug that does not reproduce shows up as XPASS and fails the run.
Run with: python -m pytest -m legacy
"""
import inspect
import json
import sys

import pytest

from .conftest import FakeEngine, FakeInputStream, FakeWhisper, pump

xfail_v4 = pytest.mark.xfail(strict=True, reason="bug present in v4.1.0")


def _items(*texts):
    return [{"text": t, "name": t, "icon": "\U0001F4AC"} for t in texts]


@xfail_v4
def test_bug01_auto_queue_plays_each_item_once(v4):
    mod, app, root, clip = v4
    app.speech_queue = _items("Alpha item.", "Bravo item.")
    app.clipboard_auto_queue = True
    app.play_queue()
    pump(root, lambda: False, 2.0)
    assert FakeEngine.said.count("Alpha item.") == 1


@xfail_v4
def test_bug02_stop_then_speak_never_overlaps(v4):
    mod, app, root, clip = v4
    FakeEngine.run_seconds = 3
    app.txt.insert("1.0", "Some text to read.")
    app.on_speak()
    assert pump(root, lambda: FakeEngine.running == 1, 3)
    app.on_stop()
    app.on_speak()
    pump(root, lambda: False, 0.5)
    assert FakeEngine.max_running == 1


@xfail_v4
def test_bug03_clipboard_speech_marks_app_busy(v4):
    mod, app, root, clip = v4
    app.clipboard_var.set(True)
    app.toggle_clipboard_monitor()
    FakeEngine.run_seconds = 2
    clip["text"] = "Clipboard sentence to read."
    assert pump(root, lambda: FakeEngine.running == 1, 3)
    assert app.speaking is True


@xfail_v4
def test_bug04_single_clipboard_poll_loop(v4):
    mod, app, root, clip = v4
    app.performance_mode = False
    calls = []
    root.clipboard_get = lambda *a, **k: calls.append(1) or clip["text"]
    for _ in range(10):
        app.clipboard_var.set(True)
        app.toggle_clipboard_monitor()
        app.clipboard_var.set(False)
        app.toggle_clipboard_monitor()
    app.clipboard_var.set(True)
    app.toggle_clipboard_monitor()
    calls.clear()
    pump(root, lambda: False, 2.2)
    assert len(calls) <= 3  # one poll per second


@xfail_v4
def test_bug05_selection_highlight_starts_at_selection(v4):
    mod, app, root, clip = v4
    app.txt.insert("1.0", "Intro text here. Selected words to read.")
    start = app.txt.search("Selected", "1.0")
    app.txt.tag_add("sel", start, "end-1c")
    highlighted = []
    original = app.txt.tag_add
    app.txt.tag_add = lambda tag, a, *rest: (highlighted.append(app.txt.index(a)) if tag == app.highlight_tag else None,
                                             original(tag, a, *rest))[1]
    app.on_speak_selected()
    pump(root, lambda: not app.speaking and FakeEngine.said, 3)
    assert start in highlighted


@xfail_v4
def test_bug06a_rebinding_releases_the_old_key(v4):
    mod, app, root, clip = v4
    app.hotkeys = dict(app.hotkeys, clear="<Control-k>")
    app.bind_shortcuts()
    assert root.bind("<Control-l>") == ""


@xfail_v4
def test_bug06b_missing_shortcut_does_not_crash(v4):
    mod, app, root, clip = v4
    app.hotkeys = {"stop": "<Escape>"}
    try:
        app.bind_shortcuts()
    except KeyError as exc:
        pytest.fail(f"KeyError: {exc}")


@xfail_v4
def test_bug07_record_button_label_after_stop(v4):
    mod, app, root, clip = v4
    app.current_mode = "stt"
    app.refresh_mode_ui()
    app._transcribe_with_whisper = lambda path: "hello"
    app.start_stt_recording()
    app.stop_stt_recording()
    pump(root, lambda: not app.stt_processing, 3)
    assert app.stt_record_btn.cget("text") == "Start Recording"


@xfail_v4
def test_bug08_regex_find_selects_whole_match(v4):
    mod, app, root, clip = v4
    app.txt.insert("1.0", "caaat")
    dialog = mod.SearchDialog(root, app.txt)
    dialog.find_entry.insert(0, "a+")
    dialog.use_regex.set(True)
    dialog.find_next()
    assert _selection(app) == "aaa"


def _selection(app):
    ranges = app.txt.tag_ranges("sel")
    return app.txt.get(ranges[0], ranges[1]) if ranges else ""


@xfail_v4
def test_bug08b_find_honours_the_case_option(v4):
    mod, app, root, clip = v4
    app.txt.insert("1.0", "say hello")
    dialog = mod.SearchDialog(root, app.txt)
    dialog.find_entry.insert(0, "HELLO")  # Case sensitive is off by default
    dialog.find_next()
    assert _selection(app) == "hello"


@xfail_v4
def test_bug09_mp3_export_is_really_mp3(v4, tmp_path):
    mod, app, root, clip = v4
    path = str(tmp_path / "speech.mp3")
    app._export_audio_worker("Hello there.", path)
    pump(root, lambda: False, 0.1)
    with open(path, "rb") as f:
        assert f.read(4) != b"RIFF"


@xfail_v4
def test_bug10_output_device_setting_is_used_for_speech(v4):
    mod, app, root, clip = v4
    speech_code = inspect.getsource(mod.ReaderApp._speak_worker) + inspect.getsource(mod.ReaderApp._play_queue_worker)
    assert "tts_output_device" in speech_code


@xfail_v4
def test_bug11_changing_the_model_reloads_it(v4, tmp_path):
    mod, app, root, clip = v4
    wav = str(tmp_path / "x.wav")
    open(wav, "wb").close()
    app.stt_whisper_model = "small"
    app._transcribe_with_whisper(wav)
    app.stt_whisper_model = "tiny"
    app._transcribe_with_whisper(wav)
    assert FakeWhisper.loaded == ["small", "tiny"]


@xfail_v4
def test_bug12_removing_the_playing_last_item_ends_the_queue(v4):
    mod, app, root, clip = v4
    FakeEngine.run_seconds = 0.6
    app.speech_queue = _items("Alpha item.", "Bravo item.")
    app.play_queue()
    assert pump(root, lambda: "Bravo item." in FakeEngine.said, 5)
    pump(root, lambda: False, 0.05)
    app.queue_tree.selection_set("1")
    app.remove_from_queue()
    pump(root, lambda: False, 1.5)
    assert FakeEngine.said.count("Alpha item.") == 1


@xfail_v4
def test_bug14_find_and_replace_opens_once(v4):
    mod, app, root, clip = v4
    app.on_search()
    app.on_search()
    windows = [w for w in root.winfo_children() if w.winfo_class() == "Toplevel" and w.title() == "Find and Replace"]
    assert len(windows) == 1


@xfail_v4
def test_bug15_closing_stops_speech(v4):
    mod, app, root, clip = v4
    FakeEngine.run_seconds = 3
    app.txt.insert("1.0", "Long text being read.")
    app.on_speak()
    assert pump(root, lambda: FakeEngine.running == 1, 3)
    engine = FakeEngine.instances[-1]
    app.on_close()
    assert engine.stop_calls >= 1


@xfail_v4
def test_bug16_literal_replace_keeps_backslashes(v4):
    mod, app, root, clip = v4
    app.txt.insert("1.0", "save to old")
    dialog = mod.SearchDialog(root, app.txt)
    dialog.find_entry.insert(0, "old")
    dialog.replace_entry.insert(0, r"C:\new")
    dialog.replace_all()
    assert app.txt.get("1.0", "end-1c") == r"save to C:\new"


@xfail_v4
def test_bug17_open_then_save_keeps_the_file_bytes(v4, tmp_path, monkeypatch):
    mod, app, root, clip = v4
    path = tmp_path / "doc.txt"
    path.write_bytes(b"abc")
    monkeypatch.setattr(mod.filedialog, "askopenfilename", lambda **k: str(path))
    app.on_open()
    app.on_save()
    assert path.read_bytes() == b"abc"


@xfail_v4
def test_bug18_replace_all_is_one_undo_step(v4):
    mod, app, root, clip = v4
    app.txt.insert("1.0", "one two one")
    app.txt.edit_separator()
    dialog = mod.SearchDialog(root, app.txt)
    dialog.find_entry.insert(0, "one")
    dialog.replace_entry.insert(0, "1")
    dialog.replace_all()
    app.txt.edit_undo()
    assert app.txt.get("1.0", "end-1c") == "one two one"


@xfail_v4
def test_bug19_voice_rate_volume_are_saved(v4):
    mod, app, root, clip = v4
    app.rate.set(222)
    app.vol.set(0.4)
    app.save_settings()
    with open(app.settings_file, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved.get("tts_rate") == 222


@xfail_v4
def test_bug20_microphone_follows_the_device_not_its_index(v4, monkeypatch):
    mod, app, root, clip = v4
    devices = [{"name": "Mapper", "max_input_channels": 2, "max_output_channels": 2}] * 5 + \
              [{"name": "USB Mic", "max_input_channels": 1, "max_output_channels": 0}]
    sys.modules["sounddevice"].query_devices = lambda *a, **k: devices
    app.current_mode = "stt"
    app.stt_input_device = "3"  # USB Mic was index 3 when it was picked; it is now index 5
    app.start_stt_recording()
    app.recording = False
    assert FakeInputStream.devices[-1] == 5
