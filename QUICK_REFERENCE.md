# TTSPython Quick Reference (v5)

## At a glance

- **Speak**: read text aloud with play, pause, stop, sentence highlighting, voice, speed, volume and output device. Speed, volume and voice change while it speaks.
- **Voices**: system voices plus natural Piper voices from **Settings > Speech > Get more voices**.
- **Listen**: offline dictation into the editor, with a choice of Whisper model and language.
- **Mini mode**: a floating bar that dictates into any app (with live captions) and reads highlighted text or the clipboard, without taking focus.
- **Global hotkeys**: dictate, speak the clipboard or stop from anywhere.
- **Queue**: line up text, files and clipboard items; drag to reorder; loop; kept between sessions.
- **Clipboard monitor**: speak or queue copied text; Auto-Queue while speaking.
- **Export**: WAV or MP3, of all the text or just the selection.
- **Find and replace**: inline, with match case and regular expressions.
- **12 themes**, Performance Mode, tray icon.

## In-window shortcuts

| Action | Default |
|--------|---------|
| Speak all | `Ctrl+Enter` |
| Speak selected | `Ctrl+Shift+Enter` |
| Speak from the cursor | `Ctrl+Alt+Enter` |
| Pause or resume | `Ctrl+Space` |
| Stop | `Esc` |
| New document | `Ctrl+N` |
| Open file | `Ctrl+O` |
| Save | `Ctrl+S` |
| Save as | `Ctrl+Shift+S` |
| Paste | `Ctrl+V` |
| Clear text | `Ctrl+L` |
| Find and replace | `Ctrl+F` |
| Export audio | `Ctrl+E` |
| Switch Speak / Listen | `Ctrl+M` |
| Show or hide the queue | `Ctrl+Q` |
| Settings | `Ctrl+,` |

## Global hotkeys (work from any app)

| Action | Default |
|--------|---------|
| Start or stop dictation | `Ctrl+Alt+D` |
| Speak highlighted text or clipboard (again to stop) | `Ctrl+Alt+S` |
| Stop speaking | `Ctrl+Alt+X` |
| Show or hide mini mode | `Ctrl+Alt+Shift+M` |
| Cancel the dictation (only while dictating into another app) | `Esc` |

All of these except `Esc` can be changed in **Settings > Shortcuts**.

## Common workflows

### Listen to an article
1. Copy the article, press **Paste** (or `Ctrl+V`).
2. Press **Play** (`Ctrl+Enter`). Follow the highlighted sentence.
3. `Ctrl+Space` pauses, `Esc` stops.

### Dictate an email
1. Click into the email body.
2. Press `Ctrl+Alt+D` and speak; the caption bubble shows each word as you say it (dimmer words are a first guess that Whisper corrects a moment later).
3. Press `Ctrl+Alt+D` again. The text appears at your cursor, almost at once if you paused first (`Esc` instead throws it away).

### Read anything you copy, without switching windows
1. Turn on mini mode (`Ctrl+Alt+Shift+M`).
2. Copy text anywhere, then press the play button on the bar (or `Ctrl+Alt+S`).

### Build an audiobook playlist
1. In the queue panel press **Add files** and pick the chapters.
2. Drag them into order, then press **Play queue**.

### Collect reading while browsing
1. Turn on **Clipboard** in the status bar and choose **Queue**.
2. Copy paragraphs as you browse; each one joins the queue.
3. Press **Play queue** when you are ready.

### Make an audio file
1. Put the text in the editor and choose voice, speed and volume (select a part to export only that).
2. Press **Export audio** (`Ctrl+E`) and choose WAV or MP3. **Open folder** in the status bar shows the file.

### Get a more natural voice
1. **Settings > Speech > Get more voices**, pick a language and a voice (**Hear samples online** to compare).
2. **Download** (about 60 MB, once), then **Use this voice**.

## Command line

```
python TTSPython.py --mini | --show | --toggle-dictation | --speak-clipboard | --stop | --pause | --quit
python TTSPython.py --settings PATH
```

When TTSPython is already running, these are passed to the running copy.

## Files

- Settings: `%APPDATA%\TTSPython\settings.json` (Windows), `~/.config/ttspython/settings.json` (Linux). Saved automatically, with the queue (`queue.json`) and unsaved text (`recovery.json`) next to it.
- Downloaded Piper voices and the Piper program: `%LOCALAPPDATA%\TTSPython` (Windows), `~/.local/share/ttspython` (Linux).
