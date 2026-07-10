# TTSPython — Quick Reference Guide (v4.0.0)

## 🎯 At a Glance

Your TTS application now has these major feature areas:

### 0️⃣ Speech-to-Text (STT)
- 🎙 Offline speech recognition via faster-whisper (CPU, int8)
- Mode toggle switches between TTS and STT
- Start/Stop Recording button (STT mode) transcribes microphone audio into the editor
- STT input mic, unload-when-idle, and auto-unload delay in Settings → Audio

### 1️⃣ Core TTS Features
- ▶ Speak All Text (`Ctrl+Enter`)
- ▶ Speak Selected Text (`Ctrl+Shift+Enter`)
- ■ Stop Speaking (`Escape`)
- Voice, Rate, and Volume controls
- Refresh / "🎙️ Voices" buttons for managing SAPI5 voices

### 2️⃣ File Operations
- 📁 Open File (`Ctrl+O`)
- 💾 Save File (`Ctrl+S`)
- 💾 Save As (`Ctrl+Shift+S`)
- 📋 Paste (`Ctrl+V`)
- 🗑️ Clear (`Ctrl+L`)

### 3️⃣ 🎵 Export Audio
- Export text to WAV/MP3 files (`Ctrl+E`)
- Uses the current voice and rate/volume settings
- Perfect for creating audio files

### 4️⃣ 🔍 Find & Replace
- Search with case sensitivity (`Ctrl+F`)
- Regular expression support
- Replace one or all occurrences
- Highlights the current match in the editor

### 5️⃣ 🎨 Themes (11 Presets)
- 11 built-in themes via Settings → Theme tab
- Dark, Twilight, Light, High Contrast, Forest, New Vegas, Spiral, Poly, Sunset, Paper, Graphite
- The now-playing queue item is highlighted with the theme accent color
- Settings persist automatically

### 6️⃣ 📎 Clipboard Monitoring
- Auto-speak OR queue copied text
- Two modes: **Speak** (immediate) or **Queue** (add to queue)
- **Auto-Queue** option: queue clipboard text while already speaking
- Toggle monitoring on/off with checkbox
- Background monitoring (1-second interval, or 2s in Performance Mode)
- Smart filtering (ignores text shorter than 5 chars)
- Perfect for collecting articles while browsing!

### 7️⃣ 📋 Speech Queue System
- **Add Current Text** - Queue the editor text
- **Add File(s)** - Queue multiple text files at once
- **Play Queue** - Sequential playback
- **Remove Selected** - Delete specific queue items (or press **Delete**)
- **Move Up** / **Move Down** - Reorder queue items
- **Loop queue** - Repeat playback from the top
- **Clear Queue** - Remove all items
- Tree view with a color icon per item (💬 text / 📄 file / 📋 clipboard)
- Highlighted with the theme accent color while playing
- Progress tracking

### 8️⃣ ✨ Word Highlighting
- Real-time word highlighting during speech (when supported by the engine)
- Highlight follows along using the theme accent color
- Auto-scrolls to keep the word visible

### 9️⃣ ⚙️ Settings & Customization
- Customize all 10 keyboard shortcuts (Hotkeys tab)
- Theme preset + Performance Mode (Theme tab)
- STT input mic, TTS output note, and STT unload options (Audio tab)
- Persistent settings (saved to `tts_settings.json`)

---

## 📋 Complete Hotkey List

| Action | Default Hotkey | Customizable |
|--------|---------------|--------------|
| Speak All | `Ctrl+Enter` | ✅ |
| Speak Selected | `Ctrl+Shift+Enter` | ✅ |
| Stop | `Escape` | ✅ |
| Open File | `Ctrl+O` | ✅ |
| Save File | `Ctrl+S` | ✅ |
| Save As | `Ctrl+Shift+S` | ✅ |
| Paste | `Ctrl+V` | ✅ |
| Clear | `Ctrl+L` | ✅ |
| Find/Replace | `Ctrl+F` | ✅ |
| Export Audio | `Ctrl+E` | ✅ |

---

## 🎬 Common Workflows

### Workflow 1: Quick Text Reading
1. Paste text (`Ctrl+V`)
2. Click "▶ Speak All" or press `Ctrl+Enter`
3. Watch words highlight as they're spoken
4. Press `Escape` to stop

### Workflow 2: Create Audio File
1. Type or paste your text
2. Click "🎵 Export Audio" or press `Ctrl+E`
3. Choose WAV or MP3 format
4. Save to your desired location

### Workflow 3: Audiobook Playlist
1. Click "📄 Add File(s)" in Queue panel
2. Select multiple text files (Ctrl+Click)
3. Review queue list
4. Click "▶️ Play Queue"
5. Sit back and listen to all files in sequence!

### Workflow 4: Edit Before Speaking
1. Open or paste text
2. Click "🔍 Find/Replace" or press `Ctrl+F`
3. Fix typos or replace words
4. Click "▶ Speak All"

### Workflow 5: Clipboard Auto-Speak
1. Enable "📎 Monitor Clipboard"
2. Select "Speak" mode
3. Copy any text from anywhere
4. Text automatically speaks
5. Great for reading web articles!

### Workflow 6: Clipboard Queue Collection ⭐ NEW!
1. Enable "📎 Monitor Clipboard"
2. Select "Queue" mode
3. Browse the web and copy interesting articles
4. Each copied text is added to queue automatically
5. Click "▶ Play Queue" when ready
6. Listen to all collected content in sequence!

---

## 💡 Pro Tips

1. **Clipboard Queue for Research**: Enable Queue mode, copy excerpts from multiple sources, play back later! ⭐
2. **Batch Audio Creation**: Use Queue + Export to create multiple audio files
3. **Theme for Night**: Pick Dark, Twilight, or Graphite in **Settings → Theme** for comfortable late-night use
4. **Custom Shortcuts**: Set `F1` for Speak All for quick access
5. **Queue Management**: Remove items you've already heard while queue is playing
6. **Stop Mid-Queue**: Press `Escape` to stop queue at any time
7. **Preview Queue Items**: Queue shows first 50 chars of each text item
8. **Queue Icons**: 💬 for text, 📄 for files, 📋 for clipboard items
9. **Mix Sources**: Combine files, manual text, and clipboard in one queue!

---

## 🗂️ Files Created by App

- `tts_settings.json` - Your preferences (theme, hotkeys, clipboard monitor)
- *Automatically saved on exit*

---

## 📊 Feature Comparison

| Feature | Before | Now |
|---------|--------|-----|
| STT (Speech-to-Text) | ❌ | ✅ Offline faster-whisper |
| Themes | ❌ | ✅ 11 presets |
| Export Audio | ❌ | ✅ WAV/MP3 |
| Find/Replace | ❌ | ✅ Full search + regex |
| Queue System | ❌ | ✅ Multiple items |
| Clipboard Monitor | ❌ | ✅ Speak or Queue |
| Word Highlighting | ❌ | ✅ Real-time |
| Custom Hotkeys | ❌ | ✅ All 10 actions |
| Settings Persistence | ❌ | ✅ Auto-save |

---

## 🎓 Learning Path

**Beginner**: Basic TTS (Speak All, Stop, Volume)
↓
**Intermediate**: File operations, Export audio, Themes
↓
**Advanced**: Queue system, Custom hotkeys, Clipboard monitoring
↓
**Expert**: Regex search, Audiobook workflows, Batch processing

---

Enjoy your feature-rich TTS application! 🎉

