import math
import os
import queue
import struct
import threading
import time

import numpy as np
import pytest

from fakes import FakeRenderer, FakeSD, wait_for
from ttspython.core.queue_model import SpeechQueue
from ttspython.core.tts import export as export_mod
from ttspython.core.tts.controller import SpeechController, State, Source
from ttspython.core.tts.player import AudioPlayer, Marker
from ttspython.core.tts.render import sapi_rate, trim_leading_silence, pick_default_voice, Voice
from ttspython.core.tts.wavparse import parse_wav

LONG_TEXT = " ".join(f"This is sentence number {i} in a long passage." for i in range(40))


class Rig:
    def __init__(self, render_delay=0.0, seconds=0.05, speed=20.0, **sd_kwargs):
        self.sd = FakeSD(speed=speed, **sd_kwargs)
        self.renderer = None
        self.queue = SpeechQueue()

        def factory():
            self.renderer = FakeRenderer(seconds, render_delay)
            return self.renderer

        self.player = AudioPlayer(queue.Queue(), sd_module=self.sd, idle_close=30)
        self.ctl = SpeechController(self.queue, renderer_factory=factory, player=self.player)
        assert self.ctl.wait_ready(5)
        self.log = []
        for name in ("state_changed", "chunk_started", "queue_item_started", "utterance_finished",
                     "queue_finished", "error"):
            self.ctl.events.on(name, lambda *a, n=name: self.log.append((n,) + a))

    def names(self, name):
        return [e for e in self.log if e[0] == name]

    def close(self):
        self.ctl.shutdown()


@pytest.fixture
def rig():
    r = Rig()
    yield r
    r.close()


def test_voices_and_default_pick(rig):
    assert [v.id for v in rig.ctl.voices] == ["v-david", "v-zira"]
    assert rig.ctl.voice_id == "v-zira"  # v4 picked a female/Zira voice by default


def test_speak_plays_every_chunk_in_order(rig):
    assert rig.ctl.speak("One sentence here. Another sentence there. And a third one now.")
    assert wait_for(lambda: rig.names("utterance_finished"))
    assert wait_for(lambda: rig.ctl.state is State.IDLE)
    starts = rig.names("chunk_started")
    assert [e[4] for e in starts] == list(range(len(starts)))
    assert rig.names("utterance_finished")[0][2] is False


def test_speak_while_busy_is_refused_without_overlap(rig):
    rig.ctl.speak(LONG_TEXT)
    assert wait_for(lambda: rig.ctl.state is State.PLAYING)
    assert rig.ctl.speak("Second request text.") is False
    rig.ctl.stop()
    assert rig.renderer.max_active == 1
    assert rig.sd.max_open == 1


def test_stop_returns_only_after_worker_is_idle(rig):
    rig.ctl.speak(LONG_TEXT)
    assert wait_for(lambda: rig.ctl.state is State.PLAYING)
    assert rig.ctl.stop() is True
    assert rig.ctl.state is State.IDLE
    assert rig.renderer.active == 0
    rendered = len(rig.renderer.rendered)
    time.sleep(0.15)
    assert len(rig.renderer.rendered) == rendered


def test_replace_stops_then_speaks(rig):
    rig.ctl.speak(LONG_TEXT)
    assert wait_for(lambda: rig.ctl.state is State.PLAYING)
    assert rig.ctl.speak("Replacement text goes here.", replace=True)
    assert wait_for(lambda: any(e[2] is False for e in rig.names("utterance_finished")))
    assert rig.renderer.max_active == 1
    assert rig.renderer.rendered[-1][0] == "Replacement text goes here."


def test_pause_holds_position_and_resume_finishes(rig):
    rig.ctl.speak("First part of it. Second part of it. Third part of it. Fourth part of it.")
    assert wait_for(lambda: rig.ctl.state is State.PLAYING)
    rig.ctl.pause()
    assert rig.ctl.state is State.PAUSED
    time.sleep(0.05)  # an audio callback already in flight may finish its block
    count = len(rig.names("chunk_started"))
    time.sleep(0.2)
    assert len(rig.names("chunk_started")) == count
    rig.ctl.resume()
    assert wait_for(lambda: rig.names("utterance_finished"))


def test_base_offset_reaches_chunk_events(rig):
    rig.ctl.speak("Selected words here.", source=Source.SELECTION, base16=100)
    assert wait_for(lambda: rig.names("chunk_started"))
    _, utt, pos16, end16, idx, total, source = rig.names("chunk_started")[0]
    assert pos16 == 100 and end16 == 100 + len("Selected words here.")
    assert source is Source.SELECTION


def _queue_items(rig, n):
    return [rig.queue.add(f"Queue item {i} text.", f"Item {i}") for i in range(n)]


def test_queue_plays_in_order_once(rig):
    items = _queue_items(rig, 3)
    assert rig.ctl.play_queue()
    assert wait_for(lambda: rig.names("queue_finished"))
    assert [e[1] for e in rig.names("queue_item_started")] == [i.id for i in items]
    assert rig.names("queue_finished")[0][1] is False


def test_bug01_auto_queue_plays_each_item_once(rig):
    a, b = _queue_items(rig, 2)
    rig.ctl.auto_queue = True
    rig.ctl.play_queue()
    assert wait_for(lambda: rig.names("queue_finished"))
    time.sleep(0.3)
    assert [e[1] for e in rig.names("queue_item_started")] == [a.id, b.id]
    rig.ctl.speak("A new sentence after the queue.")
    assert wait_for(lambda: len(rig.names("utterance_finished")) >= 3)
    time.sleep(0.3)
    assert len(rig.names("queue_item_started")) == 2  # already-played items are not replayed
    c = rig.queue.add("Freshly copied text.", "New")
    rig.ctl.speak("Another sentence.")
    assert wait_for(lambda: len(rig.names("queue_item_started")) == 3)
    assert rig.names("queue_item_started")[-1][1] == c.id  # only the new item auto-plays


def test_bug12_removing_the_playing_last_item_ends_the_queue():
    slow = Rig(seconds=0.4)
    try:
        a, b = (slow.queue.add(f"Item {i} text here.", f"Item {i}") for i in range(2))
        slow.ctl.play_queue()
        assert wait_for(lambda: len(slow.names("queue_item_started")) == 2, timeout=10)
        slow.queue.remove(b.id)
        assert wait_for(lambda: slow.names("queue_finished"), timeout=10)
        assert [e[1] for e in slow.names("queue_item_started")] == [a.id, b.id]
    finally:
        slow.close()


def test_queue_loop_wraps_until_stopped(rig):
    _queue_items(rig, 2)
    rig.ctl.loop = True
    rig.ctl.play_queue()
    assert wait_for(lambda: len(rig.names("queue_item_started")) >= 5)
    rig.ctl.stop()
    assert rig.ctl.state is State.IDLE


def test_remove_and_reorder_during_playback(rig):
    a, b, c, d = _queue_items(rig, 4)
    slow = Rig(seconds=0.4)
    try:
        items = [slow.queue.add(f"Item {i} text here.", f"Item {i}") for i in range(4)]
        slow.ctl.play_queue()
        assert wait_for(lambda: slow.names("queue_item_started"))
        slow.queue.remove(items[1].id)
        slow.queue.move(items[3].id, -1)  # order now 0, 3, 2
        assert wait_for(lambda: slow.names("queue_finished"), timeout=10)
        assert [e[1] for e in slow.names("queue_item_started")] == [items[0].id, items[3].id, items[2].id]
    finally:
        slow.close()


def test_set_volume_is_instant_gain():
    events = queue.Queue()
    sd = FakeSD(speed=50)
    sd.capture = True
    player = AudioPlayer(events, sd_module=sd)
    player.set_gain(0.25)
    pcm = np.full(2048, 16384, dtype=np.int16)
    player.enqueue(pcm, 22050, Marker(utt_id=1))
    assert wait_for(lambda: player.pending_count() == 0)
    stream = sd.streams[0]
    peak = max(float(np.abs(block).max()) for block in stream.output if block.size)
    assert abs(peak - 0.125) < 1e-3
    player.close()


def test_same_output_device_does_not_interrupt_speech(rig):
    rig.ctl.speak(LONG_TEXT)
    assert wait_for(lambda: rig.ctl.state is State.PLAYING)
    rig.ctl.set_output_device(None)  # unchanged: keep speaking
    assert rig.ctl.state is State.PLAYING
    rig.ctl.set_output_device(4)  # changed: the stream must reopen
    assert rig.ctl.state is State.IDLE
    assert rig.player.device == 4


def test_output_device_is_used_and_rate_fallback():
    sd = FakeSD(reject_rates={22050}, default_rate=48000)
    player = AudioPlayer(queue.Queue(), sd_module=sd)
    player.set_device(7)
    player.wait_open()
    assert sd.streams[-1].device == 7
    assert player.stream_rate == 48000
    player.close()


def test_rate_uses_the_nearest_sapi_step():
    from ttspython.core.tts.render import SapiRenderer

    for wpm in (100, 150, 200, 250):
        assert sapi_rate(wpm) == int(math.log(wpm / 156.63, 1.11))  # v4's speeds are unchanged
    for wpm in range(100, 401):
        native = SapiRenderer.native_wpm(wpm)
        assert abs(native / wpm - 1) < 0.056  # the player stretches the rest (at most half a step)


def test_default_voice_prefers_saved():
    voices = [Voice("a", "A"), Voice("b", "Zira")]
    assert pick_default_voice(voices, "a") == "a"
    assert pick_default_voice(voices, "missing") == "b"
    assert pick_default_voice([], "") == ""


def test_trim_leading_silence():
    pcm = np.concatenate([np.zeros(22050, dtype=np.int16), np.full(100, 5000, dtype=np.int16)])
    trimmed = trim_leading_silence(pcm, 22050)
    assert len(pcm) - len(trimmed) == int(0.3 * 22050)


def test_wav_parser_tolerates_streamed_sizes():
    samples = (np.arange(100) * 10).astype(np.int16)
    header = b"RIFF" + struct.pack("<I", 0xFFFFFFFF) + b"WAVE"
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 22050, 44100, 2, 16)
    data = b"data" + struct.pack("<I", 0xFFFFFFFF) + samples.tobytes()
    out, rate = parse_wav(header + fmt + data)
    assert rate == 22050 and np.array_equal(out, samples)


def _export(tmp_path, name):
    exporter = export_mod.AudioExporter(renderer_factory=lambda: FakeRenderer(0.1))
    done = threading.Event()
    result = {}
    exporter.events.on("finished", lambda p: (result.setdefault("path", p), done.set()))
    exporter.events.on("failed", lambda m: (result.setdefault("error", m), done.set()))
    path = str(tmp_path / name)
    assert exporter.start("Hello there. This is an export test.", path, "", 200, 0.8)
    assert done.wait(10)
    return result, path


def test_export_wav(tmp_path):
    result, path = _export(tmp_path, "out.wav")
    assert "error" not in result
    data = open(path, "rb").read()
    assert data[:4] == b"RIFF"
    assert not os.path.exists(path + ".part")


def test_export_mp3_is_real_mp3(tmp_path):
    result, path = _export(tmp_path, "out.mp3")
    assert "error" not in result
    data = open(path, "rb").read()
    assert data[:4] != b"RIFF"
    assert data[:3] == b"ID3" or (data[0] == 0xFF and (data[1] & 0xE0) == 0xE0)
