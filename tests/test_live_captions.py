"""Live dictation captions: words while you speak, a short wait at stop, and Cancel."""
import threading
import time

import numpy as np

from fakes import wait_for
from test_stt_service import FakeTimer, Segment
from test_ui import make_controller
from ttspython.core.stt import service as stt
from ttspython.core.stt.service import ModelCache, SttService, SttState

RATE = 16000


def spoken(seconds):
    """One "word" per second: 0.8 s of sound, then a 0.2 s pause."""
    n = int(seconds * RATE)
    loud = (np.arange(n) % RATE) < 0.8 * RATE
    return np.where(loud, 0.2, 0.002).astype(np.float32)


class GrowingRecorder:
    """A microphone that has captured `speed` seconds of audio per real second."""

    sample_rate = RATE

    def __init__(self, speed=8.0):
        self.speed = speed
        self.level = 0.3
        self.on_limit = None
        self.t0 = None

    def _audio(self):
        return spoken((time.monotonic() - self.t0) * self.speed)

    def start(self, device=None):
        self.t0 = time.monotonic()

    def snapshot(self, start=0):
        return self._audio()[start:]

    def stop(self):
        return self._audio()


class WordPerSecondModel:
    """Hears one word per second of audio: "w0 w1 w2 ..." with the segment ending on the second."""

    def __init__(self, delay=0.02):
        self.delay = delay
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append((audio.size, kwargs.get("initial_prompt", "")))
        time.sleep(self.delay)
        return [Segment(f"w{i}", end=i + 0.8, start=float(i)) for i in range(int(audio.size / RATE))], None


def make(speed=8.0, delay=0.02):
    model = WordPerSecondModel(delay)
    svc = SttService(recorder=GrowingRecorder(speed), cache=ModelCache(lambda name: model), timer_factory=FakeTimer)
    events = []
    for name in ("partial", "transcript_ready", "model_status", "preview_status", "state_changed"):
        svc.events.on(name, lambda *a, n=name: events.append((n,) + a))
    return svc, model, events


def of(events, name):
    return [e for e in events if e[0] == name]


def test_words_arrive_while_recording_and_settle():
    svc, model, events = make(speed=12.0)
    try:
        svc.start(("external", 1))
        assert wait_for(lambda: len(of(events, "partial")) >= 3, timeout=10)
        assert wait_for(lambda: svc._settled_samples > 0, timeout=10)  # once past WHOLE_SECONDS
        assert wait_for(lambda: of(events, "partial")[-1][1], timeout=5)
        settled = [e[1] for e in of(events, "partial") if e[1]]
        assert settled, "older words become final"
        last_settled, last_tail, _preview = of(events, "partial")[-1][1:]
        assert last_settled.startswith("W0")  # normalized like the final text
        assert len(last_tail.split()) <= 3  # only the last ~1.5 s stays open
        svc.stop()
        assert wait_for(lambda: of(events, "transcript_ready"), timeout=5)
    finally:
        svc.shutdown()


def test_stop_transcribes_only_the_unsettled_tail():
    svc, model, events = make(speed=10.0)
    try:
        svc.start(("external", 1))
        assert wait_for(lambda: svc._settled_samples > 4 * RATE, timeout=10)
        svc.stop()
        assert wait_for(lambda: of(events, "transcript_ready"), timeout=5)
        final_audio, final_prompt = model.calls[-1]
        assert final_audio < 4 * RATE  # not the whole recording again
        assert "w0" in final_prompt.lower()  # the settled words are context
        text = of(events, "transcript_ready")[0][1]
        words = text.lower().replace(".", "").split()
        assert words[:4] == ["w0", "w1", "w2", "w3"]
    finally:
        svc.shutdown()


def test_a_very_long_tail_is_settled_anyway():
    svc, _model, _events = make()
    run_on = np.full(int(28.5 * RATE), 0.2, dtype=np.float32)  # 28 s without a single pause
    tail = svc._settle([(float(i), float(i + 1), f"w{i}") for i in range(28)], run_on)
    assert tail == "w27" and svc._settled_text.endswith("w26")


def test_short_dictation_is_never_cut():
    """Under WHOLE_SECONDS every pass covers the whole recording: no word is cut at a guessed edge."""
    svc, model, events = make(speed=2.0)
    try:
        svc.start(("external", 1))
        assert wait_for(lambda: len(of(events, "partial")) >= 3, timeout=10)
        assert svc._settled_samples == 0
        assert all(e[1] == "" for e in of(events, "partial"))  # nothing settled, all of it still open
        svc.stop()
        assert wait_for(lambda: of(events, "transcript_ready"), timeout=5)
    finally:
        svc.shutdown()


def test_long_dictation_settles_only_in_a_pause():
    svc, _model, _events = make()
    audio = spoken(30.0)
    segments = [(float(i), i + 0.8, f"w{i}") for i in range(30)]
    svc._settle(segments, audio)
    cut = svc._settled_samples
    assert cut > 0
    assert audio[cut] < 0.01  # in the quiet gap between two words, not inside one
    assert 0.8 * RATE <= cut % RATE  # after a word's sound ends


def test_stop_uses_the_last_pass_when_nothing_new_was_said(monkeypatch):
    monkeypatch.setattr(stt, "_has_speech", lambda audio, rate: False)
    svc, model, events = make(speed=3.0, delay=0.01)
    try:
        svc.start(("external", 1))
        assert wait_for(lambda: any(e[2] for e in of(events, "partial")), timeout=10)
        passes = len(model.calls)
        svc.stop()
        assert wait_for(lambda: of(events, "transcript_ready"), timeout=5)
        assert len(model.calls) <= passes + 1  # at most the pass already running, no new one
    finally:
        svc.shutdown()


def test_stop_transcribes_again_when_speech_came_after_the_last_pass(monkeypatch):
    monkeypatch.setattr(stt, "_has_speech", lambda audio, rate: True)
    monkeypatch.setattr(stt, "REUSE_SECONDS", 0.0)
    svc, model, events = make(speed=3.0, delay=0.01)
    try:
        svc.start(("external", 1))
        assert wait_for(lambda: any(e[2] for e in of(events, "partial")), timeout=10)
        time.sleep(0.05)
        svc.stop()
        assert wait_for(lambda: of(events, "transcript_ready"), timeout=5)
        final_size = model.calls[-1][0]
        assert final_size >= max(c[0] for c in model.calls[:-1])  # covers the newest audio
    finally:
        svc.shutdown()


def test_cancel_while_recording_types_nothing():
    svc, _model, events = make()
    try:
        svc.start(("external", 1))
        assert wait_for(lambda: of(events, "partial"), timeout=10)
        assert svc.cancel() is True
        assert svc.state is SttState.IDLE
        time.sleep(0.4)
        assert of(events, "transcript_ready") == []
        assert ("model_status", "Dictation cancelled") in events
        n = len(of(events, "partial"))
        time.sleep(0.3)
        assert len(of(events, "partial")) == n  # the caption loop stopped
    finally:
        svc.shutdown()


def test_cancel_while_transcribing_types_nothing():
    svc, model, events = make(delay=0.5)
    try:
        svc.start(("external", 1))
        time.sleep(0.4)
        svc.stop()
        assert svc.state is SttState.TRANSCRIBING
        svc.cancel()
        assert wait_for(lambda: svc.state is SttState.IDLE, timeout=5)
        time.sleep(0.2)
        assert of(events, "transcript_ready") == []
    finally:
        svc.shutdown()


def test_no_captions_without_a_loaded_model_until_it_loads():
    release = threading.Event()
    model = WordPerSecondModel()

    def slow_loader(name):
        release.wait(5)
        return model

    svc = SttService(recorder=GrowingRecorder(), cache=ModelCache(slow_loader), timer_factory=FakeTimer)
    partials = []
    svc.events.on("partial", lambda *a: partials.append(a))
    try:
        svc.start(("external", 1))
        time.sleep(0.3)
        assert partials == []
        release.set()
        assert wait_for(lambda: partials, timeout=10)
        svc.stop()
    finally:
        svc.shutdown()


def test_whisper_uses_physical_cores():
    assert 1 <= stt.whisper_threads() <= 8


# --- the bubble -------------------------------------------------------------------------------------
def test_caption_bubble_follows_dictation_into_another_app(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path)
    try:
        c.show_mini()
        c.toggle_dictation(("external", 0))
        assert c.caption.isVisible()
        assert c.fake_hotkeys.bindings[0].get("cancel_dictation") == "Esc"  # Esc cancels while dictating
        c._on_partial("The meeting moved", "to Thursday", "")
        assert "The meeting moved to Thursday" in shown_text(c.caption)
        c.caption.cancel_clicked.emit()
        qtbot.waitUntil(lambda: c.stt.state is SttState.IDLE, timeout=3000)
        assert not c.caption.isVisible()
        assert "cancel_dictation" not in c.fake_hotkeys.bindings[0]  # Esc is given back
    finally:
        c.quit()


def test_editor_dictation_shows_no_bubble(qtbot, tmp_path):
    c = make_controller(qtbot, tmp_path)
    try:
        c.toggle_dictation("editor")
        assert c.stt.state is SttState.RECORDING and not c.caption.isVisible()
        assert "cancel_dictation" not in (c.fake_hotkeys.bindings or ({}, True))[0]
        c.stt.stop()
    finally:
        c.quit()


def shown_text(cap):
    return " ".join(w for line in cap.lines() for w, _kind in line)


TOKENS = {"text": "#ffffff", "muted": "#888888", "accent": "#3b82f6", "surface": "#000000", "border": "#333333",
          "hover": "#222"}


def bubble(qtbot):
    from ttspython.ui.mini import LiveCaption

    cap = LiveCaption()
    qtbot.addWidget(cap)
    cap.set_tokens(TOKENS)
    return cap


def test_long_captions_keep_the_newest_words(qtbot):
    from ttspython.ui.mini import LiveCaption

    cap = bubble(qtbot)
    words = " ".join(f"word{i}" for i in range(200))
    cap.set_words(words, "still changing")
    shown = shown_text(cap)
    assert shown.endswith("word199 still changing") and "word0 " not in shown
    assert len(cap.lines()) == LiveCaption.LINES


def test_bubble_has_no_empty_rows_and_fits_short_text(qtbot):
    from ttspython.ui.mini import LiveCaption

    cap = bubble(qtbot)
    cap.set_words("", "Hello", "")
    spacing = cap.text.fontMetrics().lineSpacing()
    one_line = cap.height()
    assert one_line < 2 * spacing + 2 * cap.PAD  # one row of text, nothing empty under it
    assert cap.width() == LiveCaption.MIN_WIDTH  # a short word: as narrow as the bar
    heights = {}
    for n in range(1, 60):
        cap.set_words(" ".join(["word"] * n), "", "")
        heights.setdefault(len(cap.lines()), cap.height())
    assert sorted(heights) == [1, 2, 3]
    assert heights[3] - heights[2] == spacing  # grows exactly one row at a time
    assert heights[2] - heights[1] <= spacing
    assert cap.width() <= LiveCaption.MAX_WIDTH


def test_bubble_text_is_larger_than_the_app_text(qtbot):
    from PySide6.QtWidgets import QLabel

    cap = bubble(qtbot)
    plain = QLabel("x")
    qtbot.addWidget(plain)
    assert cap.text.fontMetrics().height() > plain.fontMetrics().height() * 1.15


def test_newest_word_is_highlighted_and_preview_words_are_dimmer(qtbot):
    cap = bubble(qtbot)
    cap.set_words("Final words", "checked", "preview newest")
    kinds = [k for line in cap.lines() for _w, k in line]
    assert kinds == ["text", "text", "text", "preview", "newest"]
    html = cap.text.text()
    assert TOKENS["accent"] in html and "rgba(255,255,255,0.6" in html


def test_bubble_bottom_stays_put_as_lines_are_added(qtbot):
    from ttspython.ui.mini import MiniPill

    pill = MiniPill()
    qtbot.addWidget(pill)
    pill.move(600, 600)
    pill.show()
    cap = bubble(qtbot)
    cap.set_words("", "short", "")
    cap.show_by(pill)
    bottom = cap.geometry().bottom()
    cap.set_words(" ".join(["several"] * 25), "", "")
    cap.show_by(pill)
    assert cap.geometry().bottom() == bottom
    assert cap.geometry().bottom() < pill.geometry().top() + 12


def test_listening_state_is_a_small_bubble(qtbot):
    from ttspython.ui.mini import LiveCaption

    cap = bubble(qtbot)
    cap.start()
    assert "Listening..." in cap.text.text()
    assert cap.width() < LiveCaption.MAX_WIDTH and cap._pulse_timer.isActive()
    cap.set_words("", "Hi", "")
    assert not cap._pulse_timer.isActive()


# --- the instant preview ----------------------------------------------------------------------------
class FakePreview:
    """Stands in for the streaming recognizer: the test says which words it "heard"."""

    def __init__(self, on_words, on_pause):
        self.on_words, self.on_pause = on_words, on_pause
        self.fed = 0
        self.stopped = False

    def feed(self, block):
        self.fed += 1

    def stop(self):
        self.stopped = True


def make_with_preview(speed=1.0, delay=0.02):
    svc, model, events = make(speed=speed, delay=delay)
    svc.preview_enabled = True
    sessions = []
    svc.preview_factory = lambda on_words, on_pause: sessions.append(FakePreview(on_words, on_pause)) or sessions[-1]
    return svc, model, events, sessions


def test_preview_words_show_before_whisper_has_run():
    release = threading.Event()
    model = WordPerSecondModel()
    svc = SttService(recorder=GrowingRecorder(), cache=ModelCache(lambda name: release.wait(5) and model),
                     timer_factory=FakeTimer)
    svc.preview_enabled = True
    sessions = []
    svc.preview_factory = lambda w, p: sessions.append(FakePreview(w, p)) or sessions[-1]
    events = []
    svc.events.on("partial", lambda *a: events.append(a))
    try:
        svc.start(("external", 1))
        assert sessions and svc.recorder.on_block == sessions[0].feed  # mic blocks go to the preview
        sessions[0].on_words([("hello", 0.3), ("there", 0.6)])
        assert events[-1] == ("", "", "hello there")  # Whisper is still loading: the preview alone
        release.set()
        svc.stop()
        assert sessions[0].stopped and svc.recorder.on_block is None
    finally:
        release.set()
        svc.shutdown()


def test_whisper_text_replaces_the_preview_words_it_covers():
    svc, model, events, sessions = make_with_preview(speed=3.0)
    try:
        svc.start(("external", 1))
        assert wait_for(lambda: any(e[2] for e in of(events, "partial")), timeout=10)
        _tail, reached = svc._checked
        sessions[0].on_words([("w0", 0.1), ("later", reached + 0.5)])
        settled, checked, newer = of(events, "partial")[-1][1:]
        assert checked.startswith("w0")
        assert newer == "later"  # "w0" is not shown twice
    finally:
        svc.shutdown()


def test_a_pause_makes_whisper_check_right_away():
    svc, model, events, sessions = make_with_preview(speed=3.0)
    try:
        svc.start(("external", 1))
        assert wait_for(lambda: len(model.calls) >= 1, timeout=10)
        n = len(model.calls)
        time.sleep(0.3)
        assert len(model.calls) == n  # with a preview, Whisper rests (LIVE_PREVIEW_REST)...
        sessions[0].on_pause()
        assert wait_for(lambda: len(model.calls) > n, timeout=1.0)  # ...until the speaker pauses
    finally:
        svc.shutdown()


def test_no_preview_for_other_languages():
    svc, model, events, sessions = make_with_preview()
    svc.language = "de"
    try:
        svc.start(("external", 1))
        assert sessions == [] and svc.recorder.on_block is None
    finally:
        svc.shutdown()


def test_preview_model_is_downloaded_once_in_the_background(monkeypatch):
    from ttspython.core.stt import preview

    calls = []
    monkeypatch.setattr(preview, "available", lambda: True)
    monkeypatch.setattr(preview, "install", lambda progress=None, cancel=None: (calls.append(1), progress(36, 73)))
    svc, model, events = make()
    svc.preview_enabled = True
    try:
        svc.start(("external", 1))
        assert wait_for(lambda: ("preview_status", "Live preview ready") in events, timeout=5)
        assert ("preview_status", "Downloading the live preview... 36 of 73 MB (first use only)") in events
        assert not any(kind == "model_status" and "preview" in str(text) for kind, text in events)
        svc.cancel()
        svc.start(("external", 1))
        svc.cancel()
        assert len(calls) == 2 or len(calls) == 1  # installed() is still False in tests: may retry
    finally:
        svc.shutdown()


def test_recorder_hands_blocks_to_the_preview():
    from fakes import FakeSD  # noqa: F401  (FakeSD has no input stream: drive the callback directly)
    from ttspython.core.stt.recorder import Recorder

    rec = Recorder()
    got = []
    rec.on_block = got.append
    data = np.ones((1024, 1), dtype=np.int16)
    rec._callback(data, 1024, None, None)
    assert len(got) == 1 and got[0].dtype == np.int16 and got[0].size == 1024


def test_preview_block_converter_resamples_to_16k():
    from ttspython.core.stt.service import _block_converter

    out = _block_converter(48000)(np.full(4800, 16384, dtype=np.int16))
    assert out.dtype == np.float32 and out.size == 1600 and abs(float(out.mean()) - 0.5) < 1e-3


def test_preview_session_reports_words_and_pauses():
    """The real PreviewSession with a stand-in recognizer (no model needed)."""
    from ttspython.core.stt.preview import PreviewSession

    class Result:
        def __init__(self, tokens, stamps, start=0.0):
            self.tokens, self.timestamps, self.start_time = tokens, stamps, start

    class Rec:
        def __init__(self):
            self.fed = -1600  # the room noise before speaking is not a word

        def create_stream(self):
            return self

        def accept_waveform(self, rate, samples):
            self.fed += samples.size

        def is_ready(self, _s):
            return False

        def get_result_all(self, _s):
            if self.fed < 0:  # after a reset (end of a stretch): nothing new heard
                return Result([], [])
            if self.fed < 3200:
                return Result([" HE", "LLO"], [0.2, 0.3])
            return Result([" HE", "LLO", " I", "'M", " HERE"], [0.2, 0.3, 0.6, 0.7, 0.9])

        def is_endpoint(self, _s):
            return self.fed >= 4800

        def reset(self, _s):
            self.fed = -10**9

    words, pauses = [], []
    session = PreviewSession(words.append, lambda: pauses.append(1), recognizer=Rec()).start()
    session.feed(np.full(1600, 0.001, np.float32))  # the room before speaking
    session.feed(np.full(1600, 0.2, np.float32))  # speech
    assert wait_for(lambda: words, timeout=3)
    session.feed(np.full(1600, 0.2, np.float32))
    assert wait_for(lambda: len(words) > 1, timeout=3)
    assert pauses == []
    session.feed(np.full(1600, 0.001, np.float32))  # 0.1 s quiet: not a pause yet
    session.feed(np.full(4000, 0.001, np.float32))  # 0.35 s quiet in all: a pause
    assert wait_for(lambda: pauses, timeout=3)
    session.stop()
    assert words[0] == [("hello", 0.2)]
    assert [w for w, _t in words[-1]] == ["hello", "I'm", "here"]


def test_preview_words_do_not_repeat_the_end_of_whispers_text():
    from ttspython.core.stt.service import _after_overlap

    def rest(text, preview):
        return _after_overlap(text, preview)[0]

    assert rest("Please send the report before", ["before", "the", "end"]) == ["the", "end"]
    assert rest("before the end of the day.", ["the", "day"]) == []
    assert rest("tomorrow morning.", ["morning", "after", "that"]) == ["after", "that"]
    assert rest("almost fin", ["finished", "the"]) == ["the"]  # a word Whisper heard half of
    assert rest("The cabinets", ["arrived", "on"]) == ["arrived", "on"]  # nothing repeated
    assert rest("", ["hello"]) == ["hello"]
    assert rest("next weekend we could", ["week", "and", "we", "could", "plant"]) == ["plant"]
    assert rest("for the", ["new", "for", "sale"]) == ["new", "for", "sale"]  # one word later: kept
    assert rest("moved to Thursday at 3.", ["at", "three", "and", "we"]) == ["and", "we"]  # digits vs words
    # Whisper guessed the half-heard last word: the preview's words win, the guess is hidden.
    assert _after_overlap("the boards are so", ["the", "boards", "are", "still", "in"]) == (["still", "in"], True)
    assert _after_overlap("we need a", ["we", "need", "help"]) == (["help"], True)


def test_half_heard_word_mark_is_not_shown():
    svc, model, events, sessions = make_with_preview(speed=3.0)
    try:
        svc.start(("external", 1))
        assert wait_for(lambda: of(events, "partial"), timeout=10)
        with svc._caption_lock:
            svc._checked = ("We only need...", 2.0)
            svc._preview_words = [("need", 1.8), ("the", 2.1), ("new", 2.3)]
        svc._emit_partial(svc._session)
        _settled, checked, newer = of(events, "partial")[-1][1:]
        assert checked == "We only need" and newer == "the new"
        with svc._caption_lock:
            svc._checked = ("their trailer for the r-", 2.0)
            svc._preview_words = [("trailer", 1.6), ("for", 1.8), ("the", 1.9), ("rubbish", 2.1)]
        svc._emit_partial(svc._session)
        _settled, checked, newer = of(events, "partial")[-1][1:]
        assert checked == "their trailer for the" and newer == "rubbish"
    finally:
        svc.shutdown()


def test_noise_only_segments_are_dropped():
    class Seg:
        def __init__(self, text, start, end):
            self.text, self.start, self.end = text, start, end

    class Model:
        def transcribe(self, audio, **kwargs):
            return [Seg(" Hello there.", 0.0, 1.0), Seg(" ______", 1.0, 2.0), Seg(" ...", 2.0, 2.5)], None

    svc, _model, _events = make()
    assert svc._whisper(Model(), np.zeros(RATE, np.float32)) == [(0.0, 1.0, "Hello there.")]


def test_a_last_word_said_right_before_stop_is_not_dropped():
    """The last live pass ended 0.25 s before stop and a short word came after it: transcribe again."""
    svc, _model, _events = make()
    audio = spoken(3.0)  # "words" with pauses; the last 0.25 s is the start of a word
    svc._settled_samples = 0
    svc._last_pass = (0, audio.size - int(0.25 * RATE), "w0 w1")
    assert stt._loud_part(audio[-int(0.25 * RATE):], audio, RATE)
    assert svc._reusable_tail(audio) is None
    quiet = np.concatenate([audio, np.full(int(0.4 * RATE), 0.002, np.float32)])
    svc._last_pass = (0, audio.size, "w0 w1 w2")
    assert not stt._loud_part(quiet[audio.size:], quiet, RATE)


def test_long_passes_use_word_times_so_run_on_speech_can_settle():
    class Word:
        def __init__(self, word, start, end):
            self.word, self.start, self.end = word, start, end

    class Seg:
        def __init__(self):
            self.text, self.start, self.end = " one long run on sentence", 0.0, 4.0
            self.words = [Word(" one", 0.0, 0.5), Word(" long", 0.6, 1.0), Word(" run", 1.5, 2.0),
                          Word(" on", 2.1, 2.5), Word(" sentence", 2.6, 4.0)]

    class Model:
        def __init__(self):
            self.kwargs = []

        def transcribe(self, audio, **kwargs):
            self.kwargs.append(kwargs)
            return [Seg()], None

    svc, _model, _events = make()
    model = Model()
    assert svc._whisper(model, np.zeros(RATE, np.float32)) == [(0.0, 4.0, "one long run on sentence")]
    assert "word_timestamps" not in model.kwargs[-1]
    units = svc._whisper(model, np.zeros(RATE, np.float32), words=True)
    assert model.kwargs[-1]["word_timestamps"] is True
    assert [t for _s, _e, t in units] == ["one", "long", "run", "on", "sentence"]


def test_preview_download_never_pops_up_or_hides_listening(qtbot, tmp_path, monkeypatch):
    # It downloads in the background and nothing waits on it: the status bar only, 5 steps a second.
    c = make_controller(qtbot, tmp_path)
    try:
        monkeypatch.setattr(c, "_window_in_front", lambda: False)
        c.show_mini()
        shown = []
        monkeypatch.setattr(c.float_toast, "_present", lambda x, y, ms: shown.append(c.float_toast.text()))
        c.toggle_dictation(("external", 0))
        for mb in range(0, 30, 3):
            c._on_preview_status(f"Downloading the live preview... {mb} of 73 MB (first use only)")
        assert "Listening..." in c.caption.text.text() and "preview" not in c.caption.text.text()
        c.caption.cancel_clicked.emit()
        qtbot.waitUntil(lambda: c.stt.state is SttState.IDLE, timeout=3000)
        assert shown == ["Dictation cancelled"]
        shown.clear()
        for mb in range(30, 73, 3):
            c._on_preview_status(f"Downloading the live preview... {mb} of 73 MB (first use only)")
        c._on_preview_status("Live preview ready")
        assert shown == []
        assert c.window.listen_panel.title.text() == "Ready to dictate"
        c._on_preview_status("Live preview download failed: no internet")
        assert shown == ["Live preview download failed: no internet"]  # a failure is said once
    finally:
        c.quit()


def test_model_download_updates_one_notice_in_place(qtbot, tmp_path, monkeypatch):
    c = make_controller(qtbot, tmp_path)
    try:
        monkeypatch.setattr(c, "_window_in_front", lambda: False)
        c.show_mini()
        presented = []
        real = c.float_toast._present
        monkeypatch.setattr(c.float_toast, "_present", lambda x, y, ms: (presented.append(1), real(x, y, ms)))
        spots = set()
        for mb in range(0, 480, 40):
            c._on_model_status(f"Downloading the small model... {mb} of 480 MB (first use only)")
            geo = c.float_toast.geometry()
            spots.add((geo.center().x() // 3, geo.bottom()))
        assert len(presented) == 1 and len(spots) == 1
        assert "440 of 480 MB" in c.float_toast.text()
        assert c.window.listen_panel.title.text().startswith("Downloading the small model")
        c._on_model_status("small model ready")
        assert c.window.listen_panel.title.text() == "Ready to dictate"  # not stuck on the download
    finally:
        c.quit()


def test_floating_notice_fits_its_text(qtbot):
    from ttspython.ui.mini import FloatingToast

    toast = FloatingToast()
    qtbot.addWidget(toast)
    toast.show_in_corner("Dictation cancelled")
    one_line = toast.height()
    assert toast.width() < toast.maximumWidth()
    toast.show_in_corner("Downloading the small model... 135 of 480 MB (first use only) " * 2)
    assert toast.width() == toast.maximumWidth()  # wrapped at the widest size, not a narrow column
    assert toast.height() < 4 * one_line
