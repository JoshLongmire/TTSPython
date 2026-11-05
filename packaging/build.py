"""Build the standalone app for this OS.

Windows: dist/TTSPython/TTSPython.exe, zipped as dist/TTSPython-<version>-windows-x64.zip
Linux:   dist/TTSPython/TTSPython, archived as dist/TTSPython-<version>-linux-x86_64.tar.gz
PyInstaller cannot cross-compile, so each OS builds its own package.

Usage: python packaging/build.py [--no-archive]
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from ttspython import APP_NAME, __version__  # noqa: E402


def folder_size(path):
    return sum(os.path.getsize(os.path.join(d, f)) for d, _, files in os.walk(path) for f in files)


# What requirements.txt brings in. PyAV is left out of the build (see TTSPython.spec).
LICENSE_ROOTS = ("PySide6-Essentials", "pyttsx3", "comtypes", "pynput", "numpy", "sounddevice", "lameenc",
                 "faster-whisper", "sherpa-onnx")
NOT_BUNDLED = {"av"}
NOTICE_INTRO = f"""{APP_NAME} is free software under the MIT License (see LICENSE.txt). It includes the components below,
each under its own license.

Qt and PySide6 are used unmodified under the GNU Lesser General Public License v3. Source: https://code.qt.io. You may
replace their libraries in the _internal/PySide6 folder. LAME (through lameenc) is under the LGPL too. Source:
https://lame.sourceforge.io. The full texts of the LGPL and the GPL are below, with lameenc and numpy.
CTranslate2 ships Intel's OpenMP runtime (libiomp5md.dll) and a small cuDNN loader (cudnn64_9.dll), included as it provides them.
This package also includes Python (PSF License, https://docs.python.org/3/license.html) and PortAudio (MIT License,
https://www.portaudio.com/license.html).

Not included: Piper voices, the Piper program and the speech recognition models are downloaded only when you ask for
them, and keep their own licenses. (Piper includes eSpeak NG, GPL-3.0, and runs as a separate program.)
"""


def _dist_key(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def _marker_applies(marker):
    from packaging.markers import Marker

    return Marker(marker).evaluate()


def bundled_distributions(roots=LICENSE_ROOTS):
    """The installed packages the roots depend on, on this OS, by normalized name."""
    found = {}
    pending = list(roots)
    while pending:
        name = pending.pop()
        key = _dist_key(name)
        if key in found or key in NOT_BUNDLED:
            continue
        try:
            dist = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        found[key] = dist
        for requirement in dist.requires or []:
            spec, _, marker = requirement.partition(";")
            marker = marker.strip()
            if "extra" in marker or (marker and not _marker_applies(marker)):
                continue
            pending.append(re.match(r"[A-Za-z0-9._-]+", spec.strip()).group())
    return found


def _license_files(dist):
    """Its license and notice files: in its metadata folder, or next to its code."""
    return [file for file in dist.files or []
            if re.search(r"licen[cs]e|copying|notice", file.name, re.I) and "commercial" not in file.name.lower()
            and file.suffix.lower() in ("", ".txt", ".md", ".rst")
            and (".dist-info" in str(file) or len(file.parts) <= 2)]


def third_party_notices():
    parts = [NOTICE_INTRO]
    dists = bundled_distributions()
    for key in sorted(dists):
        dist = dists[key]
        meta = dist.metadata
        kind = meta.get("License-Expression") or (meta.get("License") or "").split("\n")[0].strip() or ", ".join(
            c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License"))
        home = meta.get("Home-page") or next((u.split(",", 1)[-1].strip() for u in meta.get_all("Project-URL") or []), "")
        parts.append(f"{'=' * 78}\n{meta['Name']} {dist.version}\nLicense: {kind or 'see the project page'}\n{home}\n")
        for file in _license_files(dist):
            try:
                with open(file.locate(), encoding="utf-8", errors="replace") as f:
                    parts.append(f"--- {file.name}\n{f.read().strip()}\n")
            except OSError:
                pass
    notices = "\n".join(parts)
    for needed in ("GNU LESSER GENERAL PUBLIC LICENSE", "GNU GENERAL PUBLIC LICENSE"):
        if needed not in notices:  # they come with other packages: a new version could drop them
            sys.exit(f"Build failed, the notices lack the text of the {needed}")
    return notices


def add_license_files(app_dir):
    """A package given to people has to carry the licenses of what is in it."""
    shutil.copy2(os.path.join(ROOT, "LICENSE"), os.path.join(app_dir, "LICENSE.txt"))
    with open(os.path.join(app_dir, "THIRD_PARTY_LICENSES.txt"), "w", encoding="utf-8") as f:
        f.write(third_party_notices())


def self_test(app_dir):
    """Start the built app with temporary settings and data; it reports what it could not load, then quits."""
    with tempfile.TemporaryDirectory(prefix="ttspython-build-check-") as tmp:
        report_path = os.path.join(tmp, "report.json")
        env = dict(os.environ, TTSPYTHON_SELFTEST=report_path, TTSPYTHON_SETTINGS=os.path.join(tmp, "settings.json"),
                   TTSPYTHON_DATA=os.path.join(tmp, "data"), HF_HOME=os.path.join(tmp, "hf"), QT_QPA_PLATFORM="offscreen")
        subprocess.run([os.path.join(app_dir, APP_NAME)], env=env, check=True, timeout=180)
        with open(report_path, encoding="utf-8") as f:
            problems = json.load(f)["problems"]
    if problems:
        sys.exit("The built app's self-test failed:\n" + "\n".join(problems))
    print("Self-test: no problems")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-archive", action="store_true", help="Skip the .zip / .tar.gz")
    parser.add_argument("--check", action="store_true", help="Run the built app's self-test; fail if it finds a problem")
    args = parser.parse_args(argv)
    windows = sys.platform == "win32"
    dist = os.path.join(ROOT, "dist")
    work = os.path.join(ROOT, "build")
    t0 = time.perf_counter()

    subprocess.run([sys.executable, os.path.join(HERE, "make_icon.py"), os.path.join(work, "icon")], check=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", os.path.join(HERE, "TTSPython.spec"), "--noconfirm",
                    "--clean", "--distpath", dist, "--workpath", os.path.join(work, "pyinstaller")], check=True)
    app_dir = os.path.join(dist, APP_NAME)
    with open(os.path.join(work, "pyinstaller", APP_NAME, f"warn-{APP_NAME}.txt"), encoding="utf-8") as f:
        broken = [line.strip() for line in f if line.startswith("invalid module named ttspython")]
    if broken:  # PyInstaller only warns when one of our modules does not compile
        sys.exit("Build failed, these modules were left out:\n" + "\n".join(broken))

    if not windows:
        shutil.copy2(os.path.join(work, "icon", "TTSPython.png"), os.path.join(app_dir, "TTSPython.png"))
        for name in ("install.sh", "uninstall.sh"):
            target = os.path.join(app_dir, name)
            shutil.copy2(os.path.join(HERE, "linux", name), target)
            os.chmod(target, 0o755)

    add_license_files(app_dir)
    print(f"\nBuilt {app_dir} ({folder_size(app_dir) / 1e6:.0f} MB) in {time.perf_counter() - t0:.0f} s")
    if args.check:
        self_test(app_dir)
    if args.no_archive:
        return 0
    arch = "x64" if windows else platform.machine() or "x86_64"
    base = os.path.join(dist, f"{APP_NAME}-{__version__}-{'windows' if windows else 'linux'}-{arch}")
    archive = shutil.make_archive(base, "zip" if windows else "gztar", dist, APP_NAME)
    print(f"Archive {archive} ({os.path.getsize(archive) / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
