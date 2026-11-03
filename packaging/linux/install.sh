#!/usr/bin/env bash
# Install TTSPython for the current user (no root needed):
#   ~/.local/opt/TTSPython        the app
#   ~/.local/bin/ttspython        command to start it (and send it --mini, --stop, ...)
#   a menu entry and icon
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.local/opt/TTSPython"
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/256x256/apps"

if [ "$SRC" != "$DEST" ]; then
    rm -rf "$DEST"
    mkdir -p "$(dirname "$DEST")"
    cp -a "$SRC" "$DEST"
fi
mkdir -p "$BIN" "$APPS" "$ICONS"
ln -sf "$DEST/TTSPython" "$BIN/ttspython"
cp "$DEST/TTSPython.png" "$ICONS/ttspython.png"
cat > "$APPS/ttspython.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=TTSPython
Comment=Offline text-to-speech and dictation
Exec=$DEST/TTSPython
Icon=ttspython
Terminal=false
Categories=Utility;Accessibility;AudioVideo;
Actions=Mini;Dictate;

[Desktop Action Mini]
Name=Show the mini bar
Exec=$DEST/TTSPython --mini

[Desktop Action Dictate]
Name=Start or stop dictation
Exec=$DEST/TTSPython --toggle-dictation
DESKTOP
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" >/dev/null 2>&1 || true

echo "Installed to $DEST"
echo "Start it from your app menu or with: ttspython"
missing=""
command -v espeak-ng >/dev/null || missing="$missing espeak-ng"
ldconfig -p 2>/dev/null | grep -q libportaudio.so || missing="$missing libportaudio2"
if [ -n "$missing" ]; then
    echo "Also needed for speech and audio:$missing"
    echo "  Debian/Ubuntu: sudo apt install$missing"
fi
