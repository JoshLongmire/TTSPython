"""TTSPython: offline text-to-speech and speech-to-text desktop app."""

__version__ = "5.0.0"
APP_NAME = "TTSPython"


def _keep_python_away_from_wmi():
    """Python's platform module asks Windows for its version through WMI, on a native thread that can
    outlive the query and crash the whole process when WMI is slow (a busy PC). The audio library
    asks at import, so 9 of 180 starts crashed on a loaded test PC. Without WMI, the same questions
    are answered from the Windows version call and the registry, which is all the app needs."""
    import platform

    platform._wmi = None


_keep_python_away_from_wmi()
