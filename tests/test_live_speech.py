"""Speed and voice changes are heard while speaking, not at the next chunk."""
import time

import numpy as np
import pytest

from fakes import wait_for
from test_speech_engine import Rig
from ttspython.core.tts.controller import State
from ttspython.core.tts.stretch import DEAD_ZONE, Stretcher, speed_factor, stretch

RATE = 22050


def dominant_hz(x):
    spec = np.abs(np.fft.rfft(x * np.hanning(x.size)))
    return np.argmax(spec) * RATE / x.size


@pytest.mark.parametrize("factor", [0.5, 0.75, 1.25, 1.5, 2.0])
def test_stretch_changes_length_but_not_pitch(factor):
    t = np.arange(RATE * 2) / RATE
    voice_like = (0.5 * np.sin(2 * np.pi * 180 * t) + 0.25 * np.sin(2 * np.pi * 360 * t)).astype(np.float32)
    out = stretch(voice_like, factor, RATE)
    assert abs(voice_like.size / out.size / factor - 1) < 0.02
    assert abs(dominant_hz(out) / 180.0 - 1) < 0.03


def test_stretch_is_fast_enough_to_follow_a_slider():
    noise = np.random.default_rng(1).standard_normal(RATE * 15).astype(np.float32) * 0.2  # a 15 s chunk
    t0 = time.perf_counter()
    stretch(noise, 1.5, RATE)
    assert time.perf_counter() - t0 < 0.5


def test_speeds_near_the_engine_rate_are_left_untouched():
    assert speed_factor(200, 200) == 1.0
    assert speed_factor(200 * (1 + DEAD_ZONE * 0.9), 200) == 1.0
    assert speed_factor(300, 200) == 1.5
    assert speed_factor(None, 200) == speed_factor(200, None) == 1.0


def _playing_segment(player):
    with player._lock:
        for seg in player._segments:
            if seg.announced and seg.marker is not None and not seg.marker.end:
                return seg
    return None


def test_speed_change_is_heard_mid_chunk():
    rig = Rig(seconds=4.0, speed=1.0)  # one 4 s chunk playing in real time
    try:
        rig.ctl.speak("A single sentence that plays for a while.")
        assert wait_for(lambda: _playing_segment(rig.player) is not None, timeout=5)
        seg = _playing_segment(rig.player)
        time.sleep(0.3)
        t0 = time.perf_counter()
        rig.ctl.set_rate(400)  # twice as fast
        assert wait_for(lambda: seg.stretcher.factor == 2.0, timeout=2, interval=0.001)
        latency = time.perf_counter() - t0
        assert latency < 0.05  # the next 10 ms hop
        with rig.player._lock:
            left_seconds = seg.remaining(400) / rig.player.stream_rate
        assert left_seconds < 2.0  # about (4 - 0.3 - latency) / 2
        assert seg.fraction() < 1.0  # still mid-chunk: nothing was skipped
    finally:
        rig.close()


def test_slowing_down_keeps_the_place_in_the_sentence():
    rig = Rig(seconds=3.0, speed=1.0)
    try:
        rig.ctl.speak("Another sentence that plays for a while.")
        assert wait_for(lambda: _playing_segment(rig.player) is not None, timeout=5)
        seg = _playing_segment(rig.player)
        time.sleep(0.5)
        before = seg.fraction()
        rig.ctl.set_rate(100)  # half speed
        assert wait_for(lambda: seg.stretcher.factor == 0.5, timeout=2, interval=0.001)
        after = seg.fraction()
        assert 0 <= after - before < 0.15  # continued from where it was, no jump back or ahead
    finally:
        rig.close()


def test_voice_change_restarts_at_the_word_being_heard():
    rig = Rig(seconds=2.0, speed=1.0)
    text = "First words of the sentence. Second sentence follows here. Third sentence ends it."
    try:
        rig.ctl.speak(text)
        assert wait_for(lambda: rig.ctl.state is State.PLAYING, timeout=5)
        time.sleep(1.0)  # about half way through the first chunk
        rig.ctl.set_voice("v-david")
        assert wait_for(lambda: any(r[1] == "v-david" for r in rig.renderer.rendered), timeout=3)
        first_new = next(r[0] for r in rig.renderer.rendered if r[1] == "v-david")
        assert first_new != text.split(". ")[0] + "."  # not from the top of the chunk
        assert first_new.split()[0] in text.split()  # starts on a whole word
        assert text.index(first_new.split()[0]) > 0
        starts = rig.names("chunk_started")
        assert wait_for(lambda: len(rig.names("chunk_started")) > len(starts), timeout=3)
        rig.ctl.stop()
    finally:
        rig.close()


def test_new_audio_arrives_at_the_new_speed():
    rig = Rig(seconds=0.5, speed=1.0)
    try:
        rig.ctl.set_rate(300)
        rig.ctl.speak("Short sentence one. Short sentence two. Short sentence three.")
        assert wait_for(lambda: _playing_segment(rig.player) is not None, timeout=5)
        seg = _playing_segment(rig.player)
        assert seg.native == 300 and seg.stretcher.factor == 1.0  # rendered at 300 by the engine itself
        rig.ctl.stop()
    finally:
        rig.close()


def _play(stretcher, factors, block=256):
    """Read a Stretcher to the end; factors(i) gives the speed for block i."""
    outs = []
    while not stretcher.done:
        buf = np.zeros(block, dtype=np.float32)
        outs.append(buf[:stretcher.read(buf, factors(len(outs)))])
    return np.concatenate(outs)


def _tone(seconds=3.0):
    t = np.arange(int(RATE * seconds)) / RATE
    return (0.5 * np.sin(2 * np.pi * 180 * t) + 0.25 * np.sin(2 * np.pi * 360 * t)).astype(np.float32)


def test_streaming_stretch_at_normal_speed_gives_the_original_back():
    x = _tone()
    y = _play(Stretcher(x, RATE), lambda i: 1.0)
    assert np.abs(y[:x.size] - x).max() < 1e-5


@pytest.mark.parametrize("factor", [0.5, 1.5, 2.0])
def test_streaming_stretch_changes_length_but_not_pitch(factor):
    x = _tone()
    y = _play(Stretcher(x, RATE), lambda i: factor)
    assert abs(x.size / y.size / factor - 1) < 0.02
    assert abs(dominant_hz(y) / 180.0 - 1) < 0.03


def test_streaming_stretch_changes_speed_without_clicks():
    """A slider drag: the speed changes every few blocks, the sound stays smooth."""
    x = _tone()
    y = _play(Stretcher(x, RATE), lambda i: 1.0 + 0.1 * ((i // 3) % 8))
    assert np.abs(np.diff(y)).max() < 1.5 * np.abs(np.diff(x)).max()


def test_drag_is_heard_while_dragging():
    """Every slider step reaches the playing chunk within a hop, not after the drag ends."""
    rig = Rig(seconds=4.0, speed=1.0)
    try:
        rig.ctl.speak("A single sentence that plays for a while.")
        assert wait_for(lambda: _playing_segment(rig.player) is not None, timeout=5)
        seg = _playing_segment(rig.player)
        heard = 0
        for percent in range(105, 165, 5):  # a step every 30 ms, never pausing
            rig.ctl.set_rate(percent * 2)
            if wait_for(lambda p=percent: abs(seg.stretcher.factor - p * 2 / seg.native) < 1e-6,
                        timeout=0.03, interval=0.001):
                heard += 1
        assert heard >= 10  # of 12 steps (a step can land between two hops)
    finally:
        rig.close()
