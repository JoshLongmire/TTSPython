"""Audio device listing and stable device references.

PortAudio indexes change when devices are plugged in or the PC reboots, so
settings store {"name", "hostapi", "index"} and resolve by name first.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceInfo:
    index: int
    name: str
    hostapi: str
    max_input: int
    max_output: int
    default_samplerate: float

    def ref(self):
        return {"name": self.name, "hostapi": self.hostapi, "index": self.index}


def query_devices(sd=None):
    """All devices as DeviceInfo. Returns [] if sounddevice is unavailable."""
    try:
        if sd is None:
            import sounddevice as sd  # noqa: PLW0621
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
    except Exception:
        return []
    out = []
    for idx, dev in enumerate(devices):
        api_index = dev.get("hostapi", 0)
        try:
            api_name = hostapis[api_index]["name"]
        except Exception:
            api_name = ""
        out.append(DeviceInfo(
            index=idx,
            name=str(dev.get("name", f"Device {idx}")),
            hostapi=api_name,
            max_input=int(dev.get("max_input_channels", 0)),
            max_output=int(dev.get("max_output_channels", 0)),
            default_samplerate=float(dev.get("default_samplerate", 0) or 0),
        ))
    return out


def rescan(sd=None):
    """Make PortAudio list devices plugged in since it started (it scans only once).

    Only safe while no stream is open; device indexes may change, so refs must be
    resolved again afterwards. Returns False if it could not rescan.
    """
    try:
        if sd is None:
            import sounddevice as sd  # noqa: PLW0621
        sd._terminate()
        sd._initialize()
        return True
    except Exception:
        return False


def default_hostapi_name(sd=None):
    try:
        if sd is None:
            import sounddevice as sd  # noqa: PLW0621
        return sd.query_hostapis(sd.default.hostapi)["name"]
    except Exception:
        return ""


def list_devices(kind, devices=None, hostapi=None):
    """Every device usable for kind ("input"/"output"), default host API first.

    Devices that exist only on another host API (WASAPI, WDM-KS) stay selectable.
    """
    devices = query_devices() if devices is None else devices
    hostapi = default_hostapi_name() if hostapi is None else hostapi
    usable = [d for d in devices if (d.max_input if kind == "input" else d.max_output) > 0]
    return sorted(usable, key=lambda d: (bool(hostapi) and d.hostapi != hostapi, d.hostapi, d.index))


def label(device, default_hostapi=""):
    """Display name; devices from a non-default host API show it, e.g. "Speakers (WASAPI)"."""
    if device.hostapi and device.hostapi != default_hostapi:
        api = device.hostapi.replace("Windows ", "")
        return f"{device.name}  ({api})"
    return device.name


def resolve(ref, kind, devices=None):
    """Return the PortAudio index for a stored ref, or None for the system default."""
    if not ref:
        return None
    devices = query_devices() if devices is None else devices
    usable = [d for d in devices if (d.max_input if kind == "input" else d.max_output) > 0]
    name = ref.get("name") or ""
    hostapi = ref.get("hostapi") or ""
    index = ref.get("index")
    if name:
        for d in usable:
            if d.name == name and (not hostapi or d.hostapi == hostapi):
                return d.index
        for d in usable:
            if d.name == name:
                return d.index
        return None
    if isinstance(index, int):
        for d in usable:
            if d.index == index:
                return d.index
    return None


def complete_ref(ref, kind, devices=None):
    """Fill in the name of an index-only ref (migrated from v4)."""
    if not ref or ref.get("name"):
        return ref
    devices = query_devices() if devices is None else devices
    idx = resolve(ref, kind, devices)
    for d in devices:
        if d.index == idx:
            return d.ref()
    return None


def describe(ref):
    if not ref:
        return "System default"
    return ref.get("name") or f"Device {ref.get('index')}"
