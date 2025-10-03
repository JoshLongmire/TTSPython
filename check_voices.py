#!/usr/bin/env python3
"""
Quick script to check what TTS voices are installed on your system
"""

import pyttsx3

def check_voices():
    """List all available SAPI5 voices on the system"""
    try:
        print("\n" + "="*60)
        print("🎤 TTS VOICE CHECKER")
        print("="*60 + "\n")
        
        engine = pyttsx3.init()
        voices = engine.getProperty('voices')
        
        print(f"Found {len(voices)} voice(s) installed on your system:\n")
        
        for i, voice in enumerate(voices, 1):
            print(f"{'─'*60}")
            print(f"Voice #{i}")
            print(f"{'─'*60}")
            print(f"  Name:      {voice.name}")
            print(f"  ID:        {voice.id}")
            print(f"  Languages: {voice.languages if voice.languages else 'Not specified'}")
            print(f"  Gender:    {voice.gender if hasattr(voice, 'gender') else 'Not specified'}")
            print(f"  Age:       {voice.age if hasattr(voice, 'age') else 'Not specified'}")
            print()
        
        engine.stop()
        
        print("="*60)
        print("\n💡 To add more voices:")
        print("   1. Open Windows Settings (Win + I)")
        print("   2. Go to: Time & Language → Speech")
        print("   3. Click 'Add voices'")
        print("   4. Download voices you want")
        print("   5. Click 🔄 in the TTS app to refresh!")
        print("\n📖 See ADD_VOICES_GUIDE.md for detailed instructions")
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        print("Make sure pyttsx3 is installed: pip install pyttsx3\n")

if __name__ == "__main__":
    check_voices()
    input("Press Enter to exit...")

