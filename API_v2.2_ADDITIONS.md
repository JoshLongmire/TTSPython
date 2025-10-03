# API v2.2 Additions - New Features Reference

Complete reference for features added in v2.0-2.2

## New Instance Variables

### ReaderApp Class Extensions

| Variable | Type | Description | Version |
|----------|------|-------------|---------|
| `settings_file` | str | Path to tts_settings.json | v2.0 |
| `dark_mode` | bool | Current theme (True=dark, False=light) | v2.0 |
| `clipboard_monitor_enabled` | bool | Clipboard monitoring state | v2.0 |
| `last_clipboard` | str | Last clipboard content (to detect changes) | v2.0 |
| `highlight_tag` | str | Tag name for word highlighting | v2.0 |
| `current_word_indices` | list | Positions of highlighted words | v2.0 |
| `speech_queue` | list | Queue of items to speak | v2.0 |
| `queue_playing` | bool | Whether queue is currently playing | v2.0 |
| `current_queue_index` | int | Current position in queue | v2.0 |
| `hotkeys` | dict | Custom hotkey mappings | v2.0 |
| `clipboard_action` | tk.StringVar | Clipboard mode ("speak" or "queue") | v2.1 |
| `clipboard_var` | tk.BooleanVar | Clipboard monitor checkbox state | v2.0 |
| `voice_map` | dict | Mapping of voice names to IDs | v1.0 |
| `voice_combo` | ttk.Combobox | Voice selection dropdown | v1.0 |

## New Methods Reference

### Settings Management

#### `load_settings()`
```python
def load_settings(self) -> None
```
**Purpose**: Load user settings from JSON file

**Behavior**:
- Loads settings from `tts_settings.json`
- Creates file if it doesn't exist
- Sets default values on error
- Called during `__init__`

**Settings Loaded**:
- `dark_mode`: Theme preference
- `clipboard_monitor`: Clipboard monitoring state
- `hotkeys`: Custom keyboard shortcuts

**Example**:
```python
self.load_settings()  # Loads all user preferences
```

---

#### `save_settings()`
```python
def save_settings(self) -> None
```
**Purpose**: Save current settings to JSON file

**Behavior**:
- Writes to `tts_settings.json` in app directory
- Includes theme, hotkeys, clipboard monitor state
- Handles write errors gracefully
- Called on exit and when settings change

**Example**:
```python
self.dark_mode = True
self.save_settings()  # Persists theme change
```

---

#### `get_default_hotkeys()`
```python
def get_default_hotkeys(self) -> dict
```
**Purpose**: Return default hotkey mappings

**Returns**: Dictionary of action->hotkey mappings

**Default Hotkeys**:
```python
{
    'speak_all': '<Control-Return>',
    'speak_selected': '<Control-Shift-Return>',
    'stop': '<Escape>',
    'open': '<Control-o>',
    'save': '<Control-s>',
    'save_as': '<Control-Shift-S>',
    'paste': '<Control-v>',
    'clear': '<Control-l>',
    'find': '<Control-f>',
    'export': '<Control-e>'
}
```

---

### Theme Management

#### `apply_theme()`
```python
def apply_theme(self) -> None
```
**Purpose**: Apply current theme (dark/light) to all UI elements

**Behavior**:
- Sets colors for root, text widget, queue listbox
- Adjusts highlight colors
- Called during init and when theme changes

**Dark Theme Colors**:
```python
bg_color = "#2b2b2b"
text_bg = "#1e1e1e"
text_fg = "#d4d4d4"
highlight_bg = "#4a4a00"
highlight_fg = "#ffff00"
```

**Light Theme Colors**:
```python
bg_color = "#f0f0f0"
text_bg = "#ffffff"
text_fg = "#000000"
highlight_bg = "yellow"
highlight_fg = "black"
```

---

#### `toggle_theme()`
```python
def toggle_theme(self) -> None
```
**Purpose**: Toggle between dark and light themes

**Behavior**:
1. Flips `self.dark_mode` boolean
2. Calls `apply_theme()`
3. Saves settings
4. Updates status bar

---

### Speech Queue System

#### `add_current_to_queue()`
```python
def add_current_to_queue(self) -> None
```
**Purpose**: Add current editor text to speech queue

**Behavior**:
- Gets text from editor
- Creates preview (first 50 chars)
- Adds to `speech_queue` list
- Updates queue display
- Shows status message

**Queue Item Format**:
```python
{
    'text': "Full text content...",
    'name': "Text: Preview text..."
}
```

---

#### `add_files_to_queue()`
```python
def add_files_to_queue(self) -> None
```
**Purpose**: Add multiple text files to queue

**Behavior**:
- Opens file dialog (multi-select)
- Reads each file (UTF-8)
- Adds to queue with filename
- Handles errors per file

**Queue Item Format**:
```python
{
    'text': "File content...",
    'name': "📄 filename.txt"
}
```

---

#### `play_queue()`
```python
def play_queue(self) -> None
```
**Purpose**: Start sequential playback of queue items

**Behavior**:
- Validates queue not empty
- Checks not already playing
- Sets `queue_playing = True`
- Resets `current_queue_index = 0`
- Starts `_play_queue_worker` thread

**Preconditions**:
- Queue must have items
- Not currently speaking or playing queue

---

#### `_play_queue_worker()`
```python
def _play_queue_worker(self) -> None
```
**Purpose**: Worker thread for sequential queue playback

**Behavior**:
1. Initializes COM for thread
2. Loops through queue items
3. Creates fresh engine for each item
4. Speaks item text
5. Updates UI (progress, status)
6. Handles stop requests
7. Pauses 0.5s between items
8. Cleans up COM on exit

**Thread-Safety**:
- Uses `root.after()` for all UI updates
- Proper COM init/uninit
- Cleanup in `finally` block

---

#### `update_queue_display()`
```python
def update_queue_display(self) -> None
```
**Purpose**: Update queue listbox with current items

**Behavior**:
- Clears listbox
- Shows "▶" for current item
- Numbers all items
- Highlights current item (light blue)

**Display Format**:
```
   1. Text: Sample text...
▶  2. 📄 chapter1.txt
   3. 📋 Clipboard: Copied text...
```

---

#### `remove_from_queue()`
```python
def remove_from_queue(self) -> None
```
**Purpose**: Remove selected item from queue

---

#### `clear_queue()`
```python
def clear_queue(self) -> None
```
**Purpose**: Clear all items from queue (with confirmation)

---

### Clipboard Monitoring

#### `toggle_clipboard_monitor()`
```python
def toggle_clipboard_monitor(self) -> None
```
**Purpose**: Enable/disable clipboard monitoring

**Behavior**:
- Gets checkbox state
- Saves setting
- Starts monitoring if enabled
- Updates status bar

---

#### `monitor_clipboard()`
```python
def monitor_clipboard(self) -> None
```
**Purpose**: Background clipboard monitoring (recursive)

**Behavior**:
1. Checks if monitoring enabled (exits if not)
2. Gets current clipboard content
3. Compares to `last_clipboard`
4. If different and > 5 chars:
   - **Speak mode**: Starts speech (if not speaking)
   - **Queue mode**: Adds to queue
5. Schedules next check in 1 second (`root.after(1000)`)

**Polling Interval**: 1000ms (1 second)

**Modes**:
- `"speak"`: Immediate speech
- `"queue"`: Add to speech queue

---

### Voice Management

#### `refresh_voices()`
```python
def refresh_voices(self) -> None
```
**Purpose**: Refresh voice list without restarting app

**Behavior**:
1. Saves current selection
2. Reinitializes engine to get updated voices
3. Rebuilds `voice_map`
4. Updates combobox values
5. Restores selection (if still available)
6. Shows info dialog with count

**Use Case**: After installing new Windows voices

**Dialog Message**:
```
Found X voice(s) installed on your system.

To add more voices:
1. Open Windows Settings
2. Go to Time & Language → Speech
3. Click 'Add voices'
4. Click 🔄 to refresh again!
```

---

### Export Audio

#### `on_export_audio()`
```python
def on_export_audio(self) -> None
```
**Purpose**: Export current text as audio file

**Behavior**:
1. Validates text exists
2. Opens save dialog (WAV/MP3)
3. Creates engine with current settings
4. Uses `engine.save_to_file(text, path)`
5. Calls `engine.runAndWait()`
6. Shows success message

**Supported Formats**: WAV, MP3 (via file dialog)

**Uses Current Settings**:
- Voice
- Rate
- Volume

---

### Find & Replace

#### `on_search()`
```python
def on_search(self) -> None
```
**Purpose**: Open Find/Replace dialog

**Behavior**:
- Creates `SearchDialog` instance
- Passes root window and text widget
- Dialog manages its own lifecycle

---

### Hotkey Management

#### `bind_shortcuts()`
```python
def bind_shortcuts(self) -> None
```
**Purpose**: Bind all keyboard shortcuts

**Behavior**:
1. Unbinds all existing shortcuts
2. Binds each action from `self.hotkeys`
3. Handles errors gracefully

**Called**: During init and after hotkey changes

---

#### `on_settings()`
```python
def on_settings(self) -> None
```
**Purpose**: Open Settings dialog

**Behavior**:
- Creates `SettingsDialog` instance
- Passes root window and self
- Dialog manages hotkey capture and saving

---

### Word Highlighting

#### `highlight_word(location, length)`
```python
def highlight_word(self, location: int, length: int) -> None
```
**Purpose**: Highlight a word during speech

**Parameters**:
- `location` (int): Character offset in text
- `length` (int): Length of word

**Behavior**:
1. Removes previous highlight
2. Calculates text widget indices
3. Adds highlight tag
4. Auto-scrolls to word

**Called**: Via TTS engine callback (Windows SAPI5 only)

**Text Widget Indices**:
```python
start_idx = f"1.0 + {location} chars"
end_idx = f"1.0 + {location + length} chars"
```

---

### Enhanced Speech Worker

#### `_speak_worker(text)` (Enhanced)
```python
def _speak_worker(self, text: str) -> None
```
**New Features**:
- **COM Initialization**: `pythoncom.CoInitialize()` for Python 3.13
- **Word Callbacks**: `engine.connect('started-word', on_word)`
- **Highlighting**: Real-time word highlighting
- **Better Cleanup**: COM uninit in `finally`

**Python 3.13 Fix**:
```python
try:
    import pythoncom
    pythoncom.CoInitialize()
    com_initialized = True
except (ImportError, Exception):
    try:
        import win32com.client
        import pythoncom
        pythoncom.CoInitializeEx(0)
        com_initialized = True
    except:
        pass
```

---

## Dialog Classes

### SearchDialog

**Purpose**: Find and Replace functionality

**Methods**:
- `find_next()`: Find next occurrence
- `replace_one()`: Replace current selection
- `replace_all()`: Replace all occurrences

**Features**:
- Case-sensitive search
- Regular expression support
- Replace one or all

**Constructor**:
```python
SearchDialog(parent: tk.Tk, text_widget: tk.Text)
```

---

### SettingsDialog

**Purpose**: Hotkey customization

**Methods**:
- `capture_hotkey(event, action)`: Capture key press
- `save_hotkeys()`: Save new mappings
- `reset_defaults()`: Restore default hotkeys

**Features**:
- Visual hotkey capture
- Real-time feedback
- Reset to defaults
- Save/cancel options

**Constructor**:
```python
SettingsDialog(parent: tk.Tk, app: ReaderApp)
```

**Hotkey Capture Logic**:
```python
modifiers = []
if event.state & 0x4: modifiers.append("Control")
if event.state & 0x1: modifiers.append("Shift")
if event.state & 0x20000: modifiers.append("Alt")

hotkey = f"<{'-'.join(modifiers)}-{key}>"
```

---

## Python 3.13 Compatibility

### COM Threading Fix

**Problem**: GIL error in Python 3.13 when using `runAndWait()` in threads

**Solution**: COM initialization per thread

**Implementation**:
```python
def _speak_worker(self, text):
    com_initialized = False
    try:
        import pythoncom
        pythoncom.CoInitialize()
        com_initialized = True
    except:
        pass
    
    try:
        engine = pyttsx3.init()
        # ... TTS operations ...
    finally:
        if com_initialized:
            pythoncom.CoUninitialize()
```

**Required Package**: pywin32

**Installation**:
```bash
pip install pywin32
python -m pywin32_postinstall -install
```

---

## Settings File Format

### tts_settings.json

```json
{
  "dark_mode": false,
  "clipboard_monitor": false,
  "hotkeys": {
    "speak_all": "<Control-Return>",
    "speak_selected": "<Control-Shift-Return>",
    "stop": "<Escape>",
    "open": "<Control-o>",
    "save": "<Control-s>",
    "save_as": "<Control-Shift-S>",
    "paste": "<Control-v>",
    "clear": "<Control-l>",
    "find": "<Control-f>",
    "export": "<Control-e>"
  }
}
```

**Location**: Application directory (`os.path.dirname(__file__)`)

**Auto-created**: Yes, on first run

**Auto-loaded**: Yes, during `__init__`

**Auto-saved**: Yes, on exit and setting changes

---

## Best Practices v2.2

### 1. Settings Management
- Always call `save_settings()` after changing preferences
- Load settings in `__init__` before UI creation
- Handle JSON errors gracefully

### 2. Queue Management
- Clear queue indices when stopping
- Update display after every queue change
- Use thread-safe updates for progress

### 3. Theme Application
- Apply theme after all UI elements created
- Update all widgets (text, listbox, etc.)
- Save theme preference immediately

### 4. COM Threading (Windows)
- Always initialize COM in worker threads
- Always uninitialize in `finally` blocks
- Handle import errors (pywin32 not installed)

### 5. Clipboard Monitoring
- Use 1-second polling (balance responsiveness/CPU)
- Filter short content (< 5 chars)
- Stop monitoring when disabled

### 6. Hotkey Binding
- Unbind old shortcuts before rebinding
- Handle invalid hotkey strings
- Provide reset to defaults

---

## Version History

- **v2.2**: Voice refresh, enhanced voice management
- **v2.1**: Clipboard queue mode, settings path fix
- **v2.0**: Major features (queue, export, themes, search, hotkeys, clipboard, highlighting)
- **v1.0**: Basic TTS functionality

---

**See main API.md for base class documentation**

