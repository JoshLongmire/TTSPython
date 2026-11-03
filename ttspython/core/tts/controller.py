"""SpeechController: one synth thread, one audio stream, one state machine.

Threads (none touch the UI):
  synth       owns the renderer (COM apartment on Windows), renders chunk N+1
              while chunk N plays, runs single utterances and the queue
  audio       the PortAudio callback inside AudioPlayer
  dispatch    turns player events into controller events

Events (EventEmitter names and arguments):
  state_changed(State)
  voices_ready(list[Voice], renderer_name)
  chunk_started(utt_id, pos16, end16, index, total, source)
  queue_item_started(item_id)
  utterance_finished(utt_id, stopped)
  queue_finished(stopped)
  error(message)
"""
from __future__ import annotations

import enum
import gc
import itertools
import queue
import threading
from dataclasses import dataclass

from ..chunking import split_chunks, utf16_len
from ..events import EventEmitter
from ..platform import com_apartment
from ..queue_model import SpeechQueue
from .player import AudioPlayer, Marker
from .render import Cancelled, create_renderer, pick_default_voice, trim_leading_silence

LOOKAHEAD_SECONDS = 3.0  # keep this much audio rendered ahead of what is heard...
LOOKAHEAD_MAX = 5        # ...but never more than this many chunks
RERENDER_DELAY = 0.35    # after a speed change, re-render upcoming chunks once the slider settles
QUEUE_GAP_SECONDS = 0.5  # same pause between queue items as v4
STALL_SECONDS = 5.0


class AudioStalled(RuntimeError):
    """The output stream stopped consuming audio (device gone or driver error)."""


class State(enum.Enum):
    IDLE = "idle"
    STARTING = "starting"
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPING = "stopping"


class Source(enum.Enum):
    EDITOR = "editor"
    SELECTION = "selection"
    CLIPBOARD = "clipboard"
    QUEUE = "queue"
    TEST = "test"


@dataclass
class _Job:
    kind: str                 # "single" or "queue"
    text: str = ""
    source: Source = Source.EDITOR
    base16: int = 0
    start_item: str = ""
    manual: bool = True
    generation: int = 0


_SHUTDOWN = object()


class SpeechController:
    def __init__(self, queue_model: SpeechQueue | None = None, renderer_factory=create_renderer,
                 player: AudioPlayer | None = None, voice_id="", rate=200, volume=1.0):
        self.events = EventEmitter()
        self.queue = queue_model if queue_model is not None else SpeechQueue()
        self._renderer_factory = renderer_factory
        self._player_events = queue.Queue()
        self.player = player or AudioPlayer(self._player_events)
        if player is not None:
            player._events = self._player_events
        self.player.set_gain(volume)
        self.player.set_target_wpm(int(rate))

        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._cmds = queue.Queue()
        self._cancel = threading.Event()
        self._idle = threading.Event()
        self._idle.set()
        self._ready = threading.Event()
        self._state = State.IDLE
        self._pending_jobs = 0
        self._generation = 0
        self._utt_ids = itertools.count(1)
        self._current_utt = 0
        self._playing_index = -1
        self._drained_utt = 0
        self._params_dirty = False
        self._restart_pending = False
        self._rerender_timer = None
        self._current_source = None

        self.voice_id = voice_id
        self.rate = int(rate)
        self.volume = float(volume)
        self.auto_queue = False
        self.loop = False
        self.playing_item_id = ""
        self.voices = []
        self.renderer_name = ""

        self._synth = threading.Thread(target=self._synth_main, name="tts-synth", daemon=True)
        self._dispatch = threading.Thread(target=self._dispatch_main, name="tts-dispatch", daemon=True)
        self._synth.start()
        self._dispatch.start()

    # --- public API (any thread) --------------------------------------------------
    @property
    def state(self):
        return self._state

    @property
    def busy(self):
        with self._lock:
            return self._state is not State.IDLE or self._pending_jobs > 0

    def wait_ready(self, timeout=10.0):
        return self._ready.wait(timeout)

    def speak(self, text, source=Source.EDITOR, base16=0, replace=False):
        """Speak text. Returns False if busy and replace is False, or text is blank."""
        if not text or not text.strip():
            return False
        if replace:
            self.stop()
        with self._lock:
            if self._state is not State.IDLE or self._pending_jobs:
                return False
            self._submit(_Job(kind="single", text=text, source=source, base16=base16))
        return True

    def play_queue(self, start_item_id="", manual=True):
        with self._lock:
            if self._state is not State.IDLE or self._pending_jobs or not len(self.queue):
                return False
            self._submit(_Job(kind="queue", start_item=start_item_id, manual=manual, source=Source.QUEUE))
        return True

    def _submit(self, job):
        job.generation = self._generation
        self._pending_jobs += 1
        self._idle.clear()
        self._set_state(State.STARTING)
        self._cmds.put(job)

    def pause(self):
        with self._lock:
            if self._state in (State.PLAYING, State.STARTING):
                self.player.pause()
                self._set_state(State.PAUSED)

    def resume(self):
        with self._lock:
            if self._state is State.PAUSED:
                self.player.resume()
                self._set_state(State.PLAYING)

    def toggle_pause(self):
        if self._state is State.PAUSED:
            self.resume()
        else:
            self.pause()

    def stop(self, timeout=2.0):
        """Stop everything and return once the synth thread is idle.

        Bumping the generation cancels the running job and makes any job still
        waiting in the command queue a no-op when the synth thread reaches it.
        """
        with self._lock:
            if self._state is State.IDLE and not self._pending_jobs:
                return True
            self._generation += 1
            self._cancel.set()
            # Anything the stopped job is still about to enqueue is dropped by the player.
            self.player.flush(min_generation=self._generation)
            self.player.resume()
            self._set_state(State.STOPPING)
            self._cond.notify_all()
        return self._idle.wait(timeout)

    def set_voice(self, voice_id):
        """While speaking, the new voice takes over from the start of the word being heard."""
        voice_id = voice_id or ""
        if voice_id == self.voice_id:
            return
        self.voice_id = voice_id
        with self._lock:
            if self._state is not State.IDLE:
                self._restart_pending = True
                self._cond.notify_all()

    def set_rate(self, wpm):
        """Heard at once: the player stretches what is queued. Upcoming chunks are then
        rendered again at the engine's own rate for the most natural sound."""
        wpm = int(wpm)
        if wpm == self.rate:
            return
        self.rate = wpm
        self.player.set_target_wpm(wpm)
        if self._rerender_timer is not None:
            self._rerender_timer.cancel()
        self._rerender_timer = threading.Timer(RERENDER_DELAY, self._mark_dirty)
        self._rerender_timer.daemon = True
        self._rerender_timer.start()

    def set_volume(self, volume):
        self.volume = float(volume)
        self.player.set_gain(self.volume)

    def set_output_device(self, index):
        """Switch output device; speech in progress stops only if the device really changes."""
        if index == self.player.device:
            return
        if self.busy:
            self.stop()
        self.player.set_device(index)

    def refresh_voices(self):
        self._cmds.put(("refresh",))

    def output_level(self):
        return self.player.level

    def shutdown(self, timeout=3.0):
        self.stop(timeout)
        self._cmds.put(_SHUTDOWN)
        self._player_events.put(None)
        self._synth.join(timeout)
        self._dispatch.join(timeout)
        self.player.close()

    # --- internals ------------------------------------------------------------------
    def _mark_dirty(self):
        with self._lock:
            if self._state is not State.IDLE:
                self._params_dirty = True
                self._cond.notify_all()

    def _set_state(self, state):
        if state is self._state:
            return
        self._state = state
        self.events.emit("state_changed", state)

    def _synth_main(self):
        with com_apartment():
            try:
                renderer = self._renderer_factory()
                self.renderer_name = getattr(renderer, "name", "")
                self._load_voices(renderer)
            except Exception as exc:
                renderer = None
                # Held: this can happen before the UI has subscribed to errors.
                self.events.emit("error", f"Speech engine failed to start: {exc}", hold=True)
            self._warm_up(renderer)
            self._ready.set()
            while True:
                cmd = self._cmds.get()
                if cmd is _SHUTDOWN:
                    del renderer  # COM objects must be released before the apartment closes
                    gc.collect()
                    break
                if isinstance(cmd, tuple) and cmd[0] == "refresh":
                    if renderer is not None:
                        try:
                            self._load_voices(renderer)
                        except Exception as exc:
                            self.events.emit("error", f"Could not list voices: {exc}")
                    continue
                self._run_job(renderer, cmd)

    def _warm_up(self, renderer):
        """Pay one-time costs now (PortAudio init, first SAPI render), not on first Speak."""
        try:
            _ = self.player.sd
        except Exception:
            pass
        if renderer is not None:
            try:
                if hasattr(renderer, "warm_up"):
                    renderer.warm_up(self.rate)
                else:
                    renderer.render("a", self.voice_id, self.rate, threading.Event())
            except Exception:
                pass

    def _load_voices(self, renderer):
        self.voices = renderer.list_voices()
        self.voice_id = pick_default_voice(self.voices, self.voice_id)
        self.events.emit("voices_ready", list(self.voices), self.renderer_name)

    def _run_job(self, renderer, job):
        with self._lock:
            self._pending_jobs -= 1
            skip = job.generation != self._generation
            if not skip:
                self._cancel.clear()
            self._params_dirty = False
            generation = self._generation
        stopped = False
        try:
            if skip:
                return
            if renderer is None:
                raise RuntimeError("No speech engine is available.")
            self.player.prepare()
            if job.kind == "single":
                utt = next(self._utt_ids)
                finished = self._speak_text(renderer, job.text, job.base16, utt, job.source, generation)
                stopped = not finished
                self.events.emit("utterance_finished", utt, stopped)
                # Auto-Queue continues after real reading, never after a Settings voice test.
                if (finished and self.auto_queue and job.source is not Source.TEST
                        and self.queue.first_pending() is not None):
                    self._run_queue(renderer, "", False, generation)
            else:
                self._run_queue(renderer, job.start_item, job.manual, generation)
        except AudioStalled as exc:
            self.player.close()  # the next job reopens a fresh stream
            self.events.emit("error", str(exc))
        except Exception as exc:
            self.player.flush()  # never leave this job's audio playing behind an IDLE state
            self.events.emit("error", str(exc))
        finally:
            with self._lock:
                self.playing_item_id = ""
                self._current_source = None
                self.player.resume()
                if self._pending_jobs == 0:
                    self._set_state(State.IDLE)
                    self._idle.set()

    def _run_queue(self, renderer, start_item, manual, generation):
        q = self.queue
        if manual:
            q.mark_all_pending()
            item = q.get(start_item) if start_item else q.first()
        else:
            item = q.first_pending()
        stopped = False
        first = True
        while item is not None:
            if self._cancel.is_set():
                stopped = True
                break
            if not first:
                self.player.enqueue_silence(QUEUE_GAP_SECONDS, Marker(utt_id=-1, generation=generation))
            first = False
            self.playing_item_id = item.id
            q.mark_played(item.id)
            self.events.emit("queue_item_started", item.id)
            utt = next(self._utt_ids)
            if not self._speak_text(renderer, item.text, 0, utt, Source.QUEUE, generation, item.id):
                stopped = True
                break
            self.events.emit("utterance_finished", utt, False)
            nxt = q.next_after(item.id, loop=False)
            if nxt is None and self.loop and len(q):
                q.mark_all_pending()
                nxt = q.first()
            item = nxt
        self.playing_item_id = ""
        self.events.emit("queue_finished", stopped)

    def _ahead_enough(self, utt, idx):
        """True when enough audio is rendered ahead of what is being heard."""
        ahead = idx - self._playing_index
        if ahead > LOOKAHEAD_MAX:
            return True
        if ahead <= 1:  # always have the next chunk ready
            return False
        return self.player.queued_seconds(utt) >= LOOKAHEAD_SECONDS

    def _restart_at_heard_word(self, utt, text, base16, chunks):
        """New chunks starting at the word being heard (the voice changed mid-sentence)."""
        pos = self.player.position(utt)
        if pos is None:  # nothing heard yet
            index, fraction = max(0, self._playing_index), 0.0
        else:
            index, fraction = pos
        index = min(index, len(chunks) - 1)
        chunk = chunks[index]
        local = min(len(chunk.text), int(fraction * len(chunk.text)))
        while local > 0 and not chunk.text[local - 1].isspace():
            local -= 1
        self.player.drop_utterance(utt)
        text = text[chunk.start + local:]
        base16 = chunk.pos16 + utf16_len(chunk.text[:local])
        return text, base16, split_chunks(text, base16), index

    def _speak_text(self, renderer, text, base16, utt, source, generation, item_id=""):
        """Render and play text. Returns True if it played to the end."""
        chunks = split_chunks(text, base16)
        if not chunks:
            return True
        shown = 0  # chunks already heard before a voice change re-split the text

        def begin(new_utt):
            with self._lock:
                self._current_utt = new_utt
                self._playing_index = -1
                self._current_source = source

        begin(utt)
        idx = 0
        while True:
            restart = False
            while idx < len(chunks):
                with self._cond:
                    while (self._ahead_enough(utt, idx) and not self._cancel.is_set()
                           and not self._params_dirty and not self._restart_pending):
                        self._cond.wait(0.05)
                        self._check_stalled()
                    if self._cancel.is_set():
                        return False
                    if self._restart_pending:
                        restart = True
                        break
                    if self._params_dirty:
                        self._params_dirty = False
                        dropped = self.player.drop_queued(utt)
                        if dropped is not None:
                            idx = min(idx, dropped)
                chunk = chunks[idx]
                wpm = self.rate
                try:
                    pcm, rate = renderer.render(chunk.text, self.voice_id, wpm, self._cancel)
                except Cancelled:
                    return False
                if idx == 0:
                    pcm = trim_leading_silence(pcm, rate)
                marker = Marker(utt_id=utt, index=idx, total=len(chunks), pos16=chunk.pos16, end16=chunk.end16,
                                generation=generation, item_id=item_id, shown=shown)
                native = renderer.native_wpm(wpm, self.voice_id) if hasattr(renderer, "native_wpm") else wpm
                if self._cancel.is_set() or not self.player.enqueue(pcm, rate, marker, native_wpm=native):
                    return False
                idx += 1
            if not restart:
                self.player.enqueue_end(Marker(utt_id=utt, index=len(chunks), total=len(chunks),
                                               generation=generation, end=True))
                with self._cond:
                    while (self._drained_utt != utt and not self._cancel.is_set() and not self._params_dirty
                           and not self._restart_pending):
                        self._cond.wait(0.05)
                        self._check_stalled()
                    if self._cancel.is_set():
                        return False
                    if self._drained_utt == utt:
                        return True
                    restart = self._restart_pending
                    if not restart:
                        self._params_dirty = False
                        dropped = self.player.drop_queued(utt)
                        if dropped is None:
                            continue
                        idx = dropped
                        continue
            with self._cond:
                self._restart_pending = False
                self._params_dirty = False
            text, base16, chunks, heard = self._restart_at_heard_word(utt, text, base16, chunks)
            shown += heard
            if not chunks:
                return True
            utt = next(self._utt_ids)
            begin(utt)
            idx = 0

    def _check_stalled(self):
        if self.player.stalled(STALL_SECONDS):
            raise AudioStalled("The audio output stopped responding. Check the output device, then try again.")

    def _dispatch_main(self):
        while True:
            event = self._player_events.get()
            if event is None:
                break
            kind, marker = event
            if marker is None or marker.utt_id < 0:  # silence between queue items
                continue
            with self._cond:
                if marker.generation != self._generation:
                    continue
                if kind == "chunk":
                    if marker.utt_id == self._current_utt:
                        self._playing_index = marker.index
                    if self._state is State.STARTING:
                        self._set_state(State.PLAYING)
                    source = self._current_source
                elif kind == "drained":
                    self._drained_utt = marker.utt_id
                self._cond.notify_all()
            if kind == "chunk":
                self.events.emit("chunk_started", marker.utt_id, marker.pos16, marker.end16,
                                 marker.shown + marker.index, marker.shown + marker.total, source)
