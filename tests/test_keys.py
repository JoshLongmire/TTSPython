import pytest

from ttspython.core import keys

V4_DEFAULTS = {
    "speak_all": "<Control-Return>",
    "speak_selected": "<Control-Shift-Return>",
    "stop": "<Escape>",
    "open": "<Control-o>",
    "save": "<Control-s>",
    "save_as": "<Control-Shift-S>",
    "paste": "<Control-v>",
    "clear": "<Control-l>",
    "find": "<Control-f>",
    "export": "<Control-e>",
}


def test_all_v4_defaults_migrate_to_v5_defaults():
    for action, tk in V4_DEFAULTS.items():
        assert keys.tk_to_portable(tk) == keys.DEFAULT_SHORTCUTS[action], action


@pytest.mark.parametrize("tk,expected", [
    ("<Control-S>", "Ctrl+Shift+S"),
    ("<Alt-F4>", "Alt+F4"),
    ("<Mod1-x>", "Alt+X"),
    ("<Control-minus>", "Ctrl+-"),
    ("<Control-Alt-Prior>", "Ctrl+Alt+PgUp"),
    ("<Shift-Control-a>", "Ctrl+Shift+A"),
    ("<F5>", "F5"),
    ("<Control-KeyPress-q>", "Ctrl+Q"),
])
def test_tk_conversions(tk, expected):
    assert keys.tk_to_portable(tk) == expected


@pytest.mark.parametrize("bad", ["", "<>", "<Bogus-x>", "Control-x", "<Control-NoSuchKey>", None, 5])
def test_unreadable_tk_returns_none(bad):
    assert keys.tk_to_portable(bad) is None


def test_merge_fills_missing_and_keeps_blank_unassigned():
    merged = keys.merge_shortcuts({"stop": "", "open": "<Control-p>", "junk": "x"})
    assert merged["stop"] == ""
    assert merged["open"] == "Ctrl+P"
    assert merged["save"] == "Ctrl+S"
    assert "junk" not in merged
    assert set(merged) == set(keys.DEFAULT_SHORTCUTS)


def test_merge_bad_value_falls_back_to_default():
    merged = keys.merge_shortcuts({"find": "<Nope-z>", "clear": 42})
    assert merged["find"] == "Ctrl+F"
    assert merged["clear"] == "Ctrl+L"


def test_conflicts_detected():
    shortcuts = dict(keys.DEFAULT_SHORTCUTS, clear="Ctrl+S")
    assert keys.find_conflicts(shortcuts) == {"Ctrl+S": ["save", "clear"]}


def test_win_hotkey_mapping():
    flags, vk = keys.to_win_hotkey("Ctrl+Alt+D")
    assert vk == ord("D")
    assert flags & keys.WIN_MOD_CONTROL and flags & keys.WIN_MOD_ALT and flags & keys.WIN_MOD_NOREPEAT
    assert keys.to_win_hotkey("Ctrl+F5")[1] == 0x74
    assert keys.to_win_hotkey("Meta+Space")[1] == 0x20
    assert keys.to_win_hotkey("Ctrl+") is None
    assert keys.to_win_hotkey("Ctrl+Alt") is None


def test_pynput_mapping():
    assert keys.to_pynput("Ctrl+Alt+D") == "<ctrl>+<alt>+d"
    assert keys.to_pynput("Shift+F9") == "<shift>+<f9>"
    assert keys.to_pynput("Ctrl+Return") == "<ctrl>+<enter>"
