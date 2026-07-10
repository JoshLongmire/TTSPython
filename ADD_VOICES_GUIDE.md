# How to Add More Voices to Your TTS Application

## Current Situation

Your TTS app uses **Windows SAPI5 voices**. It automatically detects all voices installed on your system.

By default, Windows 10/11 comes with 2-3 voices:
- **David** (Male, English US)
- **Zira** (Female, English US)
- **Mark** (Male, English US)

## 🎤 Add More Voices

### Method 1: Free Windows Voices (Easiest)

**Step 1: Open Windows Settings**
```
Windows Key → Settings → Time & Language → Speech
```

**Step 2: Add Speech Voices**
1. Click "Add voices" or "Manage voices"
2. Browse available voices by language
3. Download the ones you want

**Available Languages Include:**
- English (UK, US, Australia, India)
- Spanish, French, German, Italian
- Chinese, Japanese, Korean
- Portuguese, Russian, Arabic
- And many more!

**Step 3: Restart Your TTS App**
The new voices will appear in the Voice dropdown automatically!

---

### Method 2: Third-Party SAPI5 Voices

**Free Options:**
1. **eSpeak** - Open source, many languages
   - Download: http://espeak.sourceforge.net/
   - Robotic but functional

2. **NVDA Voices** - Screen reader voices
   - Some can be used with SAPI5

**Paid Options (High Quality):**
1. **CereProc** - Natural-sounding voices
   - Website: https://www.cereproc.com/
   - Price: ~$30-50 per voice

2. **Ivona Voices** (now Amazon Polly)
   - Very natural speech
   - Price: ~$40-60 per voice

3. **NaturalReader** - Commercial voices
   - Website: https://www.naturalreaders.com/
   - Price: Subscription-based

4. **Acapela** - Professional voices
   - Website: https://www.acapela-group.com/
   - Price: ~$50+ per voice

---

## 🔄 How to Refresh the Voice List (Without Restarting)

The app already has built-in voice controls next to the Voice dropdown:

- **Refresh button (🔄)**: Re-scans your system for installed SAPI5 voices and updates the dropdown immediately — no restart needed.
- **"🎙️ Voices" button**: Opens Windows Speech settings (`ms-settings:speech`) so you can install new voices, then click **Refresh** to pick them up.

So the workflow is: install a voice in Windows → click the **🎙️ Voices** button (or open Speech settings yourself) → click **Refresh** → select the new voice from the dropdown.

---

## 📊 Check Currently Available Voices

Run this Python script to see what voices you have:

```python
import pyttsx3

engine = pyttsx3.init()
voices = engine.getProperty('voices')

print(f"\n🎤 You have {len(voices)} voice(s) installed:\n")
for i, voice in enumerate(voices, 1):
    print(f"{i}. {voice.name}")
    print(f"   ID: {voice.id}")
    print(f"   Languages: {voice.languages}")
    print()
```

---

## 🌍 Language-Specific Voice Recommendations

### English
- **UK**: Hazel (Female), George (Male) - Available in Windows
- **US**: Zira, David - Default
- **Australia**: Catherine - Windows add-on
- **India**: Heera, Ravi - Windows add-on

### Spanish
- **Spain**: Helena (Female), Pablo (Male)
- **Mexico**: Sabina (Female)

### French
- **France**: Hortense (Female), Paul (Male)
- **Canada**: Caroline (Female)

### German
- **Germany**: Hedda (Female), Stefan (Male)

### Asian Languages
- **Chinese (Mandarin)**: Huihui (Female), Kangkang (Male)
- **Japanese**: Haruka (Female), Ichiro (Male)
- **Korean**: Heami (Female)

---

## 💡 Pro Tips

1. **Test Before Using**: Some free voices sound robotic
2. **Language Packs**: Install Windows language packs for best results
3. **Neural Voices**: Worth the investment for professional use
4. **Storage**: Each voice is ~50-200 MB
5. **License**: Check license for commercial use

---

## 🎯 Quick Start: Add a New Windows Voice

**Fastest way to get more voices:**

1. Press `Windows + I` (Settings)
2. Go to: **Time & Language** → **Language & region**
3. Click "Add a language"
4. Choose a language (e.g., English (United Kingdom))
5. Download the language pack
6. Go to: **Time & Language** → **Speech**
7. The new voices appear in Windows!
8. In the app, click **🎙️ Voices** (or open Speech settings), then click **Refresh**
9. New voices are in the dropdown! 🎉

---

## ❓ Troubleshooting

**Problem**: New voice doesn't appear in app
- **Solution**: Click the **Refresh** button next to the Voice dropdown. If it still doesn't appear, fully restart the app.

**Problem**: Voice sounds robotic
- **Solution**: Try premium voices or neural voices from Azure

**Problem**: Can't find voice settings in Windows
- **Solution**: Windows 10: Settings → Time & Language → Speech
- **Solution**: Windows 11: Settings → Accessibility → Speech

**Problem**: Want to preview voices before downloading
- **Solution**: Use Windows Speech settings - it has a preview button

---

## 🚀 Next Steps

1. **Add 2-3 free Windows voices** (5 minutes)
2. **Click the "🎙️ Voices" button** in the app to open Windows Speech settings (or open it yourself)
3. **Install the voices**, then click **Refresh** in the app
4. **Try your TTS app with new voices** 
5. **If you love it, consider premium voices**

---

**Your TTS app will automatically detect and list ALL installed SAPI5 voices!** 🎤✨

