# Release v1.0.0 - Initial Release

## Overview

First public release of **Read Aloud** - a modern, feature-rich text-to-speech application built with Python and tkinter.

## Features

### Text-to-Speech Engine
- High-quality text-to-speech conversion using pyttsx3
- Cross-platform support (Windows, macOS, Linux)
- Speak entire document or selected text only
- Stop/interrupt speech at any time

### Voice Customization
- Adjustable speech rate (100-250 words per minute)
- Volume control (0.1 to 1.0)
- Multiple voice selection from available system voices
- Real-time settings application

### Text Editor
- Built-in text editor with full undo/redo support
- Multi-line text input with word wrapping
- Scrollbar for long documents
- Clipboard integration

### File Management
- Open text files (.txt and all file types)
- Save current document
- Save As functionality for new files
- UTF-8 encoding support for international characters
- Tracks current file path for quick saves

### User Interface
- Clean, modern interface using ttk widgets
- Visual button labels for easy recognition
- Status bar with real-time feedback
- Non-blocking operations (UI remains responsive during speech)
- Smooth scrolling and text navigation

### Keyboard Shortcuts
- `Ctrl+Enter` - Speak all text
- `Ctrl+Shift+Enter` - Speak selected text
- `Esc` - Stop speaking
- `Ctrl+O` - Open file
- `Ctrl+S` - Save file
- `Ctrl+Shift+S` - Save as
- `Ctrl+V` - Paste
- `Ctrl+L` - Clear text

### Technical Highlights
- Thread-safe architecture with daemon threads
- Proper TTS engine lifecycle management
- Comprehensive error handling
- Platform-specific voice optimization
- Clean separation of UI and TTS logic

## Installation

### Requirements
- Python 3.7 or higher
- pyttsx3 library

### Quick Start
```bash
# Clone the repository
git clone https://github.com/yourusername/TTSPython.git
cd TTSPython

# Install dependencies
pip install pyttsx3

# Run the application
python TTSPython/TTSPython.py
```

### Platform-Specific Setup

**Windows:**
- No additional setup required
- Uses SAPI5 voices (Microsoft Speech API)

**macOS:**
- No additional setup required
- Uses NSSpeechSynthesizer

**Linux:**
- Install espeak: `sudo apt-get install espeak`
- Uses espeak engine

## Known Issues

None at this time. Please report any issues you encounter!

## What's Next

Future releases may include:
- Audio file export functionality
- Additional voice effects and filters
- Custom keyboard shortcut configuration
- Recent files menu
- Multi-language support
- Dark mode theme
- Speech queue for multiple selections

## Credits

- Built with Python and tkinter
- TTS powered by [pyttsx3](https://github.com/nateshmbhat/pyttsx3)

## License

MIT License - See LICENSE file for details

---

**Release Date:** October 2, 2025  
**Version:** 1.0.0  
**Status:** Stable

