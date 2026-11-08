"""A copy of the user's own voice, made only from a recording of them reading a consent statement.

The speech comes from MOSS-TTS-Nano (Apache-2.0), run with ONNX Runtime and no PyTorch. The model is an
optional download (about 760 MB) into the per-user data folder; nothing here loads until it is used:

    <data dir>/clone-model/               the model files, pinned by checksum
    <data dir>/cloned-voices/<id>/        voice.json, codes.npy and consent.wav per voice

There is deliberately no way to make a voice from a file: the recording has to come from the
microphone, with fresh code words in it (see new_consent and check_consent).
"""
from __future__ import annotations

import contextlib
import difflib
import json
import math
import os
import random
import re
import shutil
import threading
import time
import uuid
import wave
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np

from ..download import fetch
from ..platform import data_dir
from ..resample import resample
from ..settings import atomic_replace, write_json_atomic
from .render import AudioBlock, Cancelled, Voice

PREFIX = "clone:"
_BASE = "https://huggingface.co/OpenMOSS-Team/{repo}/resolve/{revision}/{name}"
_REVISIONS = {"MOSS-TTS-Nano-100M-ONNX": "f52645cb467506d8e18e746ddd59482685b74e58",
              "MOSS-Audio-Tokenizer-Nano-ONNX": "ceff0d0749bfb3fa2d61149794ec6feef0d1e1ae"}
# Only what speaking needs. The repo's browser_poc_manifest.json is left out on purpose: its sample
# voices include other people's.
MODEL_FILES = (
    ("MOSS-TTS-Nano-100M-ONNX", "tts_browser_onnx_meta.json", 4487, "3edf25232dcd0af3d061c837e9a968a39e2f8592e06777d740503c4f2244f95c"),
    ("MOSS-TTS-Nano-100M-ONNX", "tokenizer.model", 470897, "c353ee1479b536bf414c1b247f5542b6607fb8ae91320e5af1781fee200fddff"),
    ("MOSS-TTS-Nano-100M-ONNX", "moss_tts_prefill.onnx", 283305, "d56126dcd0574c2f15d98fc6b35eda68d0386b5bd9c5e38e28548d6f2ea8f3db"),
    ("MOSS-TTS-Nano-100M-ONNX", "moss_tts_decode_step.onnx", 291483, "698cbc2fc1c2feca16e5895614ed52bbb32ded10f236c076f477b2e69abf32d8"),
    ("MOSS-TTS-Nano-100M-ONNX", "moss_tts_local_fixed_sampled_frame.onnx", 471262, "40cdb00efc171c450cf91468e01429caa41b0252222cd308e978f58fe354afa8"),
    ("MOSS-TTS-Nano-100M-ONNX", "moss_tts_global_shared.data", 440813568, "bce8312c3df6a44545302cae229b61054fe0672e0b252ba59cba47adeed831dc"),
    ("MOSS-TTS-Nano-100M-ONNX", "moss_tts_local_shared.data", 229678080, "bae7782032c0fb12490ab42afe009f87ae6c75a0f0596fc7b5c08e4d5ee93916"),
    ("MOSS-Audio-Tokenizer-Nano-ONNX", "codec_browser_onnx_meta.json", 17036, "3e291c883bb7d11ff2fe8e964e3e495519760358859f35c951254c7741592731"),
    ("MOSS-Audio-Tokenizer-Nano-ONNX", "moss_audio_tokenizer_encode.onnx", 815775, "eadea4a645abdcf98714c7aead122ee2ce7da6e080f9f80b977cd1ca8e19473a"),
    ("MOSS-Audio-Tokenizer-Nano-ONNX", "moss_audio_tokenizer_encode.data", 44507136, "aa751265b2bab2887eac224484546b194875aa7494b607115439b3dc6b228a2c"),
    ("MOSS-Audio-Tokenizer-Nano-ONNX", "moss_audio_tokenizer_decode_step.onnx", 351400, "9527c86a29e1837edec1f74db57d5eeaadb3a715af3382703566460afed25855"),
    ("MOSS-Audio-Tokenizer-Nano-ONNX", "moss_audio_tokenizer_decode_shared.data", 44198912, "e69d52e0f4e84ca27850557ee54face46632d3a5a16c89bd246c7c408466dcad"),
)
MODEL_BYTES = sum(f[2] for f in MODEL_FILES)
MODEL_MB = round(MODEL_BYTES / 1e6)
MEMORY_GB = 1.3  # memory in use while a cloned voice speaks (measured, 1.23 to 1.36); released when idle

# The conversation the model was trained on (token ids), from the same revision of the model.
_USER_PREFIX = (600, 289, 10356, 13, 10356, 10425, 1860, 4546, 12907, 10363, 13325, 11492)
_AFTER_REFERENCE = (10356, 10425, 3965, 7738, 11492, 505, 587, 10356, 10425, 352, 500, 856, 11492, 505, 587, 10356,
                    10425, 2128, 1247, 594, 11492, 505, 587, 10356, 10425, 348, 909, 561, 3648, 11492, 505, 587, 10356,
                    10425, 2818, 1305, 355, 348, 909, 11492, 505, 587, 10356, 10425, 484, 339, 10367, 783, 11492, 505,
                    587, 10356, 10425, 2427, 980, 11492)
_ASSISTANT_PREFIX = (10356, 14, 5, 4, 8165, 430)

MAX_TOKENS = 75  # the model's longest reliable sentence; longer text is spoken in pieces
MAX_FRAMES = 375  # 30 s, the model's limit for one piece
_DECODE_EVERY = 8  # frames in each block of sound, 0.64 s. How they are grouped does not change the sound (at most 1e-6)
_FRAME_SECONDS = 0.08
_SECONDS_PER_TOKEN = 0.22  # sound comes at 2.3 to 3 frames per token: to guess how long a sentence will be
_PIECE_GAP_SECONDS = 0.12
IDLE_SECONDS = 120  # the model holds over a gigabyte: let it go soon after speech ends
FALLBACK_WPM = 180  # until a voice has spoken something long enough to measure
_MEASURE_MIN_WORDS = 5
_NATIVE_RANGE = (110, 280)
_PACE_SAVE_CHANGE = 0.05
_PACE_ODD = 0.25    # a sentence this far from the voice's pace is babble from the model, not its pace...
_PACE_ODD_RUN = 3   # ...unless this many in a row say so: then the voice really is different

MIN_SECONDS, MAX_SECONDS = 6, 40
_LIMIT_MARGIN_SECONDS = 2  # the window stops by itself at MAX_SECONDS, and its timer runs a little behind
_CONSENT_MATCH = 0.75
_CONSENT_MOST_EXTRA = 1.25  # words heard, against words in the statement
_SILENT_PEAK = 0.01
_CLIPPED_SHARE = 0.01
_REFERENCE_PEAK = 0.7
_REFERENCE_MAX_SECONDS = 20
SPEED_CHECK_TEXT = "This is a short check of how quickly this computer can speak in your voice."
SMOOTH_SPEED = 1.2  # below this, speech is likely to pause between sentences


# --- where things live ------------------------------------------------------------------------
def model_dir():
    return os.path.join(data_dir(), "clone-model")


def voices_dir():
    return os.path.join(data_dir(), "cloned-voices")


def model_installed():
    folder = model_dir()
    for _repo, name, size, _sha in MODEL_FILES:
        try:
            if os.path.getsize(os.path.join(folder, name)) != size:
                return False
        except OSError:
            return False
    return True


def install_model(progress=None, cancel=None, opener=None):
    """Download the model. progress(done_bytes, total_bytes). A cancelled or failed download keeps
    the files already finished, so trying again carries on from there."""
    folder = model_dir()
    os.makedirs(folder, exist_ok=True)
    kwargs = {"opener": opener} if opener else {}
    missing = sum(size for _repo, name, size, _sha in MODEL_FILES
                  if not (os.path.isfile(os.path.join(folder, name)) and os.path.getsize(os.path.join(folder, name)) == size))
    free = shutil.disk_usage(folder).free
    if free < missing:
        raise OSError(f"The voice model needs {missing / 1e6:.0f} MB of free disk space, and only {free / 1e6:.0f} MB is free.")
    done = 0
    for repo, name, size, sha in MODEL_FILES:
        path = os.path.join(folder, name)
        if not (os.path.isfile(path) and os.path.getsize(path) == size):
            start = done
            fetch(_BASE.format(repo=repo, revision=_REVISIONS[repo], name=name), path,
                  (lambda d, _t, s=start: progress(s + d, MODEL_BYTES)) if progress else None,
                  sha256=sha, cancel=cancel, **kwargs)
        done += size
        if progress:
            progress(done, MODEL_BYTES)
    return folder


def remove_model():
    """Delete the model (the voices stay, ready for when it is downloaded again). Returns bytes freed."""
    with _engine_lock:  # never under a sentence being spoken, and nothing can load it again meanwhile
        _drop_engine()
        freed = _folder_size(model_dir())
        shutil.rmtree(model_dir(), ignore_errors=True)
        if os.path.exists(model_dir()):
            raise OSError("Could not delete the voice model. Close what is using it and try again.")
    return freed


def model_size():
    return _folder_size(model_dir())


def _folder_size(folder):
    total = 0
    for root, _dirs, names in os.walk(folder):
        for name in names:
            with contextlib.suppress(OSError):
                total += os.path.getsize(os.path.join(root, name))
    return total


# --- consent ------------------------------------------------------------------------------------
CODE_WORDS = ("river", "candle", "orange", "window", "garden", "pencil", "silver", "thunder", "basket", "marble",
              "ladder", "violin", "forest", "carpet", "button", "hammer", "island", "pepper", "rocket", "tunnel")


@dataclass(frozen=True)
class Consent:
    text: str
    code_words: tuple


def new_consent(chooser=None):
    """The statement to read aloud. Fresh code words each time, so an old recording of someone
    cannot be played to the microphone instead. They are spread from start to end, so a clip of
    someone else cannot fill the part of the recording the voice is made from."""
    first, second, last = (chooser or random.SystemRandom()).sample(CODE_WORDS, 3)
    return Consent(f"My first code word is {first}. This is my own voice, and I am reading these words myself. "
                   f"My second code word is {second}. I agree to let this computer make a copy of my voice, for my "
                   f"own use. It can say anything that I give it to read. My last code word is {last}.",
                   (first, second, last))


def _words(text):
    return re.findall(r"[a-z']+", text.lower().replace("’", "'"))


def check_consent(consent, heard):
    """Did the recording say the statement? Returns an empty string if so, else what to tell the person."""
    said = _words(heard)
    missing = [w for w in consent.code_words if w not in said]
    if not said:
        return "No words were heard. Read the statement out loud and try again."
    if missing:
        return "The code words were not heard clearly. Read the whole statement again, code words included."
    wanted = _words(consent.text)
    if len(said) > len(wanted) * _CONSENT_MOST_EXTRA:
        return "That had too much other speech in it. Read only the statement, with nobody else talking."
    if difflib.SequenceMatcher(None, wanted, said, autojunk=False).ratio() < _CONSENT_MATCH:
        return "That did not match the statement closely enough. Read it again, just as it is written."
    return ""


def check_recording(audio, rate):
    """Is this recording usable? Returns an empty string if so, else what to tell the person."""
    seconds = audio.size / rate if rate else 0
    if seconds < MIN_SECONDS:
        return "That was too short. Read the whole statement."
    if seconds > MAX_SECONDS + _LIMIT_MARGIN_SECONDS:
        return "That was too long. Press Stop as soon as you finish reading."
    peak = float(np.abs(audio).max())
    if peak < _SILENT_PEAK:
        return "The microphone was silent. Check that it is not muted, then try again."
    if float(np.mean(np.abs(audio) > 0.99)) > _CLIPPED_SHARE:
        return "The recording was too loud and distorted. Move back from the microphone and try again."
    return ""


def clean_reference(audio, rate):
    """Quiet ends trimmed and an even level, at the most the model uses."""
    loud = np.flatnonzero(np.abs(audio) > max(0.02, 0.05 * float(np.abs(audio).max())))
    if loud.size:
        margin = int(0.15 * rate)
        audio = audio[max(0, int(loud[0]) - margin):int(loud[-1]) + margin]
    audio = audio[:int(_REFERENCE_MAX_SECONDS * rate)]
    peak = float(np.abs(audio).max()) if audio.size else 0.0
    return audio * (_REFERENCE_PEAK / peak) if peak else audio


# --- the voices ---------------------------------------------------------------------------------
def voice_folder(voice_id):
    key = voice_id[len(PREFIX):] if voice_id.startswith(PREFIX) else voice_id
    if not re.fullmatch(r"[0-9a-f]{12}", key):
        raise ValueError("Not a cloned voice.")
    return os.path.join(voices_dir(), key)


def voice_info(voice_id):
    with open(os.path.join(voice_folder(voice_id), "voice.json"), encoding="utf-8") as f:
        return json.load(f)


def saved_voices():
    """Every saved voice as (id, its details), oldest first, even with the model not downloaded."""
    try:
        names = os.listdir(voices_dir())
    except OSError:
        return []
    out = []
    for name in names:
        voice_id = PREFIX + name
        try:
            info = voice_info(voice_id)
            folder = voice_folder(voice_id)
            if isinstance(info, dict) and all(os.path.isfile(os.path.join(folder, n)) for n in ("codes.npy", "consent.wav")):
                out.append((voice_id, info))
        except (OSError, ValueError, KeyError):
            continue  # a folder this is not, or a voice left half written
    return sorted(out, key=lambda item: item[1].get("created", 0))


def installed_voices():
    """Every saved voice, even with the model deleted: a voice leaving the list would change the
    voice saved in Settings for good. Speaking with one then says where to get the model."""
    note = "" if model_installed() else " (model not downloaded)"
    return [Voice(id=voice_id, name=f"{info.get('name') or 'My voice'} - your voice{note}", language="en")
            for voice_id, info in saved_voices()]


def build_voice(name, consent, audio, rate, heard, engine=None):
    """Save a voice made from this recording, after checking the recording says the statement.
    audio: float32 mono from the microphone. Raises ValueError with what to tell the person."""
    problem = check_recording(audio, rate) or check_consent(consent, heard)
    if problem:
        raise ValueError(problem)
    clean = clean_reference(audio, rate)
    if engine is None:
        with _engine_lock:
            try:
                codes = shared_engine().encode(clean, rate)
            finally:
                _release_when_idle()
    else:
        codes = engine.encode(clean, rate)
    os.makedirs(voices_dir(), mode=0o700, exist_ok=True)  # recordings of someone's voice: this user only
    for left_over in os.listdir(voices_dir()):
        if left_over.endswith(".new"):  # left by a crash in the middle of saving: it holds a recording
            shutil.rmtree(os.path.join(voices_dir(), left_over), ignore_errors=True)
    key = uuid.uuid4().hex[:12]
    folder = os.path.join(voices_dir(), key)
    staging = folder + ".new"
    os.makedirs(staging, mode=0o700, exist_ok=True)
    try:
        np.save(os.path.join(staging, "codes.npy"), codes.astype(np.int16), allow_pickle=False)
        with wave.open(os.path.join(staging, "consent.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(int(rate))
            w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
        info = {"name": " ".join(str(name).split())[:60] or "My voice", "created": time.time(),
                "statement": consent.text, "heard": heard}
        path = os.path.join(staging, "voice.json")
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=1)
        atomic_replace(path + ".tmp", path)
        os.replace(staging, folder)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return PREFIX + key


def speed_message(speed):
    """What the speed check means for the person."""
    if speed >= SMOOTH_SPEED:
        return f"Your voice is ready. This computer makes speech {speed:.1f} times as fast as it plays, so it should read smoothly."
    if speed >= 1:
        return (f"Your voice is ready. This computer makes speech only {speed:.1f} times as fast as it plays, so "
                "it may pause between sentences, especially while other programs are busy.")
    return (f"Your voice is ready, but this computer makes speech slower than it plays ({speed:.1f} times), so it "
            "will pause between sentences. Longer text may be easier to listen to as an exported file.")


def remove_voice(voice_id):
    """Delete a voice and its recording. Returns False if something could not be deleted."""
    folder = voice_folder(voice_id)
    shutil.rmtree(folder, ignore_errors=True)
    return not os.path.exists(folder)


def _pace(text, seconds):
    """Words per minute of this speech, or 0 if it is too short to tell."""
    words = len(text.split())
    if words < _MEASURE_MIN_WORDS or seconds <= 0:
        return 0
    return max(_NATIVE_RANGE[0], min(_NATIVE_RANGE[1], words * 60 / seconds))


def _saved_pace(voice_id):
    try:
        pace = voice_info(voice_id).get("pace")
    except (OSError, ValueError, AttributeError):
        return 0
    return pace if isinstance(pace, (int, float)) and _NATIVE_RANGE[0] <= pace <= _NATIVE_RANGE[1] else 0


def _save_pace(voice_id, pace):
    """Kept with the voice, so the speed is right from the first sentence after a restart: playback
    has started by the time a sentence's own pace is known. A failure only costs that."""
    try:
        info = voice_info(voice_id)
        if isinstance(info, dict):
            info["pace"] = round(pace, 1)
            write_json_atomic(os.path.join(voice_folder(voice_id), "voice.json"), info)
    except (OSError, ValueError):
        pass


def load_codes(voice_id):
    return np.load(os.path.join(voice_folder(voice_id), "codes.npy"), allow_pickle=False).astype(np.int32)


def split_tokens(text, encode, limit=MAX_TOKENS):
    """text split at punctuation (or else spaces, or else characters) into pieces of at most limit tokens each.
    Chinese and Japanese put no space after their punctuation, and none between words."""
    pieces = []
    current = ""
    for part in re.findall(r"\S.*?(?:[.!?…;:,]+(?=\s)|[。！？；：，、]+|$)", text.strip(), flags=re.S):
        joined = _join(current, part.strip())
        if current and len(encode(joined)) > limit:
            pieces.append(current)
            current = part.strip()
        else:
            current = joined
    if current:
        pieces.append(current)
    out = []
    for piece in pieces:
        if len(encode(piece)) <= limit:
            out.append(piece)
            continue
        spaced = len(piece.split()) > 1
        units = piece.split() if spaced else list(piece)  # no punctuation; no spaces either (Chinese, a long link)
        current = ""
        for unit in units:
            joined = f"{current} {unit}".strip() if spaced else current + unit
            if current and len(encode(joined)) > limit:
                out.append(current)
                current = unit
            else:
                current = joined
        if current:
            out.append(current)
    return out


def _join(a, b):
    """Two parts of a text, with a space between them unless that is not how the language is written."""
    if not a or not b:
        return a or b
    ends_cjk = bool(_CJK.match(a[-1])) or a[-1] in "。！？；：，、"
    return a + b if ends_cjk and _CJK.match(b[0]) else f"{a} {b}"


def frame_limit(tokens):
    return min(MAX_FRAMES, 10 + 6 * tokens)


# Run-on speech ("babble"): the model sometimes keeps talking after the words, most often after a lone
# word: "Okay." came out as "Okay. Oh, okay." in 18 of 42 tries of short replies (none in 92 tries of
# full sentences). A piece longer than its words could take at twice the voice's pace is run-on.
BABBLE_BASE_SECONDS = 0.8  # breath before and after: a lone word of 0.3 s took up to 0.72 s
BABBLE_PACE_FACTOR = 2.0   # normal sentences took at most 1.3 times their pace (0.395 s a word against 0.30)
SHORT_WORDS = 5            # a piece this short is held back until it is whole, and made again if it ran on
BABBLE_RETRIES = 1  # 2 left 2 of 42 run-ons against 18, but a word then waited up to 3.8 s
_FADE_SECONDS = 0.015


_DIGITS = re.compile(r"\d+")
_CJK = re.compile("[぀-ヿ㐀-䶿一-鿿가-힯]")
_DIGIT_WORDS = 0.8  # "555" is said as three words, "2026" as three or four
_CJK_WORDS = 0.7    # a Chinese or Japanese character takes about 0.2 s, a word 0.3 s


def spoken_words(text):
    """About how many words text is when said: digits are said one by one or in pairs, and Chinese and
    Japanese have no spaces to count."""
    digits = sum(len(run) for run in _DIGITS.findall(text))
    cjk = len(_CJK.findall(text))
    rest = _CJK.sub(" ", _DIGITS.sub(" ", text))
    return len(re.findall(r"\w+", rest)) + _DIGIT_WORDS * digits + _CJK_WORDS * cjk


def babble_frames(text, pace=None):
    """The most frames text should take at the voice's pace (words per minute)."""
    pace = pace if pace and pace > 0 else FALLBACK_WPM
    seconds = BABBLE_BASE_SECONDS + BABBLE_PACE_FACTOR * spoken_words(text) * 60.0 / pace
    return math.ceil(seconds / _FRAME_SECONDS)


def _fade_out(last, rate):
    """A short ramp from where cut-off sound stopped down to silence, instead of a click."""
    n = int(_FADE_SECONDS * rate)
    end = float(last[-1]) if last is not None and last.size else 0.0
    return (end * np.linspace(1.0, 0.0, n, dtype=np.float32)).astype(np.float32)


# --- the model ----------------------------------------------------------------------------------
def engine_threads():
    """4 at most: 6 was only 8% faster on a 10-core CPU (2.5x real time against 2.3x) for one more busy core."""
    return max(1, min(4, (os.cpu_count() or 4) // 2))


class Engine:
    """The loaded model. Not safe for two callers at once: use it through the lock in CloneRenderer."""

    speed = 0.0  # seconds of audio it makes per second, lately

    def __init__(self, folder=None, threads=None):
        import onnxruntime as ort
        import sentencepiece as spm

        folder = folder or model_dir()
        with open(os.path.join(folder, "tts_browser_onnx_meta.json"), encoding="utf-8") as f:
            self._tts = json.load(f)
        with open(os.path.join(folder, "codec_browser_onnx_meta.json"), encoding="utf-8") as f:
            self._codec = json.load(f)
        config = self._tts["model_config"]
        self._n_vq = config["n_vq"]
        self._pad = config["audio_pad_token_id"]
        self._config = config
        self.rate = self._codec["codec_config"]["sample_rate"]
        self._threads = threads or engine_threads()

        def session(name):
            options = ort.SessionOptions()
            options.intra_op_num_threads = self._threads
            options.inter_op_num_threads = 1
            # Waiting without spinning: 3 CPU cores instead of 10, at the same speed.
            options.add_session_config_entry("session.intra_op.allow_spinning", "0")
            options.add_session_config_entry("session.inter_op.allow_spinning", "0")
            # Weights stay in the shared file mapping: 0.9 GB less private memory, 7% slower.
            options.add_session_config_entry("session.disable_prepacking", "1")
            return ort.InferenceSession(os.path.join(folder, name), sess_options=options, providers=["CPUExecutionProvider"])

        files, codec = self._tts["files"], self._codec["files"]
        # Side by side: 2.4 s instead of 5.5. Speaking never uses the encoder, which is left until a voice is made.
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="clone-load") as pool:
            self._prefill, self._decode, self._frame, self._audio_decoder = pool.map(session, (
                files["prefill"], files["decode_step"], files["local_fixed_sampled_frame"], codec["decode_step"]))
        self._open_encoder = lambda: session(codec["encode"])
        self._audio_encoder = None
        self._tokenizer = spm.SentencePieceProcessor(model_file=os.path.join(folder, "tokenizer.model"))
        self._random = np.random.default_rng()

    @staticmethod
    def _named(session, outputs):
        return dict(zip([o.name for o in session.get_outputs()], outputs, strict=True))

    def tokens(self, text):
        return [int(t) for t in self._tokenizer.encode(text, out_type=int)]

    def encode(self, audio, rate):
        """float32 mono audio -> the voice's audio codes, shape (frames, n_vq)."""
        if self._audio_encoder is None:
            self._audio_encoder = self._open_encoder()
        audio = resample(np.asarray(audio, dtype=np.float32), int(rate), self.rate)
        stereo = np.stack([audio, audio])[None]
        out = self._named(self._audio_encoder, self._audio_encoder.run(
            None, {"waveform": stereo, "input_lengths": np.asarray([stereo.shape[-1]], dtype=np.int32)}))
        length = int(np.asarray(out["audio_code_lengths"]).reshape(-1)[0])
        return np.asarray(out["audio_codes"], dtype=np.int32)[0, :length, :self._n_vq]

    def _request(self, codes, token_ids):
        config = self._config

        def text_rows(ids):
            rows = np.full((len(ids), self._n_vq + 1), self._pad, dtype=np.int32)
            rows[:, 0] = ids
            return rows

        audio = np.full((len(codes), self._n_vq + 1), self._pad, dtype=np.int32)
        audio[:, 0] = config["audio_user_slot_token_id"]
        audio[:, 1:] = codes
        return np.concatenate([
            text_rows([*_USER_PREFIX, config["audio_start_token_id"]]), audio,
            text_rows([config["audio_end_token_id"], *_AFTER_REFERENCE, *token_ids, *_ASSISTANT_PREFIX,
                       config["audio_start_token_id"]]),
        ])[None]

    def _new_decoder_state(self):
        stream = self._codec["streaming_decode"]
        state = {}
        for s in stream["transformer_offsets"]:
            state[s["input_name"]] = np.zeros(tuple(s["shape"]), dtype=np.int32)
        for s in stream["attention_caches"]:
            state[s["offset_input_name"]] = np.zeros(tuple(s["offset_shape"]), dtype=np.int32)
            state[s["cached_keys_input_name"]] = np.zeros(tuple(s["cache_shape"]), dtype=np.float32)
            state[s["cached_values_input_name"]] = np.zeros(tuple(s["cache_shape"]), dtype=np.float32)
            state[s["cached_positions_input_name"]] = np.full(tuple(s["positions_shape"]), -1, dtype=np.int32)
        return state

    def _to_audio(self, frames, state):
        stream = self._codec["streaming_decode"]
        out = self._named(self._audio_decoder, self._audio_decoder.run(None, {
            "audio_codes": np.asarray(frames, dtype=np.int32)[None],
            "audio_code_lengths": np.asarray([len(frames)], dtype=np.int32), **state}))
        for s in stream["transformer_offsets"]:
            state[s["input_name"]] = out[s["output_name"]]
        for s in stream["attention_caches"]:
            for key in ("offset", "cached_keys", "cached_values", "cached_positions"):
                state[s[f"{key}_input_name"]] = out[s[f"{key}_output_name"]]
        return out["audio"][0, :, :int(np.asarray(out["audio_lengths"]).reshape(-1)[0])]

    def _piece_blocks(self, codes, token_ids, cancel, limit=None):
        """Yields float32 mono audio as soon as there is some. self.speed follows how fast it comes.
        self.ran_over says afterwards whether it stopped at the limit instead of by itself."""
        self.ran_over = False
        ids = self._request(codes, token_ids)
        names = self._tts["onnx"]
        out = self._named(self._prefill, self._prefill.run(
            None, {"input_ids": ids, "attention_mask": np.ones(ids.shape[:2], dtype=np.int32)}))
        hidden = out["global_hidden"][:, -1, :]
        past_length = ids.shape[1]
        past = {n.replace("present_", "past_"): out[n] for n in names["prefill_output_names"][1:]}
        seen = np.zeros((1, self._n_vq, self._config["audio_codebook_sizes"][0]), dtype=np.int32)
        state = self._new_decoder_state()
        pending = []
        started = time.perf_counter()
        # Sound comes at 2.3 to 3 frames per token. The limit stops a runaway, which short text can
        # be: "Yes." once went on for 4 s of babble.
        for _ in range(min(frame_limit(len(token_ids)), limit or MAX_FRAMES)):
            if cancel.is_set():
                raise Cancelled()
            sampled = self._named(self._frame, self._frame.run(None, {
                "global_hidden": hidden, "repetition_seen_mask": seen,
                "assistant_random_u": np.minimum(self._random.random(1, dtype=np.float32), 0.99999994),
                "audio_random_u": np.minimum(self._random.random((1, self._n_vq), dtype=np.float32), 0.99999994)}))
            if not int(np.asarray(sampled["should_continue"]).reshape(-1)[0]):
                break
            frame = np.asarray(sampled["frame_token_ids"]).reshape(-1).astype(np.int32)
            seen[0, np.arange(self._n_vq), frame] = 1
            pending.append(frame)
            row = np.full((1, 1, self._n_vq + 1), self._pad, dtype=np.int32)
            row[0, 0, 0] = self._config["audio_assistant_slot_token_id"]
            row[0, 0, 1:] = frame
            step = self._named(self._decode, self._decode.run(None, {
                "input_ids": row, "past_valid_lengths": np.asarray([past_length], dtype=np.int32), **past}))
            hidden = step["global_hidden"][:, -1, :]
            past_length += 1
            past = {n.replace("present_", "past_"): step[n] for n in names["decode_output_names"][1:]}
            if len(pending) >= _DECODE_EVERY:
                block = self._to_audio(pending, state).mean(axis=0).astype(np.float32)
                self._note_speed(block.size / self.rate, time.perf_counter() - started)
                yield block
                started = time.perf_counter()
                pending = []
        else:
            self.ran_over = True
        if pending:
            yield self._to_audio(pending, state).mean(axis=0).astype(np.float32)

    def _note_speed(self, seconds, elapsed):
        if elapsed > 0:
            now = seconds / elapsed
            self.speed = 0.5 * (self.speed + now) if self.speed else now

    babble_retries = 0  # pieces made again because they ran on (for measuring)

    def _whole_piece(self, codes, ids, cancel, limit):
        """A piece made before any of it is heard: again, up to BABBLE_RETRIES times, while it runs on."""
        for attempt in range(1 + BABBLE_RETRIES):
            blocks = list(self._piece_blocks(codes, ids, cancel, limit))
            if not self.ran_over:
                break
            if attempt < BABBLE_RETRIES:
                self.babble_retries += 1
        if self.ran_over and blocks:  # still running on: cut where it should have ended
            blocks.append(_fade_out(blocks[-1], self.rate))
        return blocks

    def speak_blocks(self, codes, text, cancel, pace=None, hold=False):
        """Yields (float32 mono audio at self.rate, seconds likely still to come) as they are made.
        pace: the voice's words per minute, to tell run-on speech. hold: nothing is heard until all of it
        is made (a file), so any piece that runs on is made again, not only a short one."""
        texts = split_tokens(text, self.tokens)
        pieces = [self.tokens(piece) for piece in texts]
        expected = sum(len(ids) for ids in pieces) * _SECONDS_PER_TOKEN + (len(pieces) - 1) * _PIECE_GAP_SECONDS
        made = 0.0
        for i, (piece, ids) in enumerate(zip(texts, pieces)):
            if i:
                gap = np.zeros(int(_PIECE_GAP_SECONDS * self.rate), dtype=np.float32)
                made += gap.size / self.rate
                yield gap, max(0.0, expected - made)
            limit = babble_frames(piece, pace)
            short = spoken_words(piece) < SHORT_WORDS
            if hold or short:
                blocks = self._whole_piece(codes, ids, cancel, limit)
            else:
                blocks = self._piece_blocks(codes, ids, cancel, limit)  # heard as it is made: cut, never said twice
            last = None
            for block in blocks:
                last = block
                made += block.size / self.rate
                yield block, max(0.0, expected - made)
            if self.ran_over and not (hold or short) and last is not None:
                yield _fade_out(last, self.rate), max(0.0, expected - made)

    def speak(self, codes, text, cancel, pace=None):
        """float32 mono samples at self.rate."""
        out = [block for block, _left in self.speak_blocks(codes, text, cancel, pace, hold=True)]
        return np.concatenate(out) if out else np.zeros(0, dtype=np.float32)


_engine = None
_engine_lock = threading.RLock()  # held for each sentence: speech and export take turns on the one model
_idle_timer = None
_idle_turn = 0
_loader = None
_load_error = None


def shared_engine():
    """The one model of the whole app, loaded if needed."""
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = Engine()
        return _engine


def engine_loaded():
    return _engine is not None


def _drop_engine():
    global _engine
    _cancel_idle_timer()
    _engine = None


def release_engine():
    """Let the model go. Waits for a sentence being made, if any."""
    with _engine_lock:
        _drop_engine()


def _cancel_idle_timer():
    global _idle_timer, _idle_turn
    _idle_turn += 1
    if _idle_timer is not None:
        _idle_timer.cancel()
        _idle_timer = None


def _release_after_idle(turn):
    with _engine_lock:
        if turn == _idle_turn:  # no sentence started while this waited for the lock
            _drop_engine()


def _release_when_idle():
    global _idle_timer
    _cancel_idle_timer()
    _idle_timer = threading.Timer(IDLE_SECONDS, _release_after_idle, (_idle_turn,))
    _idle_timer.daemon = True
    _idle_timer.start()


def _load_in_background():
    global _load_error
    try:
        with _engine_lock:
            shared_engine()
            _release_when_idle()
    except Exception as exc:
        _load_error = exc


def _load_engine(cancel):
    """Load the model on its own thread (about 3 seconds), so that Stop still works meanwhile.
    A load left behind by Stop finishes, and is ready for the next sentence or let go when idle."""
    global _loader, _load_error
    if _engine is not None:
        return
    if _loader is None or not _loader.is_alive():
        _load_error = None
        _loader = threading.Thread(target=_load_in_background, name="clone-load", daemon=True)
        _loader.start()
    loader = _loader
    while loader.is_alive():
        loader.join(0.03)
        if cancel.is_set():
            raise Cancelled()
    error, _load_error = _load_error, None
    if error is not None:
        raise error


def wait_for_load(timeout):
    if _loader is not None:
        _loader.join(timeout)


def _take_turn(cancel):
    """Wait for the model, for as long as Stop is not pressed."""
    while not _engine_lock.acquire(timeout=0.03):
        if cancel.is_set():
            raise Cancelled()


def speed_check(voice_id, cancel=None, text=SPEED_CHECK_TEXT):
    """How many seconds of speech this computer makes per second, in this voice."""
    cancel = cancel or threading.Event()
    codes = load_codes(voice_id)
    _load_engine(cancel)
    _take_turn(cancel)
    try:
        _cancel_idle_timer()
        engine = shared_engine()
        # The first sentence after loading is slow while the model is read from disk: that is a
        # one-time wait, not this computer's speed (0.6x on the test PC, against 2.3x after it).
        engine.speak(codes, "One moment.", cancel)
        start = time.perf_counter()
        audio = engine.speak(codes, text, cancel)
        elapsed = time.perf_counter() - start
    finally:
        _release_when_idle()
        _engine_lock.release()
    pace = _pace(text, audio.size / engine.rate)
    if pace:
        _save_pace(voice_id, pace)
    return (audio.size / engine.rate) / elapsed if elapsed > 0 else 0.0


class CloneRenderer:
    """Speaks the saved voices. The model has no speed control, so it always renders at the voice's
    natural pace and the player stretches that to the speed the user chose."""

    name = "clone"
    sample_rate = 48000

    def __init__(self, engine_factory=None):
        self._engine_factory = engine_factory  # for tests: the model is loaded and shared otherwise
        self._codes = {}
        self._native = {}  # voice id -> words per minute of its last long enough sentence
        self._odd_paces = {}  # voice id -> how many sentences in a row were far from that

    def list_voices(self):
        return installed_voices()

    def native_wpm(self, wpm, voice_id=None):
        pace = self._native.get(voice_id) or _saved_pace(voice_id)
        if pace:
            self._native[voice_id] = pace
        return pace or FALLBACK_WPM

    def _check_ready(self, voice_id, cancel):
        """Everything that can be told before the model is touched. Returns the voice's codes."""
        if cancel.is_set():
            raise Cancelled()
        if not model_installed():
            raise RuntimeError("Your voice needs its model, which is not downloaded. Open Settings > Speech > Get more voices.")
        try:
            codes = self._codes.get(voice_id)
            if codes is None:
                codes = self._codes[voice_id] = load_codes(voice_id)
        except (OSError, ValueError) as exc:
            raise RuntimeError("This voice is gone. Pick another voice.") from exc
        return codes

    def _note_pace(self, voice_id, text, seconds, smooth=False):
        pace = _pace(text, seconds)
        if not pace:
            return
        before = self._native.get(voice_id)
        if smooth and before:  # it applies to the next sentence: one odd sentence should not swing it
            if abs(pace - before) > before * _PACE_ODD:
                self._odd_paces[voice_id] = self._odd_paces.get(voice_id, 0) + 1
                if self._odd_paces[voice_id] < _PACE_ODD_RUN:
                    return
            self._odd_paces[voice_id] = 0
            pace = (before + pace) / 2
        self._native[voice_id] = pace
        if abs(pace - (_saved_pace(voice_id) or 0)) > pace * _PACE_SAVE_CHANGE:
            _save_pace(voice_id, pace)

    def render(self, text, voice_id, wpm, cancel):
        codes = self._check_ready(voice_id, cancel)
        if not any(ch.isalnum() for ch in text):
            return np.zeros(self.sample_rate // 10, dtype=np.int16), self.sample_rate
        if self._engine_factory is None:
            _load_engine(cancel)
        _take_turn(cancel)
        try:
            _cancel_idle_timer()  # it must not let the model go in the middle of a long sentence
            engine = self._engine_factory() if self._engine_factory else shared_engine()
            audio = engine.speak(codes, text, cancel, pace=self.native_wpm(wpm, voice_id))
        finally:
            _release_when_idle()
            _engine_lock.release()
        self._note_pace(voice_id, text, audio.size / engine.rate)
        return _to_pcm(audio), engine.rate

    def stream(self, text, voice_id, wpm, cancel):
        """Yields AudioBlocks as they are made: always at least one. Holds the model until it ends
        or is closed, on the thread that started it."""
        codes = self._check_ready(voice_id, cancel)
        if not any(ch.isalnum() for ch in text):
            yield AudioBlock(np.zeros(self.sample_rate // 10, dtype=np.int16), self.sample_rate)
            return
        if self._engine_factory is None:
            _load_engine(cancel)
        _take_turn(cancel)
        made = 0
        try:
            _cancel_idle_timer()  # it must not let the model go in the middle of a long sentence
            engine = self._engine_factory() if self._engine_factory else shared_engine()
            for audio, left in engine.speak_blocks(codes, text, cancel, pace=self.native_wpm(wpm, voice_id)):
                made += audio.size
                yield AudioBlock(_to_pcm(audio), engine.rate, left, engine.speed, _DECODE_EVERY * _FRAME_SECONDS)
            if not made:
                yield AudioBlock(np.zeros(0, dtype=np.int16), engine.rate)
        finally:
            _release_when_idle()
            _engine_lock.release()
        self._note_pace(voice_id, text, made / engine.rate, smooth=True)


def _to_pcm(audio):
    return (np.clip(audio, -1, 1) * 32767).astype(np.int16)
