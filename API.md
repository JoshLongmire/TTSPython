# API Documentation - Read Aloud TTS Application

This document provides technical documentation for developers who want to understand, modify, or extend the Read Aloud application.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Class Reference](#class-reference)
- [Method Reference](#method-reference)
- [Threading Model](#threading-model)
- [TTS Engine Lifecycle](#tts-engine-lifecycle)
- [Extension Guide](#extension-guide)
- [Best Practices](#best-practices)

## Architecture Overview

### Component Diagram

```
┌─────────────────────────────────────────────┐
│           ReaderApp (Main Class)            │
├─────────────────────────────────────────────┤
│  ┌─────────────┐  ┌──────────────────────┐ │
│  │ GUI Layer   │  │  TTS Layer           │ │
│  │ (tkinter)   │◄─┤  (pyttsx3)           │ │
│  │             │  │                      │ │
│  │ - Text      │  │ - Engine Management  │ │
│  │ - Buttons   │  │ - Voice Settings     │ │
│  │ - Controls  │  │ - Speech Worker      │ │
│  └─────────────┘  └──────────────────────┘ │
│  ┌─────────────┐  ┌──────────────────────┐ │
│  │ File I/O    │  │  Threading           │ │
│  │             │  │                      │ │
│  │ - Open      │  │ - Speech Thread      │ │
│  │ - Save      │  │ - Thread Safety      │ │
│  │ - Save As   │  │ - UI Updates         │ │
│  └─────────────┘  └──────────────────────┘ │
└─────────────────────────────────────────────┘
```

### Key Design Patterns

1. **Fresh Engine Pattern**: Creates new pyttsx3 engine for each speech operation
2. **Worker Thread Pattern**: Non-blocking TTS using daemon threads
3. **Thread-Safe UI Updates**: Uses `root.after()` for UI updates from worker threads
4. **State Management**: Tracks speaking state, current file, and engine references

## Class Reference

### `ReaderApp`

Main application class that manages the GUI, TTS engine, and all application logic.

#### Constructor

```python
def __init__(self, root: tk.Tk)
```

**Parameters**:
- `root` (tk.Tk): Root tkinter window

**Initializes**:
- GUI components (text area, buttons, controls)
- TTS engine settings (rate, volume, voices)
- File operation state
- Keyboard shortcuts
- Status bar

#### Instance Variables

| Variable | Type | Description |
|----------|------|-------------|
| `root` | tk.Tk | Root tkinter window |
| `speaking` | bool | Whether TTS is currently active |
| `speak_thread` | threading.Thread | Reference to current speech thread |
| `current_engine` | pyttsx3.Engine | Reference to active TTS engine |
| `stop_requested` | bool | Flag for interrupt requests |
| `current_file` | str | Path to currently open file |
| `rate` | tk.IntVar | Speech rate (100-250 WPM) |
| `vol` | tk.DoubleVar | Volume level (0.1-1.0) |
| `selected_voice` | str | ID of selected voice |
| `voices` | list | Available system voices |
| `status_var` | tk.StringVar | Status bar text |

## Method Reference

### TTS Operations

#### `on_speak()`

Speaks all text in the text area.

```python
def on_speak(self) -> None
```

**Behavior**:
1. Checks if already speaking (returns early if true)
2. Validates text exists
3. Sets speaking state and disables buttons
4. Launches worker thread with all text
5. Updates status bar

**Thread Safety**: Yes (main thread only)

---

#### `on_speak_selected()`

Speaks only the selected text.

```python
def on_speak_selected(self) -> None
```

**Behavior**:
1. Checks if already speaking
2. Attempts to get selected text
3. Validates selection exists
4. Launches worker thread with selected text
5. Shows info dialog if no selection

**Error Handling**: Catches `tk.TclError` for no selection

**Thread Safety**: Yes (main thread only)

---

#### `_speak_worker(text: str)`

Worker thread that performs actual TTS operation.

```python
def _speak_worker(self, text: str) -> None
```

**Parameters**:
- `text` (str): Text to be spoken

**Behavior**:
1. Creates fresh pyttsx3 engine
2. Stores engine reference for stop functionality
3. Applies current settings (rate, volume, voice)
4. Checks if stop was requested
5. Performs speech with `runAndWait()`
6. Cleans up in finally block

**Thread Safety**: Runs in daemon thread; uses `root.after()` for UI updates

**Critical Notes**:
- Engine must be fresh (never reused after `runAndWait()`)
- Must clear `current_engine` in finally block
- UI updates must use `root.after()`

---

#### `on_stop()`

Interrupts current speech operation.

```python
def on_stop(self) -> None
```

**Behavior**:
1. Checks if speech is active
2. Sets stop flag
3. Calls `engine.stop()`
4. Re-enables buttons
5. Updates status

**Thread Safety**: Yes (handles cross-thread stop safely)

---

### File Operations

#### `on_open()`

Opens a text file and loads content into editor.

```python
def on_open(self) -> None
```

**Behavior**:
1. Shows file dialog
2. Reads file with UTF-8 encoding
3. Clears current text
4. Inserts file content
5. Updates `current_file` path
6. Updates status bar

**Error Handling**: Shows error dialog on file read failure

---

#### `on_save()`

Saves current text to file.

```python
def on_save(self) -> None
```

**Behavior**:
- If `current_file` exists: Saves to that file
- If no current file: Calls `on_save_as()`

**Encoding**: UTF-8

---

#### `on_save_as()`

Saves current text to a new file.

```python
def on_save_as(self) -> None
```

**Behavior**:
1. Shows save dialog
2. Writes content with UTF-8 encoding
3. Updates `current_file` path
4. Updates status bar

---

### Text Operations

#### `on_paste()`

Pastes clipboard content at cursor position.

```python
def on_paste(self) -> None
```

**Error Handling**: Shows info dialog if clipboard is empty

---

#### `on_clear()`

Clears all text from editor.

```python
def on_clear(self) -> None
```

---

### Settings Callbacks

#### `_on_rate_change(value: str)`

Updates speech rate when slider moves.

```python
def _on_rate_change(self, value: str) -> None
```

**Parameters**:
- `value` (str): Slider value as string (tkinter convention)

**Behavior**: Converts to int and updates `self.rate`

---

#### `_on_volume_change(value: str)`

Updates volume when slider moves.

```python
def _on_volume_change(self, value: str) -> None
```

**Parameters**:
- `value` (str): Slider value as string

**Behavior**: Converts to float and updates `self.vol`

---

#### `on_voice_change(event)`

Updates selected voice when combobox changes.

```python
def on_voice_change(self, event) -> None
```

**Behavior**: Updates `self.selected_voice` with voice ID from mapping

---

## Threading Model

### Thread Architecture

```
Main Thread (UI)                Worker Thread (TTS)
     │                                 │
     ├─► on_speak()                   │
     │   └─► spawn thread ────────────┼─► _speak_worker()
     │                                 │   ├─► init engine
     │                                 │   ├─► apply settings
     │                                 │   ├─► engine.say()
     │                                 │   └─► engine.runAndWait()
     │                                 │
     │◄────── root.after(update) ──────┤
     │                                 │
     ├─► on_stop()                     │
     │   └─► engine.stop() ────────────┼─► [interrupt]
     │                                 │
```

### Thread Safety Rules

1. **UI Updates**: Always use `root.after(0, callback)` from worker threads
2. **Engine Reference**: Store in `self.current_engine` for stop access
3. **State Flags**: Use `self.speaking` and `self.stop_requested` for coordination
4. **Daemon Threads**: All TTS threads are daemons (prevent hanging on exit)

### Critical Section: Button State

```python
# Thread-safe button state management
self.speak_btn.state(["disabled"])  # Main thread
# ... speech happens in worker thread ...
self.speak_btn.state(["!disabled"])  # Main thread via root.after()
```

## TTS Engine Lifecycle

### Critical Pattern: Fresh Engine Per Operation

**Problem**: pyttsx3 engines become unusable after `runAndWait()` completes.

**Solution**: Create fresh engine for each speech operation.

```python
# CORRECT - Fresh engine each time
def _speak_worker(self, text):
    try:
        engine = pyttsx3.init()  # Fresh engine
        self.current_engine = engine
        engine.setProperty("rate", self.rate.get())
        engine.say(text)
        engine.runAndWait()
    finally:
        self.current_engine = None  # Clean up reference

# INCORRECT - Reusing engine
def __init__(self):
    self.engine = pyttsx3.init()  # DON'T DO THIS

def _speak_worker(self, text):
    self.engine.say(text)
    self.engine.runAndWait()  # Engine now unusable!
```

### Engine Initialization Sequence

```python
# 1. Temporary engine for startup discovery
temp_engine = pyttsx3.init()
self.default_rate = temp_engine.getProperty("rate")
self.default_volume = temp_engine.getProperty("volume")
self.voices = temp_engine.getProperty("voices")
temp_engine.stop()  # Clean up

# 2. Store settings as instance variables
self.rate = tk.IntVar(value=self.default_rate)
self.vol = tk.DoubleVar(value=self.default_volume)
self.selected_voice = voice_id

# 3. Apply to fresh engine during speech
engine = pyttsx3.init()  # New engine
engine.setProperty("rate", self.rate.get())
engine.setProperty("volume", self.vol.get())
engine.setProperty("voice", self.selected_voice)
```

## Extension Guide

### Adding New TTS Features

#### Example: Add Pitch Control

```python
# 1. Add UI control in __init__()
ttk.Label(controls, text="Pitch").grid(row=0, column=11, padx=(8,4))
self.pitch = tk.IntVar(value=50)  # 0-100
self.pitch_scale = ttk.Scale(controls, from_=0, to=100, orient="horizontal",
                             command=self._on_pitch_change)
self.pitch_scale.set(50)
self.pitch_scale.grid(row=0, column=12, sticky="ew")

# 2. Add callback
def _on_pitch_change(self, value):
    self.pitch.set(int(float(value)))

# 3. Apply in _speak_worker()
def _speak_worker(self, text):
    engine = pyttsx3.init()
    # ... existing settings ...
    # Note: Pitch support varies by platform
    try:
        engine.setProperty("pitch", self.pitch.get())
    except:
        pass  # Not all engines support pitch
```

### Adding Custom Voice Filters

```python
def on_voice_change(self, _):
    # Filter voices by criteria
    selected_name = self.voice_combo.get()
    vid = self.voice_map.get(selected_name)
    
    if vid:
        self.selected_voice = vid
        
        # Example: Log voice metadata
        voice = next(v for v in self.voices if v.id == vid)
        print(f"Voice: {voice.name}")
        print(f"Languages: {voice.languages}")
        print(f"Gender: {voice.gender}")
```

### Adding Export to Audio File

```python
def on_export_audio(self):
    """Export text to audio file"""
    file_path = filedialog.asksaveasfilename(
        defaultextension=".mp3",
        filetypes=[("MP3 files", "*.mp3"), ("WAV files", "*.wav")]
    )
    
    if file_path:
        text = self.txt.get("1.0", "end").strip()
        engine = pyttsx3.init()
        engine.setProperty("rate", self.rate.get())
        engine.setProperty("volume", self.vol.get())
        engine.setProperty("voice", self.selected_voice)
        
        # Save to file (platform dependent)
        engine.save_to_file(text, file_path)
        engine.runAndWait()
        
        self.status_var.set(f"Exported: {os.path.basename(file_path)}")
```

## Best Practices

### Error Handling

```python
# CORRECT - Comprehensive error handling
def on_open(self):
    file_path = filedialog.askopenfilename(...)
    if file_path:
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                content = file.read()
            # ... success ...
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open file: {str(e)}")
```

### State Management

```python
# CORRECT - Consistent state tracking
def on_speak(self):
    if self.speaking:
        return  # Prevent concurrent speech
    
    self.speaking = True
    self.stop_requested = False
    # ... launch thread ...

def _speak_worker(self, text):
    try:
        # ... speech operation ...
    finally:
        self.speaking = False  # Always reset state
```

### UI Thread Safety

```python
# CORRECT - Safe UI update from worker thread
def _speak_worker(self, text):
    try:
        # ... TTS operation ...
    except Exception as e:
        self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
    finally:
        self.root.after(0, lambda: self.status_var.set("Ready"))
```

## Testing

### Manual Test Checklist

- [ ] Speak all text works
- [ ] Speak selected text works
- [ ] Stop button interrupts speech
- [ ] Rate/volume/voice changes apply
- [ ] Open file loads content
- [ ] Save/Save As works
- [ ] Keyboard shortcuts work
- [ ] No crashes on rapid button clicks
- [ ] Status bar updates correctly
- [ ] Thread cleanup on exit

### Edge Cases

1. **Empty text**: Should show info dialog
2. **No selection**: Should show info dialog
3. **Rapid stop/start**: Should handle gracefully
4. **Large files**: Should load without freezing
5. **Unicode text**: Should handle UTF-8 correctly

## Performance Considerations

- **Engine Creation**: ~50-200ms per initialization (acceptable for this use case)
- **Speech Start**: ~100-500ms latency (platform dependent)
- **Memory**: ~10-50MB depending on platform TTS engine
- **Thread Cleanup**: Automatic with daemon threads

## Platform-Specific Notes

### Windows (SAPI5)
- Best voice quality
- Supports pitch control
- Fast initialization

### macOS (NSSpeechSynthesizer)
- Good voice quality
- Limited property support
- Medium initialization time

### Linux (espeak)
- Robotic voice quality
- Fast and lightweight
- Requires external package

---

**Last Updated**: October 2, 2025  
**Version**: 1.0  
**Maintainer**: Development Team

