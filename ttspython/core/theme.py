"""Theme presets and design tokens (toolkit-agnostic)."""
from __future__ import annotations


# --- Color helpers -------------------------------------------------------------
def _clamp_channel(value):
    return max(0, min(255, int(round(value))))


def hex_to_rgb(color):
    color = str(color).lstrip("#")
    if len(color) == 3:
        color = "".join(ch * 2 for ch in color)
    try:
        return (int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16))
    except (ValueError, IndexError):
        return (30, 30, 30)


def rgb_to_hex(rgb):
    return "#%02x%02x%02x" % (_clamp_channel(rgb[0]), _clamp_channel(rgb[1]), _clamp_channel(rgb[2]))


def mix(color_a, color_b, t):
    """Linear blend from color_a (t=0) to color_b (t=1)."""
    t = max(0.0, min(1.0, t))
    ra, ga, ba = hex_to_rgb(color_a)
    rb, gb, bb = hex_to_rgb(color_b)
    return rgb_to_hex((ra + (rb - ra) * t, ga + (gb - ga) * t, ba + (bb - ba) * t))


def lighten(color, t=0.12):
    return mix(color, "#ffffff", t)


def darken(color, t=0.12):
    return mix(color, "#000000", t)


def relative_luminance(color):
    r, g, b = (c / 255.0 for c in hex_to_rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def is_dark(color):
    return relative_luminance(color) < 0.5


def contrast_text(bg, light="#ffffff", dark="#111111"):
    return dark if relative_luminance(bg) > 0.55 else light


def wcag_luminance(color):
    def channel(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = hex_to_rgb(color)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(a, b):
    la, lb = wcag_luminance(a), wcag_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def ensure_contrast(fg, bg, minimum=4.5):
    """Push fg toward white or black until it meets the contrast ratio on bg."""
    if contrast_ratio(fg, bg) >= minimum:
        return fg
    target = "#ffffff" if is_dark(bg) else "#000000"
    for step in range(1, 21):
        candidate = mix(fg, target, step / 20)
        if contrast_ratio(candidate, bg) >= minimum:
            return candidate
    return target


def normalize_theme(theme):
    """Return a theme dict with every design-system key present.

    Presets that only define the original 8 keys still load: any missing key
    is derived from the base colors so the UI stays cohesive.
    """
    t = dict(theme or {})
    bg = t.setdefault("bg", "#1e1e1e")
    dark = is_dark(bg)
    bg_elev = t.setdefault("bg_elev", lighten(bg, 0.06) if dark else darken(bg, 0.03))
    text = t.setdefault("text", "#d4d4d4" if dark else "#111827")
    accent = t.setdefault("accent", "#3b82f6")
    t.setdefault("border", lighten(bg, 0.22) if dark else darken(bg, 0.16))
    t.setdefault("muted", mix(text, bg, 0.4))
    t.setdefault("danger", "#f87171")
    t.setdefault("name", "Custom")

    t.setdefault("header", mix(bg_elev, accent, 0.22 if dark else 0.14))
    t.setdefault("header2", mix(bg, accent, 0.06))
    t.setdefault("header_text", contrast_text(t["header"], lighten(text, 0.2), darken(text, 0.1)))

    t.setdefault("button", lighten(bg_elev, 0.05) if dark else darken(bg_elev, 0.02))
    t.setdefault("button_text", text)
    t.setdefault("button_hover", mix(t["button"], accent, 0.34))
    t.setdefault("button_active", accent)

    t.setdefault("field", bg_elev)
    t.setdefault("field_text", text)
    t.setdefault("field_border", t["border"])

    t.setdefault("disabled", mix(bg_elev, bg, 0.5))
    t.setdefault("disabled_text", mix(t["muted"], bg, 0.35))
    t.setdefault("on_accent", contrast_text(accent))
    return t


ORIGINAL_PRESETS = {
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

STUDIO = {
    "bg": "#0f1115", "bg_elev": "#171a21", "border": "#262b36", "text": "#e6e8ee",
    "muted": "#8b93a7", "accent": "#7c8cff", "danger": "#f87171", "name": "Studio"
}

DEFAULT_THEME = "studio"

THEME_PRESETS = {"studio": normalize_theme(STUDIO)}
THEME_PRESETS.update({key: normalize_theme(value) for key, value in ORIGINAL_PRESETS.items()})


def derive_tokens(theme):
    """Extend a normalized theme with the interaction tokens the Qt style needs."""
    t = normalize_theme(theme)
    bg, elev, accent, text = t["bg"], t["bg_elev"], t["accent"], t["text"]
    dark = is_dark(bg)
    high_contrast = t.get("name") == "High Contrast"

    t["text"] = ensure_contrast(text, elev)
    t["field_text"] = ensure_contrast(t["field_text"], t["field"])
    t["muted"] = ensure_contrast(t["muted"], elev, 3.0)
    # Primary buttons: pick the better of white/near-black text, then nudge the
    # fill (not the brand accent used for lines and icons) until it reads well.
    on_accent = max(("#ffffff", "#111111"), key=lambda c: contrast_ratio(c, accent))
    fill = accent
    toward = "#000000" if on_accent == "#ffffff" else "#ffffff"
    for step in range(1, 21):
        if contrast_ratio(on_accent, fill) >= 4.5:
            break
        fill = mix(accent, toward, step / 20)
    t["on_accent"] = on_accent
    t["accent_fill"] = fill
    t["window"] = bg
    t["surface"] = elev
    t["surface2"] = lighten(elev, 0.04) if dark else darken(elev, 0.03)
    t["hover"] = mix(elev, text, 0.08)
    t["pressed"] = mix(elev, text, 0.14)
    # Hover/pressed move away from the text color so contrast only improves.
    t["accent_hover"] = mix(fill, toward, 0.10)
    t["accent_pressed"] = mix(fill, toward, 0.20)
    t["accent_soft"] = mix(elev, accent, 0.18)
    t["accent_text"] = ensure_contrast(accent, elev, 3.0)
    t["focus"] = accent
    t["selection_bg"] = mix(t["field"], accent, 0.35)
    t["selection_text"] = ensure_contrast(t["field_text"], t["selection_bg"])
    t["sentence_bg"] = mix(t["field"], accent, 0.16)
    t["scrollbar"] = mix(elev, text, 0.22)
    t["scrollbar_hover"] = mix(elev, text, 0.35)
    t["divider"] = mix(t["border"], elev, 0.35)
    t["shadow"] = "rgba(0, 0, 0, 110)" if dark else "rgba(15, 23, 42, 40)"
    t["border_w"] = 2 if high_contrast else 1
    t["radius_card"] = 12
    t["radius_ctrl"] = 8
    t["dark"] = dark
    return t

