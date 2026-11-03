# Build-only runtime hook. faster_whisper imports PyAV (FFmpeg, about 65 MB) at load time, but
# only uses it to decode audio files; TTSPython passes recorded audio as arrays. The build leaves
# PyAV out and this stands in for it.
import sys
import types


def _not_included(*_args, **_kwargs):
    raise RuntimeError("Decoding audio files is not included in this build")


_av = types.ModuleType("av")
_av.open = _not_included
sys.modules.setdefault("av", _av)
