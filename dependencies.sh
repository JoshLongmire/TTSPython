#!/usr/bin/env bash
# TTSPython dependency installer (Linux / macOS)
# Installs missing Python packages only; does not upgrade Python or pip.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "========================================="
echo "TTSPython dependency installer"
echo "========================================="
echo
echo "This script installs missing dependencies only."
echo "It does NOT upgrade Python or pip."
echo

if command -v uv >/dev/null 2>&1; then
  if [[ ! -d .venv ]]; then
    echo "Creating .venv with uv..."
    uv venv .venv
  fi
  # shellcheck disable=SC1091
  source .venv/bin/activate
  echo "Python: $(python -V)"
  echo
  uv pip install -r requirements.txt
else
  PYTHON="${PYTHON:-python3}"
  if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "[ERROR] python3 not found in PATH."
    exit 1
  fi
  echo "Python: $($PYTHON -V)"
  echo
  if [[ ! -d .venv ]]; then
    echo "Creating .venv..."
    "$PYTHON" -m venv .venv
  fi
  # shellcheck disable=SC1091
  source .venv/bin/activate
  python -m pip install -r requirements.txt
fi

echo
echo "========================================="
echo "Complete."
echo "Activate with:  source .venv/bin/activate"
echo "Run with:       python TTSPython.py"
echo "========================================="

if [[ "$(uname -s)" == "Linux" ]]; then
  echo
  echo "Linux system packages (if missing):"
  echo "  - espeak-ng   (TTS voices; required by pyttsx3)"
  echo "  - alsa-utils  (aplay; used by pyttsx3 for playback)"
  echo "  - tk / tcl    (tkinter GUI)"
  echo "  - portaudio   (microphone input for STT)"
fi
