"""Bugs and gaps found by the code base check before 5.1. Each test failed on the code before the fix."""
import os
import re
import shutil
import threading
import time
import types

import numpy as np
import pytest
import yaml
from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMessageBox

from test_clone import (  # noqa: F401 (fixtures)
    CONSENT, RATE, FakeEngine, FakeRecorder, app, data, model, speech, voice, window,
)
from ttspython.core import settings as settings_mod
from ttspython.core.stt import preview, service
from ttspython.core.tts import clone, piper
from ttspython.core.tts.render import Cancelled
from ttspython.platform import inject
from ttspython.ui import clone_dialog
from ttspython.ui.mini import LiveCaption

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def say_yes(monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)


def say_no(monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)


# --- the startup crash --------------------------------------------------------------------------
def test_the_app_keeps_python_away_from_wmi():
    import platform

    assert platform._wmi is None


def test_what_the_app_asks_about_the_system_still_works_without_wmi():
    import platform

    uname = platform.uname()
    assert uname.system and uname.machine
    if os.name == "nt":
        assert uname.system == "Windows" and platform.win32_ver()[0]
        assert piper._platform_key()[0] == "win32"


def test_a_built_app_does_not_contain_the_wmi_module():
    with open(os.path.join(ROOT, "packaging", "TTSPython.spec"), encoding="utf-8") as f:
        assert '"_wmi"' in f.read()


# --- consent ------------------------------------------------------------------------------------
def test_someone_elses_speech_before_the_statement_is_refused():
    consent = clone.new_consent()
    other = "the quarterly results were read out at the meeting and everyone agreed that the plan for next year looks good so we moved on to the budget"
    assert "too much" in clone.check_consent(consent, f"{other} {consent.text}")


def test_the_code_words_are_spread_through_the_statement():
    """A clip played first would otherwise fill the part of the recording the voice is made from."""
    consent = clone.new_consent()
    words = clone._words(consent.text)
    first, _second, last = [words.index(w) for w in consent.code_words]
    assert first < len(words) * 0.2 and last > len(words) * 0.8


# --- saved voices -------------------------------------------------------------------------------
def test_a_voice_without_its_recording_is_not_listed(model):  # noqa: F811
    vid = voice()
    os.remove(os.path.join(clone.voice_folder(vid), "consent.wav"))
    assert clone.saved_voices() == []


def test_a_damaged_voice_file_does_not_stop_the_list(model):  # noqa: F811
    vid = voice()
    with open(os.path.join(clone.voice_folder(vid), "voice.json"), "w", encoding="utf-8") as f:
        f.write("[]")
    assert clone.saved_voices() == []


def test_a_recording_left_by_a_crash_is_removed_next_time(model):  # noqa: F811
    stale = os.path.join(clone.voices_dir(), "0123456789ab.new")
    os.makedirs(stale)
    with open(os.path.join(stale, "consent.wav"), "wb") as f:
        f.write(b"a recording")
    voice()
    assert not os.path.exists(stale)


def test_removing_a_voice_reports_failure(model, monkeypatch):  # noqa: F811
    vid = voice()
    monkeypatch.setattr(clone.shutil, "rmtree", lambda *a, **k: None)
    assert clone.remove_voice(vid) is False


def test_voices_stay_listed_when_the_model_is_gone_so_the_setting_survives(model):  # noqa: F811
    vid = voice()
    shutil.rmtree(clone.model_dir())
    listed = {v.id: v.name for v in clone.installed_voices()}
    assert "model not downloaded" in listed[vid]
    with pytest.raises(RuntimeError, match="Get more voices"):
        clone.CloneRenderer(FakeEngine).render("Hello.", vid, 200, threading.Event())


def test_the_download_checks_for_free_space_first(data, monkeypatch):  # noqa: F811
    monkeypatch.setattr(clone.shutil, "disk_usage", lambda _p: types.SimpleNamespace(free=1000))
    with pytest.raises(OSError, match="free"):
        clone.install_model(opener=lambda *_a, **_k: pytest.fail("no download without room"))


# --- the engine ---------------------------------------------------------------------------------
class SlowEngine(FakeEngine):
    release = None

    def __init__(self):
        super().__init__()
        SlowEngine.release.wait(10)


@pytest.fixture
def slow_load(model, monkeypatch):  # noqa: F811
    SlowEngine.release = threading.Event()
    monkeypatch.setattr(clone, "Engine", SlowEngine)
    clone.release_engine()
    yield SlowEngine.release
    SlowEngine.release.set()
    clone.wait_for_load(5)
    clone.release_engine()


def test_stop_works_while_the_model_loads(slow_load):
    vid = voice()
    cancel = threading.Event()
    threading.Timer(0.1, cancel.set).start()
    start = time.perf_counter()
    with pytest.raises(Cancelled):
        clone.CloneRenderer().render("Hello there.", vid, 200, cancel)
    assert time.perf_counter() - start < 1


def test_a_load_stopped_by_stop_is_still_released_when_idle(slow_load):
    vid = voice()
    cancel = threading.Event()
    threading.Timer(0.05, cancel.set).start()
    with pytest.raises(Cancelled):
        clone.CloneRenderer().render("Hello.", vid, 200, cancel)
    slow_load.set()
    clone.wait_for_load(5)
    assert clone.engine_loaded() and clone._idle_timer is not None


def test_stop_works_while_an_export_holds_the_model(model):  # noqa: F811
    engine = FakeEngine()
    vid = voice(engine)
    holding, finish = threading.Event(), threading.Event()

    class Busy(FakeEngine):
        def speak(self, codes, text, cancel):
            holding.set()
            finish.wait(5)
            return speech(1)

    export = threading.Thread(target=lambda: clone.CloneRenderer(lambda _c=None: Busy()).render(
        "A long export.", vid, 200, threading.Event()), daemon=True)
    export.start()
    assert holding.wait(5)
    cancel = threading.Event()
    threading.Timer(0.1, cancel.set).start()
    start = time.perf_counter()
    with pytest.raises(Cancelled):
        clone.CloneRenderer(lambda _c=None: engine).render("Hello.", vid, 200, cancel)
    assert time.perf_counter() - start < 1
    finish.set()
    export.join(5)


def test_a_failed_render_still_lets_the_model_go(model):  # noqa: F811
    class Broken(FakeEngine):
        def speak(self, codes, text, cancel):
            raise RuntimeError("out of memory")

    vid = voice()
    clone.release_engine()
    clone._idle_timer = None
    with pytest.raises(RuntimeError):
        clone.CloneRenderer(lambda _c=None: Broken()).render("Hello.", vid, 200, threading.Event())
    assert clone._idle_timer is not None


def test_the_idle_timer_cannot_drop_the_model_during_a_render(model):  # noqa: F811
    seen = []

    class Watches(FakeEngine):
        def speak(self, codes, text, cancel):
            seen.append(clone._idle_timer)
            return speech(1)

    vid = voice()
    clone._release_when_idle()
    clone.CloneRenderer(lambda _c=None: Watches()).render("Hello.", vid, 200, threading.Event())
    assert seen == [None]


def test_the_model_cannot_be_deleted_during_a_render(model):  # noqa: F811
    holding, finish = threading.Event(), threading.Event()

    class Busy(FakeEngine):
        def speak(self, codes, text, cancel):
            holding.set()
            finish.wait(5)
            return speech(1)

    vid = voice()
    worker = threading.Thread(target=lambda: clone.CloneRenderer(lambda _c=None: Busy()).render(
        "Hello.", vid, 200, threading.Event()), daemon=True)
    worker.start()
    assert holding.wait(5)
    removed = threading.Event()
    threading.Thread(target=lambda: (clone.remove_model(), removed.set()), daemon=True).start()
    assert not removed.wait(0.3)
    assert clone.model_installed()
    finish.set()
    assert removed.wait(5)
    worker.join(5)
    assert not clone.model_installed()


def test_a_model_that_cannot_be_deleted_says_so(model, monkeypatch):  # noqa: F811
    monkeypatch.setattr(clone.shutil, "rmtree", lambda *a, **k: None)
    with pytest.raises(OSError, match="delete"):
        clone.remove_model()


def test_the_longest_recording_the_window_allows_is_accepted():
    """It stops by itself at the limit, so a recording of that length must not then be refused."""
    assert clone.check_recording(speech(clone.MAX_SECONDS + 0.5), RATE) == ""


# --- the window ---------------------------------------------------------------------------------
def blocked_window(qtbot, **kwargs):
    """A window whose recording check waits until the test lets it go."""
    go = threading.Event()

    def heard(consent):
        go.wait(5)
        return consent.text

    return window(qtbot, heard=heard, **kwargs), go


def start_build(qtbot, dlg):
    dlg.record_btn.click()
    dlg.record_btn.click()
    qtbot.waitUntil(lambda: dlg._working, timeout=1000)


def test_a_build_can_be_cancelled(model, qtbot):  # noqa: F811
    dlg, go = blocked_window(qtbot)
    start_build(qtbot, dlg)
    assert dlg.stop_btn.isVisible() or not dlg.isVisible()
    dlg.stop_btn.click()
    go.set()
    qtbot.waitUntil(lambda: not dlg._working, timeout=5000)
    assert clone.saved_voices() == [] and "ancelled" in dlg.status.text()


def test_closing_during_a_build_keeps_nothing(model, qtbot):  # noqa: F811
    dlg, go = blocked_window(qtbot)
    start_build(qtbot, dlg)
    dlg.close()
    go.set()
    qtbot.waitUntil(lambda: not dlg._work_thread.is_alive(), timeout=5000)
    assert clone.saved_voices() == []


def test_closing_after_the_voice_is_made_but_before_the_speed_check_ends_keeps_nothing(model, qtbot):  # noqa: F811
    from ttspython.ui.clone_dialog import CloneDialog

    engine = FakeEngine()
    checking, go = threading.Event(), threading.Event()

    def speed(_vid, _cancel=None):
        checking.set()
        go.wait(5)
        return 2.0

    dlg = CloneDialog(lambda _a: dlg._consent.text, recorder=FakeRecorder(), speed_check=speed,
                      builder=lambda n, c, a, r, h: clone.build_voice(n, c, a, r, h, engine))
    qtbot.addWidget(dlg)
    dlg.record_btn.click()
    dlg.record_btn.click()
    assert checking.wait(5)
    assert len(clone.saved_voices()) == 1
    dlg.close()
    go.set()
    qtbot.waitUntil(lambda: not dlg._work_thread.is_alive(), timeout=5000)
    assert clone.saved_voices() == []


def test_a_cancelled_whisper_download_is_stopped_too(model, qtbot):  # noqa: F811
    stopped = []
    dlg, go = blocked_window(qtbot, stop_transcribe=lambda: stopped.append(True))
    start_build(qtbot, dlg)
    dlg.stop_btn.click()
    go.set()
    qtbot.waitUntil(lambda: not dlg._working, timeout=5000)
    assert stopped == [True]


def test_the_in_use_check_asks_for_the_live_voice(model, qtbot, monkeypatch):  # noqa: F811
    say_yes(monkeypatch)
    vid = voice()
    live = ["v-zira"]
    dlg = window(qtbot, current_voice_id=lambda: live[0])
    live[0] = vid  # changed in the mini bar while this window is open
    dlg.remove_btn.click()
    assert os.path.isdir(clone.voice_folder(vid)) and "in use" in dlg.status.text()


def test_nothing_is_removed_while_speech_or_an_export_runs(model, qtbot, monkeypatch):  # noqa: F811
    say_yes(monkeypatch)
    vid = voice()
    dlg = window(qtbot, busy_speaking=lambda: "Stop speech first.")
    dlg.remove_btn.click()
    assert os.path.isdir(clone.voice_folder(vid)) and "Stop speech" in dlg.status.text()
    dlg.remove_model_btn.click()
    assert clone.model_installed() and "Stop speech" in dlg.status.text()


def test_removing_asks_first(model, qtbot, monkeypatch):  # noqa: F811
    vid = voice()
    dlg = window(qtbot)
    say_no(monkeypatch)
    dlg.remove_btn.click()
    assert os.path.isdir(clone.voice_folder(vid))
    dlg.remove_model_btn.click()
    assert clone.model_installed()
    say_yes(monkeypatch)
    dlg.remove_btn.click()
    assert not os.path.exists(clone.voice_folder(vid))


def test_a_failed_removal_does_not_say_removed(model, qtbot, monkeypatch):  # noqa: F811
    say_yes(monkeypatch)
    voice()
    dlg = window(qtbot)
    monkeypatch.setattr(clone.shutil, "rmtree", lambda *a, **k: None)
    dlg.remove_btn.click()
    assert "Could not" in dlg.status.text()


def test_closing_during_a_download_asks(data, qtbot, monkeypatch):  # noqa: F811
    go = threading.Event()

    def install(_progress, cancel):
        while not cancel.is_set() and not go.is_set():
            time.sleep(0.01)

    dlg = window(qtbot, installer=install)
    dlg.show()
    dlg.download_btn.click()
    say_no(monkeypatch)
    dlg.close()
    assert dlg.isVisible() and not dlg._cancel.is_set()
    say_yes(monkeypatch)
    cancel = dlg._cancel
    dlg.close()
    assert not dlg.isVisible() and cancel.is_set()
    go.set()


def test_enter_in_the_name_box_does_not_start_recording(model, qtbot):  # noqa: F811
    recorder = FakeRecorder()
    dlg = window(qtbot, recorder=recorder)
    dlg.show()
    dlg.name.setFocus()
    qtbot.keyClick(dlg.name, Qt.Key_Return)
    assert not recorder.running and dlg.isVisible()


def test_the_window_works_with_a_screen_reader(model, qtbot, monkeypatch):  # noqa: F811
    voice()
    dlg = window(qtbot)
    assert dlg.statement.focusPolicy() != Qt.NoFocus
    assert dlg.statement.textInteractionFlags() & Qt.TextSelectableByKeyboard
    assert dlg.statement.accessibleName()
    assert dlg.progress.accessibleName()
    assert dlg.name_label.buddy() is dlg.name
    assert dlg.list_label.buddy() is dlg.list
    announced = []
    monkeypatch.setattr(clone_dialog, "announce", lambda _widget, text: announced.append(text))
    dlg._set_status("Something happened.")
    assert announced == ["Something happened."]


def test_a_microphone_error_is_in_plain_words(model, qtbot):  # noqa: F811
    recorder = FakeRecorder()

    def fails(_device=None):
        raise OSError("Error opening InputStream: Invalid device [PaErrorCode -9996]")

    recorder.start = fails
    dlg = window(qtbot, recorder=recorder)
    dlg.record_btn.click()
    assert "unplugged" in dlg.status.text() and "PaErrorCode" not in dlg.status.text()


def test_the_microphone_is_looked_up_when_recording_starts(model, qtbot):  # noqa: F811
    recorder = FakeRecorder()
    device = [1]
    dlg = window(qtbot, recorder=recorder, input_device=lambda: device[0])
    device[0] = 7  # a rescan moved it after the window opened
    dlg.record_btn.click()
    assert recorder.device == 7


def test_the_window_says_what_the_recording_check_is_waiting_for(model, qtbot):  # noqa: F811
    dlg, go = blocked_window(qtbot)
    start_build(qtbot, dlg)
    dlg.model_status("Downloading small model... 10 of 484 MB")
    assert "10 of 484" in dlg.status.text()
    go.set()
    qtbot.waitUntil(lambda: not dlg._working, timeout=5000)
    dlg.model_status("Downloading small model... 11 of 484 MB")
    assert "11 of 484" not in dlg.status.text()


# --- in the app ---------------------------------------------------------------------------------
def test_audio_is_not_shut_down_under_a_voice_recording(app):  # noqa: F811
    app.open_clone_dialog()
    dlg = app._clone_dialog
    dlg._recorder = FakeRecorder()
    dlg.record_btn.click()
    assert app.rescan_devices() is False
    dlg.close()


def test_a_try_of_a_voice_ends_when_its_sentence_ends(app, qtbot):  # noqa: F811
    saved = app.settings["tts_voice_id"]
    vid = voice()
    app.open_clone_dialog()
    app._clone_dialog.hear_btn.click()
    assert app.speech.voice_id == vid
    qtbot.waitUntil(lambda: not app.speech.busy and app.speech.voice_id == saved, timeout=5000)
    app._clone_dialog.close()


def test_closing_the_window_does_not_stop_other_reading(app, qtbot):  # noqa: F811
    app.open_clone_dialog()
    dlg = app._clone_dialog
    app.speech.speak("Some other text being read for a while. " * 5)
    qtbot.waitUntil(lambda: app.speech.busy, timeout=2000)
    with qtbot.waitSignal(dlg.destroyed, timeout=2000):
        dlg.close()
    assert app.speech.busy
    app.speech.stop()


def test_settings_lists_the_voice_model(app):  # noqa: F811
    names = [n for n, _size in app.downloaded_models()]
    assert app.VOICE_MODEL_LABEL in names


def test_settings_will_not_delete_the_voice_model_while_it_is_needed(app, monkeypatch):  # noqa: F811
    vid = voice()
    app.settings.set("tts_voice_id", vid)
    assert "voice" in app.delete_model(app.VOICE_MODEL_LABEL)
    assert clone.model_installed()
    app.settings.set("tts_voice_id", "v-zira")
    assert app.delete_model(app.VOICE_MODEL_LABEL) == ""
    assert not clone.model_installed()


def test_quitting_stops_the_voice_window_work(app, qtbot):  # noqa: F811
    app.open_clone_dialog()
    dlg = app._clone_dialog
    dlg._recorder = FakeRecorder()
    dlg.record_btn.click()
    app._clone_dialog_quit()
    assert not dlg._recorder.running


# --- dictation ----------------------------------------------------------------------------------
def test_chinese_dictation_has_no_spaces_between_pieces():
    assert service._joined(["你好", "世界", "hello", "there"]) == "你好世界hello there"
    assert service._joined(["one", "", "two"]) == "one two"
    assert service._joined([]) == ""


def test_the_seam_only_looks_at_the_end_of_a_long_dictation():
    long_text = "word " * 50000 + "the week and"
    start = time.perf_counter()
    for _ in range(20):
        assert service._after_overlap(long_text, ["week", "and", "we"]) == (["we"], False)
    assert (time.perf_counter() - start) / 20 < 0.005


def naive_lines(cap):
    """The whole-text wrap the bubble is defined by."""
    from PySide6.QtGui import QFontMetrics

    settled, checked, preview_text = cap._parts
    words = ([(w, "text") for w in preview.units(f"{settled} {checked}")]
             + [(w, "preview") for w in preview.units(preview_text)])
    if not words:
        return []
    words[-1] = (words[-1][0], "newest")
    fm = QFontMetrics(cap.text.font())
    room, space = cap._room(), fm.horizontalAdvance(" ")
    lines, line, width = [], [], 0
    for word, kind in words:
        w = fm.horizontalAdvance(word)
        gap = space if line and preview.spaced(line[-1][0], word) else 0
        if line and width + gap + w > room:
            lines.append(line)
            line, width, gap = [], 0, 0
        width += gap + w
        line.append((word, kind))
    lines.append(line)
    return lines[-cap.LINES:]


def test_the_bubble_wraps_exactly_as_before_as_text_grows(qtbot):
    cap = LiveCaption()
    qtbot.addWidget(cap)
    settled = ""
    words = "the quick brown fox 你好世界 jumps over a lazy-dog and supercalifragilistic walks home".split()
    for i in range(300):
        settled = f"{settled} {words[i % len(words)]}".strip()
        if i % 7 == 0:
            cap.set_words(settled, words[i % 5], words[i % 3])
            assert cap.lines() == naive_lines(cap), i
    cap.set_words("a new dictation", "", "")  # the text no longer continues the old one
    assert cap.lines() == naive_lines(cap)
    cap.set_words("a new dictation that continues", "", "")
    assert cap.lines() == naive_lines(cap)
    cap.set_words("a new dictations", "", "")  # the last word itself changed
    assert cap.lines() == naive_lines(cap)
    cap.set_words("", "", "")
    assert cap.lines() == []


def test_the_bubble_does_not_slow_down_as_a_dictation_grows(qtbot):
    cap = LiveCaption()
    qtbot.addWidget(cap)
    text = "word " * 5000
    cap.set_words(text, "", "")
    start = time.perf_counter()
    for i in range(20):
        cap.set_words(text, f"checked {i}", "preview")
    assert (time.perf_counter() - start) / 20 < 0.01


def test_a_stale_cancel_does_not_fail_the_recording_check():
    from ttspython.core.stt.service import ModelCache, SttService

    class Model:
        def transcribe(self, audio, **kwargs):
            return [types.SimpleNamespace(text="hello")], None

    def downloader(name, progress, cancel):
        if cancel.is_set():
            raise service.DownloadCancelled()
        return name

    svc = SttService(cache=ModelCache(loader=lambda _n: Model(), downloader=downloader), auto_unload=False)
    try:
        svc.cache.cancel_download.set()  # a dictation's download was cancelled earlier
        assert svc.transcribe_once(np.zeros(16000, dtype=np.float32)) == "hello"
    finally:
        svc.shutdown()


def test_the_recording_check_follows_unload_after_each_dictation():
    from ttspython.core.stt.service import ModelCache, SttService

    class Model:
        def transcribe(self, audio, **kwargs):
            return [], None

    svc = SttService(cache=ModelCache(loader=lambda _n: Model()), unload_when_idle=True)
    try:
        svc.transcribe_once(np.zeros(16000, dtype=np.float32))
        assert svc.cache.loaded_name is None
    finally:
        svc.shutdown()


# --- models -------------------------------------------------------------------------------------
class Hub:
    def __init__(self, local=None):
        self.calls = []
        self.local = local or {}

    def __call__(self, repo, **kwargs):
        self.calls.append((repo, kwargs))
        if kwargs.get("local_files_only"):
            key = kwargs.get("revision")
            if key in self.local:
                return self.local[key]
            raise OSError("not in the cache")
        return "C:/downloaded"


@pytest.fixture
def hub(monkeypatch):
    import huggingface_hub

    fake = Hub()
    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake)
    monkeypatch.setattr(service, "model_complete", lambda _folder: True)
    return fake


def test_every_model_is_pinned_to_a_commit():
    assert set(service.WHISPER_REVISIONS) == set(service.WHISPER_REPOS)
    assert all(re.fullmatch(r"[0-9a-f]{40}", sha) for sha in service.WHISPER_REVISIONS.values())


def test_a_new_download_asks_for_the_pinned_commit(hub):
    assert service.download_whisper("small") == "C:/downloaded"
    repo, kwargs = hub.calls[-1]
    assert repo == service.WHISPER_REPOS["small"] and kwargs["revision"] == service.WHISPER_REVISIONS["small"]


def test_a_model_downloaded_by_an_older_version_is_kept(hub):
    hub.local[None] = "C:/older"
    assert service.download_whisper("small") == "C:/older"
    assert all(k.get("local_files_only") for _r, k in hub.calls)  # nothing was downloaded


def test_a_folder_named_like_a_model_is_not_loaded_as_the_model(hub, tmp_path, monkeypatch):
    os.makedirs(tmp_path / "small")
    monkeypatch.chdir(tmp_path)
    assert service.download_whisper("small") == "C:/downloaded"


def test_the_renamed_turbo_model_comes_from_its_new_home():
    assert service.WHISPER_REPOS["large-v3-turbo"].startswith("dropbox-dash/")


def test_a_turbo_model_under_its_old_name_is_still_listed_and_deleted():
    freed = []
    revision = types.SimpleNamespace(commit_hash="abc")
    old = types.SimpleNamespace(repo_id="mobiuslabsgmbh/faster-whisper-large-v3-turbo", size_on_disk=5, revisions=[revision])

    class Info:
        repos = [old]

        def delete_revisions(self, *hashes):
            freed.extend(hashes)
            return types.SimpleNamespace(execute=lambda: None, expected_freed_size=5)

    assert service.downloaded_models(scan=lambda: Info()) == [("large-v3-turbo", 5)]
    assert service.delete_model("large-v3-turbo", scan=lambda: Info()) == 5
    assert freed == ["abc"]


# --- privacy ------------------------------------------------------------------------------------
@pytest.mark.skipif(os.name != "nt", reason="Windows clipboard formats")
def test_copied_dictation_stays_out_of_clipboard_history(qtbot):
    injector = inject.TextInjector()
    injector.copy_only("private words")
    mime = QGuiApplication.clipboard().mimeData()
    assert mime.text() == "private words"
    assert inject.is_private_clipboard(mime)
    QGuiApplication.clipboard().clear()


def private_mime(fmt, value=b"\x00\x00\x00\x00"):
    mime = QMimeData()
    mime.setText("my password")
    mime.setData(fmt, value)
    return mime


def test_what_a_password_manager_copies_counts_as_private():
    assert inject.is_private_clipboard(private_mime('application/x-qt-windows-mime;value="ExcludeClipboardContentFromMonitorProcessing"'))
    assert inject.is_private_clipboard(private_mime("x-kde-passwordManagerHint", b"secret"))
    assert not inject.is_private_clipboard(private_mime("x-kde-passwordManagerHint", b"other"))
    plain = QMimeData()
    plain.setText("ordinary text")
    assert not inject.is_private_clipboard(plain)
    assert not inject.is_private_clipboard(None)


def test_the_clipboard_watcher_leaves_passwords_alone(app, monkeypatch):  # noqa: F811
    app.settings.set("clipboard_monitor", True)
    spoken = []
    before = len(app.queue)
    with monkeypatch.context() as m:
        m.setattr(QGuiApplication, "clipboard", staticmethod(lambda: types.SimpleNamespace(
            text=lambda: "my password",
            mimeData=lambda: private_mime('application/x-qt-windows-mime;value="ExcludeClipboardContentFromMonitorProcessing"'))))
        m.setattr(app.speech, "speak", lambda *a, **k: spoken.append(a) or True)
        app._on_clipboard()
    assert spoken == [] and len(app.queue) == before


def test_saved_files_are_only_for_this_user(tmp_path, monkeypatch):
    modes = []
    real = os.open

    def spy(path, flags, mode=0o777, **kwargs):
        modes.append(mode)
        return real(path, flags, mode, **kwargs)

    monkeypatch.setattr(os, "open", spy)
    settings_mod.write_json_atomic(str(tmp_path / "queue.json"), {"a": 1})
    assert modes == [0o600]
    assert (tmp_path / "queue.json").read_text(encoding="utf-8").strip().startswith("{")


def test_the_voices_folder_is_only_for_this_user(model, monkeypatch):  # noqa: F811
    modes = {}
    real = os.makedirs

    def spy(path, mode=0o777, exist_ok=False):
        modes[os.path.basename(str(path))] = mode
        real(path, mode, exist_ok)

    monkeypatch.setattr(clone.os, "makedirs", spy)
    voice()
    assert modes["cloned-voices"] == 0o700


def test_a_temp_folder_owned_by_someone_else_is_not_used(tmp_path, monkeypatch):
    from ttspython.ui import theme_manager

    monkeypatch.setattr(os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(os, "lstat", lambda _p: types.SimpleNamespace(st_uid=2000, st_mode=0o40700))
    assert not theme_manager._is_private_folder(str(tmp_path))
    monkeypatch.setattr(os, "lstat", lambda _p: types.SimpleNamespace(st_uid=1000, st_mode=0o40777))
    assert not theme_manager._is_private_folder(str(tmp_path))
    monkeypatch.setattr(os, "lstat", lambda _p: types.SimpleNamespace(st_uid=1000, st_mode=0o40700))
    assert theme_manager._is_private_folder(str(tmp_path))


@pytest.mark.parametrize("bad", ["piper:../../evil", r"piper:..\evil", "piper:C:/evil", r"piper:\\server\share\evil"])
def test_a_piper_voice_id_cannot_point_outside_its_folder(bad, monkeypatch):
    monkeypatch.setattr(piper, "program_installed", lambda: True)
    monkeypatch.setattr(piper.os.path, "isfile", lambda _p: True)
    monkeypatch.setattr(piper, "_Process", lambda *a: pytest.fail("a program was started"))
    with pytest.raises(RuntimeError, match="not downloaded"):
        piper.PiperRenderer().render("Hello.", bad, 200, threading.Event())


# --- release and install ------------------------------------------------------------------------
def workflow():
    with open(os.path.join(ROOT, ".github", "workflows", "build.yml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_every_action_is_pinned_to_a_commit():
    uses = [step["uses"] for job in workflow()["jobs"].values() for step in job["steps"] if "uses" in step]
    assert uses and all(re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", u) for u in uses), uses


def test_only_the_release_step_can_write_to_the_repo():
    flow = workflow()
    assert flow["permissions"] == {"contents": "read"}
    assert "permissions" not in flow["jobs"]["build"]
    assert flow["jobs"]["release"]["permissions"] == {"contents": "write"}
    assert flow["jobs"]["release"]["needs"] == "build"
    checkout = next(s for s in flow["jobs"]["build"]["steps"] if "checkout" in s.get("uses", ""))
    assert checkout["with"]["persist-credentials"] is False


def test_a_release_publishes_checksums():
    steps = workflow()["jobs"]["release"]["steps"]
    assert any("sha256sum" in (s.get("run") or "") for s in steps)
    publish = next(s for s in steps if "gh-release" in s.get("uses", ""))
    assert publish["with"]["fail_on_unmatched_files"] is True


def installer_script():
    with open(os.path.join(ROOT, "packaging", "windows", "TTSPython.iss"), encoding="utf-8") as f:
        return f.read()


def test_the_installer_stops_if_the_app_is_still_running():
    script = installer_script()
    prepare = script[script.index("function PrepareToInstall"):]
    assert "FileInUse" in prepare[:prepare.index("end;")] and "still running" in prepare[:prepare.index("end;")]
    assert "InitializeUninstall" in script


def test_uninstalling_offers_to_remove_private_data_and_defaults_to_no():
    script = installer_script()
    assert "MB_DEFBUTTON2" in script and "DelTree" in script and "DELETEUSERDATA" in script


def test_the_linux_uninstaller_offers_it_too():
    with open(os.path.join(ROOT, "packaging", "linux", "uninstall.sh"), encoding="utf-8") as f:
        script = f.read()
    assert "--delete-data" in script and "$HOME/.local/share}/ttspython" in script

