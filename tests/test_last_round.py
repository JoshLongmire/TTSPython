"""The last round before 5.1: spoken commands, the update notice, the retry of a babbled sentence."""
from __future__ import annotations

import pytest

from fakes import wait_for
from test_stt_service import FakeRecorder, FakeTimer, Segment
from ttspython.core.stt.service import ModelCache, SttService, SttState

try:
    from ttspython.core.stt import commands
except ImportError:  # for measuring these tests on the code from before them
    commands = None


# --- spoken commands ------------------------------------------------------------------------------
# What Whisper writes for each way of saying it: no punctuation, its own punctuation, commas for pauses.
SPOKEN = [
    ("Buy milk period new line call Sam question mark.", "Buy milk.\nCall Sam?"),
    ("Buy milk. Period. New line. Call Sam? Question mark.", "Buy milk.\nCall Sam?"),
    ("Buy milk, period, new line, call Sam, question mark.", "Buy milk.\nCall Sam?"),
    ("Hello comma how are you question mark", "Hello, how are you?"),
    ("Dear Sam colon new paragraph thanks for the help exclamation mark", "Dear Sam:\n\nThanks for the help!"),
    ("Wow exclamation point", "Wow!"),
    ("Stop full stop", "Stop."),
    ("First we eat semicolon then we sleep.", "First we eat; then we sleep."),
    ("Says this semicolon here.", "Says this semicolon here."),  # after "this" it is the word
    ("I like cats. Delete that. I like dogs.", "I like dogs."),
    ("One. Two. Scratch that. Three.", "One. Three."),
    ("Buy milk, new line, call Sam.", "Buy milk\nCall Sam."),
    ("First line. New line. Second line. New line.", "First line.\nSecond line.\n"),
]
# Words that only look like commands.
NOT_COMMANDS = [
    "In that period of time, we grew.",
    "We launched a new line of shoes.",
    "Please delete that file.",
    "Put a comma there.",
    "The question mark is missing.",
    "Plain text with nothing in it.",
    "",
]


@pytest.mark.parametrize("heard, typed", SPOKEN)
def test_spoken_commands_are_carried_out(heard, typed):
    assert commands.apply_commands(heard) == typed


@pytest.mark.parametrize("heard", NOT_COMMANDS)
def test_words_that_only_look_like_commands_stay(heard):
    assert commands.apply_commands(heard) == heard


def test_delete_that_alone_leaves_nothing():
    assert commands.apply_commands("Delete that.") == ""


def test_the_caption_shows_line_breaks_as_marks():
    assert commands.for_caption("Buy milk new line call Sam new paragraph done") == "Buy milk ↵ Call Sam ¶ Done"


class SaidModel:
    def __init__(self, text):
        self.text = text

    def transcribe(self, audio, **kwargs):
        return [Segment(self.text, end=1.0)], None


def dictate(text, **kw):
    svc = SttService(recorder=FakeRecorder(), cache=ModelCache(lambda _n: SaidModel(text)), timer_factory=FakeTimer, **kw)
    svc.live = False
    got, status = [], []
    svc.events.on("transcript_ready", lambda t, _target: got.append(t))
    svc.events.on("model_status", status.append)
    svc.toggle("editor")
    svc.toggle()
    assert wait_for(lambda: svc.state is SttState.IDLE and (got or status))
    svc.shutdown()
    return got, status


def test_dictation_types_what_the_commands_mean():
    got, _ = dictate("buy milk period new line call Sam question mark")
    assert got == ["Buy milk.\nCall Sam?"]


def test_commands_can_be_switched_off():
    svc = SttService(recorder=FakeRecorder(), cache=ModelCache(lambda _n: SaidModel("buy milk period")), timer_factory=FakeTimer)
    svc.live = False
    svc.spoken_commands = False
    got = []
    svc.events.on("transcript_ready", lambda t, _target: got.append(t))
    svc.toggle("editor")
    svc.toggle()
    assert wait_for(lambda: got)
    svc.shutdown()
    assert got == ["Buy milk period."]


def test_commands_are_english_only():
    got, _ = dictate("compra leche period", language="es")
    assert got == ["Compra leche period."]


def test_nothing_is_typed_after_deleting_everything():
    got, status = dictate("delete that")
    assert got == []
    assert "Nothing left to type" in status


def test_the_setting_is_on_by_default_and_kept():
    from ttspython.core.settings import DEFAULTS, normalize

    assert DEFAULTS["stt_spoken_commands"] is True
    assert normalize({"stt_spoken_commands": False})["stt_spoken_commands"] is False


# --- the update notice ----------------------------------------------------------------------------
import json  # noqa: E402

try:
    from ttspython.core import updates
except ImportError:
    updates = None


def release(tag, **extra):
    info = {"tag_name": tag, "draft": False, "prerelease": False,
            "html_url": f"https://github.com/JoshLongmire/TTSPython/releases/tag/{tag}", **extra}
    return lambda url, agent: json.dumps(info).encode()


@pytest.mark.parametrize("tag, found", [("v5.2.0", "5.2.0"), ("v6.0", "6.0"), ("v5.1.0", None), ("v5.0.9", None),
                                        ("v5.2.0-beta", None), ("nightly", None), (None, None)])
def test_only_a_newer_release_counts(tag, found):
    result = updates.latest_release("5.1.0", get=release(tag))
    assert (result[0] if result else None) == found


def test_drafts_and_pre_releases_do_not_count():
    assert updates.latest_release("5.1.0", get=release("v9.0.0", draft=True)) is None
    assert updates.latest_release("5.1.0", get=release("v9.0.0", prerelease=True)) is None


def test_the_link_only_ever_goes_to_this_projects_releases():
    found = updates.latest_release("5.1.0", get=release("v5.2.0", html_url="https://example.com/evil"))
    assert found == ("5.2.0", updates.RELEASES_URL)


def test_what_is_sent_is_only_the_version():
    seen = []

    def get(url, agent):
        seen.append((url, agent))
        return release("v5.1.0")(url, agent)

    updates.latest_release("5.1.0", get=get)
    assert seen == [(updates.API_URL, "TTSPython/5.1.0")]
    with pytest.raises(ValueError):
        updates._get("http://api.github.com/x", "TTSPython/5.1.0")


def test_an_endless_answer_is_refused():
    with pytest.raises(ValueError):
        updates.latest_release("5.1.0", get=lambda u, a: b"x" * (updates.MAX_BYTES + 1))


def test_once_a_day():
    now = 1_000_000_000
    assert updates.due(0, now)
    assert not updates.due(now - 3600, now)
    assert updates.due(now - 25 * 3600, now)
    assert updates.due(now + 3600, now)  # a clock set back
    assert updates.due("garbage", now)


def test_never_in_tests_or_the_self_test(monkeypatch):
    assert updates.disabled()  # conftest
    monkeypatch.delenv(updates.OFF_ENV)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("TTSPYTHON_SELFTEST", "x.json")
    assert updates.disabled()


def test_update_settings_are_kept_and_cleaned():
    from ttspython.core.settings import DEFAULTS, normalize

    assert DEFAULTS["update_check"] is None
    good = normalize({"update_check": True, "update_last_check": 5.5, "update_skipped": "5.2.0"})
    assert (good["update_check"], good["update_last_check"], good["update_skipped"]) == (True, 5.5, "5.2.0")
    bad = normalize({"update_check": "yes", "update_last_check": -1, "update_skipped": 3})
    assert (bad["update_check"], bad["update_last_check"], bad["update_skipped"]) == (None, 0, "")


def controller(qtbot, tmp_path, answer=None, tag="v5.2.0"):
    from test_ui import make_controller

    app = make_controller(qtbot, tmp_path, {"update_check": answer} if answer is not None else None)
    calls = []

    def get(url, agent):
        calls.append(url)
        return release(tag)(url, agent)

    app._update_get = get
    app.calls = calls
    return app


def test_asked_once_and_nothing_is_fetched_before_a_yes(qtbot, tmp_path):
    app = controller(qtbot, tmp_path)
    assert app.start_update_check() is False
    assert app.window.notice.isVisible() and app.window.notice.key == "update_ask"
    assert app.calls == []
    no = [b for b in app.window.notice.buttons() if b.text() == "No thanks"][0]
    no.click()
    assert app.settings["update_check"] is False
    assert not app.window.notice.isVisible()
    assert app.start_update_check() is False and app.calls == []
    assert not app.window.notice.isVisible()  # not asked again


def test_a_yes_checks_and_shows_the_news(qtbot, tmp_path):
    app = controller(qtbot, tmp_path)
    app.start_update_check()
    [b for b in app.window.notice.buttons() if b.text() == "Yes, check"][0].click()
    qtbot.waitUntil(lambda: app.window.notice.key == "update", timeout=3000)
    assert app.settings["update_check"] is True
    assert "TTSPython 5.2.0 is available" in app.window.notice.label.text()
    assert app.calls == [updates.API_URL]
    assert app.start_update_check() is False  # once a day
    assert app.calls == [updates.API_URL]


def test_a_skipped_version_is_not_shown_again(qtbot, tmp_path):
    app = controller(qtbot, tmp_path, answer=True)
    assert app.start_update_check()
    qtbot.waitUntil(lambda: app.window.notice.key == "update", timeout=3000)
    [b for b in app.window.notice.buttons() if b.text() == "Skip this version"][0].click()
    assert app.settings["update_skipped"] == "5.2.0"
    assert app.start_update_check(force=True)
    qtbot.waitUntil(lambda: not app._update_running, timeout=3000)
    assert not app.window.notice.isVisible()


def test_no_news_when_up_to_date_or_offline(qtbot, tmp_path):
    app = controller(qtbot, tmp_path, answer=True, tag="v5.1.0")
    assert app.start_update_check()
    qtbot.waitUntil(lambda: not app._update_running, timeout=3000)
    assert not app.window.notice.isVisible()

    def offline(url, agent):
        raise OSError("no network")

    app._update_get = offline
    assert app.start_update_check(force=True)
    qtbot.waitUntil(lambda: not app._update_running, timeout=3000)
    assert not app.window.notice.isVisible()


def test_the_settings_switch_keeps_not_asked_as_not_asked(qtbot, tmp_path):
    from ttspython.ui.settings_dialog import SettingsDialog

    app = controller(qtbot, tmp_path)
    app.open_settings("general")
    dialog = next(w for w in qtbot_widgets() if isinstance(w, SettingsDialog))
    assert dialog.form_values()["update_check"] is None
    dialog.update_check.setChecked(True)
    assert dialog.form_values()["update_check"] is True
    dialog.done(0)


def qtbot_widgets():
    from PySide6.QtWidgets import QApplication

    return QApplication.topLevelWidgets()


# --- found by walking through the app as a new user ------------------------------------------------
def test_the_preview_waits_for_whispers_first_download(monkeypatch):
    import threading
    import time

    from ttspython.core.stt import preview as preview_mod

    order = []
    loaded = threading.Event()

    def slow_loader(name):
        time.sleep(0.4)  # downloading
        order.append("whisper ready")
        loaded.set()
        return SaidModel("hello")

    monkeypatch.setattr(preview_mod, "available", lambda: True)
    monkeypatch.setattr(preview_mod, "installed", lambda language="en": False)
    monkeypatch.setattr(preview_mod, "install", lambda progress, language="en": order.append("preview download"))
    svc = SttService(recorder=FakeRecorder(), cache=ModelCache(slow_loader), timer_factory=FakeTimer)
    svc.preview_enabled = True
    svc.toggle("editor")
    assert wait_for(lambda: len(order) == 2, timeout=5)
    svc.cancel()
    svc.shutdown()
    assert order == ["whisper ready", "preview download"]


def test_download_steps_do_not_pop_up_over_the_listen_panel(qtbot, tmp_path, monkeypatch):
    from test_ui import make_controller

    app = make_controller(qtbot, tmp_path)
    monkeypatch.setattr(app, "_window_in_front", lambda: True)
    for done in (1, 2, 3):
        app._on_model_status(f"Downloading the small model... {done} of 464 MB (first use only)")
    assert not app.window.toast.isVisible()
    assert "3 of 464 MB" in app.window.status_label.text()


# --- run-on speech in your own voice -------------------------------------------------------------------
import threading  # noqa: E402

import numpy as np  # noqa: E402

from test_clone import CODES, fake_engine  # noqa: E402
from ttspython.core.tts import clone  # noqa: E402


def engine_with_tries(lengths):
    """Each try of a piece stops by itself after the next number of frames in lengths (None: never)."""
    from test_clone import Graph

    engine = fake_engine()
    tries = iter(lengths)
    left = {"n": None}
    real = engine._piece_blocks

    def frame(_feeds):
        if left["n"] is None:
            go = True
        else:
            left["n"] -= 1
            go = left["n"] >= 0
        return [np.asarray([go]), np.arange(16, dtype=np.int32)]

    engine._frame = Graph(["should_continue", "frame_token_ids"], frame)

    def piece(codes, ids, cancel, limit=None):
        left["n"] = next(tries)
        yield from real(codes, ids, cancel, limit)

    engine._piece_blocks = piece
    return engine


def test_a_short_reply_that_runs_on_is_made_again_before_it_is_heard():
    engine = engine_with_tries([None, 7])  # first try runs on, the second ends by itself after 7 frames
    blocks = list(engine.speak_blocks(CODES, "Okay.", threading.Event(), pace=200))
    assert sum(b.size for b, _ in blocks) == 7 * 3840
    assert engine.babble_retries == 1


def test_a_word_that_keeps_running_on_is_cut_where_it_should_end():
    engine = engine_with_tries([None, None, None])
    audio = engine.speak(CODES, "Okay.", threading.Event(), pace=200)
    frames = min(clone.babble_frames("Okay.", 200), clone.frame_limit(len(engine.tokens("Okay."))))
    assert audio.size == frames * 3840 + int(clone._FADE_SECONDS * engine.rate)
    assert audio.size / engine.rate < 1.5  # was up to 2.2 s of "Okay. Oh, okay."
    assert abs(audio[-1]) < 1e-6  # faded, no click


def test_a_long_sentence_is_never_said_twice_while_it_plays():
    words = "one two three four five six seven eight nine ten"
    engine = engine_with_tries([None, 5])
    blocks = list(engine.speak_blocks(CODES, words, threading.Event(), pace=200))
    frames = min(clone.babble_frames(words, 200), clone.frame_limit(len(engine.tokens(words))))
    assert sum(b.size for b, _ in blocks) == frames * 3840 + int(clone._FADE_SECONDS * engine.rate)
    assert engine.babble_retries == 0


def test_a_file_gets_every_piece_made_again_if_it_runs_on():
    words = "one two three four five six seven eight nine ten"
    engine = engine_with_tries([None, 30])
    audio = engine.speak(CODES, words, threading.Event(), pace=200)
    assert audio.size == 30 * 3840
    assert engine.babble_retries == 1


def test_the_limit_follows_the_voices_pace_and_leaves_room_for_normal_speech():
    assert clone.babble_frames("one two three four", 110) > clone.babble_frames("one two three four", 220)
    # The slowest normal sentence measured: 0.395 s a word at a voice pace of 0.30 s a word (200 wpm).
    words = " ".join(["w"] * 16)
    assert clone.babble_frames(words, 200) * clone._FRAME_SECONDS > 16 * 0.395 + 1.0
    # A lone word: normal takes up to 0.72 s, run-on took 1.3 to 2.3 s.
    assert 0.72 + 0.3 < clone.babble_frames("Okay.", 200) * clone._FRAME_SECONDS < 1.5


@pytest.mark.parametrize("text, at_least", [("Call me at 555-1212.", 8), ("早上的火车又晚点了，所以大家都在寒冷的站台上等着。", 14),
                                             ("朝の電車がまた遅れたので", 7), ("Okay.", 1)])
def test_words_are_counted_as_they_are_said(text, at_least):
    assert at_least <= clone.spoken_words(text) <= at_least * 1.5 + 1


def test_the_voice_maker_says_when_there_are_no_voices_yet(qtbot):
    from ttspython.ui.clone_dialog import CloneDialog

    dlg = CloneDialog(lambda _a: "", recorder=object())
    qtbot.addWidget(dlg)
    dlg.show()
    assert dlg.list.count() == 0
    assert dlg.empty.isVisible() and "None yet" in dlg.empty.text()


def test_long_chinese_and_japanese_text_is_split_into_pieces_the_model_can_say():
    encode = list  # a character a token, near enough for Chinese
    zh = "早上的火车又晚点了，所以大家都在寒冷的站台上等着。今晚离开的时候，请记得关灯并锁好后门。" * 4
    pieces = clone.split_tokens(zh, encode, limit=40)
    assert len(pieces) > 1 and all(len(p) <= 40 for p in pieces)
    assert "".join(pieces) == zh  # nothing lost, and no spaces put in
    no_marks = "一二三四五六七八九十" * 10
    assert all(len(p) <= 40 for p in clone.split_tokens(no_marks, encode, limit=40))


def test_english_is_still_split_at_sentence_ends_with_spaces():
    text = "One two three. Four five six. Seven eight nine."
    assert clone.split_tokens(text, str.split, limit=4) == ["One two three.", "Four five six.", "Seven eight nine."]


def test_a_notice_in_the_window_never_covers_the_listen_panel(qtbot, tmp_path):
    from PySide6.QtCore import QPoint

    from test_ui import make_controller

    app = make_controller(qtbot, tmp_path)
    app.set_mode("stt")
    qtbot.waitUntil(app.window.listen_panel.isVisible)
    app.window.show_toast("Downloading the small model... 3 of 464 MB (first use only)")
    root = app.window.centralWidget()
    toast = app.window.toast.geometry()
    panel_top = app.window.listen_panel.mapTo(root, QPoint(0, 0)).y()
    assert toast.bottom() < panel_top


# --- startup -----------------------------------------------------------------------------------------
def test_nothing_slow_is_imported_on_the_way_to_the_first_window():
    import subprocess
    import sys

    code = ("import sys, ttspython.app, ttspython.ui.app_controller, ttspython.core.diagnostics as d, tempfile; "
            "d.start(tempfile.mkdtemp(), crashes=False); "
            "print(sorted(m for m in ('urllib.request', 'logging.handlers', 'tarfile', 'hashlib', 'ttspython.core.tts.clone') "
            "if m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out == "[]"


def test_the_error_log_file_is_only_made_by_an_error(tmp_path):
    import logging

    from ttspython.core import diagnostics

    folder = tmp_path / "logs"
    handler = diagnostics.start(str(folder), crashes=False)
    try:
        assert not (folder / diagnostics.LOG_NAME).exists()
        logging.getLogger("ttspython.test").error("one problem")
        handler.flush()
        assert "one problem" in (folder / diagnostics.LOG_NAME).read_text(encoding="utf-8")
    finally:
        diagnostics.stop()


# --- found by the independent review ---------------------------------------------------------------
@pytest.mark.parametrize("heard, typed", [
    ("I like that period", "I like that."),
    ("Call her period new line", "Call her.\n"),
    ("Step one period step two period", "Step one. Step two."),
    ("Line one new line line two", "Line one\nLine two"),
    ("Tell them no period", "Tell them no."),
    ("Buy milk period delete that", ""),
    ("Hello. Buy milk new line delete that", "Hello."),
    ("Who is it question mark delete that, okay", "Okay"),
])
def test_commands_after_pronouns_and_spoken_marks(heard, typed):
    assert commands.apply_commands(heard) == typed


@pytest.mark.parametrize("heard", ["Her period was late.", "Put a comma there.", "In that period of time, we grew."])
def test_command_words_followed_by_more_words_after_a_determiner_stay_words(heard):
    assert commands.apply_commands(heard) == heard


class HeardAs(SaidModel):
    def __init__(self, text, language):
        super().__init__(text)
        self.language = language

    def transcribe(self, audio, **kwargs):
        import types

        return [Segment(self.text, end=1.0)], types.SimpleNamespace(language=self.language)


@pytest.mark.parametrize("text, language, typed", [
    ("Ai sensi del comma 3 dell'articolo 5.", "it", "Ai sensi del comma 3 dell'articolo 5."),
    ("Le colon est arrivé hier.", "fr", "Le colon est arrivé hier."),
    ("buy milk period", "en", "Buy milk."),
])
def test_with_auto_detect_commands_follow_the_language_heard(text, language, typed):
    svc = SttService(recorder=FakeRecorder(), cache=ModelCache(lambda _n: HeardAs(text, language)), timer_factory=FakeTimer,
                     language="auto")
    svc.live = False
    got = []
    svc.events.on("transcript_ready", lambda t, _target: got.append(t))
    svc.toggle("editor")
    svc.toggle()
    assert wait_for(lambda: got)
    svc.shutdown()
    assert got == [typed]


def test_a_long_link_is_not_read_letter_by_letter():
    pieces = clone.split_tokens("https://example.com/" + "a" * 60, list, limit=20)
    assert all(" " not in p for p in pieces)
    assert "".join(pieces) == "https://example.com/" + "a" * 60


def test_mixed_chinese_and_english_keeps_its_spaces():
    pieces = clone.split_tokens("Hello, 世界 and more words here.", list, limit=12)
    assert " ".join(pieces) == "Hello, 世界 and more words here."


def test_an_unwritable_error_log_never_breaks_the_code_that_logged(tmp_path, monkeypatch):
    import logging

    from ttspython.core import diagnostics

    monkeypatch.setattr(logging, "raiseExceptions", False)  # as in the packaged app
    folder = tmp_path / "logs"
    diagnostics.start(str(folder), crashes=False)
    try:
        (folder / diagnostics.LOG_NAME).mkdir()  # the log's name is taken by a folder: it cannot be opened
        logging.getLogger("ttspython.test").error("first")  # must not raise
        logging.getLogger("ttspython.test").error("second")
    finally:
        diagnostics.stop()


def test_an_answer_given_while_settings_is_open_is_not_undone_by_save(qtbot, tmp_path):
    from ttspython.ui.settings_dialog import SettingsDialog

    app = controller(qtbot, tmp_path)
    app.open_settings("general")
    dialog = next(w for w in qtbot_widgets() if isinstance(w, SettingsDialog))
    app.start_update_check()
    [b for b in app.window.notice.buttons() if b.text() == "No thanks"][0].click()
    assert not dialog.update_check.isChecked()
    assert dialog.form_values()["update_check"] is False
    dialog.done(0)


def test_a_dictation_ending_in_a_new_line_leaves_no_blank_line(qtbot):
    from ttspython.ui.editor import SpeechTextEdit

    editor = SpeechTextEdit()
    qtbot.addWidget(editor)
    editor.setPlainText("Notes")
    cursor = editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    editor.setTextCursor(cursor)
    editor.add_dictation("Buy milk.\n")
    assert editor.toPlainText() == "Notes\nBuy milk.\n"


# --- the quick finish: text typed at Stop without waiting for the pass in flight -------------------------
class SlowModel:
    """Each pass takes delay seconds and hears "word" for each second of audio."""

    def __init__(self, delay):
        self.delay = delay
        self.passes = 0

    def transcribe(self, audio, **kwargs):
        import time as _time

        self.passes += 1
        _time.sleep(self.delay)
        return [Segment(" ".join(["word"] * max(1, int(audio.size / 16000))), end=audio.size / 16000)], None


class FixedRecorder:
    """Speech (a loud tone) for speech_s seconds, then quiet, all there from the start; or growing."""
    sample_rate = capture_rate = 16000
    level = 0.3
    on_limit = on_block = on_lost = None
    spool = spool_folder = None

    def __init__(self, speech_s, quiet_s, more_speech_after=None):
        import numpy as _np

        t = _np.arange(int(16000 * speech_s)) / 16000
        self.audio = _np.concatenate([(0.3 * _np.sin(2 * _np.pi * 220 * t)).astype(_np.float32),
                                      _np.zeros(int(16000 * quiet_s), _np.float32)])
        self.more = more_speech_after

    def start(self, device=None):
        import time as _time

        self.t0 = _time.monotonic()

    def _now(self):
        import time as _time

        import numpy as _np

        if self.more is not None and _time.monotonic() - self.t0 > self.more:
            t = _np.arange(16000) / 16000
            return _np.concatenate([self.audio, (0.3 * _np.sin(2 * _np.pi * 300 * t)).astype(_np.float32)])
        return self.audio

    def snapshot(self, start=0):
        return self._now()[start:]

    def stop(self):
        return self._now()


def quick_service(recorder, delay):
    import time as _time

    model = SlowModel(delay)
    svc = SttService(recorder=recorder, cache=ModelCache(lambda _n: model), timer_factory=FakeTimer)
    svc.preview_enabled = False
    got = []
    svc.events.on("transcript_ready", lambda text, _t: got.append((_time.monotonic(), text)))
    return svc, model, got


def test_after_a_pause_the_text_is_typed_without_waiting_for_the_pass_in_flight():
    import time as _time

    svc, model, got = quick_service(FixedRecorder(2.0, 1.0), delay=1.0)
    svc.start("editor")
    assert wait_for(lambda: svc._last_pass is not None, timeout=5)  # one pass done, the next one under way
    assert wait_for(lambda: model.passes >= 2, timeout=5)
    stopped = _time.monotonic()
    svc.stop()
    assert wait_for(lambda: got, timeout=5)
    assert got[0][0] - stopped < 0.5  # a pass takes 1 s: before, this waited for it
    assert wait_for(lambda: svc.state is SttState.IDLE, timeout=5)
    _time.sleep(0.2)
    svc.shutdown()
    assert [text for _t, text in got] == ["Word word word."]  # typed once


def test_words_said_after_the_last_pass_are_never_skipped():
    import time as _time

    svc, model, got = quick_service(FixedRecorder(1.0, 0.0, more_speech_after=0.3), delay=0.8)
    svc.start("editor")
    assert wait_for(lambda: svc._last_pass is not None, timeout=5)
    _time.sleep(0.4)  # more speech arrives after that pass
    svc.stop()
    assert wait_for(lambda: svc.state is SttState.IDLE, timeout=10)
    svc.shutdown()
    assert len(got) == 1 and got[0][1] == "Word word."  # from the final pass, which heard the new second


def test_cancel_right_after_stop_types_nothing_twice():
    import time as _time

    svc, model, got = quick_service(FixedRecorder(2.0, 1.0), delay=0.6)
    svc.start("editor")
    assert wait_for(lambda: svc._last_pass is not None, timeout=5)
    svc.stop()
    svc.cancel()
    assert wait_for(lambda: svc.state is SttState.IDLE, timeout=5)
    _time.sleep(0.2)
    svc.shutdown()
    assert len(got) <= 1


# --- startup -----------------------------------------------------------------------------------------------
def test_the_speech_engine_starts_only_after_the_window_is_painted():
    import time as _time

    from fakes import FakeRenderer
    from ttspython.core.queue_model import SpeechQueue
    from ttspython.core.tts.controller import SpeechController

    made = []
    gate = threading.Event()
    speech = SpeechController(SpeechQueue(), renderer_factory=lambda: made.append(1) or FakeRenderer(0.1), start_gate=gate)
    _time.sleep(0.3)
    assert made == []  # nothing competes with building the window
    gate.set()
    assert speech.wait_ready(5) and made == [1]
    speech.shutdown()


def test_the_first_paint_releases_the_engine_and_the_device_scan(qtbot, tmp_path):
    from test_ui import make_controller

    app = make_controller(qtbot, tmp_path)  # make_controller shows the window and waits for it
    qtbot.waitUntil(app._first_paint.is_set, timeout=2000)
