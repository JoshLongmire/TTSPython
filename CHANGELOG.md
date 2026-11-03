# Changelog - TTSPython

## Version 5.0.0 - 2026-11-03
- Measured against 4.1.0 on the same Windows PC (median of 10 runs):
  startup to first window 1012 ms -> 976 ms; idle memory 65 MB -> 130 MB (RSS), mostly the Qt interface and
  keeping the voice loaded for instant speech; Python packages about 197 MB larger (Qt replaces Pillow).
  Tests: 283 pass (plus 5 on real audio and the desktop); 21 bug specs fail on 4.1.0 and pass on 5.0.0.
- New interface built with Qt (PySide6), replacing tkinter. Every v4 control and setting is kept.
  Word-by-word highlighting (which v4 only did on Python 3.12 and older) is replaced by sentence highlighting
  that works everywhere.
  - Top bar with a Speak / Listen switch and icon buttons; editor card with live word and character counts;
    collapsible speech queue panel; media-player style control bar; status bar with the clipboard controls.
  - Crisp line icons that follow the theme, smooth switches, a live waveform, and sharp text on high-DPI screens.
  - 12 themes: the 11 from v4 restyled, plus a new default, **Studio**. Every theme passes text contrast checks.
  - Settings window with side navigation: Appearance (theme gallery), Speech, Listen, Clipboard, Shortcuts,
    Mini mode and General.
- New **mini mode**: a floating bar that stays on top of other apps and never takes focus.
  - Mic button dictates into whatever app you are using; the text is typed at your cursor (or copied, if you prefer).
  - Play button reads the text you have highlighted in any app, or the clipboard when nothing is highlighted
    (also `Ctrl+Alt+S` and `--speak-clipboard`). The highlight is read through UI Automation, without touching the
    clipboard; apps without it get a quick Ctrl+C with your clipboard put back, but terminals never do.
  - Live waveform; voice, speed, volume and Pause popover; mouse wheel over the bar changes the volume;
    snaps to screen edges.
  - **Live captions** while dictating into another app: a bubble above the bar shows each word about half a
    second after you say it. A fast **instant preview** recognizer (sherpa-onnx, a 73 MB English model downloaded
    once) shows the words first, a little dimmer; Whisper checks them at every pause and corrects them in place;
    the newest word is highlighted. The bubble uses larger text, is only as big as the words (one to three lines,
    no empty space) and grows upward so the newest words stay above the bar. Its X or `Esc` cancels; nothing is
    typed. The preview uses about 140 MB of memory while loaded (freed with the Whisper model). Turn it off in
    Settings > Listen.
  - **The text is typed right after you stop.** Measured on 7 test dictations (4 to 42 s, Whisper small, the same
    PC), compared with the first 5.0 test build: first caption 2.6-4.4 s -> 0.6-0.9 s after you start talking; captions
    update every 4.5 s -> every 0.3 s; stop to text 3.0-5.4 s -> 0.01-0.6 s when you pause before stopping
    (under 0.1 s on 6 of the 7), and 3.1-5.6 s -> 0.5-1.2 s when you stop mid-sentence. Word errors: 2 in 664
    words vs 1 before, the same misheard phrase ("in a" for "and a") in both builds.
  - Dictation keeps full speed in the background: Windows 11 runs background apps in efficiency mode, which made
    each Whisper pass 2.6 times slower (1.03 s -> 2.68 s) while you dictate into another app; TTSPython opts out.
  - Long dictations are settled only at real pauses in the audio (never at Whisper's rough segment times, which
    could cut a word), even in run-on speech without sentence breaks, and a short dictation is always
    transcribed as a whole. A word said right before you press stop is always transcribed.
- New **global hotkeys** (rebindable): Ctrl+Alt+D dictation, Ctrl+Alt+S speak clipboard, Ctrl+Alt+X stop,
  Ctrl+Alt+Shift+M mini mode (other apps often take Ctrl+Alt+M). Keys another app already uses are shown in
  Settings and the status bar; a pop-up says so once, the first time, not on every start, and TTSPython tries
  again a few seconds after starting in case a key was only busy for a moment.
- New **ready-to-run downloads**, no Python needed: `TTSPython.exe` for Windows (94 MB zip, 248 MB unpacked)
  and a Linux build with a per-user installer (menu entry, `ttspython` command). Build them yourself with
  `build.bat` / `build.sh`; each release on GitHub gets both, built and smoke-tested automatically.
- New **system tray** icon, with an option to keep running in the tray when the window is closed.
- New command-line options that also control an already running copy: `--mini`, `--show`, `--toggle-dictation`,
  `--speak-clipboard`, `--stop`, `--pause`, `--quit`, `--settings PATH`.
- Speech engine rebuilt: sentences are prepared one ahead and played by the app itself.
  - **Pause and resume** speech (Ctrl+Space or the Play button).
  - The **sentence being read is highlighted** and followed (word highlighting was turned off on Python 3.13 in v4).
  - Speech starts quickly even for long documents: about 50 ms from Play to the first audio handed to the
    sound device, measured on Windows with a SAPI5 voice.
  - **Speed, volume and voice change while speaking.** Every step of a speed drag is heard as you drag (within
    10 ms), mid-sentence, with the same pitch (before, it waited for the next group of sentences, often the whole text). Speed now goes
    from 50% to 200% (shown in percent; 100% is the old 200 words per minute) in smooth steps instead of the
    engine's few fixed rates. A new voice takes over at the word being read. The Settings sliders apply live too,
    and Cancel puts them back.
  - The **output device** setting now works and is remembered by name, so it survives reconnecting devices.
- **More voices.** The Windows 11 voices that older apps cannot see are listed too (on the test PC: Mark), and
  **Get more voices** in Settings > Speech downloads natural-sounding **Piper** voices (178 voices in 53 languages,
  about 60 MB each, checked against their published checksums). Piper runs as its own program, downloaded with
  the first voice, so TTSPython stays MIT-licensed. The voice picker moved from the control bar to Settings and
  the mini bar's popover.
- Dictation: pick the **Whisper model** in Settings and a **language** (English by default, Auto-detect, or 15
  common languages); the model loads while you talk; a live input level meter in Settings.
- **Real MP3 export** (128 kbps) via `lameenc`; exports show progress, can be cancelled, and never leave half-written files.
- Find and replace is now an inline bar with previous/next (Enter / Shift+Enter), wrap-around and a match count.
- New: **Speak from here** (`Ctrl+Alt+Enter`, or right-click in the editor), **New** (`Ctrl+N`), recent files under
  the Open button, drop text files on the editor (opens) or the queue (adds), Settings with `Ctrl+,`, reading time
  next to the word count, the file name and an unsaved mark in the window title.
- The speech queue is kept between sessions; `Enter` plays the selected item; right-click for Play from here, Move
  to top, Copy to the editor and Remove; each item shows its listening time.
- Export uses only the selected text when there is a selection, remembers the folder and format, and offers
  **Open folder** when done. It writes as it renders, so a long book no longer sits in memory.
- Unsaved editor text is also kept every 30 seconds, so it survives a crash.
- The tray menu adds Pause or resume and Settings; its tooltip says what is happening and a red dot shows while
  dictation records.
- Settings: **Save** and **Cancel** both close (Cancel undoes previews); closing with unsaved changes asks. The
  Output, Model and Mic labels in the main window open the matching Settings page. Listen lists the downloaded
  Whisper models and the live preview model with their size and a Delete button.
- Nothing is cut off any more at small window sizes or 150% display scaling: an automatic check of every window
  at 3 window sizes, 3 Settings sizes and 2 scaling levels went from 30 problems to 0 (Settings pages are now
  narrower than the dialog, rows stack when needed, long names end in "..." instead of being cut mid-letter).
- `Ctrl+Enter` now works like the Play button: play, pause, resume.
- Output and microphone lists include every device from every audio system (for example WASAPI-only devices).
- Text files saved as UTF-16 ("Unicode" in Notepad) now open correctly instead of as garbled text.
- Closing or quitting with unsaved editor text asks first. If text cannot be stored in the file's original
  encoding, it is saved as UTF-8 and you are told.
- Unsaved editor text is kept when Windows logs off or shuts down (no prompt is possible then) and put back
  the next time TTSPython starts.
- The first dictation with a new Whisper model shows its download ("Downloading the small model... 120 of
  486 MB"), in the window and next to the mini bar. Before, it sat on "Transcribing" with no word for the whole
  download (58 s for Small in testing), which looked like a hang. Pressing the mic during the download says so.
  The notice by the mini bar is updated in place as the download goes (one notice instead of a new one 5 times a
  second) and is drawn in the theme's colors like the caption bubble. The live preview's own download is shown
  only in the status bar, so it never covers "Listening..." or pops up after you stop; only a failure is announced.
- Downloaded models load straight from disk, skipping an online check on every load (about 1.0 s instead of
  1.1 to 1.7 s for Small) and working fully offline.
- If the dictation model cannot load (for example offline on first use), you are told once; the recording no
  longer waits through the same failing load a second time. The next recording tries again.
- Play queue starts at the selected item (or the top); double-click an item to play from it; pressing it while
  something is speaking switches to the queue instead of refusing.
- Performance Mode is now off by default for new installs (your v4 setting is kept when imported).
- Python 3.8 is no longer supported (Qt needs 3.9 or newer).
- Voice, speed, volume, queue loop and panel layout are remembered between sessions.
- Settings moved to `%APPDATA%\TTSPython\settings.json` (Linux: `~/.config/ttspython/settings.json`); your
  v4 `tts_settings.json` is imported on first start and left untouched.
- Removed the Pillow dependency; added `PySide6-Essentials`, `lameenc`, `comtypes` (Windows) and `pynput` (Linux).
  Linux no longer needs `aplay`/`alsa-utils` or `tk`, but now needs `xcb-util-cursor`.
- Fixed in a second full review (each has a test that fails before the fix):
  - An interrupted model download broke dictation until the download folder was deleted by hand; it now resumes.
  - Microphones that only run at their own rate (WASAPI, some Linux devices) could not record.
  - After Settings > Test and Save, speech could stay on the device that was tested.
  - On Linux, a second user on the same PC could not start the app.
  - A saved voice that was uninstalled was silently replaced, and Export used a different voice than speech.
  - Typing a new global hotkey in Settings fired the old one instead of recording it.
  - A speech engine that failed at start (for example espeak-ng missing) gave no message until Play.
  - The Large v3 Turbo model needed a newer faster-whisper than the app asked for.
  - Speakers or microphones plugged in after start were not listed (now on opening Settings, or Refresh).
  - Restarting the queue while it played showed "Queue stopped".
  - Stopping dictation with Alt or Shift still held could paste as Ctrl+Alt+V (Paste Special in Office).
  - On Wayland, the paste key setting was ignored and the clipboard was not restored.
  - A slow app that copied late could leave the selection on your clipboard after Play.
  - An export failure opened a dialog over the app you were working in.
  - A microphone that sends only silence (blocked in Windows privacy settings) now says so instead of
    "No speech detected"; device errors are explained in plain words.
  - Clear kept the file name, so Ctrl+S could save an empty editor over the file.
- Smaller and lighter: the Windows app no longer bundles unused Qt plugins, PortAudio builds for other CPUs, or an
  OpenSSL copy picked up from another program; the level waveform stops redrawing while silent or hidden (21
  redraws per silent second before, at most 2 now); Whisper uses up to 8 threads (22% faster on a 16-thread PC);
  Settings opens without rescanning audio devices until the Speech or Listen page is shown.
- Fixed (each has a test that fails on v4.1.0 and passes now):
  - Auto-Queue replayed the whole queue over and over; queued items now play once.
  - Stop followed quickly by Speak could run two voices at the same time.
  - Clipboard speech did not mark the app as busy, so a second voice could start over it.
  - Turning the clipboard monitor off and on quickly stacked extra polling loops (22 checks in 2 s instead of 2).
  - Highlighting during Speak Selected pointed at the wrong place.
  - Changing a shortcut left the old key active; a missing shortcut in the settings file crashed startup.
  - The Start Recording button kept the stop icon and a doubled emoji after recording.
  - Find ignored the Match case and Regular expression options, and regex matches were selected at the wrong length.
  - "MP3" export saved a WAV file with an .mp3 name.
  - The output device setting was saved but never used.
  - Changing the Whisper model had no effect until restart.
  - Removing the item that was playing at the end of the queue restarted the queue from the top.
  - Find and Replace could be opened several times at once.
  - Closing the window while speaking did not stop speech.
  - Replace All treated backslashes in the replacement as escape codes (for example `\n` became a new line).
  - Saving added a newline to the end of the file every time.
  - Replace All took two undo steps, and the first left the editor empty.
  - Voice, speed and volume were not saved.
  - The microphone setting pointed at a device number, so it could switch to the wrong mic after devices changed.

## Version 4.1.0 - 2026-07-24
- Linux / Arch Linux support (cross-platform TTS)
  - `pyttsx3` now initializes with the `espeak` driver on Linux/macOS (SAPI5 remains the Windows default)
  - Platform-aware UI fonts (Noto/DejaVu/Liberation on Linux; Segoe UI on Windows)
  - Voice refresh, Add Voices, and Sound Output actions use Linux-friendly messaging and openers
    (`xdg-open`, `pavucontrol` / GNOME Sound, espeak-ng package hints)
  - `check_voices.py` works on Linux with espeak-ng and prints Arch `pacman` install guidance
- New Linux install path
  - Added `requirements.txt` (Windows-only `pywin32` via environment marker)
  - Added `dependencies.sh` for Linux/macOS venv + pip/uv install, with Arch/Linux system package notes
    (`espeak-ng`, `alsa-utils`, `tk`, `portaudio`)
- Documentation updated for Windows + Linux (Arch) install and troubleshooting
- Bumped app version to 4.1.0
---

## Version 4.0.0 - 2026-07-10
- Complete graphical UI overhaul (visual-only, no behavior change)
  - Redesigned all 11 theme presets into cohesive modern palettes + consistent component styling
  - New gradient header bar with app title and mode toggle
  - Refined ttk styling: padded/rounded buttons, themed sliders, comboboxes, check/radio, notebook,
    scrollbars, hover/active/focus states
  - Themed Search and Settings dialogs with matching headers
  - Queue "now playing" highlight now uses the theme accent
- Color emoji rendering (fixes the gray outline glyphs on Windows)
  - Added `emoji_icon()` helper that renders emoji to color bitmaps via Pillow (`ImageDraw` with
    `embedded_color=True`) using Segoe UI Emoji, with graceful `None` fallback to text-only when
    Pillow or a color font is unavailable.
  - Every toolbar, file, queue, and STT button now shows a color icon next to its text label
    (`image=` + `compound=tk.LEFT`).
- Speech Queue reworked to a `ttk.Treeview`
  - Replaced the plain `Listbox` with a Treeview that shows a per-row color icon (💬 text / 📄 file /
    📋 clipboard) and a "Speech Queue" heading.
  - "Now playing" row is highlighted using the theme accent via a `now_playing` tag.
  - Added **Move Up** / **Move Down** buttons and a **Loop queue** checkbox; the **Delete** key
    removes the selected item.
- Export Audio no longer freezes the UI
  - `on_export_audio` now runs `engine.save_to_file` + `runAndWait` on a daemon worker thread; the
    Export button disables during export and re-enables on completion.
- Header simplified
  - Top-left now reads only `TTSPython 4.0.0` (removed the `· Text-to-Speech & Speech-to-Text` subtitle).
  - Removed the quick theme switcher from the header; theming is now set via **Settings → Theme**.
- File I/O encoding robustness
  - New `_read_text_file()` decodes with `utf-8-sig` → `utf-8` → `cp1252` → lossy fallback, so BOM and
    legacy encodings no longer crash Open/Add File(s); errors show friendly messages.
- Settings → Reset to Defaults now resets everything
  - In addition to hotkeys, it now resets theme preset, Performance Mode, and STT/audio device +
    unload settings to `DEFAULT_SETTINGS`.
- Window launch UX
  - Window is centered on first launch and restores its last size/position (persisted in
    `tts_settings.json` under `geometry`).
- Documentation + repo cleanup
  - Rewrote README to reflect actual v4.0.0 features and Windows/SAPI5 scope
  - Removed duplicate `docs/` folder and stale Cursor-generated docs (API v2.2, RELEASE_NOTES, etc.)
  - Refreshed FEATURE_GUIDE, QUICK_REFERENCE, ADD_VOICES_GUIDE; added .gitignore
  - `dependencies.bat` now also verifies `Pillow` (emoji rendering depends on it; text-only fallback
    still applies if missing)
- Bumped app version to 4.0.0
---

## Version 3.1.0 - April 23, 2026
- Performance update (same STT model quality defaults)
  - STT recording now streams directly to a temporary WAV file instead of buffering full chunks in memory, and no longer uses a full `numpy.concatenate` recording path before transcription.
  - **Measured impact (Resource Tracker, auto-unload OFF):** up to **~9.9% lower peak RAM** in matched runs (799.7 MB -> 720.4 MB).
  - **Measured impact (Resource Tracker, auto-unload ON):**
    - **~30.6% lower peak RAM** in matched runs (799.7 MB -> 555.3 MB)
    - **~41.6% lower post-STT resident RAM** in matched runs (573.8 MB -> 334.9 MB)
  - **Interpretation:** early 3.1.0 runs show clear peak memory improvements from the new recording path, with additional tuning/validation in progress.
  - **User impact:** lower worst case memory spikes during STT capture/transcription and better headroom on lower memory systems, while keeping the same Whisper model quality target.
  - Added optional STT model unload controls:
    - Immediate unload when idle (toggle)
    - Auto-unload timer after configurable idle minutes
  - **User impact:** can reduce idle memory footprint between STT uses (with slower first transcript after unload), without downgrading model size.
- Responsiveness and stability cleanup
  - Centralized Windows COM thread init/deinit for TTS worker threads.
  - Batched several queue/speech UI `root.after(0, ...)` updates to reduce unnecessary main-thread wakeups.
  - Replaced broad bare exception handling in hot paths with explicit exception handling where safe.
  - Removed a redundant local `re` import in Find/Replace and tightened one shortcut unbind exception to `tk.TclError`.
  - **User impact:** cleaner internals, slightly smoother UI update behavior under load, and easier future maintenance.
---

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

## Statistics (5.0.0)

- **Shortcuts**: 13 in-window plus 6 global hotkeys, all customizable
- **Themes**: 12 presets (Studio, Dark, Twilight, Light, High Contrast, Forest, New Vegas, Spiral, Poly, Sunset, Paper, Graphite)
- **Modes**: Speak (SAPI5 on Windows, espeak-ng on Linux) + Listen (offline faster-whisper, 16 languages plus Auto-detect)
- **Queue sources**: Text, File, Clipboard
- **Platforms**: Windows 10/11 and Linux
- **Python**: 3.9 or newer

---

## What's Next?

Potential future enhancements:
- PDF and Word document support
- Pronunciation dictionary
- Recent files menu

---

**Thank you for using TTS Application!** 🎉

For questions or suggestions, check the documentation:
- `README.md` - Overview and setup
- `FEATURE_GUIDE.md` - Complete feature documentation
- `QUICK_REFERENCE.md` - Quick lookup guide
- `ADD_VOICES_GUIDE.md` - Installing more voices

