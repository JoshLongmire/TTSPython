#!/usr/bin/env python3
"""
Quick script to check what TTS voices are installed on your system.
"""

import sys

try:
    import pyttsx3
except ImportError:
    print("\n❌ Error: pyttsx3 is not installed.")
    print("Install dependencies: pip install -r requirements.txt\n")
    sys.exit(1)

IS_WINDOWS = sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")


def _init_engine():
    if IS_WINDOWS:
        return pyttsx3.init()
    try:
        return pyttsx3.init("espeak")
    except Exception:
        return pyttsx3.init()


def check_voices():
    """List all available TTS voices on the system."""
    try:
        print("\n" + "=" * 60)
        print("🎤 TTS VOICE CHECKER")
        print("=" * 60 + "\n")

        engine = _init_engine()
        voices = engine.getProperty("voices")

        backend = "SAPI5" if IS_WINDOWS else ("espeak-ng" if IS_LINUX else "system")
        print(f"Backend: {backend}")
        print(f"Found {len(voices)} voice(s) installed on your system:\n")

        for i, voice in enumerate(voices, 1):
            print(f"{'─' * 60}")
            print(f"Voice #{i}")
            print(f"{'─' * 60}")
            print(f"  Name:      {voice.name}")
            print(f"  ID:        {voice.id}")
            print(f"  Languages: {voice.languages if voice.languages else 'Not specified'}")
            print(f"  Gender:    {voice.gender if hasattr(voice, 'gender') else 'Not specified'}")
            print(f"  Age:       {voice.age if hasattr(voice, 'age') else 'Not specified'}")
            print()

        engine.stop()

        print("=" * 60)
        print("\n💡 To add more voices:")
        if IS_WINDOWS:
            print("   1. Open Windows Settings (Win + I)")
            print("   2. Go to: Time & Language → Speech")
            print("   3. Click 'Add voices'")
            print("   4. Download voices you want")
            print("   5. Click 🔄 in the TTS app to refresh!")
            print("\n📖 See ADD_VOICES_GUIDE.md for detailed instructions")
        elif IS_LINUX:
            print("   Install espeak-ng language data via your package manager,")
            print("   then refresh voices in the app (🔄).")
            print("   Example (Arch): sudo pacman -S espeak-ng")
        else:
            print("   Install additional system TTS voices for your platform.")
        print("=" * 60 + "\n")

    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        print("Make sure pyttsx3 is installed: pip install pyttsx3\n")
        sys.exit(1)


if __name__ == "__main__":
    check_voices()
    try:
        input("Press Enter to exit...")
    except EOFError:
        pass
