# Enhanced TTS Features Guide

## 🎉 All New Features

### Latest Addition: 📋 Speech Queue System
- **Panel**: Dedicated queue panel in the main window
- **Functionality**: Queue multiple text sections or files to be read in sequence
- **Features**:
  - **Add Current Text**: Add the text currently in the editor to the queue
  - **Add File(s)**: Select multiple text files to add to queue at once
  - **Play Queue**: Start sequential playback of all queued items
  - **Remove Selected**: Remove a specific item from the queue
  - **Clear Queue**: Remove all items from the queue
  - Visual feedback showing currently playing item (▶ indicator)
  - Blue highlight on active queue item
  - Shows item count and progress
  - Can be stopped mid-playback with Stop button
  - 0.5 second pause between queue items
- **Use Cases**:
  - Create audiobook playlists from multiple chapter files
  - Queue up multiple articles or documents for continuous listening
  - Prepare a reading list for hands-free consumption
  - Test different text segments without manual intervention

## 🎉 Other New Features

### 1. 🔊 Export Audio to File
- **Button**: "🔊 Export Audio" in the file operations bar
- **Functionality**: Export your text as WAV or MP3 audio files
- **How to Use**: Click the button, choose save location, and the current text will be saved as an audio file
- **Hotkey**: `Ctrl+E`

### 2. 🌓 Dark/Light Theme Toggle
- **Button**: "🌓 Theme" in the file operations bar
- **Functionality**: Switch between dark and light color schemes
- **Features**:
  - Dark theme with comfortable colors for low-light environments
  - Light theme for bright conditions
  - Settings persist between sessions
  - Highlight colors adapt to theme

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
  - Reset to defaults option
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
  - Monitors clipboard every second
  - Queue items show "📋 Clipboard:" prefix
  - Perfect for collecting multiple web articles!

### 6. ✨ Word Highlighting
- **Feature**: Automatically highlights words as they're being spoken
- **Visual Feedback**: 
  - Yellow highlight on light theme
  - Yellow/dark highlight on dark theme
  - Auto-scrolls to keep highlighted word visible
  - Clears when speech stops
- **How It Works**: Uses TTS engine callbacks to track word position (if supported by engine)

## 💾 Settings Persistence

The application now saves your preferences in `tts_settings.json`:
- Dark/Light theme preference
- Clipboard monitoring enabled/disabled
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
5. **Dark Theme**: Perfect for late-night reading sessions
6. **Find & Replace**: Great for fixing typos before speaking or exporting
7. **Word Highlighting**: Follow along visually while listening to improve comprehension
8. **Queue Workflow**: Add text → Add files → Review queue → Play queue → Relax and listen!

## 🎨 UI Enhancements

- **Larger window**: Increased minimum size to 700x400 for better usability
- **Enhanced title**: Now shows "Read Aloud — Enhanced Text-to-Speech"
- **More buttons**: All new features accessible from the main window
- **Better organization**: File operations grouped together
- **Status updates**: All actions provide feedback in the status bar

## 🔧 Technical Details

- **Settings File**: `tts_settings.json` (auto-created in app directory)
- **Audio Formats**: WAV (best quality), MP3 (if supported by engine)
- **Theme Colors**: Carefully chosen for readability in both modes
- **Thread-Safe**: All UI updates from background threads are properly synchronized
- **Engine Management**: Still uses fresh engines per operation (best practice)

Enjoy your enhanced text-to-speech experience! 🎤

