import numpy as np

from fakes import wait_for
from ttspython.core.stt.service import ModelCache, SttService, SttState


class FakeRecorder:
    sample_rate = 16000

    def __init__(self, seconds=1.0):
        self.seconds = seconds
        self.level = 0.0
        self.on_limit = None
        self.device = "unset"
        self.recording = False

    def start(self, device=None):
        self.device = device
        self.recording = True
        self.level = 0.5

    def stop(self):
        self.recording = False
        self.level = 0.0
        return np.full(int(self.sample_rate * self.seconds), 0.01, dtype=np.float32)  # quiet, not silent


class Segment:
    def __init__(self, text, end=0.0, start=None):
        self.text = text
        self.end = end
        self.start = max(0.0, end - 1.0) if start is None else start


class FakeModel:
    def __init__(self, name, calls):
        self.name = name
        self.calls = calls

    def transcribe(self, audio, **kwargs):
        self.calls.append((self.name, kwargs))
        return [Segment(" hello"), Segment("world ")], None


class FakeTimer:
    created = []

    def __init__(self, seconds, fn):
        self.seconds = seconds
        self.fn = fn
        self.cancelled = False
        self.daemon = True
        FakeTimer.created.append(self)

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True

    def fire(self):
        if not self.cancelled:
            self.fn()


def make_service(**kwargs):
    calls, loads = [], []

    def loader(name):
        loads.append(name)
        return FakeModel(name, calls)

    svc = SttService(recorder=FakeRecorder(), cache=ModelCache(loader), timer_factory=FakeTimer, **kwargs)
    events = []
    for name in ("state_changed", "transcript_ready", "model_status", "error"):
        svc.events.on(name, lambda *a, n=name: events.append((n,) + a))
    return svc, calls, loads, events


def _dictate(svc, events, target="editor"):
    before = len([e for e in events if e[0] == "transcript_ready"])
    svc.toggle(target)
    assert svc.state is SttState.RECORDING
    svc.toggle()
    assert wait_for(lambda: len([e for e in events if e[0] == "transcript_ready"]) > before)
    assert wait_for(lambda: svc.state is SttState.IDLE)


def test_toggle_records_and_delivers_to_target():
    svc, calls, loads, events = make_service()
    _dictate(svc, events, target="external:123")
    ready = [e for e in events if e[0] == "transcript_ready"][0]
    assert ready[1:] == ("Hello world.", "external:123")
    states = [e[1] for e in events if e[0] == "state_changed"]
    assert states == [SttState.RECORDING, SttState.TRANSCRIBING, SttState.IDLE]
    svc.shutdown()


def test_language_is_passed_and_auto_means_none():
    svc, calls, loads, events = make_service(language="de")
    _dictate(svc, events)
    assert calls[-1][1]["language"] == "de"
    svc.language = "auto"
    _dictate(svc, events)
    assert calls[-1][1]["language"] is None
    svc.shutdown()


def test_model_change_loads_new_model():
    svc, calls, loads, events = make_service(model="small")
    _dictate(svc, events)
    svc.set_model("tiny")
    _dictate(svc, events)
    assert loads == ["small", "tiny"]
    assert calls[-1][0] == "tiny"
    svc.shutdown()


def test_idle_unload_timer_and_immediate_unload():
    FakeTimer.created.clear()
    svc, calls, loads, events = make_service(auto_unload=True, auto_unload_minutes=2)
    _dictate(svc, events)
    assert svc.cache.loaded_name == "small"
    timer = FakeTimer.created[-1]
    assert timer.seconds == 120
    timer.fire()
    assert svc.cache.loaded_name is None
    svc.unload_when_idle = True
    _dictate(svc, events)
    assert wait_for(lambda: svc.cache.loaded_name is None)
    svc.shutdown()


def test_record_start_failure_reports_error():
    svc, calls, loads, events = make_service()

    def boom(device=None):
        raise RuntimeError("no mic")

    svc.recorder.start = boom
    assert svc.start("editor") is False
    assert svc.state is SttState.IDLE
    assert any(e[0] == "error" and "no mic" in e[1] for e in events)
    svc.shutdown()
