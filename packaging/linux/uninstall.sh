#!/usr/bin/env bash
# Remove what install.sh added. Your settings in ~/.config/ttspython are kept.
set -euo pipefail
rm -rf "$HOME/.local/opt/TTSPython"
rm -f "$HOME/.local/bin/ttspython" "$HOME/.local/share/applications/ttspython.desktop" \
      "$HOME/.local/share/icons/hicolor/256x256/apps/ttspython.png"
echo "TTSPython removed. Settings kept in ~/.config/ttspython"
