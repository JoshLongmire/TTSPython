import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter import font as tkfont
import pyttsx3
import os
import json
import re
import time
import gc
import shutil
import tempfile
import wave
import sys
import warnings
from datetime import datetime

# Reduce noisy Hugging Face warnings for local/offline use.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
warnings.filterwarnings("ignore", message="You are sending unauthenticated requests to the HF Hub.*")

__version__ = "4.0.0"

try:
    import pythoncom as _pythoncom  # type: ignore[import-not-found]
except ImportError:
    _pythoncom = None


def _com_init_thread():
    """Initialize COM for a worker thread (Windows / pywin32). Returns True if CoUninitialize is needed."""
    if _pythoncom is None:
        return False
    try:
        _pythoncom.CoInitialize()
        return True
    except Exception:
        try:
            _pythoncom.CoInitializeEx(_pythoncom.COINIT_MULTITHREADED)
            return True
        except Exception:
            return False


def _com_deinit_thread(com_initialized):
    if not com_initialized or _pythoncom is None:
        return
    try:
        _pythoncom.CoUninitialize()
    except Exception:
        pass


# --- Color emoji rendering -------------------------------------------------
# Tk paints color-emoji fonts as monochrome outline glyphs on Windows, so we
# render emoji to color bitmaps with Pillow and place them as tk.PhotoImage.
# Any failure (Pillow missing, no usable font) returns None so callers fall
# back to text-only. The cache keeps PhotoImage objects alive — Tk blanks a
# widget when its image is garbage-collected.
def _find_emoji_font():
    """Return a path or family name for a color-emoji font, or None."""
    candidates = []
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    if sys.platform.startswith("win"):
        candidates.append(os.path.join(system_root, "Fonts", "seguiemj.ttf"))
    if os.environ.get("NOTO_COLOR_EMOJI"):
        candidates.append(os.environ["NOTO_COLOR_EMOJI"])
    candidates += [
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
        "/usr/share/fonts/opentype/noto/NotoColorEmoji.ttf",
        "/usr/share/fonts/noto/NotoColorEmoji.ttf",
        "/System/Library/Fonts/Apple Color Emoji.ttf",
        r"C:\Windows\Fonts\seguiemj.ttf",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    # Fall back to family names Pillow can resolve.
    for name in ("Segoe UI Emoji", "Noto Color Emoji", "Symbola"):
        try:
            from PIL import ImageFont
            ImageFont.truetype(name, 16)
            return name
        except Exception:
            pass
    return None


_EMOJI_IMAGES = {}
_EMOJI_FONT = None


def emoji_icon(char, size=16):
    """Render a single emoji as a color ``tk.PhotoImage`` (cached).

    Returns ``None`` if rendering is unavailable so callers can fall back to
    text-only labels.
    """
    global _EMOJI_FONT
    # Strip emoji variation selectors (U+FE0F emoji / U+FE0E text). On Segoe UI
    # Emoji these render a stray mark that shifts the glyph left/right and gets
    # clipped; the color glyph still renders without them.
    clean_char = char.replace("\ufe0f", "").replace("\ufe0e", "")
    cache_key = (clean_char, size, _EMOJI_FONT is not None)
    if cache_key in _EMOJI_IMAGES:
        return _EMOJI_IMAGES[cache_key]
    image = None
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageTk
        if _EMOJI_FONT is None:
            _EMOJI_FONT = _find_emoji_font()
        if _EMOJI_FONT is not None:
            # Render larger than the target so the glyph fits with margin, then
            # center it on the canvas. Emoji ink boxes are larger than the font
            # size and often drift off-center, so drawing at (0,0) clips them.
            # Crop to the actual ink and recenter before scaling down so glyphs
            # (e.g. ▶ ⏹ ⬆) are centered and not clipped.
            render = size * 3
            font = ImageFont.truetype(_EMOJI_FONT, int(render * 0.85))
            img = Image.new("RGBA", (render, render), (0, 0, 0, 0))
            ImageDraw.Draw(img).text(
                (render / 2, render / 2), clean_char, font=font,
                embedded_color=True, anchor="mm"
            )
            bbox = img.getbbox()
            if bbox:
                glyph = img.crop(bbox)
                img = Image.new("RGBA", (render, render), (0, 0, 0, 0))
                img.paste(glyph, ((render - glyph.width) // 2, (render - glyph.height) // 2), glyph)
            img = img.resize((size, size), Image.LANCZOS)
            image = ImageTk.PhotoImage(img)
    except Exception:
        image = None
    _EMOJI_IMAGES[cache_key] = image
    return image


# --- Color helpers (used by the theme/design system and the gradient header) ---
def _clamp_channel(value):
    return max(0, min(255, int(round(value))))


def _hex_to_rgb(color):
    color = str(color).lstrip("#")
    if len(color) == 3:
        color = "".join(ch * 2 for ch in color)
    try:
        return (int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16))
    except (ValueError, IndexError):
        return (30, 30, 30)


def _rgb_to_hex(rgb):
    return "#%02x%02x%02x" % (_clamp_channel(rgb[0]), _clamp_channel(rgb[1]), _clamp_channel(rgb[2]))


def _mix(color_a, color_b, t):
    """Linear blend from color_a (t=0) to color_b (t=1)."""
    t = max(0.0, min(1.0, t))
    ra, ga, ba = _hex_to_rgb(color_a)
    rb, gb, bb = _hex_to_rgb(color_b)
    return _rgb_to_hex((ra + (rb - ra) * t, ga + (gb - ga) * t, ba + (bb - ba) * t))


def _lighten(color, t=0.12):
    return _mix(color, "#ffffff", t)


def _darken(color, t=0.12):
    return _mix(color, "#000000", t)


def _relative_luminance(color):
    r, g, b = (c / 255.0 for c in _hex_to_rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _is_dark(color):
    return _relative_luminance(color) < 0.5


def _contrast_text(bg, light="#ffffff", dark="#111111"):
    return dark if _relative_luminance(bg) > 0.55 else light


def _normalize_theme(theme):
    """Return a theme dict with every design-system key present.

    Old/custom presets that only define the original 8 keys still load: any
    missing key is derived from the base colors so the UI stays cohesive.
    """
    t = dict(theme or {})
    bg = t.setdefault("bg", "#1e1e1e")
    dark = _is_dark(bg)
    bg_elev = t.setdefault("bg_elev", _lighten(bg, 0.06) if dark else _darken(bg, 0.03))
    text = t.setdefault("text", "#d4d4d4" if dark else "#111827")
    accent = t.setdefault("accent", "#3b82f6")
    t.setdefault("border", _lighten(bg, 0.22) if dark else _darken(bg, 0.16))
    t.setdefault("muted", _mix(text, bg, 0.4))
    t.setdefault("danger", "#f87171")
    t.setdefault("name", "Custom")

    # Gradient header
    t.setdefault("header", _mix(bg_elev, accent, 0.22 if dark else 0.14))
    t.setdefault("header2", _mix(bg, accent, 0.06))
    t.setdefault("header_text", _contrast_text(t["header"], _lighten(text, 0.2), _darken(text, 0.1)))

    # Buttons
    t.setdefault("button", _lighten(bg_elev, 0.05) if dark else _darken(bg_elev, 0.02))
    t.setdefault("button_text", text)
    t.setdefault("button_hover", _mix(t["button"], accent, 0.34))
    t.setdefault("button_active", accent)

    # Fields (entries, combos, text areas)
    t.setdefault("field", bg_elev)
    t.setdefault("field_text", text)
    t.setdefault("field_border", t["border"])

    # States and misc
    t.setdefault("disabled", _mix(bg_elev, bg, 0.5))
    t.setdefault("disabled_text", _mix(t["muted"], bg, 0.35))
    t.setdefault("on_accent", _contrast_text(accent))
    return t


THEME_PRESETS = {
    "dark": {
        "bg": "#1e1e1e", "bg_elev": "#252526", "border": "#3c3c3c", "text": "#d4d4d4",
        "muted": "#9d9d9d", "accent": "#3b82f6", "danger": "#f87171", "name": "Dark"
    },
    "twilight": {
        "bg": "#171a21", "bg_elev": "#1b2838", "border": "#2a475e", "text": "#c7d5e0",
        "muted": "#8f98a0", "accent": "#66c0f4", "danger": "#ff6b6b", "name": "Twilight"
    },
    "light": {
        "bg": "#f3f4f6", "bg_elev": "#ffffff", "border": "#d1d5db", "text": "#111827",
        "muted": "#4b5563", "accent": "#2563eb", "danger": "#dc2626", "name": "Light"
    },
    "contrast": {
        "bg": "#000000", "bg_elev": "#0a0a0a", "border": "#ffffff", "text": "#ffffff",
        "muted": "#e5e5e5", "accent": "#ffff00", "danger": "#ff4444", "name": "High Contrast"
    },
    "forest": {
        "bg": "#141c16", "bg_elev": "#1c281f", "border": "#2d4a32", "text": "#dce8de",
        "muted": "#7a9a80", "accent": "#4ade80", "danger": "#f87171", "name": "Forest"
    },
    "newvegas": {
        "bg": "#0a100c", "bg_elev": "#101a14", "border": "#1f4d32", "text": "#5dff9a",
        "muted": "#3a8f5c", "accent": "#8cffb4", "danger": "#ff7a45", "name": "New Vegas"
    },
    "spiral": {
        "bg": "#0a0a0a", "bg_elev": "#131814", "border": "#2a4528", "text": "#dceadd",
        "muted": "#6b8568", "accent": "#9fd12a", "danger": "#ff5533", "name": "Spiral"
    },
    "poly": {
        "bg": "#080a12", "bg_elev": "#0f1422", "border": "#2a3f62", "text": "#e6edf7",
        "muted": "#6b82a8", "accent": "#1f8fff", "danger": "#ff5c8a", "name": "Poly"
    },
    "sunset": {
        "bg": "#1c1418", "bg_elev": "#261c22", "border": "#4a3040", "text": "#f3e8ef",
        "muted": "#b8a0b0", "accent": "#fb923c", "danger": "#f87171", "name": "Sunset"
    },
    "paper": {
        "bg": "#f2efe8", "bg_elev": "#faf8f4", "border": "#d4cec3", "text": "#2c2824",
        "muted": "#6b6560", "accent": "#8b6914", "danger": "#b45309", "name": "Paper"
    },
    "graphite": {
        "bg": "#2a2d32", "bg_elev": "#34383e", "border": "#4a5058", "text": "#e8eaed",
        "muted": "#9aa0a8", "accent": "#7dd3fc", "danger": "#f87171", "name": "Graphite"
    },
}

# Fill in derived design-system keys so every preset is complete and cohesive.
THEME_PRESETS = {key: _normalize_theme(value) for key, value in THEME_PRESETS.items()}

DEFAULT_SETTINGS = {
    "theme_preset": "twilight",
    "clipboard_monitor": False,
    "clipboard_auto_queue": False,
    "clipboard_action": "speak",
    "performance_mode": True,
    "mode": "tts",
    "stt_engine": "faster-whisper",
    "stt_whisper_model": "small",
    "stt_input_device": "",
    "tts_output_device": "",
    "stt_unload_model_when_idle": False,
    "stt_auto_unload_enabled": True,
    "stt_auto_unload_minutes": 3,
}

class GradientHeader(tk.Canvas):
    """A canvas header that paints a horizontal gradient behind a title and,
    optionally, a small cluster of ttk controls docked to the right edge.

    The gradient is redrawn on ``<Configure>`` (resize) — no timers involved.
    """

    _title_font = None
    _subtitle_font = None

    @classmethod
    def _shared_fonts(cls):
        # Lazily create shared fonts once (requires a live Tk root) so opening
        # dialogs repeatedly does not accumulate new Font objects.
        if cls._title_font is None:
            cls._title_font = tkfont.Font(family="Segoe UI", size=15, weight="bold")
            cls._subtitle_font = tkfont.Font(family="Segoe UI", size=8)
        return cls._title_font, cls._subtitle_font

    def __init__(self, master, title="", subtitle="", height=60, **kwargs):
        super().__init__(master, height=height, highlightthickness=0, bd=0, **kwargs)
        self._title = title
        self._subtitle = subtitle
        self._c1 = "#2b2f3a"
        self._c2 = "#1f2330"
        self._title_color = "#ffffff"
        self._subtitle_color = "#c8c8c8"
        self._title_font, self._subtitle_font = self._shared_fonts()
        # A frame docked to the right for interactive controls (buttons, combos).
        self.controls = ttk.Frame(self, style="Header.TFrame")
        self._controls_item = self.create_window(0, 0, window=self.controls, anchor="e")
        self.bind("<Configure>", lambda _e: self.redraw())

    def apply_colors(self, c1, c2, title_color, subtitle_color):
        self._c1 = c1
        self._c2 = c2
        self._title_color = title_color
        self._subtitle_color = subtitle_color
        self.configure(bg=c1)
        self.redraw()

    def redraw(self):
        self.delete("grad")
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 1:
            return
        steps = 60
        for i in range(steps):
            t = i / (steps - 1)
            color = _mix(self._c1, self._c2, t)
            x0 = int(w * i / steps)
            x1 = int(w * (i + 1) / steps) + 1
            self.create_rectangle(x0, 0, x1, h, outline=color, fill=color, tags="grad")
        if self._title:
            ty = (h // 2 - 8) if self._subtitle else (h // 2)
            self.create_text(18, ty, text=self._title, anchor="w",
                             fill=self._title_color, font=self._title_font, tags="grad")
        if self._subtitle:
            self.create_text(19, h // 2 + 11, text=self._subtitle, anchor="w",
                             fill=self._subtitle_color, font=self._subtitle_font, tags="grad")
        # Keep the gradient/text under the docked control widgets.
        self.tag_lower("grad")
        self.coords(self._controls_item, w - 14, h // 2)


class ReaderApp:
    def __init__(self, root):
        self.root = root
        self.style = ttk.Style(root)
        self.root.title("TTSPython")
        self.speaking = False
        self.speak_thread = None
        self.current_engine = None
        self.stop_requested = False
        self.global_stop_requested = False  # Global stop flag for all TTS operations
        self.all_engines = []  # Track all active TTS engines
        self.current_file = None
        # Store settings in the script directory, not AppData
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.settings_file = os.path.join(script_dir, "tts_settings.json")
        self.theme_preset = DEFAULT_SETTINGS["theme_preset"]
        self.performance_mode = DEFAULT_SETTINGS["performance_mode"]
        self.clipboard_monitor_enabled = False
        self.last_clipboard = ""
        self.highlight_tag = "highlight"
        self.current_word_indices = []
        self.clipboard_auto_queue = False  # Auto-queue clipboard items when speaking
        self.clipboard_action_mode = 'speak'  # Default clipboard action mode (will be overridden by load_settings)
        self.current_mode = DEFAULT_SETTINGS["mode"]
        self.stt_engine = "faster-whisper"
        self.stt_whisper_model = DEFAULT_SETTINGS["stt_whisper_model"]
        self.stt_input_device = DEFAULT_SETTINGS["stt_input_device"]
        self.tts_output_device = DEFAULT_SETTINGS["tts_output_device"]
        self.stt_unload_model_when_idle = DEFAULT_SETTINGS["stt_unload_model_when_idle"]
        self.stt_auto_unload_enabled = DEFAULT_SETTINGS["stt_auto_unload_enabled"]
        self.stt_auto_unload_minutes = DEFAULT_SETTINGS["stt_auto_unload_minutes"]
        self.recording = False
        self.recording_sample_rate = 16000
        self.recording_stream = None
        self.recording_wav_path = None
        self.recording_wav_writer = None
        self.recording_frame_count = 0
        self.stt_idle_unload_timer_id = None
        self.stt_processing = False
        self.stt_backends = {}
        self.last_highlight_update = 0.0
        
        # Speech Queue System
        self.speech_queue = []
        self.queue_playing = False
        self.current_queue_index = -1
        
        # Load settings
        self.load_settings()
        
        # Initialize engine just to get default settings and voices
        try:
            temp_engine = pyttsx3.init()
            self.default_rate = temp_engine.getProperty("rate")
            self.default_volume = temp_engine.getProperty("volume")
            self.voices = temp_engine.getProperty("voices")
            temp_engine.stop()  # Clean up temp engine
        except Exception as e:
            # Fallback if engine initialization fails
            messagebox.showerror("TTS Engine Error", 
                               f"Failed to initialize TTS engine: {str(e)}\n\n"
                               f"The app may not work correctly.\n"
                               f"Please ensure pyttsx3 is installed properly.")
            self.default_rate = 150
            self.default_volume = 1.0
            self.voices = []

        # --- UI ---
        self.ui_font_family = "Segoe UI"
        self.base_font = tkfont.Font(family=self.ui_font_family, size=10)
        self.text_font = tkfont.Font(family=self.ui_font_family, size=11)

        # Theme option lookups (used by the header switcher and the Settings dialog).
        self.theme_options = [THEME_PRESETS[k]["name"] for k in THEME_PRESETS]
        self.theme_id_by_name = {THEME_PRESETS[k]["name"]: k for k in THEME_PRESETS}
        self.theme_name_var = tk.StringVar(
            value=THEME_PRESETS[self.theme_preset]["name"] if self.theme_preset in THEME_PRESETS else "Twilight"
        )

        # Gradient header bar: title/version on the left, quick controls on the right.
        self.header = GradientHeader(
            root,
            title=f"TTSPython {__version__}",
            subtitle="",
            height=60,
        )
        self.header.pack(fill="x", side="top")
        self.mode_var = tk.StringVar(value=self.current_mode)
        self.mode_toggle = ttk.Button(
            self.header.controls, text="Mode: TTS", command=self.toggle_mode, style="Header.TButton"
        )
        self.mode_toggle.pack(side="left")

        # Text editor area with scrollbar (wrapped so they align cleanly).
        text_frame = ttk.Frame(root)
        self.text_frame = text_frame
        text_frame.pack(fill="both", expand=True, padx=10, pady=(10, 6))
        self.txt = tk.Text(text_frame, wrap="word", height=16, undo=True, font=self.text_font)
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=self.txt.yview)
        scrollbar.pack(side="right", fill="y")
        self.txt.pack(side="left", fill="both", expand=True)
        self.txt.configure(yscrollcommand=scrollbar.set)

        # Configure highlight tag
        self.txt.tag_config(self.highlight_tag, background="yellow", foreground="black")

        controls = ttk.Frame(root)
        self.controls_frame = controls
        controls.pack(fill="x", padx=10, pady=(0,10))

        self.speak_btn = ttk.Button(controls, text="Speak All", image=emoji_icon("▶️"), compound=tk.LEFT, command=self.on_speak, style="Accent.TButton")
        self.speak_selected_btn = ttk.Button(controls, text="Speak Selected", image=emoji_icon("🗣️"), compound=tk.LEFT, command=self.on_speak_selected)
        self.stop_btn  = ttk.Button(controls, text="Stop", image=emoji_icon("⏹️"), compound=tk.LEFT, command=self.on_stop)
        paste_btn      = ttk.Button(controls, text="Paste", image=emoji_icon("📋"), compound=tk.LEFT, command=self.on_paste)
        clear_btn      = ttk.Button(controls, text="Clear", image=emoji_icon("🧹"), compound=tk.LEFT, command=self.on_clear)

        self.speak_btn.grid(row=0, column=0, padx=(0,6))
        self.speak_selected_btn.grid(row=0, column=1, padx=(0,6))
        self.stop_btn.grid(row=0, column=2, padx=(0,6))
        paste_btn.grid(row=0, column=3, padx=(0,6))
        clear_btn.grid(row=0, column=4, padx=(0,12))

        # Rate
        ttk.Label(controls, text="Rate").grid(row=0, column=6, padx=(16,4))
        self.rate = tk.IntVar(value=self.default_rate)
        self.rate_scale = ttk.Scale(controls, from_=100, to=250, orient="horizontal",
                                    command=self._on_rate_change)
        self.rate_scale.set(self.rate.get())
        self.rate_scale.grid(row=0, column=7, sticky="ew", padx=(0,8))

        # Volume
        ttk.Label(controls, text="Volume").grid(row=0, column=8, padx=(8,4))
        self.vol = tk.DoubleVar(value=self.default_volume)
        self.vol_scale = ttk.Scale(controls, from_=0.1, to=1.0, orient="horizontal",
                                   command=self._on_volume_change)
        self.vol_scale.set(self.vol.get())
        self.vol_scale.grid(row=0, column=9, sticky="ew", padx=(0,8))

        # Voice selector
        ttk.Label(controls, text="Voice").grid(row=0, column=10, padx=(8,4))
        self.voice_map = { (v.name or f"Voice {i}"): v.id for i, v in enumerate(self.voices) }
        self.voice_combo = ttk.Combobox(controls, values=list(self.voice_map.keys()), width=34, state="readonly")
        # Pick a default female/neutral if available
        if self.voice_map:
            default_name = next((n for n in self.voice_map if "female" in n.lower() or "zira" in n.lower()), list(self.voice_map.keys())[0])
            self.voice_combo.set(default_name)
            self.selected_voice = self.voice_map[default_name]  # Store selected voice
        else:
            self.voice_combo.set("No voices available")
            self.selected_voice = None
        self.voice_combo.bind("<<ComboboxSelected>>", self.on_voice_change)
        self.voice_combo.grid(row=0, column=11, padx=(0,4))
        
        # Refresh voices button
        refresh_voices_btn = ttk.Button(controls, text="🔄 Refresh", command=self.refresh_voices)
        refresh_voices_btn.grid(row=0, column=12, padx=(0,0))
        voices_settings_btn = ttk.Button(controls, text="🎙️ Voices", command=self.open_voice_settings)
        voices_settings_btn.grid(row=0, column=13, padx=(6,0))

        controls.columnconfigure(7, weight=1)
        controls.columnconfigure(9, weight=1)

        # File operations and additional features
        file_frame = ttk.Frame(root)
        self.file_frame = file_frame
        file_frame.pack(fill="x", padx=10, pady=(0,5))
        
        open_btn = ttk.Button(file_frame, text="Open", image=emoji_icon("📂"), compound=tk.LEFT, command=self.on_open)
        save_btn = ttk.Button(file_frame, text="Save", image=emoji_icon("💾"), compound=tk.LEFT, command=self.on_save)
        save_as_btn = ttk.Button(file_frame, text="Save As", image=emoji_icon("💾"), compound=tk.LEFT, command=self.on_save_as)
        self.export_audio_btn = ttk.Button(file_frame, text="Export Audio", image=emoji_icon("🎵"), compound=tk.LEFT, command=self.on_export_audio)
        search_btn = ttk.Button(file_frame, text="Find/Replace", image=emoji_icon("🔍"), compound=tk.LEFT, command=self.on_search)
        settings_btn = ttk.Button(file_frame, text="Settings", image=emoji_icon("⚙️"), compound=tk.LEFT, command=self.on_settings)
        
        open_btn.pack(side="left", padx=(0,6))
        save_btn.pack(side="left", padx=(0,6))
        save_as_btn.pack(side="left", padx=(0,6))
        self.export_audio_btn.pack(side="left", padx=(0,6))
        search_btn.pack(side="left", padx=(0,6))
        settings_btn.pack(side="left", padx=(0,6))
        
        # Clipboard monitor controls
        clipboard_frame = ttk.Frame(file_frame)
        self.clipboard_frame = clipboard_frame
        clipboard_frame.pack(side="right", padx=(6,0))
        
        self.clipboard_var = tk.BooleanVar(value=self.clipboard_monitor_enabled)
        clipboard_check = ttk.Checkbutton(clipboard_frame, text="Monitor Clipboard:", image=emoji_icon("📎"),
                                         compound=tk.LEFT,
                                          variable=self.clipboard_var, command=self.toggle_clipboard_monitor)
        clipboard_check.pack(side="left")
        
        # Clipboard action mode (speak or queue) - use loaded setting
        self.clipboard_action = tk.StringVar(value=self.clipboard_action_mode)
        clipboard_speak_radio = ttk.Radiobutton(clipboard_frame, text="Speak", 
                                               variable=self.clipboard_action, value="speak")
        clipboard_queue_radio = ttk.Radiobutton(clipboard_frame, text="Queue", 
                                               variable=self.clipboard_action, value="queue")
        clipboard_speak_radio.pack(side="left", padx=(5,0))
        clipboard_queue_radio.pack(side="left")
        
        # Auto-queue option for speak mode
        self.auto_queue_var = tk.BooleanVar(value=self.clipboard_auto_queue)
        auto_queue_check = ttk.Checkbutton(clipboard_frame, text="Auto-Queue", 
                                          variable=self.auto_queue_var, command=self.toggle_auto_queue)
        auto_queue_check.pack(side="left", padx=(10,0))
        self.performance_var = tk.BooleanVar(value=self.performance_mode)
        performance_check = ttk.Checkbutton(
            clipboard_frame,
            text="Performance Mode",
            variable=self.performance_var,
            command=self.toggle_performance_mode
        )
        performance_check.pack(side="left", padx=(10, 0))
        
        # Speech Queue Panel
        queue_frame = ttk.LabelFrame(root, text="Speech Queue", padding=5)
        self.queue_frame = queue_frame
        queue_frame.pack(fill="both", expand=False, padx=10, pady=(0,5))
        
        # Queue listbox with scrollbar
        queue_list_frame = ttk.Frame(queue_frame)
        self.queue_list_frame = queue_list_frame
        queue_list_frame.pack(side="left", fill="both", expand=True)
        
        queue_scrollbar = ttk.Scrollbar(queue_list_frame, orient="vertical")
        self.queue_tree = ttk.Treeview(
            queue_list_frame, height=4, selectmode="browse",
            columns=("name",), show="tree headings",
            yscrollcommand=queue_scrollbar.set,
        )
        self.queue_tree.heading("#0", text="")
        self.queue_tree.column("#0", width=24, stretch=False, anchor="center")
        self.queue_tree.heading("name", text="Speech Queue")
        self.queue_tree.column("name", stretch=True)
        queue_scrollbar.config(command=self.queue_tree.yview)
        queue_scrollbar.pack(side="right", fill="y")
        self.queue_tree.pack(side="left", fill="both", expand=True)
        self.queue_tree.bind("<Delete>", lambda _e: self.remove_from_queue())
        self.queue_tree.bind("<Double-1>", lambda _e: self.play_queue())

        # Speech-queue playback state
        self.queue_loop = tk.BooleanVar(value=False)
        
        # Queue control buttons
        queue_controls = ttk.Frame(queue_frame)
        self.queue_controls_frame = queue_controls
        queue_controls.pack(side="right", fill="y", padx=(5,0))
        
        ttk.Button(queue_controls, text="Add Current Text", image=emoji_icon("➕"), compound=tk.LEFT,
                  command=self.add_current_to_queue).pack(fill="x", pady=2)
        ttk.Button(queue_controls, text="Add File(s)", image=emoji_icon("📄"), compound=tk.LEFT,
                  command=self.add_files_to_queue).pack(fill="x", pady=2)
        ttk.Button(queue_controls, text="Play Queue", image=emoji_icon("▶️"), compound=tk.LEFT, style="Accent.TButton",
                  command=self.play_queue).pack(fill="x", pady=2)
        ttk.Button(queue_controls, text="Remove Selected", image=emoji_icon("➖"), compound=tk.LEFT,
                  command=self.remove_from_queue).pack(fill="x", pady=2)
        ttk.Button(queue_controls, text="Clear Queue", image=emoji_icon("🗑️"), compound=tk.LEFT,
                  command=self.clear_queue).pack(fill="x", pady=2)
        ttk.Button(queue_controls, text="Move Up", image=emoji_icon("⬆️"), compound=tk.LEFT,
                  command=self.move_queue_up).pack(fill="x", pady=2)
        ttk.Button(queue_controls, text="Move Down", image=emoji_icon("⬇️"), compound=tk.LEFT,
                  command=self.move_queue_down).pack(fill="x", pady=2)
        ttk.Checkbutton(queue_controls, text="Loop queue", variable=self.queue_loop).pack(fill="x", pady=(6, 2))
        
        # STT panel (minimal UI, shown only in STT mode)
        self.stt_frame = ttk.Frame(root)
        ttk.Label(self.stt_frame, text="STT: faster-whisper", style="Section.TLabel").pack(side="left", padx=(0, 8))
        self.stt_record_btn = ttk.Button(self.stt_frame, text="Start Recording", image=emoji_icon("⏺️"), compound=tk.LEFT, command=self.on_stt_record_toggle)
        self.stt_record_btn.pack(side="left", padx=(0, 8))
        self.stt_status = ttk.Label(self.stt_frame, text="Offline STT ready")
        self.stt_status.pack(side="left")

        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(root, textvariable=self.status_var, relief="sunken", anchor="w")
        status_bar.pack(side="bottom", fill="x")
        self.status_bar = status_bar

        # Apply theme
        self.apply_theme()
        self.refresh_mode_ui()
        
        # Bind keyboard shortcuts
        self.bind_shortcuts()
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        
        # Window geometry: restore last size/position, else center on screen.
        if getattr(self, "window_geometry", ""):
            try:
                self.root.geometry(self.window_geometry)
            except Exception:
                self._center_window()
        else:
            self._center_window()

        # Start clipboard monitoring if enabled
        if self.clipboard_monitor_enabled:
            # Prime baseline so current clipboard does not auto-trigger on startup.
            try:
                self.last_clipboard = self.root.clipboard_get()
            except Exception:
                self.last_clipboard = ""
            self.monitor_clipboard()

    def _center_window(self):
        """Center the window within the screen, preserving its size."""
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        if w < 2 or h < 2:
            w, h = 800, 600
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def load_settings(self):
        """Load settings from JSON file with corruption recovery."""
        loaded = {}
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
        except Exception as e:
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                broken_file = os.path.join(os.path.dirname(self.settings_file), f"tts_settings.broken.{timestamp}.json")
                if os.path.exists(self.settings_file):
                    shutil.copy2(self.settings_file, broken_file)
            except Exception:
                pass
            print(f"Failed to load settings. Using defaults: {e}")
            loaded = {}

        self.theme_preset = loaded.get("theme_preset", DEFAULT_SETTINGS["theme_preset"])
        if not isinstance(self.theme_preset, str) or self.theme_preset not in THEME_PRESETS:
            if loaded.get("dark_mode") is True:
                self.theme_preset = "dark"
            elif loaded.get("dark_mode") is False:
                self.theme_preset = "light"
            else:
                self.theme_preset = DEFAULT_SETTINGS["theme_preset"]

        self.clipboard_monitor_enabled = bool(loaded.get("clipboard_monitor", DEFAULT_SETTINGS["clipboard_monitor"]))
        self.clipboard_auto_queue = bool(loaded.get("clipboard_auto_queue", DEFAULT_SETTINGS["clipboard_auto_queue"]))
        self.clipboard_action_mode = loaded.get("clipboard_action", DEFAULT_SETTINGS["clipboard_action"])
        if self.clipboard_action_mode not in ("speak", "queue"):
            self.clipboard_action_mode = "speak"
        self.performance_mode = bool(loaded.get("performance_mode", DEFAULT_SETTINGS["performance_mode"]))
        self.current_mode = loaded.get("mode", DEFAULT_SETTINGS["mode"])
        if self.current_mode not in ("tts", "stt"):
            self.current_mode = "tts"
        self.stt_engine = "faster-whisper"
        self.stt_whisper_model = loaded.get("stt_whisper_model", DEFAULT_SETTINGS["stt_whisper_model"])
        self.stt_input_device = loaded.get("stt_input_device", DEFAULT_SETTINGS["stt_input_device"])
        self.tts_output_device = loaded.get("tts_output_device", DEFAULT_SETTINGS["tts_output_device"])
        self.stt_unload_model_when_idle = bool(
            loaded.get("stt_unload_model_when_idle", DEFAULT_SETTINGS["stt_unload_model_when_idle"])
        )
        self.stt_auto_unload_enabled = bool(
            loaded.get("stt_auto_unload_enabled", DEFAULT_SETTINGS["stt_auto_unload_enabled"])
        )
        loaded_minutes = loaded.get("stt_auto_unload_minutes", DEFAULT_SETTINGS["stt_auto_unload_minutes"])
        try:
            self.stt_auto_unload_minutes = max(1, min(60, int(loaded_minutes)))
        except (TypeError, ValueError):
            self.stt_auto_unload_minutes = DEFAULT_SETTINGS["stt_auto_unload_minutes"]
        self.hotkeys = loaded.get("hotkeys", self.get_default_hotkeys())
        self.window_geometry = loaded.get("geometry", "")
    
    def save_settings(self):
        """Save settings to JSON file"""
        # Capture current window geometry so we can restore it next launch.
        try:
            self.window_geometry = self.root.geometry()
        except Exception:
            pass
        try:
            settings = {
                'theme_preset': self.theme_preset,
                'clipboard_monitor': self.clipboard_monitor_enabled,
                'clipboard_auto_queue': self.clipboard_auto_queue,
                'clipboard_action': self.clipboard_action.get() if hasattr(self, 'clipboard_action') else 'speak',
                'performance_mode': self.performance_mode,
                'mode': self.current_mode,
                'stt_engine': "faster-whisper",
                'stt_whisper_model': self.stt_whisper_model,
                'stt_input_device': self.stt_input_device,
                'tts_output_device': self.tts_output_device,
                'stt_unload_model_when_idle': self.stt_unload_model_when_idle,
                'stt_auto_unload_enabled': self.stt_auto_unload_enabled,
                'stt_auto_unload_minutes': self.stt_auto_unload_minutes,
                'hotkeys': self.hotkeys,
                'geometry': self.window_geometry
            }
            # Write atomically to avoid partial/corrupt JSON on interruption.
            temp_settings_file = self.settings_file + ".tmp"
            with open(temp_settings_file, 'w', encoding="utf-8") as f:
                json.dump(settings, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            self._atomic_replace(temp_settings_file, self.settings_file)
        except Exception as e:
            print(f"Failed to save settings: {e}")

    def _atomic_replace(self, src, dst):
        """Replace dst with src, tolerating Windows lock/read-only issues.

        On Windows, ``os.replace`` fails with WinError 5 when the destination
        is held open by another process (e.g. an editor) or marked read-only.
        We clear the read-only bit and retry, then fall back to a non-atomic
        copy so settings still persist.
        """
        try:
            os.replace(src, dst)
            return
        except OSError:
            pass
        # Clear read-only attribute and retry the rename.
        try:
            os.chmod(dst, 0o666)
        except OSError:
            pass
        try:
            os.replace(src, dst)
            return
        except OSError:
            pass
        # Destination may be open (locked): overwrite its contents directly.
        try:
            shutil.copyfile(src, dst)
        except OSError as e:
            print(f"Failed to save settings (fallback): {e}")
        finally:
            try:
                os.remove(src)
            except OSError:
                pass
    
    def get_default_hotkeys(self):
        """Return default hotkey mappings"""
        return {
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
    
    def bind_shortcuts(self):
        """Bind keyboard shortcuts"""
        # Unbind all existing shortcuts first
        for action, key in self.hotkeys.items():
            try:
                self.root.unbind(key)
            except tk.TclError:
                pass
        
        # Bind shortcuts
        self.root.bind(self.hotkeys['speak_all'], lambda e: self.on_speak())
        self.root.bind(self.hotkeys['speak_selected'], lambda e: self.on_speak_selected())
        self.root.bind(self.hotkeys['stop'], lambda e: self.on_stop())
        self.root.bind(self.hotkeys['open'], lambda e: self.on_open())
        self.root.bind(self.hotkeys['save'], lambda e: self.on_save())
        self.root.bind(self.hotkeys['save_as'], lambda e: self.on_save_as())
        self.root.bind(self.hotkeys['paste'], lambda e: self.on_paste())
        self.root.bind(self.hotkeys['clear'], lambda e: self.on_clear())
        self.root.bind(self.hotkeys['find'], lambda e: self.on_search())
        self.root.bind(self.hotkeys['export'], lambda e: self.on_export_audio())

    def toggle_mode(self):
        if self.current_mode == "stt" and self.stt_unload_model_when_idle:
            self._release_stt_model()
        elif self.current_mode == "stt":
            self._schedule_stt_idle_unload()
        self.current_mode = "stt" if self.current_mode == "tts" else "tts"
        self.refresh_mode_ui()
        self.save_settings()

    def refresh_mode_ui(self):
        if self.current_mode == "stt":
            self.mode_toggle.configure(text="Mode: STT")
            self.stt_frame.pack(fill="x", padx=10, pady=(0, 5))
            self.speak_btn.state(["disabled"])
            self.speak_selected_btn.state(["disabled"])
            self.status_var.set("STT mode ready (offline)")
        else:
            if self.recording:
                self.stop_stt_recording()
            self.mode_toggle.configure(text="Mode: TTS")
            self.stt_frame.pack_forget()
            self.speak_btn.state(["!disabled"])
            self.speak_selected_btn.state(["!disabled"])
            self.status_var.set("TTS mode ready")

    def get_audio_devices(self):
        """Return available input/output audio devices for settings UI."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
        except Exception:
            return {"inputs": [], "outputs": []}

        inputs = []
        outputs = []
        for idx, dev in enumerate(devices):
            name = dev.get("name", f"Device {idx}")
            if dev.get("max_input_channels", 0) > 0:
                inputs.append((str(idx), f"{idx}: {name}"))
            if dev.get("max_output_channels", 0) > 0:
                outputs.append((str(idx), f"{idx}: {name}"))
        return {"inputs": inputs, "outputs": outputs}

    def on_stt_record_toggle(self):
        if self.current_mode != "stt":
            messagebox.showinfo("Mode", "Switch to STT mode first.")
            return
        if self.stt_processing:
            self.stt_status.configure(text="Still processing previous transcription...")
            return
        if self.recording:
            self.stop_stt_recording()
        else:
            self.start_stt_recording()

    def start_stt_recording(self):
        try:
            import sounddevice as sd
        except Exception as exc:
            messagebox.showerror("STT dependency missing", f"Please install STT dependencies.\n\n{exc}")
            return

        temp_fd, wav_path = tempfile.mkstemp(prefix="stt_recording_", suffix=".wav")
        os.close(temp_fd)
        wav_writer = None
        try:
            wav_writer = wave.open(wav_path, "wb")
            wav_writer.setnchannels(1)
            wav_writer.setsampwidth(2)
            wav_writer.setframerate(self.recording_sample_rate)
        except Exception:
            if wav_writer:
                wav_writer.close()
            if os.path.exists(wav_path):
                os.remove(wav_path)
            messagebox.showerror("STT Error", "Could not prepare recording file.")
            return

        self.recording_wav_path = wav_path
        self.recording_wav_writer = wav_writer
        self.recording_frame_count = 0
        self._cancel_stt_idle_unload()
        self.recording = True
        self.stt_record_btn.configure(text="Stop Recording", image=emoji_icon("⏹️"))
        self.stt_status.configure(text="Recording... (faster-whisper)")

        selected_input = self.stt_input_device.strip()
        device_arg = None
        if selected_input:
            try:
                device_arg = int(selected_input)
            except ValueError:
                device_arg = selected_input

        def _audio_callback(indata, frames, callback_time, status):
            writer = self.recording_wav_writer
            if writer:
                writer.writeframes(indata.tobytes())
                self.recording_frame_count += frames

        try:
            self.recording_stream = sd.InputStream(
                samplerate=self.recording_sample_rate,
                channels=1,
                dtype="int16",
                device=device_arg,
                callback=_audio_callback
            )
            self.recording_stream.start()
        except Exception as exc:
            self.recording = False
            if self.recording_wav_writer:
                self.recording_wav_writer.close()
            self.recording_wav_writer = None
            if self.recording_wav_path and os.path.exists(self.recording_wav_path):
                os.remove(self.recording_wav_path)
            self.recording_wav_path = None
            self.recording_frame_count = 0
            self.stt_record_btn.configure(text="Start Recording", image=emoji_icon("⏺️"))
            self.stt_status.configure(text="STT recording failed")
            messagebox.showerror("STT Error", f"Could not start recording:\n{exc}")

    def stop_stt_recording(self):
        if not self.recording:
            return
        self.recording = False
        self.stt_processing = True
        self.stt_record_btn.configure(text="⏺️ Start Recording")
        self.stt_status.configure(text="Processing transcription...")
        stream = self.recording_stream
        self.recording_stream = None
        if stream:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        writer = self.recording_wav_writer
        self.recording_wav_writer = None
        if writer:
            try:
                writer.close()
            except Exception:
                pass
        threading.Thread(target=self._transcribe_recorded_audio_worker, daemon=True).start()

    def _transcribe_recorded_audio_worker(self):
        wav_path = self.recording_wav_path
        self.recording_wav_path = None
        frame_count = self.recording_frame_count
        self.recording_frame_count = 0

        if not wav_path or frame_count <= 0:
            self.root.after(0, lambda: self.stt_status.configure(text="No audio captured"))
            self.root.after(0, self._finish_stt_run)
            return

        try:
            text = self._transcribe_with_whisper(wav_path)
            self.root.after(0, lambda t=text: self._insert_transcript(t))
        except Exception as exc:
            msg = str(exc)
            self.root.after(0, lambda m=msg: messagebox.showerror("STT Error", f"Failed to transcribe: {m}"))
            self.root.after(0, lambda: self.stt_status.configure(text="Transcription failed"))
        finally:
            if wav_path and os.path.exists(wav_path):
                try:
                    os.remove(wav_path)
                except Exception:
                    pass
            self.root.after(0, self._finish_stt_run)

    def _transcribe_with_whisper(self, wav_path):
        if "whisper_model" not in self.stt_backends:
            from faster_whisper import WhisperModel
            cpu_threads = os.cpu_count() or 4
            model = WhisperModel(
                self.stt_whisper_model,
                device="cpu",
                compute_type="int8",
                cpu_threads=cpu_threads
            )
            self.stt_backends["whisper_model"] = model
        segments, _ = self.stt_backends["whisper_model"].transcribe(
            wav_path,
            beam_size=1,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=True,
            vad_filter=True,
            initial_prompt="Use normal capitalization and punctuation."
        )
        return " ".join((seg.text or "").strip() for seg in segments).strip()

    def _insert_transcript(self, text):
        text = self._normalize_transcript_text(text)
        if not text:
            self.stt_status.configure(text="No speech detected")
            return
        self.txt.insert("end", text + "\n")
        self.txt.see("end")
        self.stt_status.configure(text="Transcription complete")
        self.status_var.set("Transcript inserted")

    def _normalize_transcript_text(self, text):
        """Light-touch punctuation cleanup without changing word content."""
        cleaned = " ".join((text or "").split()).strip()
        if not cleaned:
            return ""

        # Capitalize the first alphabetical character.
        for idx, ch in enumerate(cleaned):
            if ch.isalpha():
                cleaned = cleaned[:idx] + ch.upper() + cleaned[idx + 1:]
                break

        # Add sentence-ending punctuation only if missing.
        if cleaned[-1] not in ".!?":
            cleaned += "."

        return cleaned

    def _finish_stt_run(self):
        self.recording = False
        self.stt_processing = False
        self.stt_record_btn.configure(text="⏺️ Start Recording")
        if self.stt_unload_model_when_idle:
            self._release_stt_model()
        else:
            self._schedule_stt_idle_unload()
        if self.current_mode == "stt":
            if not self.stt_status.cget("text").strip():
                self.stt_status.configure(text="Offline STT ready")

    def _release_stt_model(self):
        self._cancel_stt_idle_unload()
        model = self.stt_backends.pop("whisper_model", None)
        if model is not None:
            del model
            gc.collect()

    def _cancel_stt_idle_unload(self):
        timer_id = self.stt_idle_unload_timer_id
        self.stt_idle_unload_timer_id = None
        if timer_id:
            try:
                self.root.after_cancel(timer_id)
            except tk.TclError:
                pass

    def _schedule_stt_idle_unload(self):
        self._cancel_stt_idle_unload()
        if not self.stt_auto_unload_enabled:
            return
        if self.recording or self.stt_processing:
            return
        delay_ms = max(1, int(self.stt_auto_unload_minutes)) * 60 * 1000
        self.stt_idle_unload_timer_id = self.root.after(delay_ms, self._on_stt_idle_timeout)

    def _on_stt_idle_timeout(self):
        self.stt_idle_unload_timer_id = None
        if self.recording or self.stt_processing:
            self._schedule_stt_idle_unload()
            return
        self._release_stt_model()
    
    def apply_theme(self):
        """Apply the selected theme preset as a full ttk design system."""
        theme = _normalize_theme(THEME_PRESETS.get(self.theme_preset, THEME_PRESETS["twilight"]))
        self._active_theme = theme
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass

        bg = theme["bg"]
        bg_elev = theme["bg_elev"]
        border = theme["border"]
        text = theme["text"]
        muted = theme["muted"]
        accent = theme["accent"]
        field = theme["field"]
        field_text = theme["field_text"]
        field_border = theme["field_border"]
        button = theme["button"]
        button_text = theme["button_text"]
        button_hover = theme["button_hover"]
        button_active = theme["button_active"]
        on_accent = theme["on_accent"]
        disabled = theme["disabled"]
        disabled_text = theme["disabled_text"]
        header = theme["header"]
        header_text = theme["header_text"]
        header_btn = _lighten(header, 0.10) if _is_dark(header) else _darken(header, 0.07)

        s = self.style
        # ttk styling is guarded so an unexpected platform quirk can't abort theming.
        try:
            s.configure(
                ".",
                background=bg, foreground=text, fieldbackground=field,
                bordercolor=border, troughcolor=field, focuscolor=accent,
                lightcolor=bg_elev, darkcolor=bg
            )
            s.configure("TFrame", background=bg)
            s.configure("TLabel", background=bg, foreground=text)
            s.configure("Muted.TLabel", background=bg, foreground=muted)
            s.configure("Section.TLabel", background=bg, foreground=muted,
                        font=(self.ui_font_family, 9, "bold"))
            s.configure("Status.TLabel", background=bg_elev, foreground=muted, padding=(8, 3))
            s.configure("TLabelframe", background=bg, foreground=text,
                        bordercolor=border, relief="solid", borderwidth=1)
            s.configure("TLabelframe.Label", background=bg, foreground=accent,
                        font=(self.ui_font_family, 9, "bold"))

            # Buttons (fake soft rounding via padding + flat relief).
            s.configure("TButton", background=button, foreground=button_text,
                        bordercolor=border, relief="flat", borderwidth=1,
                        padding=(11, 6), anchor="center")
            s.map(
                "TButton",
                background=[("disabled", disabled), ("pressed", button_active), ("active", button_hover)],
                foreground=[("disabled", disabled_text), ("pressed", on_accent), ("active", button_text)],
                bordercolor=[("active", accent), ("focus", accent)]
            )

            # Primary / accent button.
            s.configure("Accent.TButton", background=accent, foreground=on_accent,
                        bordercolor=accent, relief="flat", borderwidth=1, padding=(13, 6))
            s.map(
                "Accent.TButton",
                background=[("disabled", disabled), ("pressed", _darken(accent, 0.16)), ("active", _lighten(accent, 0.08))],
                foreground=[("disabled", disabled_text)],
                bordercolor=[("active", accent)]
            )

            # Header widgets (sit on the gradient canvas).
            s.configure("Header.TFrame", background=header)
            s.configure("Header.TLabel", background=header, foreground=header_text)
            s.configure("Header.TButton", background=header_btn, foreground=header_text,
                        bordercolor=header_btn, focuscolor=header_btn, lightcolor=header_btn,
                        darkcolor=header_btn, relief="flat", borderwidth=1, padding=(11, 5))
            s.map(
                "Header.TButton",
                background=[("pressed", accent), ("active", _mix(header_btn, accent, 0.5))],
                foreground=[("pressed", on_accent), ("active", header_text)],
                bordercolor=[("active", header_btn), ("focus", header_btn), ("pressed", accent)]
            )
            s.configure("Header.TCombobox", fieldbackground=header_btn, background=header_btn,
                        foreground=header_text, arrowcolor=header_text, bordercolor=header_btn,
                        focuscolor=header_btn, lightcolor=header_btn, darkcolor=header_btn)
            s.map(
                "Header.TCombobox",
                fieldbackground=[("readonly", header_btn)],
                foreground=[("readonly", header_text)],
                arrowcolor=[("active", accent)],
                bordercolor=[("focus", header_btn), ("active", header_btn), ("readonly", header_btn)]
            )

            s.configure("TCheckbutton", background=bg, foreground=text, focuscolor=accent)
            s.map(
                "TCheckbutton",
                background=[("active", bg)],
                foreground=[("disabled", disabled_text), ("active", accent)],
                indicatorcolor=[("selected", accent), ("!selected", field)]
            )
            s.configure("TRadiobutton", background=bg, foreground=text, focuscolor=accent)
            s.map(
                "TRadiobutton",
                background=[("active", bg)],
                foreground=[("disabled", disabled_text), ("active", accent)],
                indicatorcolor=[("selected", accent), ("!selected", field)]
            )

            s.configure("TEntry", fieldbackground=field, foreground=field_text,
                        bordercolor=field_border, insertcolor=field_text,
                        borderwidth=1, padding=4)
            s.map("TEntry", bordercolor=[("focus", accent)], lightcolor=[("focus", accent)])

            s.configure("TSpinbox", fieldbackground=field, foreground=field_text,
                        bordercolor=field_border, arrowcolor=text, borderwidth=1, padding=3)
            s.map("TSpinbox", bordercolor=[("focus", accent)])

            s.configure("TCombobox", fieldbackground=field, background=field, foreground=field_text,
                        bordercolor=field_border, arrowcolor=text, borderwidth=1, padding=3)
            s.map(
                "TCombobox",
                fieldbackground=[("readonly", field)],
                foreground=[("readonly", field_text)],
                bordercolor=[("focus", accent)],
                arrowcolor=[("active", accent)]
            )

            s.configure("Horizontal.TScale", background=bg, troughcolor=field, borderwidth=0)
            s.map("Horizontal.TScale", background=[("active", bg)])

            for orient in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
                s.configure(orient, background=bg_elev, troughcolor=bg,
                            bordercolor=bg, arrowcolor=muted, borderwidth=0)
                s.map(orient, background=[("active", accent), ("pressed", accent)])

            s.configure("TNotebook", background=bg, borderwidth=0)
            s.configure("TNotebook.Tab", background=bg_elev, foreground=muted,
                        padding=[14, 6], borderwidth=0)
            s.map(
                "TNotebook.Tab",
                background=[("selected", accent), ("active", button_hover)],
                foreground=[("selected", on_accent), ("active", text)]
            )
        except tk.TclError:
            pass

        # tk (non-ttk) widgets and root.
        self.root.configure(bg=bg)
        self.txt.configure(
            bg=field, fg=field_text, insertbackground=field_text,
            selectbackground=accent, selectforeground=on_accent,
            relief="flat", borderwidth=0, padx=8, pady=6,
            highlightthickness=1, highlightbackground=border, highlightcolor=accent
        )
        try:
            self.style.configure("Queue.Treeview", background=field, foreground=field_text,
                                 fieldbackground=field, borderwidth=0, relief="flat", rowheight=22)
            self.style.map("Queue.Treeview",
                           background=[("selected", accent)],
                           foreground=[("selected", on_accent)])
            self.queue_tree.configure(style="Queue.Treeview")
        except tk.TclError:
            pass
        try:
            self.queue_tree.tag_configure("now_playing", background=accent, foreground=on_accent)
        except tk.TclError:
            pass
        self.txt.tag_config(self.highlight_tag, background=accent, foreground=on_accent)

        if hasattr(self, "status_bar"):
            try:
                self.status_bar.configure(style="Status.TLabel")
            except tk.TclError:
                pass

        if hasattr(self, "header"):
            self.header.apply_colors(
                header, theme["header2"], header_text,
                _mix(header_text, header, 0.35)
            )

        # Tk-level options for menus/dialog text so theme shifts feel complete.
        self.root.option_add("*Text.background", field)
        self.root.option_add("*Text.foreground", field_text)
        self.root.option_add("*Text.insertBackground", field_text)
        self.root.option_add("*Menu.background", bg_elev)
        self.root.option_add("*Menu.foreground", text)
        self.root.option_add("*Menu.activeBackground", accent)
        self.root.option_add("*Menu.activeForeground", on_accent)

    def on_theme_selected(self, _=None):
        picked = self.theme_name_var.get()
        self.theme_preset = self.theme_id_by_name.get(picked, "twilight")
        self.apply_theme()
        self.save_settings()
        self.status_var.set(f"Theme set: {picked}")

    def toggle_clipboard_monitor(self):
        """Toggle clipboard monitoring"""
        self.clipboard_monitor_enabled = self.clipboard_var.get()
        self.save_settings()
        if self.clipboard_monitor_enabled:
            # Prime baseline when enabling so existing clipboard text is not auto-processed.
            try:
                self.last_clipboard = self.root.clipboard_get()
            except Exception:
                self.last_clipboard = ""
            self.monitor_clipboard()
            self.status_var.set("Clipboard monitoring enabled")
        else:
            self.status_var.set("Clipboard monitoring disabled")
    
    def toggle_auto_queue(self):
        """Toggle auto-queue for clipboard speak mode"""
        self.clipboard_auto_queue = self.auto_queue_var.get()
        self.save_settings()
        if self.clipboard_auto_queue:
            self.status_var.set("Auto-queue enabled - clipboard items will queue when speaking")
        else:
            self.status_var.set("Auto-queue disabled - clipboard items only speak when idle")

    def toggle_performance_mode(self):
        self.performance_mode = self.performance_var.get()
        self.save_settings()
        self.status_var.set("Performance mode enabled" if self.performance_mode else "Performance mode disabled")
    
    def monitor_clipboard(self):
        """Monitor clipboard for changes and auto-speak or queue"""
        if not self.clipboard_monitor_enabled:
            return
        
        try:
            current_clipboard = self.root.clipboard_get()
            if current_clipboard != self.last_clipboard and current_clipboard.strip():
                self.last_clipboard = current_clipboard
                
                # Check if clipboard content is long enough
                if len(current_clipboard.strip()) > 5:
                    action = self.clipboard_action.get()
                    
                    if action == "speak":
                        # Auto-speak mode with auto-queue option
                        if not self.speaking and not self.queue_playing and not self.global_stop_requested:
                            # Not currently speaking - speak immediately
                            self.status_var.set("Auto-speaking clipboard content...")
                            threading.Thread(target=self._speak_worker, args=(current_clipboard,), daemon=True).start()
                        elif self.clipboard_auto_queue and not self.global_stop_requested:
                            # Currently speaking but auto-queue is enabled - add to queue
                            preview = current_clipboard[:50] + "..." if len(current_clipboard) > 50 else current_clipboard
                            self.speech_queue.append({'text': current_clipboard, 'name': f"Auto-Queued: {preview}", 'icon': '📋'})
                            self.update_queue_display()
                            self.status_var.set(f"Auto-queued clipboard content ({len(self.speech_queue)} items)")
                            
                            # Don't start queue automatically - let the current speech finish first
                            # The queue will be played after the current speech completes
                        else:
                            # Currently speaking and auto-queue is disabled - ignore clipboard change
                            # This prevents the "run loop already started" error
                            self.status_var.set("Clipboard ignored - already speaking (enable Auto-Queue to queue content)")
                    
                    elif action == "queue":
                        # Queue mode - add to speech queue
                        preview = current_clipboard[:50] + "..." if len(current_clipboard) > 50 else current_clipboard
                        self.speech_queue.append({'text': current_clipboard, 'name': f"Clipboard: {preview}", 'icon': '📋'})
                        self.update_queue_display()
                        self.status_var.set(f"Clipboard added to queue ({len(self.speech_queue)} items)")
        except (tk.TclError, UnicodeDecodeError):
            pass
        except Exception:
            # Non-text clipboard or transient failures; keep polling.
            pass
        
        # Use longer polling in performance mode to lower idle CPU
        poll_ms = 2000 if self.performance_mode else 1000
        if self.clipboard_monitor_enabled:
            self.root.after(poll_ms, self.monitor_clipboard)
    
    def add_current_to_queue(self):
        """Add current text to speech queue"""
        text = self.txt.get("1.0", "end").strip()
        if not text:
            messagebox.showinfo("Queue", "No text to add to queue.")
            return
        
        # Add to queue with a preview (first 50 chars)
        preview = text[:50] + "..." if len(text) > 50 else text
        self.speech_queue.append({'text': text, 'name': f"Text: {preview}", 'icon': '💬'})
        self.update_queue_display()
        self.status_var.set(f"Added to queue ({len(self.speech_queue)} items)")
    
    def add_files_to_queue(self):
        """Add multiple files to speech queue"""
        file_paths = filedialog.askopenfilenames(
            title="Add Files to Queue",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        
        if file_paths:
            for file_path in file_paths:
                try:
                    content = self._read_text_file(file_path).strip()
                    if content:
                        filename = os.path.basename(file_path)
                        self.speech_queue.append({'text': content, 'name': filename, 'icon': '📄'})
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to load {file_path}: {str(e)}")
            
            self.update_queue_display()
            self.status_var.set(f"Added {len(file_paths)} file(s) to queue ({len(self.speech_queue)} items)")
    
    def move_queue_up(self):
        """Move the selected queue item up one position."""
        selection = self.queue_tree.selection()
        if not selection:
            messagebox.showinfo("Queue", "Please select an item to move.")
            return
        index = int(selection[0])
        if index <= 0:
            return
        self.speech_queue[index - 1], self.speech_queue[index] = \
            self.speech_queue[index], self.speech_queue[index - 1]
        if self.current_queue_index in (index, index - 1):
            self.current_queue_index = index - 1 if self.current_queue_index == index else index
        self.update_queue_display()
        self.queue_tree.selection_set(str(index - 1))
    
    def move_queue_down(self):
        """Move the selected queue item down one position."""
        selection = self.queue_tree.selection()
        if not selection:
            messagebox.showinfo("Queue", "Please select an item to move.")
            return
        index = int(selection[0])
        if index >= len(self.speech_queue) - 1:
            return
        self.speech_queue[index + 1], self.speech_queue[index] = \
            self.speech_queue[index], self.speech_queue[index + 1]
        if self.current_queue_index in (index, index + 1):
            self.current_queue_index = index + 1 if self.current_queue_index == index else index
        self.update_queue_display()
        self.queue_tree.selection_set(str(index + 1))
    
    def remove_from_queue(self):
        """Remove selected item from queue"""
        selection = self.queue_tree.selection()
        if not selection:
            messagebox.showinfo("Queue", "Please select an item to remove.")
            return
        
        index = int(selection[0])
        del self.speech_queue[index]
        if self.current_queue_index == index:
            self.current_queue_index = -1
        elif self.current_queue_index > index:
            self.current_queue_index -= 1
        self.update_queue_display()
        self.status_var.set(f"Removed from queue ({len(self.speech_queue)} items)")
    
    def clear_queue(self):
        """Clear all items from queue"""
        if not self.speech_queue:
            return
        
        if messagebox.askyesno("Clear Queue", f"Remove all {len(self.speech_queue)} items from queue?"):
            self.speech_queue.clear()
            self.current_queue_index = -1
            self.update_queue_display()
            self.status_var.set("Queue cleared")
    
    def update_queue_display(self):
        """Update the speech-queue Treeview display."""
        for child in self.queue_tree.get_children():
            self.queue_tree.delete(child)
        for i, item in enumerate(self.speech_queue):
            icon = item.get("icon", "💬")
            playing = self.queue_playing and i == self.current_queue_index
            tags = ("now_playing",) if playing else ()
            self.queue_tree.insert(
                "", tk.END, iid=str(i),
                text="", image=emoji_icon(icon), values=(item['name'],), tags=tags
            )
    
    def play_queue(self):
        """Start playing items in the queue"""
        if not self.speech_queue:
            messagebox.showinfo("Queue", "Queue is empty. Add items to queue first.")
            return
        
        if self.speaking or self.queue_playing:
            messagebox.showinfo("Queue", "Already speaking. Stop current speech first.")
            return
        
        self.queue_playing = True
        self.stop_requested = False  # Reset stop flag
        self.global_stop_requested = False  # Reset global stop flag
        self.current_queue_index = 0
        self.status_var.set(f"Playing queue item 1 of {len(self.speech_queue)}")
        self.update_queue_display()
        
        # Start playing the queue
        threading.Thread(target=self._play_queue_worker, daemon=True).start()
    
    def _play_queue_worker(self):
        """Worker thread to play queue items sequentially"""
        com_initialized = _com_init_thread()
        
        try:
            while self.queue_playing and self.current_queue_index < len(self.speech_queue):
                if self.stop_requested or self.global_stop_requested:
                    break
                
                item = self.speech_queue[self.current_queue_index]
                self.speaking = True
                
                idx = self.current_queue_index
                nq = len(self.speech_queue)

                def _queue_item_ui(i=idx, n=nq):
                    self.update_queue_display()
                    self.status_var.set(f"Playing queue item {i+1} of {n}")
                    self.speak_btn.state(["disabled"])
                    self.speak_selected_btn.state(["disabled"])

                self.root.after(0, _queue_item_ui)
                
                # Speak the item
                engine = None
                try:
                    engine = pyttsx3.init()
                    self.current_engine = engine
                    self.all_engines.append(engine)  # Track all engines for global stop
                    
                    engine.setProperty("rate", self.rate.get())
                    engine.setProperty("volume", self.vol.get())
                    if self.selected_voice:
                        engine.setProperty("voice", self.selected_voice)
                    
                    if not self.stop_requested and not self.global_stop_requested:
                        engine.say(item['text'])
                        engine.runAndWait()
                    
                except Exception as e:
                    err_msg = str(e)
                    self.root.after(0, lambda msg=err_msg: messagebox.showerror("TTS Error", f"Failed to speak queue item: {msg}"))
                    break
                finally:
                    # Cleanup engine
                    if engine:
                        try:
                            # Remove from tracking list
                            if engine in self.all_engines:
                                self.all_engines.remove(engine)
                            del engine
                        except Exception:
                            pass
                    
                    self.current_engine = None
                
                self.speaking = False
                self.current_queue_index += 1
                
                # Small pause between items
                if self.current_queue_index < len(self.speech_queue) and not self.stop_requested and not self.global_stop_requested:
                    threading.Event().wait(0.5)
            
            # Queue finished
            self.queue_playing = False
            self.current_queue_index = -1
            
            stopped = self.stop_requested or self.global_stop_requested

            def _queue_playback_finished_ui():
                self.status_var.set("Queue playback stopped" if stopped else "Queue playback completed")
                self.speak_btn.state(["!disabled"])
                self.speak_selected_btn.state(["!disabled"])
                self.update_queue_display()
                self.txt.tag_remove(self.highlight_tag, "1.0", "end")

            self.root.after(0, _queue_playback_finished_ui)
            
            # Loop the queue if enabled and playback finished naturally.
            if (self.queue_loop.get() and not stopped
                    and self.speech_queue and not self.global_stop_requested):
                self.root.after(300, self._start_auto_queue)
            # If there are more queued items and auto-queue is enabled, continue playing
            # Only continue if there are items beyond what we just played
            elif self.current_queue_index < len(self.speech_queue) and self.clipboard_auto_queue and not self.stop_requested and not self.global_stop_requested:
                self.root.after(100, lambda: self._start_auto_queue())
            
        except Exception as e:
            self.queue_playing = False
            self.current_queue_index = -1
            err = str(e)

            def _queue_error_ui():
                messagebox.showerror("Queue Error", f"Queue playback failed: {err}")
                self.speak_btn.state(["!disabled"])
                self.speak_selected_btn.state(["!disabled"])

            self.root.after(0, _queue_error_ui)
        finally:
            _com_deinit_thread(com_initialized)

    def _on_rate_change(self, value):
        self.rate.set(int(float(value)))
    
    def _on_volume_change(self, value):
        self.vol.set(float(value))
    
    def on_voice_change(self, _):
        vid = self.voice_map.get(self.voice_combo.get())
        if vid:
            self.selected_voice = vid
    
    def refresh_voices(self):
        """Refresh the voice list to detect newly installed voices"""
        try:
            # Get current selection
            current_voice_name = self.voice_combo.get()
            
            # Re-initialize engine to get updated voice list
            temp_engine = pyttsx3.init()
            self.voices = temp_engine.getProperty("voices")
            temp_engine.stop()
            
            # Rebuild voice map
            self.voice_map = { (v.name or f"Voice {i}"): v.id for i, v in enumerate(self.voices) }
            
            # Update combobox
            self.voice_combo['values'] = list(self.voice_map.keys())
            
            # Try to restore previous selection, otherwise pick first voice
            if current_voice_name in self.voice_map:
                self.voice_combo.set(current_voice_name)
                self.selected_voice = self.voice_map[current_voice_name]
            else:
                # Pick first voice if previous selection no longer exists
                if self.voice_map:
                    first_voice = list(self.voice_map.keys())[0]
                    self.voice_combo.set(first_voice)
                    self.selected_voice = self.voice_map[first_voice]
            
            # Update status
            self.status_var.set(f"Voices refreshed! Found {len(self.voices)} voice(s)")
            
            # Show info if new voices were found
            messagebox.showinfo("Voices Refreshed", 
                              f"Found {len(self.voices)} voice(s) installed on your system.\n\n"
                              f"To add more voices:\n"
                              f"1. Open Windows Settings\n"
                              f"2. Go to Time & Language → Speech\n"
                              f"3. Click 'Add voices'\n"
                              f"4. Click 🔄 to refresh again!")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to refresh voices: {str(e)}")
            self.status_var.set("Failed to refresh voices")

    def open_voice_settings(self):
        """Open Windows voice settings so users can install more voices."""
        try:
            # Windows settings URI for speech voices.
            os.startfile("ms-settings:speech")
            self.status_var.set("Opened Windows Speech settings")
            messagebox.showinfo(
                "Add Voices",
                "Windows Speech settings opened.\n\n"
                "Install voices there, then return and click 🔄 to refresh."
            )
        except Exception:
            messagebox.showinfo(
                "Add Voices",
                "Could not open Windows settings automatically.\n\n"
                "Open Settings manually:\n"
                "Time & Language -> Speech -> Add voices"
            )

    def open_sound_output_settings(self):
        """Open Windows output sound settings."""
        try:
            os.startfile("ms-settings:sound")
        except Exception:
            messagebox.showinfo("Audio Output", "Open Windows Settings and go to System -> Sound.")

    def on_paste(self):
        try:
            self.txt.insert("insert", self.root.clipboard_get())
            self.status_var.set("Text pasted")
        except tk.TclError:
            messagebox.showinfo("Clipboard", "Clipboard is empty.")
    
    def on_clear(self):
        self.txt.delete("1.0", "end")
        self.status_var.set("Text cleared")
    
    def _read_text_file(self, path):
        """Read a text file tolerantly (BOM / UTF-8 / cp1252 / fallback)."""
        with open(path, "rb") as f:
            raw = f.read()
        for enc in ("utf-8-sig", "utf-8", "cp1252"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")

    def on_open(self):
        file_path = filedialog.askopenfilename(
            title="Open Text File",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if file_path:
            try:
                content = self._read_text_file(file_path)
                self.txt.delete("1.0", "end")
                self.txt.insert("1.0", content)
                self.current_file = file_path
                self.status_var.set(f"Opened: {os.path.basename(file_path)}")
            except Exception as e:
                messagebox.showerror("Open Failed", f"Could not read this file:\n{str(e)}")
    
    def on_save(self):
        if self.current_file:
            try:
                with open(self.current_file, 'w', encoding='utf-8') as file:
                    file.write(self.txt.get("1.0", "end"))
                self.status_var.set(f"Saved: {os.path.basename(self.current_file)}")
            except Exception as e:
                messagebox.showerror("Save Failed", f"Could not save this file:\n{str(e)}")
        else:
            self.on_save_as()
    
    def on_save_as(self):
        file_path = filedialog.asksaveasfilename(
            title="Save Text File",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as file:
                    file.write(self.txt.get("1.0", "end"))
                self.current_file = file_path
                self.status_var.set(f"Saved: {os.path.basename(file_path)}")
            except Exception as e:
                messagebox.showerror("Save Failed", f"Could not save this file:\n{str(e)}")
    
    def on_export_audio(self):
        """Export text to audio file (runs in a background thread)."""
        text = self.txt.get("1.0", "end").strip()
        if not text:
            messagebox.showinfo("Export Audio", "No text to export.")
            return
        
        file_path = filedialog.asksaveasfilename(
            title="Export Audio File",
            defaultextension=".wav",
            filetypes=[("WAV files", "*.wav"), ("MP3 files", "*.mp3")]
        )
        
        if file_path:
            self.export_audio_btn.state(["disabled"])
            self.status_var.set("Exporting audio...")
            threading.Thread(
                target=self._export_audio_worker, args=(text, file_path), daemon=True
            ).start()
    
    def _export_audio_worker(self, text, file_path):
        """Background worker for audio export (keeps the UI responsive)."""
        com_initialized = _com_init_thread()
        error = None
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", self.rate.get())
            engine.setProperty("volume", self.vol.get())
            if self.selected_voice:
                engine.setProperty("voice", self.selected_voice)
            engine.save_to_file(text, file_path)
            engine.runAndWait()
        except Exception as e:
            error = str(e)
        finally:
            _com_deinit_thread(com_initialized)
        
        def _done():
            self.export_audio_btn.state(["!disabled"])
            if error:
                messagebox.showerror("Export Error", f"Failed to export audio: {error}")
                self.status_var.set("Export failed")
            else:
                self.status_var.set(f"Audio exported: {os.path.basename(file_path)}")
                messagebox.showinfo("Export Audio", f"Audio successfully exported to:\n{file_path}")
        
        self.root.after(0, _done)
    
    def on_search(self):
        """Open search and replace dialog"""
        SearchDialog(self.root, self.txt, theme=getattr(self, "_active_theme", None))
    
    def on_settings(self, initial_tab="hotkeys"):
        """Open settings dialog."""
        SettingsDialog(self.root, self, initial_tab=initial_tab)
    
    def on_speak_selected(self):
        if self.speaking:
            return
        try:
            selected_text = self.txt.get(tk.SEL_FIRST, tk.SEL_LAST).strip()
            if not selected_text:
                messagebox.showinfo("Read Aloud", "Please select some text first.")
                return
            self.speaking = True
            self.stop_requested = False
            self.global_stop_requested = False  # Reset global stop flag
            self.speak_btn.state(["disabled"])
            self.speak_selected_btn.state(["disabled"])
            self.status_var.set("Speaking selected text...")
            self.speak_thread = threading.Thread(target=self._speak_worker, args=(selected_text,), daemon=True)
            self.speak_thread.start()
        except tk.TclError:
            messagebox.showinfo("Read Aloud", "Please select some text first.")

    def on_speak(self):
        if self.speaking:
            return
        text = self.txt.get("1.0", "end").strip()
        if not text:
            messagebox.showinfo("Read Aloud", "Paste or type some text first.")
            return
        self.speaking = True
        self.stop_requested = False
        self.global_stop_requested = False  # Reset global stop flag
        self.speak_btn.state(["disabled"])
        self.speak_selected_btn.state(["disabled"])
        self.status_var.set("Speaking all text...")
        self.speak_thread = threading.Thread(target=self._speak_worker, args=(text,), daemon=True)
        self.speak_thread.start()

    def _speak_worker(self, text):
        """Worker thread for speaking text - with Python 3.13 fix"""
        engine = None
        com_initialized = _com_init_thread()
        
        try:
            # Create a fresh engine for each speech to avoid lifecycle issues
            engine = pyttsx3.init()
            self.current_engine = engine  # Store reference for stop functionality
            self.all_engines.append(engine)  # Track all engines for global stop
            
            # Apply current settings to the new engine
            engine.setProperty("rate", self.rate.get())
            engine.setProperty("volume", self.vol.get())
            if self.selected_voice:
                engine.setProperty("voice", self.selected_voice)
            
            # Check if stop was requested before starting
            if self.stop_requested or self.global_stop_requested:
                return
            
            # Python 3.13 + SAPI5 can crash when word callbacks fire from COM events.
            # Keep speech stable by disabling started-word callbacks on 3.13+.
            enable_word_callbacks = sys.version_info < (3, 13)
            if enable_word_callbacks:
                def on_word(name, location, length):
                    if self.stop_requested or self.global_stop_requested:
                        return
                    try:
                        self.root.after(0, lambda loc=location, ln=length: self.highlight_word(loc, ln))
                    except Exception:
                        pass
                try:
                    engine.connect('started-word', on_word)
                except Exception:
                    pass
            
            # Simple say and wait
            engine.say(text)
            engine.runAndWait()
            
            # Clear highlighting
            self.root.after(0, lambda: self.txt.tag_remove(self.highlight_tag, "1.0", "end"))
            
        except Exception as e:
            # Use after() to safely show error message from worker thread
            error_msg = str(e)
            self.root.after(0, lambda msg=error_msg: messagebox.showerror("TTS Error", f"Failed to speak text: {msg}"))
        finally:
            # Cleanup engine
            if engine:
                try:
                    # Remove from tracking list
                    if engine in self.all_engines:
                        self.all_engines.remove(engine)
                    del engine
                except Exception:
                    pass
            
            _com_deinit_thread(com_initialized)
            
            self.current_engine = None
            self.speaking = False

            def _speak_worker_finished_ui():
                self.speak_btn.state(["!disabled"])
                self.speak_selected_btn.state(["!disabled"])
                if self.speech_queue and self.clipboard_auto_queue and not self.queue_playing:
                    self._start_auto_queue()
                else:
                    self.status_var.set("Ready")

            self.root.after(0, _speak_worker_finished_ui)
    
    def highlight_word(self, location, length):
        """Highlight the current word being spoken"""
        try:
            now = time.time()
            min_gap = 0.15 if self.performance_mode else 0.05
            if now - self.last_highlight_update < min_gap:
                return
            self.last_highlight_update = now

            # Remove previous highlight
            self.txt.tag_remove(self.highlight_tag, "1.0", "end")
            
            # Find position in text widget
            start_idx = f"1.0 + {location} chars"
            end_idx = f"1.0 + {location + length} chars"
            
            # Add highlight
            self.txt.tag_add(self.highlight_tag, start_idx, end_idx)
            
            # Auto-scroll to show highlighted word
            self.txt.see(start_idx)
        except Exception:
            pass  # Ignore errors in highlighting

    def on_stop(self):
        # Set global stop flag to stop all TTS operations
        self.global_stop_requested = True
        self.stop_requested = True
        
        # Stop all active engines
        engines_to_stop = self.all_engines.copy()  # Copy to avoid modification during iteration
        for engine in engines_to_stop:
            try:
                engine.stop()
            except Exception:
                pass  # Ignore errors when stopping engine
        
        # Clear all engine references
        self.all_engines.clear()
        self.current_engine = None
        
        # Stop regular speech
        if self.speaking:
            self.speaking = False
            self.speak_btn.state(["!disabled"])
            self.speak_selected_btn.state(["!disabled"])
            self.txt.tag_remove(self.highlight_tag, "1.0", "end")  # Clear highlighting
        
        # Stop queue playback
        if self.queue_playing:
            self.queue_playing = False
            self.current_queue_index = -1
            self.update_queue_display()
        
        # Reset stop flags after a short delay to allow for new operations
        self.root.after(100, lambda: self._reset_stop_flags())
        
        self.status_var.set("All speech stopped")
    
    def _reset_stop_flags(self):
        """Reset stop flags to allow new TTS operations"""
        self.global_stop_requested = False
        self.stop_requested = False
    
    def _start_auto_queue(self):
        """Start playing the queue automatically after speech finishes"""
        if not self.speech_queue or self.queue_playing or self.speaking:
            return
        
        self.queue_playing = True
        self.stop_requested = False
        self.global_stop_requested = False
        # Don't reset current_queue_index - continue from where we left off
        if self.current_queue_index < 0:
            self.current_queue_index = 0
        self.status_var.set(f"Auto-playing queue ({self.current_queue_index + 1} of {len(self.speech_queue)} items)")
        self.update_queue_display()
        threading.Thread(target=self._play_queue_worker, daemon=True).start()

    def on_close(self):
        self._cancel_stt_idle_unload()
        if self.recording:
            self.stop_stt_recording()
        self.save_settings()
        self.root.destroy()


class SearchDialog:
    """Search and Replace dialog"""
    def __init__(self, parent, text_widget, theme=None):
        self.text_widget = text_widget
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Find and Replace")
        self.dialog.geometry("450x250")
        self.dialog.resizable(False, False)
        theme = _normalize_theme(theme or THEME_PRESETS["twilight"])
        self.dialog.configure(bg=theme["bg"])

        header = GradientHeader(
            self.dialog, title="Find & Replace",
            subtitle="Search, replace, regex", height=48
        )
        header.pack(fill="x", side="top")
        header.apply_colors(
            theme["header"], theme["header2"], theme["header_text"],
            _mix(theme["header_text"], theme["header"], 0.35)
        )

        # Search frame
        search_frame = ttk.Frame(self.dialog, padding=10)
        search_frame.pack(fill="x")
        
        ttk.Label(search_frame, text="Find:").grid(row=0, column=0, sticky="w", pady=5)
        self.find_entry = ttk.Entry(search_frame, width=40)
        self.find_entry.grid(row=0, column=1, padx=5, pady=5)
        self.find_entry.focus()
        
        ttk.Label(search_frame, text="Replace:").grid(row=1, column=0, sticky="w", pady=5)
        self.replace_entry = ttk.Entry(search_frame, width=40)
        self.replace_entry.grid(row=1, column=1, padx=5, pady=5)
        
        # Options
        options_frame = ttk.Frame(self.dialog, padding=10)
        options_frame.pack(fill="x")
        
        self.case_sensitive = tk.BooleanVar(value=False)
        self.use_regex = tk.BooleanVar(value=False)
        
        ttk.Checkbutton(options_frame, text="Case sensitive", variable=self.case_sensitive).pack(side="left", padx=5)
        ttk.Checkbutton(options_frame, text="Use regex", variable=self.use_regex).pack(side="left", padx=5)
        
        # Buttons
        button_frame = ttk.Frame(self.dialog, padding=10)
        button_frame.pack(fill="x")
        
        ttk.Button(button_frame, text="Find Next", command=self.find_next).pack(side="left", padx=5)
        ttk.Button(button_frame, text="Replace", command=self.replace_one).pack(side="left", padx=5)
        ttk.Button(button_frame, text="Replace All", command=self.replace_all).pack(side="left", padx=5)
        ttk.Button(button_frame, text="Close", command=self.dialog.destroy).pack(side="right", padx=5)
        
        self.search_start = "1.0"
    
    def find_next(self):
        """Find next occurrence"""
        search_term = self.find_entry.get()
        if not search_term:
            return
        
        # Remove previous selection
        self.text_widget.tag_remove("sel", "1.0", "end")
        
        # Search
        flags = []
        if not self.case_sensitive.get():
            flags.append("nocase")
        if self.use_regex.get():
            flags.append("regexp")
        
        pos = self.text_widget.search(search_term, self.search_start, "end", *flags)
        
        if pos:
            end_pos = f"{pos}+{len(search_term)}c"
            self.text_widget.tag_add("sel", pos, end_pos)
            self.text_widget.mark_set("insert", pos)
            self.text_widget.see(pos)
            self.search_start = end_pos
        else:
            messagebox.showinfo("Find", "No more matches found.")
            self.search_start = "1.0"
    
    def replace_one(self):
        """Replace current selection"""
        try:
            selection = self.text_widget.get("sel.first", "sel.last")
            if selection:
                self.text_widget.delete("sel.first", "sel.last")
                self.text_widget.insert("insert", self.replace_entry.get())
                self.find_next()
        except tk.TclError:
            messagebox.showinfo("Replace", "No text selected. Use 'Find Next' first.")
    
    def replace_all(self):
        """Replace all occurrences"""
        search_term = self.find_entry.get()
        replace_term = self.replace_entry.get()
        
        if not search_term:
            return
        
        content = self.text_widget.get("1.0", "end-1c")
        
        if self.use_regex.get():
            flags = 0 if self.case_sensitive.get() else re.IGNORECASE
            new_content, count = re.subn(search_term, replace_term, content, flags=flags)
        else:
            if self.case_sensitive.get():
                count = content.count(search_term)
                new_content = content.replace(search_term, replace_term)
            else:
                # Case insensitive replace
                pattern = re.compile(re.escape(search_term), re.IGNORECASE)
                new_content = pattern.sub(replace_term, content)
                count = len(pattern.findall(content))
        
        if count > 0:
            self.text_widget.delete("1.0", "end")
            self.text_widget.insert("1.0", new_content)
            messagebox.showinfo("Replace All", f"Replaced {count} occurrence(s).")
        else:
            messagebox.showinfo("Replace All", "No matches found.")


class SettingsDialog:
    """Settings dialog with hotkeys, theme, and audio tabs."""
    def __init__(self, parent, app, initial_tab="hotkeys"):
        self.app = app
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Settings")
        self.dialog.geometry("520x500")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        theme = _normalize_theme(THEME_PRESETS.get(self.app.theme_preset, THEME_PRESETS["twilight"]))
        self.dialog.configure(bg=theme["bg"])

        header = GradientHeader(
            self.dialog, title="Settings",
            subtitle="", height=48
        )
        header.pack(fill="x", side="top")
        header.apply_colors(
            theme["header"], theme["header2"], theme["header_text"],
            _mix(theme["header_text"], theme["header"], 0.35)
        )

        notebook = ttk.Notebook(self.dialog)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        hotkeys_tab = ttk.Frame(notebook)
        theme_tab = ttk.Frame(notebook)
        audio_tab = ttk.Frame(notebook)
        notebook.add(hotkeys_tab, text="Hotkeys")
        notebook.add(theme_tab, text="Theme")
        notebook.add(audio_tab, text="Audio")

        # Hotkeys tab
        ttk.Label(
            hotkeys_tab,
            text="Click on a hotkey field and press the desired key combination.",
            wraplength=470
        ).pack(fill="x", padx=10, pady=(10, 6))

        canvas_frame = ttk.Frame(hotkeys_tab, padding=(10, 0, 10, 10))
        canvas_frame.pack(fill="both", expand=True)
        canvas = tk.Canvas(
            canvas_frame,
            height=240,
            bg=theme["bg"],
            highlightthickness=0,
            bd=0
        )
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        hotkey_frame = ttk.Frame(canvas)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.create_window((0, 0), window=hotkey_frame, anchor="nw")

        self.hotkey_entries = {}
        action_labels = {
            'speak_all': 'Speak All Text',
            'speak_selected': 'Speak Selected Text',
            'stop': 'Stop Speaking',
            'open': 'Open File',
            'save': 'Save File',
            'save_as': 'Save As',
            'paste': 'Paste Text',
            'clear': 'Clear Text',
            'find': 'Find/Replace',
            'export': 'Export Audio'
        }
        
        row = 0
        for action, label in action_labels.items():
            ttk.Label(hotkey_frame, text=label, width=20).grid(row=row, column=0, padx=5, pady=5, sticky="w")
            
            entry = ttk.Entry(hotkey_frame, width=25)
            entry.insert(0, self.app.hotkeys.get(action, ''))
            entry.grid(row=row, column=1, padx=5, pady=5)
            
            # Bind key press to capture hotkey
            entry.bind('<KeyPress>', lambda e, a=action: self.capture_hotkey(e, a))
            
            self.hotkey_entries[action] = entry
            row += 1
        
        hotkey_frame.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))

        # Theme tab
        theme_frame = ttk.Frame(theme_tab, padding=12)
        theme_frame.pack(fill="both", expand=True)
        ttk.Label(theme_frame, text="Theme Preset").grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.theme_var = tk.StringVar(value=self.app.theme_name_var.get())
        self.theme_combo = ttk.Combobox(
            theme_frame,
            values=self.app.theme_options,
            width=20,
            state="readonly",
            textvariable=self.theme_var
        )
        self.theme_combo.grid(row=0, column=1, sticky="ew", pady=(0, 8))
        self.performance_var = tk.BooleanVar(value=self.app.performance_mode)
        ttk.Checkbutton(theme_frame, text="Performance Mode", variable=self.performance_var).grid(
            row=1, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(
            theme_frame,
            text="Performance mode lowers update frequency for older machines.",
            style="Muted.TLabel"
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        theme_frame.columnconfigure(1, weight=1)

        # Audio tab
        audio_frame = ttk.Frame(audio_tab, padding=12)
        audio_frame.pack(fill="both", expand=True)
        device_data = self.app.get_audio_devices()
        self.input_map = {"System default": ""}
        self.output_map = {"System default": ""}
        for dev_id, label in device_data["inputs"]:
            self.input_map[label] = dev_id
        for dev_id, label in device_data["outputs"]:
            self.output_map[label] = dev_id

        current_input_label = "System default"
        for label, dev_id in self.input_map.items():
            if dev_id == self.app.stt_input_device:
                current_input_label = label
                break

        current_output_label = "System default"
        for label, dev_id in self.output_map.items():
            if dev_id == self.app.tts_output_device:
                current_output_label = label
                break

        ttk.Label(audio_frame, text="STT Input Microphone").grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.input_var = tk.StringVar(value=current_input_label)
        self.input_combo = ttk.Combobox(
            audio_frame,
            values=list(self.input_map.keys()),
            width=36,
            state="readonly",
            textvariable=self.input_var
        )
        self.input_combo.grid(row=0, column=1, sticky="ew", pady=(0, 8))

        ttk.Label(audio_frame, text="TTS Output Device").grid(row=1, column=0, sticky="w", pady=(0, 8))
        self.output_var = tk.StringVar(value=current_output_label)
        self.output_combo = ttk.Combobox(
            audio_frame,
            values=list(self.output_map.keys()),
            width=36,
            state="readonly",
            textvariable=self.output_var
        )
        self.output_combo.grid(row=1, column=1, sticky="ew", pady=(0, 8))

        ttk.Label(
            audio_frame,
            text="TTS output follows Windows default playback device for pyttsx3.",
            style="Muted.TLabel"
        ).grid(row=2, column=0, columnspan=2, sticky="w")
        self.stt_unload_var = tk.BooleanVar(value=self.app.stt_unload_model_when_idle)
        ttk.Checkbutton(
            audio_frame,
            text="Unload STT model when idle (saves RAM, slower next transcript start)",
            variable=self.stt_unload_var
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.stt_auto_unload_enabled_var = tk.BooleanVar(value=self.app.stt_auto_unload_enabled)
        ttk.Checkbutton(
            audio_frame,
            text="Auto-unload STT model after idle time",
            variable=self.stt_auto_unload_enabled_var
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(audio_frame, text="Auto-unload delay (minutes)").grid(row=5, column=0, sticky="w", pady=(0, 8))
        self.stt_auto_unload_minutes_var = tk.IntVar(value=self.app.stt_auto_unload_minutes)
        ttk.Spinbox(
            audio_frame,
            from_=1,
            to=60,
            textvariable=self.stt_auto_unload_minutes_var,
            width=8
        ).grid(row=5, column=1, sticky="w", pady=(0, 8))
        ttk.Button(
            audio_frame,
            text="Open Windows Sound Output Settings",
            command=self.app.open_sound_output_settings
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))
        audio_frame.columnconfigure(1, weight=1)

        # Dialog buttons
        button_frame = ttk.Frame(self.dialog, padding=(10, 0, 10, 10))
        button_frame.pack(fill="x")
        ttk.Button(button_frame, text="Save", command=self.save_all).pack(side="left", padx=5)
        ttk.Button(button_frame, text="Reset to Defaults", command=self.reset_defaults).pack(side="left", padx=5)
        ttk.Button(button_frame, text="Cancel", command=self.cancel_changes).pack(side="right", padx=5)
        ttk.Button(button_frame, text="Close", command=self.dialog.destroy).pack(side="right", padx=5)

        if initial_tab == "theme":
            notebook.select(theme_tab)
        elif initial_tab == "audio":
            notebook.select(audio_tab)
        else:
            notebook.select(hotkeys_tab)
    
    def capture_hotkey(self, event, action):
        """Capture hotkey combination"""
        modifiers = []
        if event.state & 0x4:  # Control
            modifiers.append("Control")
        if event.state & 0x1:  # Shift
            modifiers.append("Shift")
        if event.state & 0x20000:  # Alt
            modifiers.append("Alt")
        
        key = event.keysym
        if key not in ['Control_L', 'Control_R', 'Shift_L', 'Shift_R', 'Alt_L', 'Alt_R']:
            if modifiers:
                hotkey = f"<{'-'.join(modifiers)}-{key}>"
            else:
                hotkey = f"<{key}>"
            
            self.hotkey_entries[action].delete(0, "end")
            self.hotkey_entries[action].insert(0, hotkey)
        
        return "break"
    
    def save_all(self):
        """Save hotkeys and theme settings."""
        new_hotkeys = {}
        for action, entry in self.hotkey_entries.items():
            hotkey = entry.get().strip()
            if hotkey:
                new_hotkeys[action] = hotkey

        self.app.hotkeys = new_hotkeys
        self.app.bind_shortcuts()

        self.app.theme_name_var.set(self.theme_var.get())
        self.app.on_theme_selected()
        self.app.performance_mode = self.performance_var.get()
        if hasattr(self.app, "performance_var"):
            self.app.performance_var.set(self.app.performance_mode)
        self.app.stt_input_device = self.input_map.get(self.input_var.get(), "")
        self.app.tts_output_device = self.output_map.get(self.output_var.get(), "")
        self.app.stt_unload_model_when_idle = self.stt_unload_var.get()
        self.app.stt_auto_unload_enabled = self.stt_auto_unload_enabled_var.get()
        try:
            self.app.stt_auto_unload_minutes = max(1, min(60, int(self.stt_auto_unload_minutes_var.get())))
        except (TypeError, ValueError):
            self.app.stt_auto_unload_minutes = DEFAULT_SETTINGS["stt_auto_unload_minutes"]
        if self.app.stt_unload_model_when_idle:
            self.app._release_stt_model()
        else:
            self.app._schedule_stt_idle_unload()

        self.app.save_settings()
        messagebox.showinfo("Settings", "Settings saved successfully")
    
    def cancel_changes(self):
        """Revert unsaved UI edits in the dialog."""
        defaults = self.app.hotkeys
        for action, entry in self.hotkey_entries.items():
            entry.delete(0, "end")
            entry.insert(0, defaults.get(action, ''))

        self.theme_var.set(self.app.theme_name_var.get())
        self.performance_var.set(self.app.performance_mode)

        current_input_label = "System default"
        for label, dev_id in self.input_map.items():
            if dev_id == self.app.stt_input_device:
                current_input_label = label
                break
        self.input_var.set(current_input_label)

        current_output_label = "System default"
        for label, dev_id in self.output_map.items():
            if dev_id == self.app.tts_output_device:
                current_output_label = label
                break
        self.output_var.set(current_output_label)
        self.stt_unload_var.set(self.app.stt_unload_model_when_idle)
        self.stt_auto_unload_enabled_var.set(self.app.stt_auto_unload_enabled)
        self.stt_auto_unload_minutes_var.set(self.app.stt_auto_unload_minutes)
    
    def reset_defaults(self):
        """Reset all settings (hotkeys, theme, performance, audio) to defaults."""
        defaults = self.app.get_default_hotkeys()
        for action, entry in self.hotkey_entries.items():
            entry.delete(0, "end")
            entry.insert(0, defaults.get(action, ''))

        self.theme_var.set(THEME_PRESETS[DEFAULT_SETTINGS["theme_preset"]]["name"])
        self.performance_var.set(DEFAULT_SETTINGS["performance_mode"])
        self.input_var.set("System default")
        self.output_var.set("System default")
        self.stt_unload_var.set(DEFAULT_SETTINGS["stt_unload_model_when_idle"])
        self.stt_auto_unload_enabled_var.set(DEFAULT_SETTINGS["stt_auto_unload_enabled"])
        self.stt_auto_unload_minutes_var.set(DEFAULT_SETTINGS["stt_auto_unload_minutes"])


if __name__ == "__main__":
    root = tk.Tk()
    app = ReaderApp(root)
    root.minsize(700, 400)
    root.mainloop()
