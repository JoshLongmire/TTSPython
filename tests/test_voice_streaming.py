"""Your own voice is heard while it is being made, instead of after a whole sentence is finished."""
import os
import queue
import threading
import time

import numpy as np
import pytest

from fakes import FakeSD, wait_for
from ttspython.core.resample import StreamResampler, resample
from ttspython.core.tts import clone
from ttspython.core.tts.controller import SpeechController, State, enough_to_play
from ttspython.core.tts.player import AudioPlayer, Marker
from ttspython.core.tts.render import AudioBlock, Cancelled, MultiRenderer, Voice
from ttspython.core.tts.stretch import Stretcher

RATE = 22050


def tone(seconds, rate=RATE, hz=220.0, start=0):
    t = (start + np.arange(int(seconds * rate))) / rate
    return (0.5 * np.sin(2 * np.pi * hz * t)).astype(np.float32)


# --- changing the sample rate block by block -------------------------------------------------------
@pytest.mark.parametrize("block", [1, 37, 512, 30720])
def test_blocks_give_the_same_sound_as_one_whole_buffer(block):
    x = tone(2.0, 48000)
    r = StreamResampler(48000, 22050)
    parts = [r.feed(x[i:i + block]) for i in range(0, x.size, block)]
    parts.append(r.finish())
    out = np.concatenate(parts)
    whole = resample(x, 48000, 22050)
    assert abs(out.size - whole.size) <= 2
    n = min(out.size, whole.size) - 40  # away from the very end, where each treats the edge its own way
    assert np.abs(out[40:n] - whole[40:n]).max() < 2e-3


def test_nothing_is_heard_where_two_blocks_meet():
    x = tone(1.0, 48000)
    r = StreamResampler(48000, 22050)
    out = np.concatenate([r.feed(x[i:i + 2000]) for i in range(0, x.size, 2000)])
    largest_natural_step = 0.5 * 2 * np.pi * 220 / 22050
    assert np.abs(np.diff(out)).max() < largest_natural_step * 1.1


def test_the_same_rate_passes_through_and_going_up_works():
    x = tone(0.1, 22050)
    r = StreamResampler(22050, 22050)
    assert r.feed(x) is x and r.finish().size == 0
    up = StreamResampler(22050, 48000)
    out = np.concatenate([up.feed(x[:1000]), up.feed(x[1000:]), up.finish()])
    assert abs(out.size - x.size * 48000 / 22050) <= 3


# --- playing a buffer that is still growing ------------------------------------------------------------
def read_all(s, n, factor=1.0):
    out = np.zeros(n, dtype=np.float32)
    return out[:s.read(out, factor)]


def test_growing_audio_comes_out_exactly_as_made_at_normal_speed():
    x = tone(1.0)
    s = Stretcher(np.zeros(0, dtype=np.float32), RATE, growing=True)
    heard = []
    for i in range(0, x.size, 3000):
        s.grow(x[:i + 3000])
        heard.append(read_all(s, 2000))
    s.end()
    while not s.done:
        heard.append(read_all(s, 2000))
    out = np.concatenate(heard)
    assert out.size >= x.size * 0.99
    # There is enough each time here, so nothing fades: only the small head start and the end differ.
    assert np.abs(out[:x.size - 1000] - x[:x.size - 1000]).max() < 1e-5


def test_running_out_fades_out_waits_and_comes_back_from_the_same_place():
    x = tone(1.0)
    s = Stretcher(x[:4000], RATE, growing=True)
    first = read_all(s, 8000)
    assert s.starved and s.ran_out and not s.done
    assert 2000 < first.size <= 4000
    assert abs(first[-1]) < 0.02  # no click: it faded out
    at = s.pos
    assert read_all(s, 500).size == 0  # waiting, and not losing its place
    assert s.pos == at
    s.grow(x[:12000])
    back = read_all(s, 500)
    assert back.size == 500 and not s.starved
    assert abs(back[0]) < 0.02  # and it fades back in


def test_the_last_of_it_plays_once_nothing_more_is_coming():
    x = tone(0.1)
    s = Stretcher(x, RATE, growing=True)
    out = [read_all(s, 10000)]
    assert s.ran_out
    s.end()
    assert not s.done
    out.append(read_all(s, 10000))
    assert s.done
    frame = s.n
    assert x.size * 0.95 < sum(p.size for p in out) <= x.size + 2 * frame  # the fade repeats half a frame, the last one pads


def test_a_chunk_with_no_sound_at_all_ends():
    s = Stretcher(np.zeros(0, dtype=np.float32), RATE, growing=True)
    assert not s.done
    s.end()
    assert s.done


def test_it_keeps_its_speed_while_growing():
    x = tone(2.0)
    s = Stretcher(x[:RATE // 2], RATE, growing=True)
    made = [read_all(s, 2000, 1.5)]
    s.grow(x)
    s.end()
    while not s.done:
        made.append(read_all(s, 2000, 1.5))
    assert abs(sum(p.size for p in made) / (x.size / 1.5) - 1) < 0.03


# --- when to start ------------------------------------------------------------------------------------
def test_a_fast_computer_starts_on_the_first_block():
    assert enough_to_play(buffered=0.64, left=3.0, speed=2.2, factor=1.0, next_block=0.64)


def test_a_block_is_not_enough_if_the_next_one_would_come_too_late():
    assert not enough_to_play(buffered=0.32, left=3.0, speed=1.2, factor=1.0, next_block=0.64)


def test_a_computer_slower_than_playback_waits_up_front_until_it_will_finish_in_time():
    assert not enough_to_play(buffered=1.0, left=5.0, speed=0.7, factor=1.0, next_block=0.64)
    # 5 s at 0.7x takes 7.1 s, 8.9 s with the margin: it needs that much listening in hand.
    assert enough_to_play(buffered=4.0, left=5.0, speed=0.7, factor=1.0, next_block=0.64)


def test_listening_faster_needs_more_in_hand():
    args = dict(buffered=1.0, left=4.0, speed=1.3, next_block=0.64)
    assert enough_to_play(factor=1.0, **args)
    assert not enough_to_play(factor=1.6, **args)


def test_it_never_starts_without_knowing_the_speed():
    assert not enough_to_play(buffered=5.0, left=1.0, speed=0.0, factor=1.0, next_block=0.64)


# --- the player -----------------------------------------------------------------------------------
@pytest.fixture
def player():
    p = AudioPlayer(queue.Queue(), sd_module=FakeSD(speed=20.0), idle_close=30)
    yield p
    p.close()


def pcm(seconds, rate=RATE):
    return (tone(seconds, rate) * 32767).astype(np.int16)


def marker(index=0, generation=0):
    return Marker(utt_id=1, index=index, total=2, generation=generation)


def test_a_held_chunk_stays_silent_and_unannounced(player):
    feed = player.open_feed(RATE, marker(), 200, 1.0)
    feed.add(pcm(0.5))
    time.sleep(0.05)
    assert feed.waiting
    assert player._events.empty()
    assert player.position(1) is None
    feed.release()
    assert wait_for(lambda: not player._events.empty(), timeout=2)
    assert player._events.get()[0] == "chunk"
    feed.finish()


def test_waiting_for_speech_is_not_taken_for_a_stuck_device(player):
    feed = player.open_feed(RATE, marker(), 200, 1.0)
    time.sleep(0.1)
    assert not player.stalled(0.05)
    feed.finish()


def test_running_out_is_counted_and_holds_until_released(player):
    feed = player.open_feed(RATE, marker(), 200, 3.0)
    feed.add(pcm(0.1))
    feed.release()
    assert wait_for(lambda: player.starved == 1, timeout=2)
    assert feed.waiting
    feed.add(pcm(0.1))
    time.sleep(0.03)
    assert player.starved == 1  # more audio alone does not start it again...
    feed.release()  # ...so that it does not stutter a little at a time
    feed.finish()
    assert wait_for(lambda: player.pending_count() == 0, timeout=5)
    assert player.callback_errors == 0


def test_the_speed_slider_is_followed_while_it_is_being_made(player):
    feed = player.open_feed(RATE, marker(), 180, 1.0)
    player.set_target_wpm(360)
    assert feed.factor == 2.0
    feed.add(pcm(0.2))
    feed.finish()
    assert feed.factor == 2.0


def test_how_far_along_uses_the_expected_length_until_it_is_finished(player):
    feed = player.open_feed(RATE, marker(), 200, 10.0)
    feed.add(pcm(1.0))
    seg = feed._segment
    seg.stretcher.pos = RATE / 2
    assert seg.fraction() == pytest.approx(0.05)
    feed.finish()
    assert seg.fraction() == pytest.approx(0.5, abs=0.02)


def test_a_stopped_job_cannot_open_a_feed(player):
    player.flush(min_generation=3)
    assert player.open_feed(RATE, marker(generation=2), 200) is None


def test_stop_drops_a_chunk_being_made_and_more_of_it_does_no_harm(player):
    feed = player.open_feed(RATE, marker(), 200, 1.0)
    feed.add(pcm(0.5))
    feed.release()
    player.flush(min_generation=5)
    assert player.pending_count() == 0
    feed.add(pcm(0.5))
    feed.finish()
    assert player.pending_count() == 0 and player.callback_errors == 0


def test_a_chunk_that_lost_its_stretcher_still_plays_what_is_still_coming(player):
    feed = player.open_feed(RATE, marker(), 200, 1.0)
    feed.add(pcm(0.05))
    seg = feed._segment
    seg.stretcher = None
    feed.release()
    feed.add(pcm(0.05))
    time.sleep(0.1)
    assert player.pending_count() == 1  # played what there is, and it waits for the rest
    feed.finish()
    assert wait_for(lambda: player.pending_count() == 0, timeout=2)


# --- the controller -----------------------------------------------------------------------------------
class StreamingRenderer:
    """Makes audio in blocks, slowly, as the voice model does, for voices named stream-*."""

    name = "fake"
    sample_rate = RATE

    def __init__(self, blocks=8, block_seconds=0.25, delay=0.02, native=200, fail_after=None):
        self.blocks, self.block_seconds, self.delay = blocks, block_seconds, delay
        self.native = native
        self.fail_after = fail_after
        self.closed = threading.Event()
        self.started = []
        self.plain = []
        self.finished_block_at = None

    def list_voices(self):
        return [Voice("stream-a", "A"), Voice("stream-b", "B")]

    def native_wpm(self, wpm, voice_id=None):
        return self.native

    def streams(self, voice_id):
        return voice_id.startswith("stream")

    def render(self, text, voice_id, wpm, cancel):
        self.plain.append(voice_id)
        return pcm(0.05), RATE

    def stream(self, text, voice_id, wpm, cancel):
        self.closed.clear()
        self.started.append((text, voice_id))
        try:
            for i in range(self.blocks):
                end = time.monotonic() + self.delay
                while time.monotonic() < end:
                    if cancel.is_set():
                        raise Cancelled()
                    time.sleep(0.002)
                if self.fail_after == i:
                    raise RuntimeError("The model broke.")
                left = (self.blocks - i - 1) * self.block_seconds
                yield AudioBlock(pcm(self.block_seconds), RATE, left, self.block_seconds / self.delay, self.block_seconds)
            self.finished_block_at = time.monotonic()
        finally:
            self.closed.set()


class Rig:
    def __init__(self, voice="stream-a", speed=1.0, **renderer):
        self.renderer = StreamingRenderer(**renderer)
        self.player = AudioPlayer(queue.Queue(), sd_module=FakeSD(speed=speed), idle_close=30)
        self.ctl = SpeechController(renderer_factory=lambda: self.renderer, player=self.player, voice_id=voice)
        assert self.ctl.wait_ready(5)
        self.ctl.voice_id = voice
        self.renderer.plain.clear()  # the warm-up at start
        self.chunks, self.errors, self.finished = [], [], []
        self.ctl.events.on("chunk_started", lambda *a: self.chunks.append(a))
        self.ctl.events.on("error", self.errors.append)
        self.ctl.events.on("utterance_finished", lambda *a: self.finished.append(a))

    def close(self):
        self.ctl.shutdown()


@pytest.fixture
def rig():
    made = []

    def make(**kwargs):
        made.append(Rig(**kwargs))
        return made[-1]

    yield make
    for r in made:
        r.close()


def test_sound_starts_long_before_the_sentence_is_finished(rig):
    r = rig(blocks=10, block_seconds=0.2, delay=0.1)
    t0 = time.monotonic()
    r.ctl.speak("A sentence that takes a second to make.")
    assert wait_for(lambda: bool(r.chunks), timeout=5, interval=0.005)
    first_sound = time.monotonic() - t0
    assert first_sound < 0.5  # all ten blocks would take a second to make
    assert r.renderer.finished_block_at is None  # still being made
    assert r.ctl.state is State.PLAYING
    assert wait_for(lambda: bool(r.finished), timeout=8)
    assert r.player.starved == 0 and r.errors == []


def test_all_of_it_is_played_in_order_to_the_end(rig):
    r = rig(speed=20.0)
    r.ctl.speak("First sentence is right here. Second sentence is right here.")
    assert wait_for(lambda: bool(r.finished), timeout=8)
    assert [c[3] for c in r.chunks] == [0, 1]
    assert r.finished[0][1] is False
    assert r.renderer.plain == []  # only the system voices render a chunk in one go


def test_stop_ends_it_within_a_block_and_gives_the_model_back(rig):
    r = rig(blocks=100, delay=0.05)
    r.ctl.speak("A long sentence being made.")
    assert wait_for(lambda: bool(r.chunks), timeout=5)
    t0 = time.monotonic()
    assert r.ctl.stop()
    assert time.monotonic() - t0 < 0.2
    assert r.renderer.closed.is_set()
    assert r.player.pending_count() == 0
    assert r.errors == []


def test_a_voice_change_takes_over_without_waiting_for_the_sentence(rig):
    r = rig(blocks=100, delay=0.05)
    r.ctl.speak("A long sentence being made, one that goes on for quite a while.")
    assert wait_for(lambda: bool(r.chunks), timeout=5)
    r.ctl.set_voice("stream-b")
    assert wait_for(lambda: any(v == "stream-b" for _t, v in r.renderer.started), timeout=1)
    r.ctl.stop()
    assert r.errors == []


def test_a_change_to_a_system_voice_goes_back_to_whole_chunks(rig):
    r = rig(blocks=100, delay=0.05)
    r.ctl.speak("A long sentence being made, one that goes on for quite a while.")
    assert wait_for(lambda: bool(r.chunks), timeout=5)
    r.ctl.set_voice("plain")
    assert wait_for(lambda: "plain" in r.renderer.plain, timeout=2)
    r.ctl.stop()


def test_a_failure_part_way_tells_the_person_and_leaves_nothing_stuck(rig):
    r = rig(blocks=20, fail_after=3, delay=0.01)
    r.ctl.speak("A sentence that will not make it.")
    assert wait_for(lambda: bool(r.errors), timeout=5)
    assert "broke" in r.errors[0]
    assert wait_for(lambda: r.ctl.state is State.IDLE, timeout=3)
    assert r.player.pending_count() == 0
    assert r.renderer.closed.is_set()


def test_a_slow_model_waits_up_front_and_does_not_run_out(rig):
    # Half as fast as it plays, and the renderer says so.
    r = rig(blocks=6, block_seconds=0.1, delay=0.2)
    r.ctl.speak("A sentence on a slow computer.")
    assert wait_for(lambda: bool(r.finished), timeout=10)
    assert r.player.starved == 0


def test_playing_stops_for_a_moment_if_the_model_falls_behind_then_carries_on(rig):
    # It claims to be fast, then falls behind.
    r = rig(blocks=5, block_seconds=0.15, delay=0.01)
    original = r.renderer.stream

    def stutter(text, voice_id, wpm, cancel):
        for i, block in enumerate(original(text, voice_id, wpm, cancel)):
            if i == 2:
                time.sleep(0.5)
            yield block

    r.renderer.stream = stutter
    r.ctl.speak("A sentence with a hiccup.")
    assert wait_for(lambda: bool(r.finished), timeout=10)
    assert r.player.starved >= 1
    assert r.errors == [] and r.player.callback_errors == 0
    assert r.finished[0][1] is False


# --- the voice model ----------------------------------------------------------------------------------
class Blocks:
    rate = 48000

    def __init__(self, seconds=(0.64, 0.64), left=1.0):
        self.seconds, self.left = seconds, left
        self.speed = 2.2

    def speak_blocks(self, codes, text, cancel, pace=None, hold=False):
        for s in self.seconds:
            if cancel.is_set():
                raise Cancelled()
            yield tone(s, self.rate), self.left


@pytest.fixture
def voice(tmp_path, monkeypatch):
    monkeypatch.setenv("TTSPYTHON_DATA", str(tmp_path))
    folder = os.path.join(str(tmp_path), "clone-model")
    os.makedirs(folder)
    monkeypatch.setattr(clone, "model_installed", lambda: True)
    consent = clone.Consent("words", ("a", "b", "c"))
    monkeypatch.setattr(clone, "check_recording", lambda *_a: "")
    monkeypatch.setattr(clone, "check_consent", lambda *_a: "")

    class Encoder:
        def encode(self, audio, rate):
            return np.zeros((5, 16), dtype=np.int32)

    yield clone.build_voice("Mine", consent, tone(7, 16000), 16000, "words", Encoder())
    clone.release_engine()


def test_blocks_arrive_as_they_are_made_and_the_model_is_given_back(voice):
    r = clone.CloneRenderer(lambda: Blocks())
    gen = r.stream("Hello there.", voice, 200, threading.Event())
    first = next(gen)
    assert isinstance(first, AudioBlock)
    assert first.rate == 48000 and first.pcm.dtype == np.int16 and first.speed == 2.2 and first.left == 1.0
    assert first.next_block == pytest.approx(0.64)
    held = threading.Event()

    def try_lock():
        if clone._engine_lock.acquire(timeout=0.01):
            clone._engine_lock.release()
            held.set()

    other = threading.Thread(target=try_lock)
    other.start()
    other.join()
    assert not held.is_set()  # the model is taken while the sentence is being made
    gen.close()
    other = threading.Thread(target=try_lock)
    other.start()
    other.join()
    assert held.is_set()


def test_the_pace_is_measured_from_the_whole_chunk(voice):
    r = clone.CloneRenderer(lambda: Blocks((2.0, 2.0)))
    list(r.stream("One two three four five six seven eight nine ten.", voice, 200, threading.Event()))
    assert r.native_wpm(200, voice) == 150


def test_a_chunk_stopped_part_way_is_not_measured(voice):
    r = clone.CloneRenderer(lambda: Blocks((2.0, 2.0)))
    gen = r.stream("One two three four five six seven eight nine ten.", voice, 200, threading.Event())
    next(gen)
    gen.close()
    assert r.native_wpm(200, voice) == clone.FALLBACK_WPM


def test_nothing_to_say_still_gives_one_block(voice):
    assert len(list(clone.CloneRenderer(lambda: Blocks()).stream("...", voice, 200, threading.Event()))) == 1
    silent = Blocks(())
    assert list(clone.CloneRenderer(lambda: silent).stream("Hello.", voice, 200, threading.Event()))[0].pcm.size == 0


def test_stream_says_what_is_wrong_on_the_first_block(voice, monkeypatch):
    monkeypatch.setattr(clone, "model_installed", lambda: False)
    with pytest.raises(RuntimeError, match="not downloaded"):
        next(clone.CloneRenderer(lambda: Blocks()).stream("Hello.", voice, 200, threading.Event()))


def test_only_your_voices_stream(voice):
    class System:
        name = "s"
        sample_rate = RATE

        def list_voices(self):
            return []

        def render(self, *_a):
            return pcm(0.1), RATE

    m = MultiRenderer(System(), piper=System(), system_voices=[], clone=clone.CloneRenderer(lambda: Blocks()))
    assert m.streams(voice)
    assert not m.streams("piper:en_US-lessac-medium") and not m.streams("v-zira") and not m.streams("")
    assert len(list(m.stream("Hello.", voice, 200, threading.Event()))) == 2


def make_real_shaped_engine(frames):
    """A real Engine with the graphs replaced: see test_clone.py."""
    from test_clone import fake_engine
    return fake_engine(frames_until_end=frames)


CODES = np.zeros((5, 16), dtype=np.int32)


def test_the_model_hands_over_every_eight_frames():
    engine = make_real_shaped_engine(20)
    blocks = list(engine._piece_blocks(CODES, list(range(10)), threading.Event()))
    assert [b.size for b in blocks] == [8 * 3840, 8 * 3840, 4 * 3840]
    assert engine.speed > 0


def test_blocks_add_up_to_the_same_length_as_speaking_in_one_go():
    text = "word " * 200
    together = make_real_shaped_engine(30).speak(CODES, text, threading.Event())
    blocks = [b for b, _left in make_real_shaped_engine(30).speak_blocks(CODES, text, threading.Event())]
    assert sum(b.size for b in blocks) == together.size


def test_seconds_left_counts_down_and_never_goes_below_zero():
    engine = make_real_shaped_engine(10**9)
    lefts = [left for _b, left in engine.speak_blocks(CODES, "one two three four five", threading.Event())]
    assert lefts == sorted(lefts, reverse=True)
    assert lefts[-1] == 0.0 and lefts[0] > 0


def test_stop_ends_the_blocks_within_a_frame():
    cancel = threading.Event()
    from test_clone import fake_engine
    engine = fake_engine(on_frame=lambda n: cancel.set() if n == 11 else None)
    with pytest.raises(Cancelled):
        list(engine.speak_blocks(CODES, "one two three four five", cancel))
    assert engine._frame.calls == 11


def test_the_encoder_only_loads_when_a_voice_is_made():
    engine = make_real_shaped_engine(5)
    engine._audio_encoder = None
    opened = []

    class Encoder:
        def run(self, _o, _f):
            return [np.zeros((1, 2, 16), dtype=np.int32), np.asarray([2])]

        def get_outputs(self):
            class Name:
                def __init__(self, name):
                    self.name = name
            return [Name("audio_codes"), Name("audio_code_lengths")]

    def open_encoder():
        opened.append(1)
        return Encoder()

    engine._open_encoder = open_encoder
    list(engine._piece_blocks(CODES, [1, 2], threading.Event()))
    assert not opened
    engine.encode(tone(0.1, 48000), 48000)
    engine.encode(tone(0.1, 48000), 48000)
    assert len(opened) == 1
