#!/usr/bin/env bash
# Builds the standalone Linux app: dist/TTSPython/TTSPython
# and dist/TTSPython-<version>-linux-<arch>.tar.gz. Uses .venv if it exists.
# Build on the oldest distro you want to support (the app needs that glibc or newer).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python
"$PY" -m pip install -r requirements.txt "pyinstaller>=6.10"
"$PY" packaging/build.py "$@"
