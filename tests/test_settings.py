import json
import os

from ttspython.core import settings, keys


def test_defaults_when_nothing_exists(settings_path, tmp_path):
    data, info = settings.load(settings_path, legacy=str(tmp_path / "none.json"))
    assert info["source"] == "defaults"
    assert data == settings.defaults()


def test_imports_v4_file_without_loss_and_leaves_it_untouched(settings_path, v4_settings_file):
    with open(v4_settings_file, "rb") as f:
        before = f.read()
    v4 = json.loads(before)
    store = settings.SettingsStore(settings_path, legacy=v4_settings_file)
    assert store.info["source"] == "legacy"
    with open(v4_settings_file, "rb") as f:
        assert f.read() == before
    assert os.path.exists(settings_path)

    d = store.data
    assert d["theme_preset"] == v4["theme_preset"]
    for key in ("clipboard_monitor", "clipboard_auto_queue", "clipboard_action", "performance_mode",
                "mode", "stt_whisper_model", "stt_unload_model_when_idle", "stt_auto_unload_enabled",
                "stt_auto_unload_minutes"):
        assert d[key] == v4[key], key
    for action, tk in v4["hotkeys"].items():
        assert d["shortcuts"][action] == keys.tk_to_portable(tk)
    w, h, x, y = 1433, 849, 243, 115
    assert d["window"] == {"x": x, "y": y, "w": w, "h": h, "maximized": False}
    assert "hotkeys" not in d and "geometry" not in d


def test_round_trip(settings_path, tmp_path):
    store = settings.SettingsStore(settings_path, legacy=str(tmp_path / "none.json"))
    store.set("tts_rate", 222)
    store.set("tts_voice_id", "voice-x")
    store.set("tts_volume", 0.4)
    store.save()
    again = settings.SettingsStore(settings_path)
    assert again.info["source"] == "file"
    assert again["tts_rate"] == 222
    assert again["tts_voice_id"] == "voice-x"
    assert again["tts_volume"] == 0.4


def test_unknown_keys_survive(settings_path):
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump({"future_key": [1, 2], "tts_rate": 150}, f)
    data, _ = settings.load(settings_path)
    assert data["future_key"] == [1, 2]
    assert data["tts_rate"] == 150


def test_broken_file_is_copied_and_defaults_used(settings_path):
    with open(settings_path, "w", encoding="utf-8") as f:
        f.write("{not json")
    data, info = settings.load(settings_path)
    assert data == settings.defaults()
    assert info["broken_copy"] and os.path.exists(info["broken_copy"])


def test_validation_clamps_and_rejects():
    d = settings.normalize({
        "theme_preset": "nope", "mode": "x", "clipboard_action": "dance",
        "stt_auto_unload_minutes": 999, "tts_rate": 5, "tts_volume": "loud",
        "stt_input_device": "3", "tts_output_device": "Speakers (Realtek)",
        "stt_language": "xx", "hotkeys": "not a dict", "performance_mode": "yes",
    })
    assert d["theme_preset"] == settings.DEFAULTS["theme_preset"]
    assert d["mode"] == "tts"
    assert d["clipboard_action"] == "speak"
    assert d["stt_auto_unload_minutes"] == 60
    assert d["tts_rate"] == settings.RATE_MIN
    assert d["tts_volume"] == 1.0
    assert d["stt_input_device"] == {"name": "", "hostapi": "", "index": 3}
    assert d["tts_output_device"]["name"] == "Speakers (Realtek)"
    assert d["stt_language"] == "en"
    assert d["shortcuts"] == keys.DEFAULT_SHORTCUTS
    assert d["performance_mode"] is False


def test_legacy_dark_mode_flag():
    assert settings.normalize({"dark_mode": False})["theme_preset"] == "light"
    assert settings.normalize({"dark_mode": True})["theme_preset"] == "dark"


def test_env_override_path(monkeypatch, tmp_path):
    target = str(tmp_path / "x.json")
    monkeypatch.setenv(settings.SETTINGS_ENV, target)
    assert settings.default_path() == target
