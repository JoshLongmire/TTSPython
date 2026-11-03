"""Opt-in checks against the real speech engine and audio device.

Run with: python -m pytest -m audio
"""
import threading
import time

import pytest

from ttspython.core.platform import com_apartment
from ttspython.core.tts.controller import SpeechController, State
from ttspython.core.tts.render import Cancelled, create_renderer

pytestmark = pytest.mark.audio


def test_real_renderer_soak_200_chunks():
    with com_apartment():
        renderer = create_renderer()
        voices = renderer.list_voices()
        assert voices
        cancel = threading.Event()
        for i in range(200):
            pcm, rate = renderer.render(f"Sentence number {i}.", voices[0].id, 200, cancel)
            assert pcm.size > rate * 0.2


def test_real_cancel_is_fast():
    with com_apartment():
        renderer = create_renderer()
        cancel = threading.Event()
        threading.Timer(0.05, cancel.set).start()
        start = time.perf_counter()
        with pytest.raises(Cancelled):
            renderer.render("word " * 2000, "", 200, cancel)
        assert time.perf_counter() - start < 0.5


def test_real_playback_time_to_first_chunk():
    ctl = SpeechController()
    assert ctl.wait_ready(10)
    started = threading.Event()
    done = threading.Event()
    ctl.events.on("chunk_started", lambda *a: started.set())
    ctl.events.on("utterance_finished", lambda *a: done.set())
    t0 = time.perf_counter()
    assert ctl.speak("Testing one two three.")
    assert started.wait(5)
    first = time.perf_counter() - t0
    assert done.wait(10)
    ctl.shutdown()
    print(f"time to first chunk: {first * 1000:.0f} ms")
    assert first < 0.5
    assert ctl.state is State.IDLE
