from ttspython.core import theme


def test_all_original_presets_are_kept_with_their_base_colors():
    for key, original in theme.ORIGINAL_PRESETS.items():
        assert key in theme.THEME_PRESETS
        preset = theme.THEME_PRESETS[key]
        for color_key in ("bg", "bg_elev", "border", "text", "muted", "accent", "danger", "name"):
            assert preset[color_key] == original[color_key]


def test_twelve_presets_with_studio_default():
    assert len(theme.THEME_PRESETS) == 12
    assert theme.DEFAULT_THEME == "studio"


def test_every_preset_meets_text_contrast():
    for key, preset in theme.THEME_PRESETS.items():
        t = theme.derive_tokens(preset)
        assert theme.contrast_ratio(t["text"], t["surface"]) >= 4.5, key
        assert theme.contrast_ratio(t["field_text"], t["field"]) >= 4.5, key
        assert theme.contrast_ratio(t["on_accent"], t["accent_fill"]) >= 4.5, key
        assert theme.contrast_ratio(t["on_accent"], t["accent_hover"]) >= 4.5, key
        assert theme.contrast_ratio(t["selection_text"], t["selection_bg"]) >= 4.5, key
        assert theme.contrast_ratio(t["muted"], t["surface"]) >= 3.0, key


def test_high_contrast_gets_thicker_borders():
    assert theme.derive_tokens(theme.THEME_PRESETS["contrast"])["border_w"] == 2
    assert theme.derive_tokens(theme.THEME_PRESETS["dark"])["border_w"] == 1


def test_ensure_contrast_fixes_low_contrast():
    fixed = theme.ensure_contrast("#777777", "#808080")
    assert theme.contrast_ratio(fixed, "#808080") >= 4.5
