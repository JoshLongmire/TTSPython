"""Your own voice: consent, the model download, the saved voices, the engine's loop and the window.
The model itself is faked here; real runs are measured by hand."""
import hashlib
import io
import json
import os
import threading
import types

import numpy as np
import pytest
from PySide6.QtWidgets import QMessageBox

from fakes import FakeRenderer
from ttspython.core.download import ChecksumError, DownloadCancelled
from ttspython.core.tts import clone
from ttspython.core.tts.render import Cancelled, MultiRenderer

RATE = 48000
CONSENT = clone.Consent("This is my own voice. My code words are river, candle and orange.", ("river", "candle", "orange"))


def speech(seconds=10.0, level=0.3):
    t = np.arange(int(seconds * RATE)) / RATE
    return (np.sin(2 * np.pi * 180 * t) * level).astype(np.float32)


class FakeEngine:
    rate = RATE

    def __init__(self, seconds=2.0):
        self.seconds = seconds
        self.spoken = []

    def encode(self, audio, rate):
        self.encoded = (audio, rate)
        return np.arange(160, dtype=np.int32).reshape(10, 16)

    def speak(self, codes, text, cancel):
        if cancel.is_set():
            raise Cancelled()
        self.spoken.append((codes.shape, text))
        return speech(self.seconds)


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("TTSPYTHON_DATA", str(tmp_path))
    yield tmp_path
    clone.release_engine()


@pytest.fixture
def model(data, monkeypatch):
    """The model counts as downloaded (nothing loads it: tests give a fake engine)."""
    folder = os.path.join(str(data), "clone-model")
    os.makedirs(folder)
    with open(os.path.join(folder, "m.onnx"), "wb") as f:
        f.write(b"x")
    monkeypatch.setattr(clone, "MODEL_FILES", (("MOSS-TTS-Nano-100M-ONNX", "m.onnx", 1, ""),))
    return folder


def voice(engine=None, name="Mine"):
    return clone.build_voice(name, CONSENT, speech(), RATE, CONSENT.text, engine or FakeEngine())


# --- consent ------------------------------------------------------------------------------------
def test_each_statement_gets_new_code_words():
    seen = {clone.new_consent().code_words for _ in range(20)}
    assert len(seen) > 1
    for words in seen:
        assert len(set(words)) == 3 and all(w in clone.CODE_WORDS for w in words)


def test_a_statement_says_all_its_code_words():
    consent = clone.new_consent()
    assert all(w in consent.text for w in consent.code_words)
    assert "own voice" in consent.text and "my voice" in consent.text


def test_a_close_reading_passes():
    assert clone.check_consent(CONSENT, "This is my own voice. My code words are river candle and orange") == ""
    assert clone.check_consent(CONSENT, "this is my own voice my code words are river, candle, and orange.") == ""


@pytest.mark.parametrize("heard, wanted", [
    ("", "No words"),
    ("This is my own voice. My code words are river, candle and apple.", "code words"),  # an old statement
    ("river candle orange", "did not match"),  # only the code words
    ("Hello there, my friend was reading out river, candle and orange from a very long list of other things today.",
     "too much"),  # someone else's speech
])
def test_a_wrong_reading_is_refused(heard, wanted):
    assert wanted in clone.check_consent(CONSENT, heard)


def test_a_voice_cannot_be_built_without_the_statement(model):
    engine = FakeEngine()
    with pytest.raises(ValueError, match="code words"):
        clone.build_voice("Mine", CONSENT, speech(), RATE, "Something else entirely.", engine)
    assert clone.saved_voices() == []
    assert not hasattr(engine, "encoded")  # refused before any of the voice was processed


@pytest.mark.parametrize("audio, wanted", [
    (speech(3), "too short"), (speech(50), "too long"), (speech(10, 0.001), "silent"), (speech(10, 2.0), "too loud"),
])
def test_a_bad_recording_is_refused(audio, wanted):
    assert wanted in clone.check_recording(audio, RATE)


def test_a_good_recording_passes():
    assert clone.check_recording(speech(), RATE) == ""


def test_the_reference_is_trimmed_and_levelled():
    audio = np.concatenate([np.zeros(RATE), speech(5, 0.1), np.zeros(RATE)])
    clean = clone.clean_reference(audio, RATE)
    assert clean.size < 5.5 * RATE and clean.size >= 5 * RATE
    assert abs(float(np.abs(clean).max()) - 0.7) < 0.01


def test_the_reference_is_cut_at_the_longest_the_model_uses():
    assert clone.clean_reference(speech(35), RATE).size <= 21 * RATE


# --- the model download -------------------------------------------------------------------------
class Web:
    def __init__(self, files):
        self.files = files
        self.requested = []

    def __call__(self, url, timeout=30):
        self.requested.append(url)
        data = self.files[url.rsplit("/", 1)[-1]]
        response = io.BytesIO(data)
        response.headers = {"Content-Length": str(len(data))}
        return response


@pytest.fixture
def small_model(data, monkeypatch):
    files = {"a.onnx": b"first file", "b.data": b"the second file"}
    monkeypatch.setattr(clone, "MODEL_FILES", tuple(
        ("MOSS-TTS-Nano-100M-ONNX", name, len(body), hashlib.sha256(body).hexdigest()) for name, body in files.items()))
    monkeypatch.setattr(clone, "MODEL_BYTES", sum(len(b) for b in files.values()))
    return files


def test_every_real_model_file_is_pinned_and_the_sample_voices_are_not_fetched():
    names = [f[1] for f in clone.MODEL_FILES]
    assert all(len(f[3]) == 64 for f in clone.MODEL_FILES)
    assert "browser_poc_manifest.json" not in names
    assert clone.MODEL_MB == 762


def test_downloading_the_model(small_model):
    assert not clone.model_installed()
    seen = []
    clone.install_model(lambda d, t: seen.append((d, t)), opener=Web(small_model))
    assert clone.model_installed()
    assert seen[-1] == (clone.MODEL_BYTES, clone.MODEL_BYTES)
    assert [d for d, _t in seen] == sorted(d for d, _t in seen)  # progress never goes back
    assert not [n for n in os.listdir(clone.model_dir()) if n.endswith(".part")]


def test_a_changed_file_is_refused(small_model):
    with pytest.raises(ChecksumError):
        clone.install_model(opener=Web({**small_model, "b.data": b"somebody else's data"}))
    assert not clone.model_installed()
    assert not os.path.exists(os.path.join(clone.model_dir(), "b.data"))


def test_a_stopped_download_carries_on_from_the_files_it_finished(small_model):
    cancel = threading.Event()

    class StopsOnSecond(Web):
        def __call__(self, url, timeout=30):
            if url.endswith("b.data"):
                cancel.set()
            return super().__call__(url, timeout)

    with pytest.raises(DownloadCancelled):
        clone.install_model(cancel=cancel, opener=StopsOnSecond(small_model))
    assert not clone.model_installed()
    web = Web(small_model)
    clone.install_model(opener=web)
    assert clone.model_installed()
    assert [u.rsplit("/", 1)[-1] for u in web.requested] == ["b.data"]


def test_downloads_are_pinned_to_one_revision(small_model):
    web = Web(small_model)
    clone.install_model(opener=web)
    assert all("/resolve/f52645cb467506d8e18e746ddd59482685b74e58/" in u for u in web.requested)


def test_deleting_the_model_keeps_the_voices(small_model):
    clone.install_model(opener=Web(small_model))
    vid = voice()
    assert clone.remove_model() == clone.MODEL_BYTES
    assert not clone.model_installed()
    assert [v.id for v in clone.installed_voices()] == [vid]  # still the voice in Settings
    assert "model not downloaded" in clone.installed_voices()[0].name


# --- the saved voices ---------------------------------------------------------------------------
def test_a_saved_voice_holds_its_recording_and_codes(model):
    vid = voice(name="  My   Voice ")
    folder = clone.voice_folder(vid)
    assert sorted(os.listdir(folder)) == ["codes.npy", "consent.wav", "voice.json"]
    info = clone.voice_info(vid)
    assert info["name"] == "My Voice" and info["statement"] == CONSENT.text and info["heard"] == CONSENT.text
    assert clone.load_codes(vid).shape == (10, 16)
    assert [v.name for v in clone.installed_voices()] == ["My Voice - your voice"]
    assert clone.installed_voices()[0].id == vid


def test_no_folder_is_left_behind_when_saving_fails(model, monkeypatch):
    def broken(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(clone.np, "save", broken)
    with pytest.raises(OSError):
        voice()
    assert os.listdir(clone.voices_dir()) == []


def test_a_half_written_voice_is_not_listed(model):
    vid = voice()
    os.remove(os.path.join(clone.voice_folder(vid), "codes.npy"))
    os.makedirs(os.path.join(clone.voices_dir(), "not-a-voice"))
    assert clone.saved_voices() == []


@pytest.mark.parametrize("bad", ["clone:../../secret", "clone:..", "clone:", r"clone:..\x", "clone:ABCDEF012345"])
def test_a_voice_id_cannot_point_outside_its_folder(data, bad):
    with pytest.raises(ValueError):
        clone.voice_folder(bad)
    with pytest.raises(ValueError):
        clone.remove_voice(bad)


def test_removing_a_voice_removes_its_recording(model):
    vid = voice()
    folder = clone.voice_folder(vid)
    clone.remove_voice(vid)
    assert not os.path.exists(folder)


@pytest.mark.parametrize("speed, wanted", [(2.3, "smoothly"), (1.1, "may pause"), (0.7, "will pause")])
def test_the_speed_check_says_what_it_means(speed, wanted):
    assert wanted in clone.speed_message(speed)


# --- speaking -----------------------------------------------------------------------------------
def test_each_voice_kind_goes_to_its_own_engine(model):
    system = FakeRenderer(0.01)
    engine = FakeEngine()
    own = clone.CloneRenderer(lambda: engine)
    r = MultiRenderer(system, FakeRenderer(0.01), system_voices=system.list_voices(), clone=own)
    vid = voice(engine)
    r.render("Hello there.", vid, 200, threading.Event())
    assert engine.spoken == [((10, 16), "Hello there.")]
    assert system.rendered == []
    assert vid in [v.id for v in r.list_voices()]


def test_rendering_gives_16_bit_audio_at_the_models_rate(model):
    engine = FakeEngine(1.0)
    pcm, rate = clone.CloneRenderer(lambda: engine).render("Hello.", voice(engine), 200, threading.Event())
    assert rate == RATE and pcm.dtype == np.int16 and pcm.size == RATE


def test_text_with_nothing_to_say_does_not_run_the_model(model):
    engine = FakeEngine()
    pcm, _rate = clone.CloneRenderer(lambda: engine).render("...", voice(engine), 200, threading.Event())
    assert engine.spoken == [] and pcm.size and not pcm.any()


def test_the_natural_pace_is_measured_from_long_enough_text(model):
    engine = FakeEngine(4.0)
    r = clone.CloneRenderer(lambda: engine)
    vid = voice(engine)
    assert r.native_wpm(300, vid) == clone.FALLBACK_WPM
    r.render("One two.", vid, 200, threading.Event())
    assert r.native_wpm(300, vid) == clone.FALLBACK_WPM  # too few words to tell
    r.render("One two three four five six seven eight nine ten.", vid, 200, threading.Event())
    assert r.native_wpm(300, vid) == 150  # 10 words in 4 s; the slider never changes it


def test_a_strange_pace_is_held_in_range(model):
    engine = FakeEngine(0.5)
    r = clone.CloneRenderer(lambda: engine)
    vid = voice(engine)
    r.render("One two three four five six seven eight nine ten.", vid, 200, threading.Event())
    assert r.native_wpm(200, vid) == 280


def test_a_missing_model_says_where_to_get_it(data):
    with pytest.raises(RuntimeError, match="Get more voices"):
        clone.CloneRenderer(FakeEngine).render("Hello.", "clone:0123456789ab", 200, threading.Event())


def test_a_deleted_voice_says_so(model):
    with pytest.raises(RuntimeError, match="gone"):
        clone.CloneRenderer(FakeEngine).render("Hello.", "clone:0123456789ab", 200, threading.Event())


def test_cancel_is_honored_before_starting(model):
    engine = FakeEngine()
    vid = voice(engine)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        clone.CloneRenderer(lambda: engine).render("Hello.", vid, 200, cancel)
    assert engine.spoken == []


def test_a_speed_change_does_not_make_a_cloned_voice_render_again():
    import queue as queue_module

    from fakes import FakeSD
    from ttspython.core.queue_model import SpeechQueue
    from ttspython.core.tts.controller import SpeechController
    from ttspython.core.tts.player import AudioPlayer

    controller = SpeechController(SpeechQueue(), renderer_factory=lambda: FakeRenderer(0.01),
                                  player=AudioPlayer(queue_module.Queue(), sd_module=FakeSD()))
    try:
        controller.voice_id = "clone:0123456789ab"
        controller.set_rate(240)
        assert controller._rerender_timer is None
        assert controller.player._target_wpm == 240  # still heard at once: the player stretches it
        controller.voice_id = "v-zira"
        controller.set_rate(260)
        assert controller._rerender_timer is not None
    finally:
        controller.shutdown()


# --- splitting long text ------------------------------------------------------------------------
def words_as_tokens(text):
    return text.split()


def test_short_text_is_one_piece():
    assert clone.split_tokens("One two. Three four.", words_as_tokens, 10) == ["One two. Three four."]


def test_long_text_splits_at_punctuation():
    text = "One two three. Four five six. Seven eight nine."
    assert clone.split_tokens(text, words_as_tokens, 6) == ["One two three. Four five six.", "Seven eight nine."]


def test_a_sentence_without_punctuation_splits_at_spaces():
    pieces = clone.split_tokens(" ".join(str(i) for i in range(25)), words_as_tokens, 10)
    assert all(len(p.split()) <= 10 for p in pieces)
    assert " ".join(pieces).split() == [str(i) for i in range(25)]


def test_splitting_loses_no_words():
    text = "First part, second part; third part: fourth part. And the rest\nof it on a new line! Done"
    assert " ".join(clone.split_tokens(text, words_as_tokens, 4)).split() == text.split()


# --- the engine's loop, with fake model graphs --------------------------------------------------
class Graph:
    def __init__(self, names, run):
        self._names = names
        self.run_fn = run
        self.calls = 0

    def get_outputs(self):
        return [types.SimpleNamespace(name=n) for n in self._names]

    def run(self, _outputs, feeds):
        self.calls += 1
        self.feeds = feeds
        return self.run_fn(feeds)


def fake_engine(frames_until_end=10**9, on_frame=None):
    engine = clone.Engine.__new__(clone.Engine)
    engine._n_vq = 16
    engine._pad = 1024
    engine.rate = RATE
    engine._config = {"audio_user_slot_token_id": 8, "audio_assistant_slot_token_id": 9, "audio_start_token_id": 6,
                      "audio_end_token_id": 7, "audio_codebook_sizes": [1024] * 16}
    engine._tts = {"onnx": {"prefill_output_names": ["global_hidden", "present_key_0"],
                            "decode_output_names": ["global_hidden", "present_key_0"]}}
    engine._codec = {"streaming_decode": {"transformer_offsets": [], "attention_caches": []}}
    hidden = np.zeros((1, 1, 4), dtype=np.float32)
    engine._prefill = Graph(["global_hidden", "present_key_0"], lambda _f: [hidden, np.zeros(1)])
    engine._decode = Graph(["global_hidden", "present_key_0"], lambda _f: [hidden, np.zeros(1)])
    count = [0]

    def frame(_feeds):
        count[0] += 1
        if on_frame:
            on_frame(count[0])
        return [np.asarray([count[0] <= frames_until_end]), np.arange(16, dtype=np.int32)]

    engine._frame = Graph(["should_continue", "frame_token_ids"], frame)
    engine._audio_decoder = Graph(["audio", "audio_lengths"], lambda f: [
        np.zeros((1, 2, f["audio_codes"].shape[1] * 3840), dtype=np.float32), np.asarray([f["audio_codes"].shape[1] * 3840])])
    engine._random = np.random.default_rng(1)
    engine.tokens = lambda text: list(range(len(text.split())))
    return engine


CODES = np.zeros((5, 16), dtype=np.int32)


def test_speech_ends_when_the_model_says_so():
    engine = fake_engine(frames_until_end=20)
    audio = engine.speak(CODES, "one two three four five six seven eight nine ten", threading.Event())
    assert audio.size == 20 * 3840 and audio.ndim == 1
    assert engine._decode.calls == 20


def test_a_model_that_never_stops_is_stopped():
    engine = fake_engine()
    audio = engine.speak(CODES, "one two", threading.Event())
    assert audio.size == clone.frame_limit(2) * 3840
    assert clone.frame_limit(2) * 3840 / RATE < 2  # a word can never turn into seconds of babble
    assert clone.frame_limit(50) > 3 * 50  # and a normal sentence is never cut off


def test_one_piece_never_passes_the_models_limit():
    engine = fake_engine()
    audio = np.concatenate(list(engine._piece_blocks(CODES, list(range(1000)), threading.Event())))
    assert audio.size == clone.MAX_FRAMES * 3840


def test_stop_takes_effect_within_a_frame():
    cancel = threading.Event()
    engine = fake_engine(on_frame=lambda n: cancel.set() if n == 3 else None)
    with pytest.raises(Cancelled):
        engine.speak(CODES, "one two three four five", cancel)
    assert engine._frame.calls == 3


def test_long_text_is_spoken_in_pieces_with_a_short_gap():
    engine = fake_engine(frames_until_end=10**9)
    engine._frame.run_fn = lambda _f: [np.asarray([False]), np.arange(16, dtype=np.int32)]
    assert engine.speak(CODES, "word " * 200, threading.Event()).size == 2 * int(clone._PIECE_GAP_SECONDS * RATE)


def test_used_codes_are_marked_for_the_repetition_penalty():
    engine = fake_engine(frames_until_end=2)
    engine.speak(CODES, "one two", threading.Event())
    seen = engine._frame.feeds["repetition_seen_mask"]
    assert seen.shape == (1, 16, 1024)
    assert seen[0, 3, 3] == 1 and seen.sum() == 16


def test_the_request_puts_the_voice_before_the_text():
    engine = fake_engine()
    ids = engine._request(CODES + 7, [501, 502])
    assert ids.shape[2] == 17
    rows = ids[0]
    audio_rows = rows[rows[:, 0] == 8]
    assert len(audio_rows) == 5 and (audio_rows[:, 1:] == 7).all()
    assert list(rows[:, 0]).index(8) < list(rows[:, 0]).index(501)
    assert rows[-1, 0] == 6


def test_no_process_wide_settings_change_when_the_engine_module_loads():
    # Importing this must stay cheap: every start of the app does it.
    import subprocess
    import sys

    code = "import sys; import ttspython.core.tts.clone; print('onnxruntime' in sys.modules, 'sentencepiece' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert out.stdout.split() == ["False", "False"], out.stderr


# --- the Whisper check --------------------------------------------------------------------------
def test_transcribe_once_returns_the_words_and_types_nothing():
    from ttspython.core.stt.service import ModelCache, SttService

    class Model:
        def transcribe(self, audio, **kwargs):
            self.kwargs = kwargs
            return [types.SimpleNamespace(text=" Hello"), types.SimpleNamespace(text=" there. ")], None

    model = Model()
    svc = SttService(cache=ModelCache(loader=lambda _name: model), auto_unload=False)
    typed = []
    svc.events.on("transcript_ready", lambda *a: typed.append(a))
    try:
        assert svc.transcribe_once(np.zeros(16000, dtype=np.float32)) == "Hello there."
        assert model.kwargs["language"] == "en"
        assert typed == []
    finally:
        svc.shutdown()


# --- the window ---------------------------------------------------------------------------------
class FakeRecorder:
    sample_rate = RATE
    level = 0.5

    def __init__(self, audio=None, fails=False):
        self.audio = speech() if audio is None else audio
        self.fails = fails
        self.running = False
        self.device = "not set"

    def start(self, device=None):
        if self.fails:
            raise OSError("no microphone")
        self.device = device
        self.running = True

    def stop(self):
        self.running = False
        return self.audio


def window(qtbot, heard=None, recorder=None, **kwargs):
    from ttspython.ui.clone_dialog import CloneDialog

    engine = FakeEngine()
    consents = []

    def build(name, consent, audio, rate, words):
        consents.append(consent)
        return clone.build_voice(name, consent, audio, rate, words, engine)

    def transcribe(_audio):
        return heard(dlg._consent) if heard else dlg._consent.text

    dlg = CloneDialog(transcribe, recorder=recorder or FakeRecorder(), builder=build,
                      speed_check=lambda _vid, _cancel=None: 2.3, **kwargs)
    qtbot.addWidget(dlg)
    dlg.consents = consents
    return dlg


def record(qtbot, dlg):
    dlg.record_btn.click()
    assert dlg.record_btn.text() == "Stop recording"
    dlg.record_btn.click()
    qtbot.waitUntil(lambda: not dlg._working, timeout=5000)


def test_without_the_model_only_the_download_is_offered(data, qtbot):
    dlg = window(qtbot)
    dlg.show()
    assert dlg.model_box.isVisible() and not dlg.record_box.isVisible()
    assert str(clone.MODEL_MB) in dlg.model_box.findChildren(type(dlg.status))[0].text()


def test_the_download_runs_and_can_be_cancelled(data, qtbot):
    started = threading.Event()

    def install(_progress, cancel):
        started.set()
        assert cancel.wait(5)
        raise DownloadCancelled()

    dlg = window(qtbot, installer=install)
    dlg.show()
    dlg.download_btn.click()
    assert dlg.cancel_btn.isVisible() and started.wait(5)
    dlg.cancel_btn.click()
    qtbot.waitUntil(lambda: dlg._cancel is None, timeout=5000)
    assert "cancelled" in dlg.status.text()
    assert dlg.download_btn.isVisible()


def test_a_finished_download_opens_the_recording_part(data, qtbot, small_model):
    dlg = window(qtbot, installer=lambda progress, cancel: clone.install_model(progress, cancel, opener=Web(small_model)))
    dlg.show()
    with qtbot.waitSignal(dlg.voices_changed, timeout=5000):
        dlg.download_btn.click()
    assert dlg.record_box.isVisible() and not dlg.model_box.isVisible()


def test_reading_the_statement_makes_the_voice(model, qtbot):
    dlg = window(qtbot)
    dlg.name.setText("Test voice")
    first = dlg._consent
    assert first.text == dlg.statement.text()
    with qtbot.waitSignal(dlg.voices_changed, timeout=5000):
        record(qtbot, dlg)
    assert [i["name"] for _v, i in clone.saved_voices()] == ["Test voice"]
    assert "2.3 times" in dlg.status.text() and "smoothly" in dlg.status.text()
    assert dlg.consents == [first]
    assert dlg.selected_voice() == clone.saved_voices()[0][0]


def test_reading_something_else_makes_no_voice_and_changes_the_code_words(model, qtbot):
    dlg = window(qtbot, heard=lambda _c: "This is someone else talking about the weather for a while.")
    first = dlg._consent
    record(qtbot, dlg)
    assert clone.saved_voices() == [] and dlg.consents == []
    assert "code words" in dlg.status.text()
    assert dlg._consent is not first and dlg.statement.text() == dlg._consent.text


def test_a_failed_check_cannot_be_passed_by_the_old_recording(model, qtbot):
    """The second try needs the second statement's code words, so replaying the first fails."""
    said = []

    def heard(consent):
        said.append(consent)
        return said[0].text  # always the first statement

    dlg = window(qtbot, heard=heard)
    record(qtbot, dlg)
    assert len(clone.saved_voices()) == 1
    record(qtbot, dlg)
    assert len(clone.saved_voices()) == 1 and "code words" in dlg.status.text()


def test_a_short_recording_never_reaches_the_check(model, qtbot):
    asked = []
    dlg = window(qtbot, heard=lambda c: asked.append(c) or c.text, recorder=FakeRecorder(speech(2)))
    record(qtbot, dlg)
    assert asked == [] and "too short" in dlg.status.text()


def test_a_whisper_failure_makes_no_voice(model, qtbot):
    def fails(_consent):
        raise OSError("no model and no network")

    dlg = window(qtbot, heard=fails)
    record(qtbot, dlg)
    assert clone.saved_voices() == [] and "no network" in dlg.status.text()


def test_a_slow_computer_is_told(model, qtbot):
    from ttspython.ui.clone_dialog import CloneDialog

    engine = FakeEngine()
    dlg = CloneDialog(lambda _a: dlg._consent.text, recorder=FakeRecorder(), speed_check=lambda _v, _c=None: 0.7,
                      builder=lambda n, c, a, r, h: clone.build_voice(n, c, a, r, h, engine))
    qtbot.addWidget(dlg)
    record(qtbot, dlg)
    assert "will pause" in dlg.status.text()
    assert len(clone.saved_voices()) == 1  # still made: pauses are better than nothing


def test_recording_stops_speech_first_and_uses_the_chosen_microphone(model, qtbot):
    recorder = FakeRecorder()
    dlg = window(qtbot, recorder=recorder, input_device=3)
    with qtbot.waitSignal(dlg.recording_started, timeout=1000):
        dlg.record_btn.click()
    assert recorder.running and recorder.device == 3
    dlg.close()
    assert not recorder.running


def test_closing_while_recording_keeps_nothing(model, qtbot):
    dlg = window(qtbot)
    dlg.record_btn.click()
    dlg.close()
    assert clone.saved_voices() == [] and dlg.consents == []


def test_recording_is_refused_during_dictation(model, qtbot):
    recorder = FakeRecorder()
    dlg = window(qtbot, recorder=recorder, busy_reason=lambda: "Finish dictating first.")
    dlg.record_btn.click()
    assert not recorder.running and "dictating" in dlg.status.text()


def test_a_broken_microphone_is_reported(model, qtbot):
    dlg = window(qtbot, recorder=FakeRecorder(fails=True))
    dlg.record_btn.click()
    assert "no microphone" in dlg.status.text() and dlg.record_btn.text() == "Start recording"


def test_all_the_buttons_fit_at_the_smallest_size(model, qtbot):
    voice()
    dlg = window(qtbot)
    dlg.resize(dlg.minimumSize())
    dlg.show()
    qtbot.waitExposed(dlg)
    for button in (dlg.use_btn, dlg.hear_btn, dlg.remove_btn, dlg.remove_model_btn):
        assert button.width() >= button.sizeHint().width()


def test_a_voice_in_use_cannot_be_removed(model, qtbot):
    vid = voice()
    dlg = window(qtbot, current_voice_id=vid)
    assert dlg.selected_voice() == vid
    dlg.remove_btn.click()
    assert os.path.isdir(clone.voice_folder(vid)) and "in use" in dlg.status.text()
    assert not dlg.use_btn.isEnabled()


def test_the_model_cannot_be_deleted_while_one_of_the_voices_is_in_use(model, qtbot):
    dlg = window(qtbot, current_voice_id=voice())
    dlg.remove_model_btn.click()
    assert clone.model_installed() and "in use" in dlg.status.text()


def test_using_hearing_and_removing_a_voice(model, qtbot, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    vid = voice()
    dlg = window(qtbot)
    with qtbot.waitSignal(dlg.hear_voice, timeout=1000) as heard:
        dlg.hear_btn.click()
    assert heard.args == [vid]
    with qtbot.waitSignal(dlg.use_voice, timeout=1000) as used:
        dlg.use_btn.click()
    assert used.args == [vid]
    dlg.set_current("v-zira")
    with qtbot.waitSignal(dlg.voices_changed, timeout=1000):
        dlg.remove_btn.click()
    assert clone.saved_voices() == [] and dlg.list.count() == 0


def test_there_is_no_way_to_load_a_file_in_the_window():
    import inspect

    from ttspython.ui import clone_dialog

    assert "QFileDialog" not in inspect.getsource(clone_dialog)


def test_the_voices_file_is_plain_data(model):
    vid = voice()
    with open(os.path.join(clone.voice_folder(vid), "voice.json"), encoding="utf-8") as f:
        assert json.load(f)["name"] == "Mine"
    # codes.npy is read without pickle: a file swapped for a pickle cannot run code.
    with open(os.path.join(clone.voice_folder(vid), "codes.npy"), "wb") as f:
        np.save(f, np.array([object()]), allow_pickle=True)
    with pytest.raises(ValueError):
        clone.load_codes(vid)


def test_the_browser_links_to_your_own_voice(data, qtbot):
    from ttspython.ui.voice_browser import VoiceBrowser

    dlg = VoiceBrowser()
    qtbot.addWidget(dlg)
    with qtbot.waitSignal(dlg.make_own_voice, timeout=1000):
        dlg.own_btn.click()



# --- in the app ---------------------------------------------------------------------------------
@pytest.fixture
def app(model, qtbot, tmp_path):
    from test_ui import make_controller

    controller = make_controller(qtbot, tmp_path)
    yield controller
    controller.quit()


def test_the_window_opens_from_get_more_voices_and_only_once(app, qtbot):
    app.open_voice_browser()
    app._voice_browser.own_btn.click()
    first = app._clone_dialog
    assert first is not None and first.isVisible()
    app.open_clone_dialog()
    assert app._clone_dialog is first
    with qtbot.waitSignal(first.destroyed, timeout=2000):
        first.close()
    assert app._clone_dialog is None


def test_hearing_a_voice_only_tries_it(app, qtbot):
    saved = app.settings["tts_voice_id"]
    vid = voice()
    app.open_clone_dialog()
    dlg = app._clone_dialog
    dlg.hear_btn.click()
    assert app.speech.voice_id == vid and app.settings["tts_voice_id"] == saved
    with qtbot.waitSignal(dlg.destroyed, timeout=2000):
        dlg.close()
    assert app.speech.voice_id == saved


def test_using_a_voice_saves_it(app, monkeypatch):
    vid = voice()
    switched = []
    monkeypatch.setattr(app.speech, "set_voice", switched.append)
    app.open_clone_dialog()
    app._clone_dialog._hear()
    app._clone_dialog.use_btn.click()
    assert app.settings["tts_voice_id"] == vid and switched[-1] == vid
    assert app._hearing_clone is False  # closing the window now leaves it in use


def test_recording_stops_speech_in_the_app(app, qtbot):
    app.open_clone_dialog()
    dlg = app._clone_dialog
    app.speech.speak("Some text to read for a while.")
    dlg._recorder = FakeRecorder()
    dlg.record_btn.click()
    assert dlg._recorder.running
    qtbot.waitUntil(lambda: not app.speech.busy, timeout=3000)
    dlg.close()


def test_a_notice_shows_only_while_your_voice_loads(app, monkeypatch):
    app.speech.voice_id = "clone:0123456789ab"
    assert app._your_voice_is_loading()
    monkeypatch.setattr(clone, "_engine", object())
    assert not app._your_voice_is_loading()
    monkeypatch.setattr(clone, "_engine", None)
    app.speech.voice_id = "v-zira"
    assert not app._your_voice_is_loading()
