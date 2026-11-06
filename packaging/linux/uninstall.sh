#!/usr/bin/env bash
# Remove what install.sh added. Your settings, voices and recordings are kept unless you say otherwise:
#   uninstall.sh --delete-data   also deletes them, without asking
set -euo pipefail
rm -rf "$HOME/.local/opt/TTSPython"
rm -f "$HOME/.local/bin/ttspython" "$HOME/.local/share/applications/ttspython.desktop" \
      "$HOME/.local/share/icons/hicolor/256x256/apps/ttspython.png"
config="${XDG_CONFIG_HOME:-$HOME/.config}/ttspython"
data="${XDG_DATA_HOME:-$HOME/.local/share}/ttspython"
answer=no
if [ "${1:-}" = "--delete-data" ]; then
  answer=yes
elif [ -t 0 ]; then
  read -r -p "Also delete your settings, unsaved text, voices, voice recordings and the voice model? [y/N] " reply
  case "$reply" in [yY]*) answer=yes ;; esac
fi
if [ "$answer" = yes ]; then
  rm -rf "$config" "$data"
  echo "TTSPython and your data removed. Whisper models stay in ~/.cache/huggingface."
else
  echo "TTSPython removed. Your data is kept in $config and $data"
fi
