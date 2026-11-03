# PyInstaller spec for the Windows and Linux builds. Run packaging/build.py rather than this directly.
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
sys.path.insert(0, ROOT)
from ttspython import APP_NAME, __version__  # noqa: E402

WINDOWS = sys.platform == "win32"
ICON_DIR = os.path.join(ROOT, "build", "icon")

datas = collect_data_files("faster_whisper")  # the Silero voice-activity model
datas += [(os.path.join(ROOT, "ttspython", "core", "tts", "piper_voices.json"), "ttspython/core/tts")]
binaries = collect_dynamic_libs("ctranslate2")
# Instant dictation preview. Its onnxruntime.dll must stay beside its module: Windows ships an
# older onnxruntime.dll in System32 that it would load instead (and crash).
binaries += collect_dynamic_libs("sherpa_onnx")
hiddenimports = ["pyttsx3.drivers"]
if WINDOWS:
    hiddenimports += ["pyttsx3.drivers.sapi5", "comtypes.stream"]
else:
    hiddenimports += ["pyttsx3.drivers.espeak"] + collect_submodules("pynput")

excludes = [
    "av",  # see rthook_no_av.py
    "tkinter", "_tkinter", "pytest", "pytestqt", "IPython", "matplotlib", "PIL", "soundcard", "psutil",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtPdf", "PySide6.QtOpenGL",
    "PySide6.QtWebEngineCore", "PySide6.QtMultimedia", "PySide6.Qt3DCore",
    # Pulled in by command-line and doc tools of dependencies, never by the app:
    "pygments", "setuptools", "pydoc_data", "click", "huggingface_hub.cli", "huggingface_hub.commands",
]

a = Analysis(
    [os.path.join(ROOT, "TTSPython.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    runtime_hooks=[os.path.join(SPECPATH, "rthook_no_av.py")],
    noarchive=False,
)

# Files the app never loads:
# - Qt: the software OpenGL renderer, Qt's own translations (no translator is installed), TLS and
#   network-information plugins (QtNetwork is only used for the local single-instance socket;
#   the TLS plugin also dragged in an OpenSSL copy found on PATH), image formats other than
#   SVG/ICO, unused platform/style/touch plugins (the app uses Fusion; CI uses offscreen).
# - PortAudio builds for other CPUs and the ASIO variants (sounddevice loads libportaudio64bit.dll).
# - sherpa-onnx's C and C++ API libraries and headers (the Python module does not use them).
_SKIP_DIRS = ("/translations/", "/plugins/tls/", "/plugins/networkinformation/", "/plugins/styles/",
              "/plugins/generic/", "/sherpa_onnx/include/")
_SKIP_FILES = ("opengl32sw.dll", "libcrypto-3-x64.dll", "libssl-3-x64.dll", "qdirect2d.dll", "qminimal.dll",
               "sherpa-onnx-c-api.dll", "sherpa-onnx-cxx-api.dll", "sherpa-onnx-c-api.lib",
               "sherpa-onnx-cxx-api.lib", "libsherpa-onnx-c-api.so", "libsherpa-onnx-cxx-api.so")
_KEEP_IMAGE_FORMATS = ("qsvg", "qico")


def _needed(entry):
    dest = entry[0].replace("\\", "/").lower()
    name = dest.rsplit("/", 1)[-1]
    if dest.startswith("av.libs/") or name in _SKIP_FILES or any(d in "/" + dest for d in _SKIP_DIRS):
        return False
    if "/plugins/imageformats/" in dest and not name.startswith(_KEEP_IMAGE_FORMATS) \
            and not name.startswith(tuple("lib" + k for k in _KEEP_IMAGE_FORMATS)):
        return False
    if "portaudio-binaries/" in dest and name.endswith((".dll", ".dylib")) and name != "libportaudio64bit.dll":
        return False
    return True


a.binaries = [e for e in a.binaries if _needed(e)]
a.datas = [e for e in a.datas if _needed(e)]
pyz = PYZ(a.pure)

version_file = None
if WINDOWS:
    from PyInstaller.utils.win32 import versioninfo as vi

    nums = tuple(int(n) for n in __version__.split(".")[:3]) + (0,)
    version_file = vi.VSVersionInfo(
        ffi=vi.FixedFileInfo(filevers=nums, prodvers=nums),
        kids=[
            vi.StringFileInfo([vi.StringTable("040904B0", [
                vi.StringStruct("CompanyName", "Pure Tech"),
                vi.StringStruct("FileDescription", "TTSPython: offline text-to-speech and dictation"),
                vi.StringStruct("FileVersion", __version__),
                vi.StringStruct("InternalName", APP_NAME),
                vi.StringStruct("OriginalFilename", f"{APP_NAME}.exe"),
                vi.StringStruct("ProductName", APP_NAME),
                vi.StringStruct("ProductVersion", __version__),
            ])]),
            vi.VarFileInfo([vi.VarStruct("Translation", [0x0409, 1200])]),
        ],
    )

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,
    upx=False,
    icon=os.path.join(ICON_DIR, "TTSPython.ico") if WINDOWS else None,
    version=version_file,
)
coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME, upx=False)
