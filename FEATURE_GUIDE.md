# TTSPython Features Guide (v5)

## The main window

- **Top bar**: app name and version, the **Speak / Listen** switch, and buttons for Open (its arrow lists recent files), Save, Save as, Export audio, Find and replace, Mini mode and Settings. Hover a button to see what it does (and its shortcut, if it has one).
- **Editor card**: the document name (with a dot when there are unsaved changes), live word and character counts with the reading time at the current speed, **Paste** and **Clear** (Clear can be undone with `Ctrl+Z`; it also detaches the file, so Save asks where to save). The window title shows the file name too.
- **Speech queue panel** on the right (show or hide it with `Ctrl+Q` or the queue button at the bottom right).
- **Control bar** at the bottom: Play/Pause, Stop, Speak selected, the current sentence and progress, a live waveform while it speaks, speed and volume (both in percent). The voice is picked in Settings > Speech or the mini bar's popover.
- **Status bar**: messages, the clipboard monitor controls (Speak or Queue shows only while the monitor is on), Performance Mode and the output device in use (click it to change it). On narrow windows the output device and then Performance Mode make room for the messages (both are also in Settings).

## Speak (text-to-speech)

- **Play** (`Ctrl+Enter`) reads the whole editor. Press it again to **pause** and again to **resume** (`Ctrl+Space` also pauses and resumes).
- **Speak selected** reads only the selection. If something is already playing, it switches to the selection.
- **Speak from here** (`Ctrl+Alt+Enter`, or right-click in the editor) reads from the start of the sentence where the cursor is to the end.
- **Stop** (`Esc`) ends speech immediately.
- The **sentence being read is highlighted** and the editor scrolls to keep it in view. Editing the text while it reads simply turns the highlight off for that run. You can disable highlighting in Settings > Speech.
- **Speed** goes from 50% to 200% (100% is the old 200 words per minute) and **volume** from 10% to 100%. Both change **while it speaks**: drag the speed slider and every step is heard as you drag (within 16 ms), mid-sentence, with the same pitch. Behind the scenes the audio is time-stretched as it plays, 10 ms at a time, and once you let go the next sentences are prepared again at the new speed for the most natural sound.
- **Voice**: pick it in Settings > Speech or the mini bar's popover. Changing it while speaking continues from the word being read, in the new voice.
- **More voices**: Settings > Speech > **Get more voices** downloads natural-sounding Piper voices (see [ADD_VOICES_GUIDE.md](ADD_VOICES_GUIDE.md)). On Windows, the Windows 11 speech voices are listed next to the classic ones.
- **Output device**: pick where speech plays in Settings > Speech and press **Test** (Cancel puts back your saved choice). Every device from every audio system is listed; ones outside the default system show it in brackets, for example "(WASAPI)". The choice is remembered by device name, so it survives unplugging and reconnecting. A device plugged in after start shows up when Settings opens, or with **Refresh**.
- If the output device disappears while speaking, speech stops with a message instead of hanging.
- How it works: sentences are prepared a few seconds ahead of what you hear, so speech starts quickly and long documents never wait.
- A long pause releases the audio device after 10 seconds; Resume picks it up again.

## Listen (speech-to-text)

- Switch to **Listen** (`Ctrl+M`). A dictation panel appears under the editor with a record button, a live input waveform and the current model and microphone.
- Press record, speak, press again. The transcript is cleaned up (capital first letter, final punctuation) and added to the editor.
- When dictating into another app (the mini bar's mic or `Ctrl+Alt+D`), a **caption bubble** above the bar shows each word about half a second after you say it. A small, fast **instant preview** recognizer shows the words first (a little dimmer); Whisper checks them whenever you pause, or every couple of seconds while you keep talking, and corrects them in place. The newest word is highlighted. The bubble is only as big as the text (up to three lines, larger than the app's text) and grows upward, so the newest words stay right above the bar. **X** or `Esc` cancels the dictation; nothing is typed.
- Because Whisper checks at each pause, the text is usually ready when you stop: typed almost at once if you paused first, otherwise in about 0.5 to 1.2 seconds. Long dictations settle at real pauses in the audio as you go (never in the middle of a word), so the wait stays short however long you talk.
- The instant preview needs a 73 MB model, downloaded once in the background the first time you dictate (its progress shows in the status bar only; a pop-up appears only if it fails). It works for English; with another language the captions come from Whisper alone. While loaded it uses about 140 MB of memory, freed together with the Whisper model when that unloads. Turn it off in **Settings > Listen > Instant live preview**, and delete its model in the downloaded models list.
- Dictation keeps full speed while TTSPython is in the background: Windows 11 runs background apps in efficiency mode, which made each Whisper pass 2.6 times slower, so TTSPython opts out.
- If the microphone delivers only silence (muted, or blocked in Windows privacy settings), you are told so.
- **Settings > Listen**:
  - Microphone, with a live level meter so you can check it hears you, and **Refresh** for one plugged in later.
  - **Whisper model**: Tiny, Base, Small (default), Medium, Large v3, Large v3 Turbo, Distil Large v3. A model downloads the first time it is used; the download progress shows in the status bar, the Listen panel and next to the mini bar.
  - **Downloaded models** with their size and a **Delete** button (it asks first).
  - **Language**: English (default), Auto-detect, or one of 15 common languages.
  - **Unload the model after each dictation** or **Unload when idle** after 1 to 60 minutes.
  - How dictation reaches other apps (type at the cursor, or copy to the clipboard only) and the paste keys to use (Ctrl+V, or Shift+Insert for terminals).

## Mini mode

- A compact bar that floats above every window. It **never takes keyboard focus**, so the app you were typing in keeps its cursor.
- **Mic**: dictate into whatever app you are using. The text is typed at the cursor. Your clipboard is restored afterwards, and the dictated text is kept out of Windows clipboard history. If the paste fails, or the window runs as administrator (which ignores simulated typing), the text stays on the clipboard and you are told.
- **Play**: reads the text you have highlighted in the app you are using, or the clipboard when nothing is highlighted. Press again to stop.
- **Waveform**: shows your voice while dictating and the speech while reading.
- **Chevron or right-click**: a popover for voice, speed and volume, **Pause/Resume**, and Hide mini mode.
- **Mouse wheel** over the bar: volume up or down in 5% steps.
- **Expand**: back to the full window.
- Drag the bar by its grip or any empty area. It snaps to screen edges (Settings > Mini mode) and remembers where you left it.

## Global hotkeys

Toggle style: press once to start, again to stop.

| Action | Default |
|--------|---------|
| Start or stop dictation | `Ctrl+Alt+D` |
| Speak highlighted text or clipboard (again to stop) | `Ctrl+Alt+S` |
| Stop speaking | `Ctrl+Alt+X` |
| Show or hide mini mode | `Ctrl+Alt+Shift+M` |
| Pause or resume speech, Show main window | unassigned |

Change them in **Settings > Shortcuts**. If another program already owns a combination, the row says so, the status bar says so at start, and a pop-up tells you once (the first time that key is found taken). TTSPython tries again a few seconds after starting, in case the key was only busy for a moment. On Wayland, use the command-line options (`--toggle-dictation`, `--speak-clipboard`, `--stop`, `--pause`, `--mini`, `--show`) from a desktop keyboard shortcut instead.

## Speech queue

- **Add text** (the editor contents), **Add files** (several at once) and clipboard items (from the clipboard monitor).
- **Play queue** starts at the selected item (or the top). Double-click an item or press `Enter` to play from it. Items are separated by a half-second pause.
- **Right-click** an item: Play from here, Move to top, Copy to the editor (as a new untitled document, so Save cannot overwrite the file you had open), Remove.
- **Drop text files** on the queue to add them, even when it is empty.
- **Drag** items to reorder, or use the up and down arrows. The minus button (or Delete) removes an item; **Clear queue** removes them all (it asks first).
- **Loop** repeats the whole queue.
- Each row shows the item type, word count and listening time; the playing item is marked with an accent bar.
- The queue is kept when you quit and comes back the next time.
- Changing the queue while it plays is safe: removed items are skipped and moved items play in their new place.

## Clipboard monitor

In the status bar (or Settings > Clipboard):
- **Clipboard** switch turns it on. Text already on the clipboard when you turn it on is not used.
- **Speak** reads copied text right away; **Queue** adds it to the queue. This choice appears once the switch is on.
- **Auto-Queue**: while speech is playing, copied text is queued instead of ignored, and queued items play once after the current speech. When reading ends, the queue is read next, with the clipboard monitor on or off.
- Text shorter than 6 characters is ignored, and so is text TTSPython itself put on the clipboard.

## Export audio

- **Export audio** (`Ctrl+E`) saves the editor text, or only the selection if there is one, as **WAV** or **MP3** (128 kbps) with the current voice, speed and volume.
- It runs in the background with progress in the status bar and a Cancel button, and writes as it goes (a long book never sits in memory). Files are written to a temporary name first, so a cancelled or failed export never leaves a half-written file.
- The folder and format you used last are suggested next time; **Open folder** appears in the status bar when it is done.

## Find and replace

- `Ctrl+F` opens an inline bar above the text (only one, however many times you press it).
- **Match case** and **Regular expression** options, previous and next with wrap-around (Enter and Shift+Enter), and a match count ("3 matches", then "2 of 3").
- **Replace** replaces the current match; **Replace all** does every match in one step that `Ctrl+Z` undoes. In normal (non-regex) mode the replacement is used exactly as typed, including backslashes.

## Files

- **Open** reads UTF-8 (with or without BOM), UTF-16 and Windows-1252 text and remembers the file's encoding and line endings; **Save** writes them back the same way, so an unchanged file stays byte-for-byte identical. A file in an encoding TTSPython cannot read (such as GBK or Shift-JIS) can look wrong: you are told when it opens, and Save asks where to save, so the original stays as it is.
- **New** (`Ctrl+N`) starts an empty document. Drop a text file on the editor to open it (to read several, drop them on the queue). The Open button's arrow lists the last 8 files. Opening a file while the old one is being read stops the reading; the queue and clipboard keep playing.
- Opening a file, New, closing the window or quitting asks first if there are unsaved changes: **Save**, **Discard** or **Cancel** (Enter saves). Quitting also asks if an export or a dictation is still running.
- Unsaved text is kept every 30 seconds (and when Windows logs off or shuts down) and put back the next time TTSPython starts, even after a crash.

## Themes and appearance

- 12 themes in **Settings > Appearance**: Studio, Dark, Twilight, Light, High Contrast, Forest, New Vegas, Spiral, Poly, Sunset, Paper, Graphite. Clicking a theme previews it; **Save** keeps it, **Cancel** goes back.
- Every theme is checked for readable contrast on text, buttons and selections. High Contrast also uses thicker borders.
- **Performance Mode** halves waveform frame rates (30 to 15 per second) and turns off the animations of the status-bar switches.

## Settings

- Saved automatically to `%APPDATA%\TTSPython\settings.json` (Windows) or `~/.config/ttspython/settings.json` (Linux). Your TTSPython 4 settings are imported on first start and the old file is left alone.
- **Save** keeps the changes and closes; **Cancel** undoes them (theme, speed and volume previews included) and closes; closing the window with unsaved changes asks. **Reset to Defaults** puts the settings on these pages back to their defaults (Save to keep them). Speed and volume apply as you move them. `Ctrl+,` opens Settings.
- The pages fit any window size: on a narrow window the controls move under their labels instead of being cut off.
- The window size, position and layout, voice, speed, volume, queue options and mini bar position are remembered between sessions.
- **General > Closing the window keeps TTSPython running in the tray** (quit from the tray menu).
