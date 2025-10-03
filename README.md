# Read Aloud - Enhanced Text-to-Speech Application

A modern, feature-rich text-to-speech (TTS) application built with Python and tkinter. Read Aloud allows you to convert any text into spoken words with powerful features like speech queuing, audio export, clipboard monitoring, and full customization.

![Python](https://img.shields.io/badge/python-3.8+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)
![Version](https://img.shields.io/badge/version-2.2-brightgreen.svg)

## ✨ Features

### Core TTS Features
- **Text-to-Speech**: Convert text to speech with high-quality voices
- **Text Editor**: Built-in editor with undo/redo support and syntax highlighting
- **Voice Customization**: Adjust speech rate, volume, and select from available system voices
- **Voice Management**: Refresh voice list on-the-fly, add new voices without restart
- **Word Highlighting**: Real-time word highlighting during speech with auto-scroll
- **Selective Reading**: Speak all text or just selected portions

### Advanced Features
- **🎬 Speech Queue System**: Queue multiple text sections or files for sequential playback
- **🔊 Export Audio**: Save text as WAV/MP3 audio files with current voice settings
- **📎 Clipboard Monitoring**: Auto-speak or auto-queue copied text from anywhere
- **🌓 Dark/Light Theme**: Beautiful themes with persistent settings
- **🔍 Find & Replace**: Full text search with regex support and case sensitivity
- **⚙️ Hotkey Customization**: Customize all 10 keyboard shortcuts to your preference
- **💾 Settings Persistence**: All preferences save automatically

### File Operations
- **File Management**: Open, edit, and save text files (UTF-8 encoded)
- **Multi-File Queue**: Add multiple files to speech queue for audiobook-style listening
- **Recent Files**: Quick access to recently opened files

### User Experience
- **Keyboard Shortcuts**: Full keyboard navigation for power users
- **Modern UI**: Clean, intuitive interface with emoji icons
- **Thread-Safe**: Non-blocking speech operations with Python 3.13 compatibility
- **Status Feedback**: Real-time status updates for all operations

## Installation

### Prerequisites

- Python 3.8 or higher (tested on Python 3.13)
- pip (Python package installer)
- **Windows**: pywin32 (for Python 3.13 threading compatibility)

### Step 1: Clone the Repository

```bash
git clone https://github.com/yourusername/TTSPython.git
cd TTSPython
```

### Step 2: Install Dependencies

```bash
pip install pyttsx3
```

**For Python 3.13 users (Windows):**
```bash
pip install pywin32
python -m pywin32_postinstall -install
```

This fixes threading issues with Python 3.13. See `PYTHON_313_FIX.md` for details.

### Step 3: Run the Application

```bash
python TTSPython/TTSPython.py
```

Or on Windows PowerShell:
```powershell
cd TTSPython
python TTSPython.py
```

### Quick Start

1. The app opens with default settings
2. Type or paste text in the editor
3. Click "▶ Speak All" or press `Ctrl+Enter`
4. Adjust voice, rate, and volume as needed
5. Explore advanced features like Queue and Export!

## Usage

### Basic Operations

#### Speaking Text

1. **Type or Paste Text**: Enter your text directly in the text area or paste from clipboard
2. **Speak All**: Click "▶ Speak All" button or press `Ctrl+Enter` to speak all text
3. **Speak Selected**: Select text, then click "▶ Speak Selected" or press `Ctrl+Shift+Enter`
4. **Stop**: Click "■ Stop" or press `Esc` to interrupt speech
5. **Watch Highlighting**: Words highlight in yellow as they're spoken (with auto-scroll)

#### File Operations

- **Open File**: Click "📁 Open" or press `Ctrl+O` to open a text file
- **Save**: Click "💾 Save" or press `Ctrl+S` to save to current file
- **Save As**: Click "💾 Save As" or press `Ctrl+Shift+S` to save with a new name
- **Export Audio**: Click "🔊 Export Audio" or press `Ctrl+E` to save as WAV/MP3

#### Text Editing

- **Paste**: Click "📋 Paste" or press `Ctrl+V` to paste from clipboard
- **Clear**: Click "🗑️ Clear" or press `Ctrl+L` to clear all text
- **Find/Replace**: Click "🔍 Find/Replace" or press `Ctrl+F` for search dialog
- **Undo/Redo**: Use standard text editor shortcuts

### Advanced Features

#### 📋 Speech Queue System

Queue multiple text sections or files for sequential playback:

1. **Add Current Text**: Click "➕ Add Current Text" to queue editor content
2. **Add Files**: Click "➕ Add File(s)" to queue multiple text files
3. **Play Queue**: Click "▶ Play Queue" to start sequential playback
4. **Remove Item**: Select item and click "❌ Remove Selected"
5. **Clear Queue**: Click "🗑️ Clear Queue" to remove all items

**Queue shows:**
- 📄 for files
- Text: for manual entries
- 📋 for clipboard items

#### 📎 Clipboard Monitoring

Automatically process copied text:

1. Enable "📎 Monitor Clipboard" checkbox
2. Choose mode:
   - **Speak**: Immediately speaks copied text
   - **Queue**: Adds copied text to speech queue
3. Copy text from anywhere - it's processed automatically!

**Use Cases:**
- Research: Copy excerpts from web, queue them all, listen later
- News: Queue articles while browsing, batch listen
- Study: Collect notes from different sources

#### 🔊 Export Audio to File

Save your text as audio files:

1. Type or paste text
2. Adjust voice, rate, volume
3. Click "🔊 Export Audio" or press `Ctrl+E`
4. Choose format (WAV or MP3)
5. Save to your desired location

Perfect for creating audiobooks, podcasts, or voice memos!

#### 🌓 Dark/Light Theme

Toggle between themes:
- Click "🌓 Theme" button to switch
- Theme persists between sessions
- Highlights adapt to theme automatically

#### ⚙️ Settings & Hotkey Customization

Customize your experience:

1. Click "⚙️ Settings" button
2. Click on any hotkey field
3. Press your desired key combination
4. Click "Save" (or "Reset to Defaults")
5. All settings save automatically

### Voice Management

#### Voice Settings

- **Rate**: Adjust the slider to change speech speed (100-250 words per minute)
- **Volume**: Adjust the slider to change volume (0.1-1.0)
- **Voice**: Select from available system voices in the dropdown menu
- **Refresh (🔄)**: Click to detect newly installed voices without restart

#### Adding More Voices

1. Press `Windows + I` to open Settings
2. Go to **Time & Language → Speech**
3. Click "Add voices"
4. Download voices (100+ languages available)
5. Click **🔄** button in app to refresh

See `ADD_VOICES_GUIDE.md` for detailed instructions on adding voices.

### Keyboard Shortcuts (Customizable!)

| Action | Default Shortcut |
|--------|----------|
| Speak All | `Ctrl+Enter` |
| Speak Selected | `Ctrl+Shift+Enter` |
| Stop Speaking | `Esc` |
| Open File | `Ctrl+O` |
| Save File | `Ctrl+S` |
| Save As | `Ctrl+Shift+S` |
| Paste | `Ctrl+V` |
| Clear | `Ctrl+L` |
| Find/Replace | `Ctrl+F` |
| Export Audio | `Ctrl+E` |

💡 **All shortcuts are customizable** through the Settings dialog!

## Configuration

### Settings File

All settings are automatically saved to `tts_settings.json` in the application directory:
- **Theme**: Dark or Light mode
- **Hotkeys**: Custom keyboard shortcuts
- **Clipboard Monitor**: Enabled/disabled state

Settings load automatically on startup and save on exit.

### Default Settings

On first run, the application uses:
- **Rate**: System default (typically ~150-200 WPM)
- **Volume**: System default (typically 1.0)
- **Voice**: Female/neutral voice if available (Zira on Windows)
- **Theme**: Light mode
- **Hotkeys**: Standard shortcuts (see table above)

## 📚 Documentation Files

The application includes comprehensive documentation:

- **`README.md`** - This file, main documentation
- **`API.md`** - Complete API reference and technical details
- **`CHANGELOG.md`** - Version history and release notes
- **`PYTHON_313_FIX.md`** - Python 3.13 threading fix explanation
- **`FIX_SUMMARY.md`** - Summary of bug fixes
- **`INSTALL_FIX.md`** - Installation troubleshooting

Run `check_voices.py` to see all available voices on your system.

## Technical Details

### Architecture

- **GUI Framework**: tkinter with ttk widgets for modern appearance
- **TTS Engine**: pyttsx3 (cross-platform TTS library)
- **Threading**: Daemon threads with COM initialization for Python 3.13
- **Encoding**: UTF-8 for all file operations
- **Settings**: JSON-based persistent storage
- **Word Tracking**: Real-time word position tracking via TTS callbacks

### Key Components

- **ReaderApp**: Main application class (~1000+ lines)
- **SearchDialog**: Find/Replace dialog
- **SettingsDialog**: Hotkey customization dialog
- **Speech Queue**: Multi-item sequential playback system
- **Clipboard Monitor**: Background clipboard tracking (1-second interval)
- **Theme Engine**: Dynamic color scheme switching

### Threading Model

The app uses a sophisticated threading model to prevent UI blocking:
- Fresh pyttsx3 engine created for each speech operation
- COM initialization (Windows) for Python 3.13 compatibility
- Thread-safe UI updates via `root.after()`
- Proper cleanup in `finally` blocks

### Platform-Specific Notes

#### Windows
- Uses SAPI5 voices (Microsoft Speech API)
- Includes built-in voices like Zira, David, etc.
- Requires pywin32 for Python 3.13 (COM threading)
- 100+ additional voices available through Windows Settings

#### macOS
- Uses NSSpeechSynthesizer
- Includes built-in voices like Alex, Samantha, etc.
- Word highlighting may not work (engine limitation)

#### Linux
- Uses espeak
- May require additional installation: `sudo apt-get install espeak`
- Word highlighting may not work (engine limitation)

## Troubleshooting

### Python 3.13 GIL Error (Windows)

**Problem**: `Fatal Python error: PyEval_RestoreThread: the function must be called with the GIL held...`

**Solution**:
```bash
pip install pywin32
python -m pywin32_postinstall -install
```

See `PYTHON_313_FIX.md` and `INSTALL_FIX.md` for details.

### Settings Not Saving

**Problem**: Settings don't persist between sessions.

**Solution**:
- Check write permissions in the application directory
- Settings save to `tts_settings.json` in app folder
- Try running as Administrator if permission denied

### No Voices Available

**Problem**: Voice dropdown is empty or app crashes on startup.

**Solution**:
- **Windows**: Ensure Speech API is installed (usually comes with Windows)
- Click **🔄** button to refresh voice list
- Install additional voices through Windows Settings
- **Linux**: Install espeak: `sudo apt-get install espeak`
- **macOS**: Voices should be pre-installed; check System Preferences > Accessibility > Speech

### Speech Doesn't Stop

**Problem**: Stop button doesn't immediately stop speech.

**Solution**: This is normal behavior - the TTS engine completes the current sentence before stopping. Allow 1-2 seconds for the stop command to take effect.

### Queue Not Playing

**Problem**: Queue playback doesn't start or stops unexpectedly.

**Solution**:
- Ensure queue has items (check queue listbox)
- Stop any current speech before starting queue
- Press `Esc` if queue seems stuck, then try again

### Clipboard Monitoring Not Working

**Problem**: Copied text isn't being spoken or queued.

**Solution**:
- Verify "📎 Monitor Clipboard" is checked
- Select correct mode (Speak or Queue)
- Copy text longer than 5 characters
- Check status bar for feedback

### Word Highlighting Not Working

**Problem**: Words don't highlight during speech.

**Solution**:
- Feature only works on Windows with SAPI5
- Requires pywin32 to be properly installed
- Some voices may not support word callbacks
- macOS/Linux: Limited/no support due to engine limitations

### File Encoding Errors

**Problem**: Special characters display incorrectly or cause errors.

**Solution**: The app uses UTF-8 encoding. Ensure your text files are saved in UTF-8 format.

### Export Audio Fails

**Problem**: Can't export audio file.

**Solution**:
- Check write permissions in target directory
- Ensure disk space available
- Try WAV format if MP3 fails
- Close any programs that might lock the file

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss what you would like to change.

### Development Setup

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/AmazingFeature`
3. Commit your changes: `git commit -m 'Add some AmazingFeature'`
4. Push to the branch: `git push origin feature/AmazingFeature`
5. Open a Pull Request

### Areas for Contribution

- Additional file format support (PDF, DOCX, EPUB)
- Pronunciation dictionary for custom words
- Pause/Resume functionality
- Sentence-by-sentence navigation
- Multi-language UI
- Cloud TTS integration (Azure, Google, AWS)
- Batch audio export for queues

## Version History

- **v2.2** (Current) - Voice management, refresh voices button
- **v2.1** - Clipboard queue mode, settings fixes
- **v2.0** - Major feature update (queue, export, themes, search, etc.)
- **v1.0** - Initial release (basic TTS functionality)

See `CHANGELOG.md` for detailed version history.

## Feature Comparison

| Feature | v1.0 | v2.2 |
|---------|------|------|
| Basic TTS | ✅ | ✅ |
| File Operations | ✅ | ✅ |
| Voice Controls | ✅ | ✅ |
| Speech Queue | ❌ | ✅ |
| Export Audio | ❌ | ✅ |
| Dark Theme | ❌ | ✅ |
| Find/Replace | ❌ | ✅ |
| Custom Hotkeys | ❌ | ✅ |
| Clipboard Monitor | ❌ | ✅ |
| Word Highlighting | ❌ | ✅ |
| Settings Persistence | ❌ | ✅ |
| Voice Refresh | ❌ | ✅ |
| Python 3.13 Support | ⚠️ | ✅ |

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- [pyttsx3](https://github.com/nateshmbhat/pyttsx3) - Cross-platform TTS library
- [pywin32](https://github.com/mhammond/pywin32) - Python for Windows Extensions
- Python tkinter - GUI framework
- All contributors and users of this project

## Contact & Support

- **Issues**: Open an issue on GitHub for bug reports or feature requests
- **Discussions**: Use GitHub Discussions for questions and ideas
- **Documentation**: Check `API.md` for technical details

## Useful Commands

```bash
# Run the application
python TTSPython/TTSPython.py

# Check installed voices
python check_voices.py

# Install Python 3.13 fix
pip install pywin32
python -m pywin32_postinstall -install
```

---

## 🌟 Quick Feature Guide

### For Reading
- **Speak All/Selected** - Basic TTS
- **Word Highlighting** - Follow along visually
- **Dark Theme** - Comfortable for eyes

### For Productivity
- **Speech Queue** - Batch process multiple files
- **Clipboard Queue** - Collect content while browsing
- **Export Audio** - Create audiobooks/podcasts

### For Customization
- **10 Hotkeys** - All customizable
- **Voice Refresh** - Add voices without restart
- **Persistent Settings** - Everything saves

---

**Enjoy using Read Aloud Enhanced!** 🎉

If you find this project helpful, please consider giving it a star on GitHub ⭐

