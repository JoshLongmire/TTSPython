# Read Aloud - Text-to-Speech Application

A modern, feature-rich text-to-speech (TTS) application built with Python and tkinter. Read Aloud allows you to convert any text into spoken words with customizable voice, speed, and volume settings.

![Python](https://img.shields.io/badge/python-3.7+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)

## Features

- **Text-to-Speech**: Convert text to speech with high-quality voices
- **Text Editor**: Built-in editor with undo/redo support
- **Voice Customization**: Adjust speech rate, volume, and select from available system voices
- **File Management**: Open, edit, and save text files (UTF-8 encoded)
- **Selective Reading**: Speak all text or just selected portions
- **Keyboard Shortcuts**: Full keyboard navigation for power users
- **Modern UI**: Clean, intuitive interface
- **Thread-Safe**: Non-blocking speech operations with proper error handling

## Installation

### Prerequisites

- Python 3.7 or higher
- pip (Python package installer)

### Step 1: Clone the Repository

```bash
git clone https://github.com/yourusername/TTSPython.git
cd TTSPython
```

### Step 2: Install Dependencies

```bash
pip install pyttsx3
```

### Step 3: Run the Application

```bash
python TTSPython/TTSPython.py
```

## Usage

### Basic Operations

#### Speaking Text

1. **Type or Paste Text**: Enter your text directly in the text area or paste from clipboard
2. **Speak All**: Click "▶ Speak All" button or press `Ctrl+Enter` to speak all text
3. **Speak Selected**: Select text, then click "▶ Speak Selected" or press `Ctrl+Shift+Enter`
4. **Stop**: Click "■ Stop" or press `Esc` to interrupt speech

#### File Operations

- **Open File**: Click "📁 Open" or press `Ctrl+O` to open a text file
- **Save**: Click "💾 Save" or press `Ctrl+S` to save to current file
- **Save As**: Click "💾 Save As" or press `Ctrl+Shift+S` to save with a new name

#### Text Editing

- **Paste**: Click "📋 Paste" or press `Ctrl+V` to paste from clipboard
- **Clear**: Click "🗑️ Clear" or press `Ctrl+L` to clear all text
- **Undo/Redo**: Use standard text editor shortcuts

### Customization

#### Voice Settings

- **Rate**: Adjust the slider to change speech speed (100-250 words per minute)
- **Volume**: Adjust the slider to change volume (0.1-1.0)
- **Voice**: Select from available system voices in the dropdown menu

### Keyboard Shortcuts

| Action | Shortcut |
|--------|----------|
| Speak All | `Ctrl+Enter` |
| Speak Selected | `Ctrl+Shift+Enter` |
| Stop Speaking | `Esc` |
| Open File | `Ctrl+O` |
| Save File | `Ctrl+S` |
| Save As | `Ctrl+Shift+S` |
| Paste | `Ctrl+V` |
| Clear | `Ctrl+L` |

## Configuration

The application automatically detects system voices and settings on startup. Default settings:

- **Rate**: System default (typically ~150-200 WPM)
- **Volume**: System default (typically 1.0)
- **Voice**: Attempts to select a female/neutral voice if available, otherwise uses system default

## Technical Details

### Architecture

- **GUI Framework**: tkinter with ttk widgets for modern appearance
- **TTS Engine**: pyttsx3 (cross-platform TTS library)
- **Threading**: Daemon threads for non-blocking speech operations
- **Encoding**: UTF-8 for all file operations

### Platform-Specific Notes

#### Windows
- Uses SAPI5 voices (Microsoft Speech API)
- Includes built-in voices like Zira, David, etc.

#### macOS
- Uses NSSpeechSynthesizer
- Includes built-in voices like Alex, Samantha, etc.

#### Linux
- Uses espeak
- May require additional installation: `sudo apt-get install espeak`

## Troubleshooting

### No Voices Available

**Problem**: Voice dropdown is empty or app crashes on startup.

**Solution**:
- **Windows**: Ensure Speech API is installed (usually comes with Windows)
- **Linux**: Install espeak: `sudo apt-get install espeak`
- **macOS**: Voices should be pre-installed; check System Preferences > Accessibility > Speech

### Speech Doesn't Stop

**Problem**: Stop button doesn't immediately stop speech.

**Solution**: This is normal behavior - the TTS engine completes the current sentence before stopping. Allow 1-2 seconds for the stop command to take effect.

### File Encoding Errors

**Problem**: Special characters display incorrectly or cause errors.

**Solution**: The app uses UTF-8 encoding. Ensure your text files are saved in UTF-8 format.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss what you would like to change.

### Development Setup

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/AmazingFeature`
3. Commit your changes: `git commit -m 'Add some AmazingFeature'`
4. Push to the branch: `git push origin feature/AmazingFeature`
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- [pyttsx3](https://github.com/nateshmbhat/pyttsx3) - Cross-platform TTS library
- Python tkinter - GUI framework
- All contributors and users of this project

## Contact

For questions, suggestions, or issues, please open an issue on GitHub.

---

**Enjoy using Read Aloud!** If you find this project helpful, please consider giving it a star on GitHub.

