"""Build the standalone app for this OS.

Windows: dist/TTSPython/TTSPython.exe, zipped as dist/TTSPython-<version>-windows-x64.zip
Linux:   dist/TTSPython/TTSPython, archived as dist/TTSPython-<version>-linux-x86_64.tar.gz
PyInstaller cannot cross-compile, so each OS builds its own package.

Usage: python packaging/build.py [--no-archive]
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from ttspython import APP_NAME, __version__  # noqa: E402


def folder_size(path):
    return sum(os.path.getsize(os.path.join(d, f)) for d, _, files in os.walk(path) for f in files)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-archive", action="store_true", help="Skip the .zip / .tar.gz")
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

    print(f"\nBuilt {app_dir} ({folder_size(app_dir) / 1e6:.0f} MB) in {time.perf_counter() - t0:.0f} s")
    if args.no_archive:
        return 0
    arch = "x64" if windows else platform.machine() or "x86_64"
    base = os.path.join(dist, f"{APP_NAME}-{__version__}-{'windows' if windows else 'linux'}-{arch}")
    archive = shutil.make_archive(base, "zip" if windows else "gztar", dist, APP_NAME)
    print(f"Archive {archive} ({os.path.getsize(archive) / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
