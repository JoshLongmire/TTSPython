import random
import threading

from ttspython.core.queue_model import SpeechQueue
from ttspython.core.clipboard_router import ClipboardRouter, Action
from ttspython.core import audio_devices


def _queue(n):
    q = SpeechQueue()
    items = [q.add(f"text {i}", f"Item {i}") for i in range(n)]
    return q, items


def test_next_after_follows_moves_and_removals():
    q, (a, b, c, d) = _queue(4)
    assert q.next_after(a.id).id == b.id
    q.move(c.id, -1)  # a c b d
    assert q.next_after(a.id).id == c.id
    q.remove(b.id)    # playing b removed; continue with what followed it
    assert q.next_after(b.id).id == d.id
    assert q.next_after(d.id) is None
    assert q.next_after(d.id, loop=True).id == a.id


def test_removed_chain_is_followed():
    q, (a, b, c) = _queue(3)
    q.remove(b.id)
    q.remove(c.id)
    assert q.next_after(b.id) is None
    assert q.next_after(b.id, loop=True).id == a.id


def test_pending_tracking():
    q, (a, b) = _queue(2)
    q.mark_played(a.id)
    assert q.first_pending().id == b.id
    q.mark_all_pending()
    assert q.first_pending().id == a.id


def test_concurrent_mutation_is_safe():
    q, _ = _queue(50)
    errors = []

    def hammer(seed):
        rng = random.Random(seed)
        try:
            for _ in range(500):
                items = q.snapshot()
                if not items:
                    q.add("x", "x")
                    continue
                item = rng.choice(items)
                op = rng.randrange(4)
                if op == 0:
                    q.remove(item.id)
                elif op == 1:
                    q.move(item.id, rng.choice([-1, 1]))
                elif op == 2:
                    q.add("y", "y")
                else:
                    q.next_after(item.id, loop=True)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=hammer, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    ids = [i.id for i in q.snapshot()]
    assert len(ids) == len(set(ids))


def test_router_rules():
    r = ClipboardRouter()
    r.prime("existing text")
    assert r.decide("existing text", busy=False, action="speak", auto_queue=False)[0] is Action.IGNORE
    assert r.decide("short", busy=False, action="speak", auto_queue=False)[0] is Action.IGNORE
    assert r.decide("long enough", busy=False, action="speak", auto_queue=False)[0] is Action.SPEAK
    assert r.decide("another one", busy=True, action="speak", auto_queue=False) == (Action.IGNORE, "busy")
    assert r.decide("and another", busy=True, action="speak", auto_queue=True) == (Action.ENQUEUE, "Auto-Queued")
    assert r.decide("queue me please", busy=False, action="queue", auto_queue=False) == (Action.ENQUEUE, "Clipboard")


def test_router_ignores_own_writes():
    now = [0.0]
    r = ClipboardRouter(clock=lambda: now[0])
    r.suppress("dictated sentence")
    assert r.decide("dictated sentence", busy=False, action="speak", auto_queue=False)[0] is Action.IGNORE
    now[0] = 5.0
    r.last_text = ""
    assert r.decide("dictated sentence", busy=False, action="speak", auto_queue=False)[0] is Action.SPEAK


def _dev(index, name, api="MME", inp=0, out=2):
    return audio_devices.DeviceInfo(index, name, api, inp, out, 44100.0)


def test_device_resolves_by_name_after_index_shift():
    before = [_dev(0, "Mapper"), _dev(3, "Headphones (USB)"), _dev(4, "Speakers")]
    ref = before[1].ref()
    after = [_dev(0, "Mapper"), _dev(2, "New Mic", inp=1, out=0), _dev(5, "Headphones (USB)"), _dev(6, "Speakers")]
    assert audio_devices.resolve(ref, "output", after) == 5


def test_missing_device_falls_back_to_default():
    ref = {"name": "Gone", "hostapi": "MME", "index": 3}
    assert audio_devices.resolve(ref, "output", [_dev(3, "Other")]) is None


def test_index_only_ref_from_v4_is_completed():
    devices = [_dev(0, "Mapper"), _dev(3, "Mic", inp=1, out=0)]
    ref = audio_devices.complete_ref({"name": "", "hostapi": "", "index": 3}, "input", devices)
    assert ref == {"name": "Mic", "hostapi": "MME", "index": 3}


def test_list_devices_keeps_every_host_api_default_first():
    devices = [_dev(0, "A", "WASAPI"), _dev(1, "A", "MME"), _dev(2, "Mic", "MME", inp=1, out=0),
               _dev(3, "USB DAC only on WASAPI", "Windows WASAPI")]
    outs = audio_devices.list_devices("output", devices, "MME")
    assert [d.index for d in outs] == [1, 0, 3]
    assert [d.index for d in audio_devices.list_devices("input", devices, "MME")] == [2]
    assert audio_devices.label(outs[0], "MME") == "A"
    assert audio_devices.label(outs[2], "MME") == "USB DAC only on WASAPI  (WASAPI)"
