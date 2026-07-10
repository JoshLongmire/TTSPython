# TTSPython Features Guide (v4.0.0)

## Features

### Speech Queue System
- **Panel**: Dedicated queue panel in the main window (a tree view with a color icon per item: 💬 text / 📄 file / 📋 clipboard)
- **Functionality**: Queue multiple text sections or files to be read in sequence
- **Features**:
  - **Add Current Text**: Add the text currently in the editor to the queue
  - **Add File(s)**: Select multiple text files to add to queue at once
  - **Play Queue**: Start sequential playback of all queued items
  - **Remove Selected**: Remove a specific item from the queue (or press **Delete**)
  - **Clear Queue**: Remove all items from the queue
  - **Move Up** / **Move Down**: Reorder queue items
  - **Loop queue**: Repeat playback from the top when the queue finishes
  - Now-playing item highlighted with the theme accent color
  - Shows item count and progress
  - Can be stopped mid-playback with the Stop button
  - 0.5 second pause between queue items
- **Use Cases**:
  - Create audiobook playlists from multiple chapter files
  - Queue up multiple articles or documents for continuous listening
  - Prepare a reading list for hands-free consumption
  - Test different text segments without manual intervention

## 🎙️ Speech-to-Text (STT)

The app can also convert your speech to text, fully offline:

- **Engine**: faster-whisper, running locally on CPU using int8 quantization (no internet or API keys required)
- **Controls**: A **Mode** toggle button switches between TTS and STT. In STT mode, a Start/Stop Recording button appears
- **Recording**: Press Start Recording to capture from your microphone; press again (or Stop) to transcribe. The transcript is inserted into the editor
- **Performance**: The STT model is loaded on demand and can be unloaded to free memory
- **Options** (Settings → Audio tab):
  - Choose the STT input microphone
  - Unload STT model when idle (frees RAM, slower next transcription)
  - Auto-unload STT model after an idle delay (in minutes)

## Other Features

### 1. 🎵 Export Audio to File
- **Button**: "Export Audio" (color icon) in the file operations bar
- **Functionality**: Export your text as WAV or MP3 audio files
- **How to Use**: Click the button, choose save location, and the current text will be saved as an audio file
- Runs in a background thread, so the UI stays responsive while exporting; the button is disabled until it finishes
- **Hotkey**: `Ctrl+E`

### 2. 🎨 Themes (11 Presets)
- **Location**: Settings → Theme tab
- **Functionality**: Choose from 11 built-in color presets (not just a Dark/Light toggle)
- **Available themes**: Dark, Twilight, Light, High Contrast, Forest, New Vegas, Spiral, Poly, Sunset, Paper, Graphite
- **Features**:
  - Theme applies to the whole window, including the editor, queue, and highlight colors
  - The now-playing queue item is highlighted with the theme accent color
  - Switch themes anytime in **Settings → Theme** (applies to the whole window, including the editor, queue, and highlight colors)
  - Performance Mode toggle (lowers UI update frequency and clipboard polling) is also on the Theme tab
  - Settings persist between sessions

### 3. 🔍 Find & Replace
- **Button**: "🔍 Find/Replace" in the file operations bar
- **Hotkey**: `Ctrl+F`
- **Features**:
  - Find Next - locate text in your document
  - Replace - replace current selection
  - Replace All - replace all occurrences at once
  - Case-sensitive search option
  - Regular expression (regex) support
  - Highlights found text automatically

### 4. ⚙️ Settings - Hotkey Customization
- **Button**: "⚙️ Settings" in the file operations bar
- **Functionality**: Customize all keyboard shortcuts to your preference
- **Features**:
  - Visual hotkey capture (just press your desired key combo)
  - Reset to defaults restores hotkeys, theme, Performance Mode, and STT/audio settings
  - All 10 actions are customizable:
    - Speak All Text
    - Speak Selected Text
    - Stop Speaking
    - Open File
    - Save File
    - Save As
    - Paste Text
    - Clear Text
    - Find/Replace
    - Export Audio

### 5. 📎 Clipboard Monitoring (Enhanced!)
- **Controls**: "📎 Monitor Clipboard" with Speak/Queue radio buttons
- **Functionality**: Automatically speaks OR queues text when you copy it
- **Two Modes**:
  - **Speak Mode**: Immediately speaks copied text (original behavior)
  - **Queue Mode**: Adds copied text to speech queue for later playback ⭐ NEW!
- **Features**:
  - Toggle monitoring on/off easily
  - Choose action: immediate speak or add to queue
  - Only speaks when not already speaking (Speak mode)
  - Ignores very short clipboard content (< 5 chars)
  - Monitors clipboard every second (every 2 seconds when Performance Mode is on)
  - Queue items show a "📋 Clipboard:" (Queue mode) or "📋 Auto-Queued:" (Speak + Auto-Queue) prefix
  - Auto-Queue option: when already speaking, copied text is added to the queue instead of being ignored
  - Perfect for collecting multiple web articles!

### 6. ✨ Word Highlighting
- **Feature**: Automatically highlights words as they're being spoken
- **Visual Feedback**: 
  - Highlight uses the theme accent color
  - Auto-scrolls to keep the highlighted word visible
  - Clears when speech stops
- **How It Works**: Uses TTS engine callbacks to track word position (when supported by the engine; disabled on Python 3.13+ for stability)

## 💾 Settings Persistence

The application now saves your preferences in `tts_settings.json`:
- Selected theme preset and Performance Mode
- Clipboard monitoring enabled/disabled, action mode, and Auto-Queue
- STT settings (model, input device, unload behavior, auto-unload minutes)
- Custom hotkey mappings

These settings are automatically loaded when you restart the application.

## 🎮 Default Hotkeys

| Action | Default Hotkey |
|--------|----------------|
| Speak All | `Ctrl+Enter` |
| Speak Selected | `Ctrl+Shift+Enter` |
| Stop | `Escape` |
| Open File | `Ctrl+O` |
| Save File | `Ctrl+S` |
| Save As | `Ctrl+Shift+S` |
| Paste | `Ctrl+V` |
| Clear | `Ctrl+L` |
| Find/Replace | `Ctrl+F` |
| Export Audio | `Ctrl+E` |

## 🚀 Usage Tips

1. **Speech Queue for Audiobooks**: Add multiple chapter files to the queue and let them play sequentially - perfect for listening to entire books!
2. **Export Audio for Audiobooks**: Type or paste long text and export to WAV for podcast/audiobook creation
3. **Clipboard Auto-speak**: Enable for hands-free reading of copied text
4. **Custom Hotkeys**: Set up shortcuts that match your workflow (e.g., gaming-style WASD controls)
5. **Themes**: Pick a preset that suits your environment — e.g., Dark or Twilight for late-night reading, Light or Paper for bright conditions
6. **Find & Replace**: Great for fixing typos before speaking or exporting
7. **Word Highlighting**: Follow along visually while listening to improve comprehension
8. **Queue Workflow**: Add text → Add files → Review queue → Play queue → Relax and listen!

## 🎨 UI Enhancements (v4.0.0)

- **Gradient header bar**: The window now features a refined gradient header showing the title (`TTSPython 4.0.0`) and Mode toggle
- **Refined styling**: Updated controls, panels, and color theming throughout the app
- **Color emoji icons**: Toolbar, file, queue, and STT buttons show color emoji icons (rendered to bitmaps via Pillow so they are not gray outline glyphs on Windows)
- **Larger window**: Increased minimum size to 700x400 for better usability
- **More buttons**: All features accessible from the main window
- **Better organization**: File operations grouped together; theming is set in Settings → Theme
- **Status updates**: All actions provide feedback in the status bar

## 🔧 Technical Details

- **Settings File**: `tts_settings.json` (auto-created in app directory)
- **Audio Formats**: WAV (best quality), MP3 (if supported by engine)
- **Theme Colors**: 11 presets carefully chosen for readability, with highlight colors that adapt per theme
- **Thread-Safe**: All UI updates from background threads are properly synchronized
- **Engine Management**: Still uses fresh engines per operation (best practice)

