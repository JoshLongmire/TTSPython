#!/usr/bin/env python3
"""
Quick script to check what TTS voices are installed on your system.
Uses the same speech engine as the app (SAPI5 on Windows, espeak-ng on Linux).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

IS_WINDOWS = sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")


def check_voices():
    """List all available TTS voices on the system."""
    try:
        from ttspython.core.tts.render import list_voices_once
    except ImportError as exc:
        print(f"\nError: a dependency is missing ({exc}).")
        print("Install dependencies: pip install -r requirements.txt\n")
        sys.exit(1)

    try:
        print("\n" + "=" * 60)
        print("TTS VOICE CHECKER")
        print("=" * 60 + "\n")

        backend, voices = list_voices_once()
        print(f"Backend: {backend}")
        print(f"Found {len(voices)} voice(s) installed on your system:\n")

        for i, voice in enumerate(voices, 1):
            print("-" * 60)
            print(f"Voice #{i}")
            print("-" * 60)
            print(f"  Name:      {voice.name}")
            print(f"  ID:        {voice.id}")
            print(f"  Language:  {voice.language or 'Not specified'}")
            print(f"  Gender:    {voice.gender or 'Not specified'}")
            print()

        print("=" * 60)
        print("\nTo add more voices:")
        if IS_WINDOWS:
            print("   1. Open Windows Settings (Win + I)")
            print("   2. Go to: Time & language > Speech")
            print("   3. Click 'Add voices' and download the ones you want")
            print("   4. Press Refresh next to the voice list in TTSPython")
            print("\nSee ADD_VOICES_GUIDE.md for detailed instructions")
        elif IS_LINUX:
            print("   Install espeak-ng language data via your package manager,")
            print("   then press Refresh next to the voice list in TTSPython.")
            print("   Example (Arch): sudo pacman -S espeak-ng")
        else:
            print("   Install additional system TTS voices for your platform.")
        print("=" * 60 + "\n")

    except Exception as e:
        print(f"\nError: {e}")
        print("Make sure the requirements are installed: pip install -r requirements.txt\n")
        sys.exit(1)


if __name__ == "__main__":
    check_voices()
    try:
        input("Press Enter to exit...")
    except EOFError:
        pass
