# Adding Voices to TTSPython

TTSPython speaks with two kinds of voices:

- **Natural voices (Piper)**: neural voices that sound much closer to a person. They run offline on your
  computer, on Windows and Linux. You download the ones you want from inside the app.
- **System voices**: the voices your operating system already has. On **Windows** these are the SAPI5 voices
  and the Windows 10/11 speech voices (for example David, Zira and Mark). On **Linux** they come from **espeak-ng**.

Pick the voice in **Settings > Speech > Voice**, or in the mini bar's popover (chevron or right-click).

## Natural voices (Piper)

1. Open **Settings > Speech** and press **Get more voices**. Pick a language, and type in the filter box to narrow the list by name, country or quality.
2. Choose a **language**. Each voice is listed with its country, quality (smallest, small, medium or best) and download size.
3. Not sure which one? **Hear samples online** opens the official sample page, where you can listen to each voice.
4. Select a voice and press **Download** (or double-click it). Most voices are about 60 MB; the "best" ones about
   115 MB. The first voice also downloads the Piper program (about 23 MB).
5. Press **Use this voice**. It is used for speech and export right away, and it shows up in the voice lists.

Good English voices to start with: **Lessac** (United States, medium), **Amy** (United States, medium),
**Ryan** (United States, best), **Alan** and **Cori** (Great Britain).

Things to know:
- There are 178 voices in 53 languages. Each one is downloaded once; after that it works without internet.
- Downloads are checked against their published checksums. A broken or cancelled download leaves nothing behind.
- Speed works the same as with system voices (50% to 200%), and changes while it speaks.
- To remove a voice, select it in **Get more voices** and press **Remove** (switch to another voice first).
- Voices and the Piper program are stored in `%LOCALAPPDATA%\TTSPython` (Windows) or `~/.local/share/ttspython` (Linux).
- Piper is the official program from the [Piper project](https://github.com/rhasspy/piper) (MIT license, with
  espeak-ng under GPL-3.0). TTSPython downloads it and runs it as a separate program. Each voice has its own
  license, listed in its model card on [Hugging Face](https://huggingface.co/rhasspy/piper-voices); some are for
  non-commercial use only, so check before using one for a commercial project.
- Piper builds exist for Windows (64-bit), Linux on x86-64 and Linux on ARM64.

## Windows voices

Windows 10/11 comes with a few English voices (David, Zira and often Mark). TTSPython lists both the classic
SAPI5 voices and the newer Windows speech voices, so a voice Windows installed in only one of those places still
appears.

To add more:
1. In **Get more voices**, press **Open speech settings** (or open **Settings > Time & language >
   Speech** yourself).
2. Press **Add voices** and pick a language (for example English (United Kingdom) for Hazel and George).
3. Back in TTSPython, press **Refresh** next to the voice list in **Settings > Speech**. No restart needed.

Third-party SAPI5 voices (for example from CereProc or Acapela) also appear in the list once installed.

## Linux voices (espeak-ng)

TTSPython reads the voices espeak-ng provides. Install espeak-ng and its language data with your package
manager, then press **Refresh**:
```bash
sudo pacman -S espeak-ng        # Arch
sudo apt install espeak-ng      # Debian / Ubuntu
```
Piper voices (above) sound much more natural and work on Linux too.

## Check which voices are installed

```bash
python check_voices.py
```
lists the system voices TTSPython can use (the same engine as the app). Downloaded Piper voices are listed in
**Get more voices** as "Installed".

## Troubleshooting

**A new Windows voice does not appear**: press **Refresh** in Settings > Speech. Voices added through
Windows language packs can need a sign-out and sign-in before Windows reports them.

**A Piper download fails**: check the internet connection and try again. Downloads come from GitHub (the
program) and Hugging Face (the voices); a company firewall may block them.

**"Piper voices are not available for this computer's processor"**: Piper is available for 64-bit Windows and for Linux on x86-64
and ARM64. On other systems, use the system voices.

**A voice sounds robotic**: try a Piper voice in "medium" or "best" quality.
