# Changelog - TTSPython

## Version 3.0 - April 9, 2026
- Added Pure Tech as a collaborator for their help in 3.0
- Huge UI Changes
	- Imported Pure Tech's theme system
	- Tabs added for Theme & Audio in the settings window
	- Replaced 8 second recording button with start and stop buttons
	- Settings dialog now stays open after saving
	- Simplified button labeling and alignment for better Windows rendering consistency.
	- App window title is now `TTSPython`
- Revised documents and put them into a `docs` folder
	- Added MIT License to repo
- Added a Speech to Text Mode using `faster_whisper`
- Added Audio settings
- Added `create_shortcut.bat` to create a shortcut, as opposed to launching the script in the repo everytime.
- Bug fixes
	- Fixed tts_settings.json breaking the script by saving settings atomically [Save as .tmp -> Replace -> if corrupted, replace file with defaults if a backup is not saved]
	- Fixed an STT callback transcription failure, and added a processing guard that prevents overlapping transcription runs
---

## Version 2.2 - October 2, 2025

### 🎤 Voice Management Features

**New: Refresh Voices Button**
- Added 🔄 button next to voice selector
- Refresh voice list without restarting app
- Automatically detects newly installed voices
- Shows helpful message about adding more voices

**New: Voice Checker Script**
- Run `check_voices.py` to see all installed voices
- Lists voice names, languages, gender, and age
- Helpful for checking what voices you have

**New: Add Voices Guide**
- Complete guide on adding more voices (`ADD_VOICES_GUIDE.md`)
- Instructions for free Windows voices
- Info on premium voice options
- Language-specific recommendations

---

## Version 2.1 - October 2, 2025

### 🎉 Major New Feature: Clipboard Queue Mode

**What's New:**
- Clipboard monitoring now has **two modes**: Speak or Queue
- **Speak Mode**: Immediately speaks copied text (original behavior)
- **Queue Mode**: Automatically adds copied text to speech queue ⭐ NEW!

**How to Use:**
1. Enable "📎 Monitor Clipboard" checkbox
2. Choose your mode:
   - **Speak**: For immediate playback
   - **Queue**: For collecting items to play later
3. Copy text from anywhere
4. In Queue mode, click "▶ Play Queue" when ready to listen

**Perfect For:**
- 📚 Research: Copy excerpts from multiple web pages, listen to all later
- 📰 News Reading: Queue up articles while browsing, batch listen
- 📖 Study Materials: Collect lecture notes and review in sequence
- 🌐 Multi-source Content: Gather text from different sources for continuous playback

**Visual Indicators:**
- Queue items from clipboard show "📋 Clipboard:" prefix
- Easy to distinguish from files (📄) and manual text entries

### 🐛 Critical Bug Fix: Python 3.13 Threading

**Problem Solved:**
- Fixed GIL (Global Interpreter Lock) error that was crashing the app in Python 3.13
- Error: "PyEval_RestoreThread: the function must be called with the GIL held..."

**Solution:**
- Added proper COM (Component Object Model) initialization for Windows threads
- `pythoncom.CoInitialize()` at thread start
- `pythoncom.CoUninitialize()` at thread end
- Applied to both regular speech and queue playback

**Result:**
- ✅ App now runs perfectly on Python 3.13
- ✅ No more crashes during TTS operations
- ✅ All features work smoothly with threading
- ✅ Backward compatible with older Python versions

### 📝 Files Modified

1. **TTSPython.py**
   - Added clipboard mode selection (Speak/Queue)
   - Enhanced `monitor_clipboard()` to support both modes
   - Fixed `_speak_worker()` with COM initialization
   - Fixed `_play_queue_worker()` with COM initialization
   - Better lambda capture to prevent closure issues

2. **FEATURE_GUIDE.md**
   - Updated clipboard monitoring section
   - Added details about Speak vs Queue modes

3. **QUICK_REFERENCE.md**
   - Added Workflow 6: Clipboard Queue Collection
   - Updated Pro Tips with clipboard queue strategies
   - Enhanced feature descriptions

4. **PYTHON_313_FIX.md**
   - Updated with COM initialization solution
   - Explained the root cause (Windows SAPI5 + threading)
   - Provided code examples

---

## Version 2.0 - October 2, 2025

### 🎉 Major Features Added

1. **Speech Queue System**
   - Queue multiple text sections or files
   - Sequential playback with visual feedback
   - Add current text, files, or clipboard items
   - Play, pause, remove, clear controls

2. **Export Audio to File**
   - Export text as WAV/MP3 files
   - Uses current voice settings
   - Hotkey: `Ctrl+E`

3. **Dark/Light Theme Toggle**
   - Beautiful dark theme for night use
   - Crisp light theme for daytime
   - Settings persist between sessions

4. **Find & Replace**
   - Full text search with highlighting
   - Case-sensitive and regex support
   - Replace one or all occurrences
   - Hotkey: `Ctrl+F`

5. **Hotkey Customization**
   - Settings dialog with visual hotkey capture
   - Customize all 10 keyboard shortcuts
   - Reset to defaults option
   - Settings save automatically

6. **Clipboard Monitoring**
   - Auto-speak copied text
   - Background monitoring (1-second interval)
   - Smart filtering (ignores short text)

7. **Word Highlighting**
   - Real-time word highlighting during speech
   - Yellow highlight that follows along
   - Auto-scrolls to keep word visible
   - Theme-adaptive colors

8. **Settings Persistence**
   - All settings save to `tts_settings.json`
   - Theme, hotkeys, clipboard monitor
   - Auto-loads on startup

---

## Version 1.0 - Original Release

### Core Features

- Text-to-speech for all text and selected text
- File operations (open, save, save as)
- Voice, rate, and volume controls
- Keyboard shortcuts
- Status bar feedback
- Stop functionality

---

## Statistics

- **Total Lines of Code**: 950+
- **Total Features**: 15+
- **Hotkeys**: 10 customizable
- **Themes**: 2 (Light + Dark)
- **Queue Modes**: File, Text, Clipboard
- **Python Compatibility**: 3.8 - 3.13

---

## What's Next?

Potential future enhancements:
- PDF and Word document support
- Pronunciation dictionary
- Pause/Resume functionality
- Recent files menu
- Text statistics
- Auto-scroll during speech
- Multi-language support

---

**Thank you for using TTS Application!** 🎉

For questions or suggestions, check the documentation:
- `FEATURE_GUIDE.md` - Complete feature documentation
- `QUICK_REFERENCE.md` - Quick lookup guide
- `PYTHON_313_FIX.md` - Technical details on threading fix

