# TTSPython

A free, open-source, offline text-to-speech (TTS) and speech-to-text (STT) desktop app for Windows and Linux, with a full editor window and a floating mini bar that works over any app. Speech uses your system voices (SAPI5 on Windows, espeak-ng on Linux) or natural-sounding Piper voices you download once, and dictation runs locally with `faster-whisper`. Nothing you read or say leaves your computer: the app only goes online to download the voices and models you ask for, and, if you say yes when asked, to check for a new version once a day.

![TTSPython main window](assets/screenshots/main.png)

| Dictating into any app, with live captions | Natural voices, downloaded once |
|:---:|:---:|
| ![The mini bar with the live caption bubble above it](assets/screenshots/mini.png) | ![The Get more voices window](assets/screenshots/voices.png) |

| Listen mode | Settings > Listen |
|:---:|:---:|
| ![The main window in Listen mode](assets/screenshots/listen.png) | ![The Listen page of Settings](assets/screenshots/settings.png) |

![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Version](https://img.shields.io/badge/version-5.1.0-brightgreen.svg)

## Features

### Speak (text-to-speech)
- **Play / Pause / Stop** with a media-player style control bar, plus **Speak selected** and **Speak from here** (from the sentence where the cursor is; also in the editor's right-click menu).
- The sentence being read is **highlighted** and the editor follows along.
- **Speed** (50% to 200%, 100% is normal) and **volume** change **while it speaks**: drag the speed slider and you hear every step as you drag (within 16 ms), mid-sentence, with the same pitch. Changing the **voice** mid-sentence continues from the word being read.
- **More voices:** besides the system voices (including the Windows 11 voices Windows hides from older apps, such as Mark), **Settings > Speech > Get more voices** downloads natural-sounding **Piper** voices: dozens in English and many other languages, about 60 MB each, downloaded once and then fully offline.
- **Your own voice:** read a short statement out loud and the app makes a copy of your voice, entirely on your computer. See [Your own voice](#your-own-voice).
- Choose the **output device** in Settings (speakers, headset, virtual cable); every device from every audio system is listed, and **Refresh** finds one you plugged in later.
- With system and Piper voices, speech starts within a fraction of a second, even for very long texts, because it is prepared a few seconds ahead of what you hear. Your own voice is heard while it is being made: see [Your own voice](#your-own-voice).

### Listen (speech-to-text)
- Offline dictation with `faster-whisper` (CPU, int8). Press the record button, speak, press again.
- **Live captions:** when you dictate into another app, a bubble above the mini bar shows each word about half a second after you say it, so you can spot a mistake early. A fast **instant preview** recognizer shows the words first (slightly dimmer); Whisper then checks them and corrects them in place, and the newest word is highlighted. The bubble grows a line at a time (up to three), with the newest words right above the bar. Its **X** (or `Esc`) cancels the dictation and nothing is typed.
- **Typed right after you stop:** Whisper checks the text whenever you pause, so if you pause before stopping, the text is typed almost at once (usually under 0.1 s in tests, 0.6 s at most); otherwise in about 0.5 to 1.2 s. Long dictations settle at real pauses as you go, so this stays short however long you talk.
- **Spoken commands:** say "period" (or "full stop"), "comma", "question mark", "exclamation mark" (or "exclamation point"), "colon", "semicolon", "new line", "new paragraph", and "delete that" (or "scratch that") to remove the sentence before it. After "the", "a", "this" and similar words, with more words following, they stay words ("the period of time"). English, and Auto-detect when it hears English; turn them off in **Settings > Listen > Spoken commands**.
- Dictation keeps full speed while TTSPython is in the background (Windows 11 would otherwise slow it down 2.6 times while you work in another app).
- Pick the **Whisper model** (from Tiny to Large v3 Turbo) and the **language**: English by default, Auto-detect, or Spanish, French, German, Italian, Portuguese, Dutch, Polish, Russian, Ukrainian, Turkish, Arabic, Hindi, Japanese, Korean or Chinese.
- The model loads while you are still talking and can unload itself after a set idle time to free memory.

### Mini mode
- A small **floating bar** that stays on top of every window and **never takes focus**, so your cursor stays where you were typing.
- **Mic button**: dictate, and the text is **typed where your cursor is** in any app (or copied to the clipboard, if you prefer).
- **Play button**: reads the text you have **highlighted** in any app (or the **clipboard** if nothing is highlighted); press again to stop.
- **Live waveform** while speaking or listening, plus a quick **voice, speed, volume and Pause** popover (chevron or right-click). Scroll the mouse wheel over the bar to change the volume.
- Drag it anywhere; it snaps to screen edges and remembers its position.

### Global hotkeys
Work even when TTSPython is in the background. All can be changed in **Settings > Shortcuts**.

| Action | Default |
|--------|---------|
| Start or stop dictation | `Ctrl+Alt+D` |
| Speak selection or clipboard (press again to stop) | `Ctrl+Alt+S` |
| Stop speaking | `Ctrl+Alt+X` |
| Show or hide mini mode | `Ctrl+Alt+Shift+M` |
| Pause or resume speech, Show main window | unassigned |

### Speech queue
- Add the editor text, text files or clipboard items and play them back to back.
- **Drag to reorder** (or the up and down arrows), **Remove** (the minus button or the Delete key), **Clear**, **Loop**.
- Double-click an item (or press `Enter`) to play from there; right-click for Play from here, Move to top, Copy to the editor and Remove. Each item shows how long it takes to listen to.
- Drop text files on the queue to add them, even when it is empty. The playing item is marked, editing the queue while it plays is safe, and the queue is kept for the next start.

### Clipboard monitor
- Watches the clipboard and either **speaks** or **queues** copied text (6 characters or more).
- **Auto-Queue**: while speech is playing, copied text is queued instead of ignored, then played once. When reading ends, the queue is read next (this part works with the clipboard monitor off too).

### Export audio
- Save the text (or just the selected part) as **WAV** or **MP3** with the current voice, speed and volume. Export runs in the background with progress and a Cancel button, writes as it goes (a whole book never sits in memory), remembers the folder and format, and offers **Open folder** when done.

### Editor
- **New**, open and save text files (UTF-8, UTF-16 and Windows-1252) without changing their encoding or line endings. A file in another encoding (such as GBK or Shift-JIS) can look wrong; you are told when it opens, and Save asks where to save, so the original stays as it is. The **Open** button's arrow lists recent files, and you can drop a text file on the editor to open it. The window title shows the file name and whether it has unsaved changes. Closing with unsaved text offers **Save**, **Discard** or **Cancel**.
- Unsaved text is kept every 30 seconds, so it comes back after a crash or a logoff.
- The word count also shows the reading time at the current speed.
- Inline **Find and replace** (`Ctrl+F`) with match case, regular expressions, previous/next with wrap-around, a match count ("2 of 5"), Replace and Replace all (one undo step).

### Look and feel
- 12 themes: **Studio** (new default), Dark, Twilight, Light, High Contrast, Forest, New Vegas, Spiral, Poly, Sunset, Paper, Graphite. Every theme is checked for readable text contrast.
- **Performance Mode** reduces animations and redraws for slower PCs.
- **System tray** icon (Show window, Mini mode, Speak selection or clipboard, Pause or resume, Stop, Copy last dictation, Settings, Quit). Its tooltip says what is happening, and a red dot shows while dictation records. Optionally, closing the window keeps TTSPython running in the tray.
- The window, Settings and mini bar fit small windows and large display scaling without cutting anything off.

## Requirements
- **Windows 10/11** or **Linux** (X11 or Wayland). Linux is a preview in 5.0: it is built and smoke-tested automatically, but has had less hands-on testing than Windows, so please report what you find.
- To run from source: Python 3.10 or newer (developed on 3.13; the full test suite also passes on 3.10).
- Python packages (installed by the scripts below): `PySide6-Essentials`, `pyttsx3`, `numpy`, `sounddevice`, `lameenc`, `faster-whisper`, `sherpa-onnx` (the instant live preview), `sentencepiece` (your own voice); on Windows also `comtypes` (talks to the SAPI5 voices; pyttsx3 brings `pywin32` for its fallback driver); on Linux also `pynput`.
- For your own voice (optional): a microphone, 762 MB of disk space and about 1.3 GB of free memory.
- Linux system packages: `espeak-ng`, `portaudio`, `xcb-util-cursor` (Debian/Ubuntu: `libxcb-cursor0`). Optional: `wtype` to type dictation at the cursor on Wayland.

## Installation

### Ready-to-run app (no Python needed)
Download the latest build from [Releases](https://github.com/JoshLongmire/TTSPython/releases):
- **Windows installer:** `TTSPython-<version>-windows-x64-setup.exe`. Installs for your user, with no administrator
  rights, adds a Start menu entry and can be removed in Windows Settings > Apps. Installing a new version over an old
  one keeps your settings. Uninstalling asks whether to delete your settings, unsaved text, voices and voice
  recordings, and keeps them unless you say yes (`unins000.exe /VERYSILENT /DELETEUSERDATA=1` says yes without asking).
  That includes the voice model, the live preview models and downloaded voices. Whisper models are shared with other
  programs and are kept either way: delete them first in **Settings > Listen**.
- **Windows zip:** `TTSPython-<version>-windows-x64.zip`. Extract it anywhere and run `TTSPython\TTSPython.exe`.
- The app is not code-signed, so SmartScreen may warn you about either one: choose **More info > Run anyway**.
  Each release lists its files' checksums in `SHA256SUMS.txt`, so you can check what you downloaded.
  The app folder also holds `LICENSE.txt` and `THIRD_PARTY_LICENSES.txt`.
- **Linux:** `TTSPython-<version>-linux-x86_64.tar.gz`. Extract it and run `TTSPython/install.sh` (installs for your
  user only: app menu entry, with **Show the mini bar** and **Start or stop dictation** as actions, and a `ttspython` command; `uninstall.sh` removes it and asks about your data, and `uninstall.sh --delete-data` deletes it without asking). It also needs
  `espeak-ng`, `libportaudio2` and `libxcb-cursor0` from your distribution; the installer tells you if one is missing.
  Built on Ubuntu 22.04, so it runs on distributions from 2022 or newer.

The first dictation downloads the Whisper model you picked (once; it stays in the shared Hugging Face cache until you delete it in **Settings > Listen > Downloaded models**) and, for English, French or Chinese, the live preview model (73 to 134 MB, once per language), a Piper voice downloads when you pick it, and the model for your own voice (762 MB) downloads when you ask for it, so the app needs internet for those. The check for new versions is asked once and only runs after a yes.

### From source: Windows
1. Install Python 3.10 or newer from [python.org](https://www.python.org/downloads/windows/) (tick **Add Python to PATH**).
2. Get the code and install the dependencies:
   ```powershell
   git clone https://github.com/JoshLongmire/TTSPython.git
   cd TTSPython
   ./dependencies.bat
   py TTSPython.py
   ```

### From source: Linux (Arch and others)
1. System packages (Arch example):
   ```bash
   sudo pacman -S python espeak-ng portaudio xcb-util-cursor
   ```
2. Get the code and install the Python dependencies:
   ```bash
   git clone https://github.com/JoshLongmire/TTSPython.git
   cd TTSPython
   chmod +x dependencies.sh
   ./dependencies.sh
   source .venv/bin/activate
   python TTSPython.py
   ```
   `dependencies.sh` creates a `.venv` and installs from `requirements.txt` (with `uv` if available, otherwise `pip`).

## Usage

### Reading text aloud
1. Type or paste text into the editor.
2. Press **Play** (`Ctrl+Enter`). Press it again to pause, and again to resume.
3. Select text and press **Speak selected** (`Ctrl+Shift+Enter`) to read just that part.
4. **Stop** (`Esc`) ends speech right away.

### Dictating into the editor
1. Switch the top toggle from **Speak** to **Listen** (`Ctrl+M`).
2. Press the red record button, speak, press it again. The text goes in at the cursor, like typing. At the very end of the text, it gets a line of its own.

Speech stops when you start dictating, wherever the text is going, so the microphone cannot type what the speakers say.

Say "period", "comma", "question mark", "new line" and the like for the mark or the line break, and "delete that" to remove the sentence before it. "Buy milk period new line call Sam question mark" is typed as two lines: "Buy milk." and "Call Sam?".

### Dictating into any app
1. Press `Ctrl+Alt+D` (or the mic in mini mode) while your cursor is in another app.
2. Speak. A caption bubble shows each word as you say it. Dimmer words are the instant preview's first guess; Whisper checks them a moment later (usually when you pause) and corrects them in place.
3. Press it again. The text is typed where your cursor is. If the window changed in the meantime, the text is copied to the clipboard instead and a note tells you so. Press `Esc` or the bubble's **X** to throw the dictation away instead.

### Mini mode
- Click the **Mini mode** button in the top bar, press `Ctrl+Alt+Shift+M`, or use the tray menu.
- Highlight text in any app and press the bar's **Play** button (or `Ctrl+Alt+S`) to hear it. With nothing highlighted, it reads the clipboard.
- The expand button on the bar brings the full window back.

### Command line
These also work while TTSPython is already running (the running copy receives them), which is handy for desktop shortcuts and for Wayland, where apps cannot register global hotkeys:

```
python TTSPython.py --mini               Show the floating mini bar
python TTSPython.py --toggle-dictation   Start or stop dictation into the active app
python TTSPython.py --speak-clipboard    Speak the highlighted text, or the clipboard (or stop speaking)
python TTSPython.py --stop               Stop speaking
python TTSPython.py --pause              Pause or resume speech
python TTSPython.py --show               Show the main window
python TTSPython.py --quit               Quit the running app
python TTSPython.py --settings PATH      Use a different settings file
python TTSPython.py --version            Print the version
```

With the ready-to-run app, use `TTSPython.exe --mini` (Windows) or `ttspython --mini` (Linux) the same way.

### Adding voices
- **Natural voices (Windows and Linux):** **Settings > Speech > Get more voices**, pick a language and a voice, press **Download**, then **Use this voice**. The first one also downloads the Piper program (about 23 MB). **Hear samples online** opens the official samples page. Voices are stored in `%LOCALAPPDATA%\TTSPython` (Windows) or `~/.local/share/ttspython` (Linux) and can be removed again in the same window.
- **Your own voice:** the same window has **Make my voice**. See [Your own voice](#your-own-voice).
- **Windows voices:** the same window opens Windows Speech settings (`ms-settings:speech`); install voices there, then press **Refresh**.
- **Linux system voices:** install espeak-ng language data with your package manager, then press **Refresh**.
- See [`ADD_VOICES_GUIDE.md`](ADD_VOICES_GUIDE.md) for details. Run `python check_voices.py` to list installed voices.

### Your own voice
**Settings > Speech > Get more voices > Make my voice** copies your voice:
1. Download the voice model once (762 MB).
2. Press **Start recording**, read the statement on screen out loud, then press **Stop recording** (a recording has to last 6 to 40 seconds, and stops by itself at 40). You can name the voice first. The app checks that the recording says the statement, makes the voice, and tells you how quickly this computer can speak in it.
3. Press **Hear it** to try it, or **Use this voice** to read with it.

It is for your own voice only. The statement says that you agree to the copy and includes three code words, spread from start to end, that change on every try. The recording has to say the statement and little else, and there is no way to make a voice from a file. This is a safeguard against misuse, not proof of who is speaking, so please only use it for your own voice.

The check uses your Whisper model, so if you have never dictated, that also downloads once when you stop recording (Small is about 480 MB). **Cancel** stops the whole thing and nothing is kept, as does closing the window.

- **Privacy:** the recording, the voice and all the speech stay on your computer, in `%LOCALAPPDATA%\TTSPython\cloned-voices` (Windows) or `~/.local/share/ttspython/cloned-voices` (Linux). **Remove** deletes a voice and its recording. **Delete the voice model** frees the disk space and keeps your voices; it is refused while your voice is in use, so pick another voice first. If the model is gone some other way, your voice stays selected and speaking with it says where to download it again.
- **What it needs:** on the test PC (Intel i5-12600K) it makes speech 2.2 to 2.4 times as fast as it plays, using about 3 processor cores and 1.3 GB of memory, which is released 2 minutes after speech ends. On a slower or busy computer it may pause between sentences; the app measures this when it makes the voice; exporting to a file is not affected, it only takes longer.
- **Run-on speech:** the model sometimes keeps talking after a short reply ("Okay. Oh, okay."). A piece under five words is made in full before you hear it, and made again once if it runs past what its words need at your voice's pace; such a word can start up to about 1.8 seconds later. A longer sentence that runs on is cut where it should have ended, never said twice.
- **Waiting:** on the test PC speech starts about half a second after you press Play, because you hear each sentence while it is being made, or about 3 seconds if the model has to load first (it is let go 2 minutes after speech ends). On a computer too slow to keep up, it waits longer before starting a sentence so that it does not stop in the middle of a word.
- **Other languages:** your voice reads any text you give it, but outside English it is much less clear. With Whisper listening to 6 sentences in each language, it misheard about 1 word in 50 in English, 1 in 10 in Spanish, 1 in 6 in Portuguese and Chinese, 1 in 5 in French and German, 1 in 3 in Italian and 2 in 5 in Japanese (characters, for Chinese and Japanese). For other languages, a Piper voice from **Get more voices** sounds far better.
- **Limits:** made from English, and not yet tried with a real microphone in a real room. Very short phrases sometimes gain a stray word (6 of 42 tries with one to three words, such as "Yes. All of them."), and digit strings such as phone numbers can come out wrong (555-0142 was heard as 535-042), so check anything important. Longer sentences had about 1.5% of words heard wrong.

## Keyboard shortcuts (in the window)

The Enter on the numeric keypad works in every shortcut below that uses `Enter`.

All can be changed in **Settings > Shortcuts**.

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
| Clear text (undo with `Ctrl+Z`) | `Ctrl+L` |
| Find and replace | `Ctrl+F` |
| Export audio | `Ctrl+E` |
| Switch Speak / Listen | `Ctrl+M` |
| Show or hide the queue | `Ctrl+Q` |
| Settings | `Ctrl+,` |

While you dictate into another app, `Esc` cancels the dictation (only then; it is given back afterwards).
In the editor, `Tab` types a tab, so `Ctrl+Tab` and `Ctrl+Shift+Tab` move to the next and previous control.

## Settings

Settings are saved automatically to:
- **Windows:** `%APPDATA%\TTSPython\settings.json`
- **Linux:** `~/.config/ttspython/settings.json`

Unsaved editor text is kept next to the settings file every 30 seconds (`recovery.json`) and put back the next
time TTSPython starts after a crash, logoff or shutdown. The speech queue is kept there too (`queue.json`).

**New versions:** a few seconds after the first start of 5.1, a line above the text asks whether TTSPython may check GitHub for new versions. After a yes it asks GitHub's public release list at most once a day, sends nothing but that request, and when a newer version is out it says so with a **Download page** button and **Skip this version**. Nothing downloads by itself. Change your answer in **Settings > General > Check for new versions**.

The first time TTSPython 5 starts, it imports your old `tts_settings.json` from the app folder (theme, shortcuts, clipboard, dictation and window size). The old file is left untouched.

The Settings window has these pages: **Appearance** (theme gallery, Performance Mode), **Speech** (voice and Get more voices, speed and volume, which apply as you move them, output device with Refresh, Test and Sound settings, sentence highlight), **Listen** (microphone with a live level meter, Whisper model, downloaded models (Whisper, the live preview and your own voice) with their size and a Delete button, **Unload now**, language, **Instant live preview** on or off, **Keep the recording until it is typed**, **Spoken commands**, memory options, how dictation reaches other apps), **Clipboard**, **Shortcuts** (in-window and global, with **Enable global hotkeys**), **Mini mode** (with **Show the live waveform** and **Reset position**) and **General** (tray behavior, **Check for new versions**, settings file location). **Save** keeps the changes and closes; **Cancel** undoes them, previews included; closing with unsaved changes asks. The Output, Model and Mic labels in the main window open the matching page.

## Troubleshooting

Errors are written to the `logs` folder inside `%LOCALAPPDATA%\TTSPython` (Windows) or `~/.local/share/ttspython` (Linux): `ttspython.log`, and `crash.log` if the app itself crashed. They hold errors and program details, never what you read or dictate, and they stay on your computer unless you choose to send them with a bug report.

### No voices available
- Download a natural voice in **Settings > Speech > Get more voices** (works on Windows and Linux).
- **Windows:** system voices come from SAPI5 (built into Windows) and the Windows 11 speech voices. Install more in Windows Speech settings, then **Refresh**.
- **Linux:** install `espeak-ng` and confirm `espeak-ng "hello"` works in a terminal.
- Run `python check_voices.py` to list what is installed.

### No sound
- Check **Settings > Speech > Output device** and press **Test**. "System default" follows your OS default device. Plugged in a headset after starting TTSPython? Press **Refresh** next to the device list.
- On Linux, make sure `portaudio` is installed.

### The first dictation takes a while
- The first time you use a Whisper model it is downloaded once (Small is about 480 MB). The download progress shows
  in the status bar, the Listen panel, and next to the mini bar; your recording is transcribed as soon as it finishes.
  **Cancel** in the Listen panel, or `Esc` from the mini bar, stops it.
  Pick **Tiny** or **Base** in **Settings > Listen** for a smaller download.
- The live preview model (73 MB, or 128 MB for French and 134 MB for Chinese) also downloads once, in the background; its progress shows in the status bar
  only, and until it is ready the captions come from Whisper alone (about every 1.5 s). Turn the preview off in
  **Settings > Listen > Instant live preview**.

### The caption shows a wrong word
- The dimmer words come from the instant preview, which is fast but less accurate. Whisper corrects them a moment
  later, and only Whisper's text is typed.

### Play reads the clipboard instead of what I highlighted
- Play reads the highlight through Windows UI Automation, which most apps support. Apps that don't support it get a
  quick `Ctrl+C` instead, and your clipboard is put back right after. Terminals never get `Ctrl+C` (it would stop the
  running program), so in a terminal, copy the text first.
- On Linux, Play reads the primary selection (the text you last highlighted in any app).

### Dictation says the microphone sent only silence
- The microphone is muted, or Windows does not let apps use it: **Settings > Privacy & security > Microphone**, turn on access for desktop apps.

### A dictation could not be transcribed
- The text that was already final is typed, and the recording is kept: press **Try again** on the Listen page, for example once you are back online, or after picking another model. **Discard** deletes it. It stays until then, even if you quit, or until you start a new dictation.

### The app crashed or the power went while I was dictating
- Nothing you said is lost, up to about the last second. The sound goes to a file on your computer as you speak, in the `dictation` folder inside `%LOCALAPPDATA%\TTSPython` (Windows) or `~/.local/share/ttspython` (Linux). At the next start the app says so: press **Try again** on the Listen page to get the text in the editor, or **Discard** to delete the recording. The file is deleted as soon as the text is delivered. To keep recordings in memory only, turn off **Settings > Listen > Keep the recording until it is typed**.

### The microphone stopped in the middle
- If a microphone stops sending sound (unplugged, or its driver stopped), dictation stops and types what it heard, and the status bar says so.

### Dictation is not typed into another app
- On the desktop or a page with nowhere to type, a paste lands nowhere and Windows does not say so. **Copy last dictation** in the tray menu puts the last text on the clipboard again. It is kept in memory only, and is gone when you quit.
- A window running as administrator ignores simulated typing. TTSPython notices, leaves the text on the clipboard and says so: press `Ctrl+V`. The same happens if a paste fails.
- Terminals often paste with `Shift+Insert`: change **Settings > Listen > Paste using** (also used with `wtype` on Wayland).
- If you still hold `Alt` or `Shift` from the stop hotkey, the text is copied instead of pasted (pasting then would trigger another command): press `Ctrl+V`.
- On Wayland, install `wtype`, or use the clipboard option.

### A global hotkey does not work
- On Windows, **Settings > Shortcuts** shows "Already used by another app" next to any hotkey another program owns, and the status bar says so at start. A pop-up tells you once, the first time a key is found taken, not on every start. Pick a different combination (global hotkeys are paused while you type one in). TTSPython tries again a few seconds after starting, in case the key was only busy for a moment.
- On Wayland, bind the command-line options above in your desktop's keyboard settings instead.

### The window looks wrong on Linux
- Install `xcb-util-cursor` (`libxcb-cursor0` on Debian/Ubuntu). On Wayland, TTSPython runs through XWayland (when it is available) so the mini bar can stay on top.

### Export to MP3 is missing
- MP3 needs the `lameenc` package: `pip install lameenc`. WAV export always works.

## Development

```bash
python -m pip install -r requirements-dev.txt
python -m pytest                 # unit and UI tests (offscreen, fake audio)
python -m pytest -m audio        # real speech engine and speakers
python -m pytest -m desktop      # mini bar focus check on the real Windows desktop
python -m pytest -m legacy       # the bug specs, run against v4.1.0 from git (expected to fail there)
python tools/bench/bench.py --target v5 --runs 10 --metrics startup   # startup time and memory
python tools/bench/bench.py --target v5 --metrics ttfa                # time to first audio (speaks; needs silence)
python tools/screenshots.py --out shots --themes all --extras
```

Tests never touch your real settings: they use temporary files, and a guard fails the run if a real settings file changes.

### Building the ready-to-run app
```bash
build.bat        # Windows: dist/TTSPython/TTSPython.exe and dist/TTSPython-<version>-windows-x64.zip
./build.sh       # Linux:   dist/TTSPython/TTSPython and dist/TTSPython-<version>-linux-<arch>.tar.gz
python packaging/build.py --installer   # Windows: also the installer (needs Inno Setup 6, or its ISCC in the ISCC environment variable)
```
Each system builds its own app (PyInstaller cannot build for another OS). Build Linux on the oldest distribution
you want to support. Pushing a `v*` tag runs `.github/workflows/build.yml`, which builds and smoke-tests both
and attaches them to the GitHub release, after the test suite. Packages come from `packaging/requirements-windows.lock` and `requirements-linux.lock`, which hold the exact tested versions and the hash of every file (made from `packaging/constraints.txt`; `packaging/build-requirements.txt` says how). To try the whole thing without releasing, run the workflow by hand: only a `v*` tag publishes. To check a build, run it with `TTSPYTHON_SELFTEST=<report.json>`: it loads
every part (voices, the Piper voice list, MP3 export, Whisper libraries, the live preview engine and, if downloaded,
its model, audio devices), writes the report (with a `problems` list, empty when all is well) and quits,
without sound. `python packaging/build.py --check` does this right after building and fails if it finds a problem. Add `TTSPYTHON_SELFTEST_STT=tiny` to also dictate a spoken test phrase through the real transcription
path, played in real time with live captions (downloads that model if needed; the result is never typed anywhere).
`TTSPYTHON_SELFTEST_PHRASE` changes the phrase, `TTSPYTHON_SELFTEST_LIVE=0` turns the captions off for comparison,
and `TTSPYTHON_SELFTEST_VOICE=<voice id>` exports the test MP3 with that voice (for example a downloaded Piper voice).

## License

Released under the MIT License. See the [`LICENSE`](LICENSE) file. The ready-to-run app also includes Qt, Whisper's
engine and other components under their own licenses, listed in its `THIRD_PARTY_LICENSES.txt`. Whisper models (MIT) and
the live preview models (Apache-2.0) are downloaded when needed and keep their own licenses.

Piper voices are spoken by the official [Piper](https://github.com/rhasspy/piper) program (MIT, with espeak-ng under
GPL-3.0), which TTSPython downloads and runs as a separate program; it is not part of TTSPython. Each voice has its
own license (see its model card on [Hugging Face](https://huggingface.co/rhasspy/piper-voices)).

Your own voice is spoken by [MOSS-TTS-Nano](https://github.com/OpenMOSS/MOSS-TTS-Nano) (Apache-2.0) from the OpenMOSS team,
which TTSPython downloads when you ask for it and runs with ONNX Runtime; it is not part of TTSPython.

## Changelog

See [`CHANGELOG.md`](CHANGELOG.md) for the full version history.

## Additional guides

- [`FEATURE_GUIDE.md`](FEATURE_GUIDE.md): in-depth feature walkthrough.
- [`QUICK_REFERENCE.md`](QUICK_REFERENCE.md): shortcuts and workflows at a glance.
- [`ADD_VOICES_GUIDE.md`](ADD_VOICES_GUIDE.md): installing and managing voices.
