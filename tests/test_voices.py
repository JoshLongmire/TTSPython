"""More voices: the Windows 11 voices SAPI hides, and downloadable Piper voices."""
import hashlib
import io
import os
import threading
import zipfile

import pytest

from fakes import FakeRenderer, wait_for
from ttspython.core.download import ChecksumError, DownloadCancelled
from ttspython.core.platform import IS_WINDOWS
from ttspython.core.tts import piper
from ttspython.core.tts.render import MultiRenderer, Voice, _base_voice_name


class FakeResponse(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FakeWeb:
    """Serves fixed bytes per URL, like GitHub and Hugging Face would."""

    def __init__(self, files):
        self.files = files
        self.requested = []

    def __call__(self, url, timeout=None):
        self.requested.append(url)
        return FakeResponse(self.files[url])


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TTSPYTHON_DATA", str(tmp_path))
    return tmp_path


def program_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("piper/piper.exe" if IS_WINDOWS else "piper/piper", b"program")
        z.writestr("piper/espeak-ng-data/phontab", b"data")
    return buf.getvalue()


def fake_web_for(voice, monkeypatch, model=b"onnx model bytes", config=b'{"audio": {}}'):
    archive = program_zip()
    name = "piper_test.zip"
    monkeypatch.setattr(piper, "PROGRAMS", {piper._platform_key(): (name, hashlib.sha256(archive).hexdigest())})
    monkeypatch.setattr(piper, "find", lambda key: voice if key in (voice.key, voice.id) else None)
    return FakeWeb({
        piper.RELEASE_URL + name: archive,
        piper.VOICES_URL + voice.model: model,
        piper.VOICES_URL + voice.config: config,
    })


def a_voice(model=b"onnx model bytes", config=b'{"audio": {}}'):
    entry = piper.find("en_US-lessac-medium")
    import dataclasses

    return dataclasses.replace(entry, model_md5=hashlib.md5(model).hexdigest(),
                               config_md5=hashlib.md5(config).hexdigest(), size=len(model))


# --- catalog ----------------------------------------------------------------------------------
def test_catalog_lists_every_piper_voice_offline():
    voices = piper.catalog()
    assert len(voices) == 178
    english = [v for v in voices if v.language == "English"]
    assert len(english) == 38
    lessac = piper.find("piper:en_US-lessac-medium")
    assert lessac.label == "Lessac (English, United States, medium)"
    assert lessac.model.endswith("en_US-lessac-medium.onnx") and len(lessac.model_md5) == 32


# --- Windows 11 voices --------------------------------------------------------------------------
def test_a_voice_in_both_windows_lists_is_shown_once():
    assert _base_voice_name("Microsoft Zira Desktop - English (United States)") == \
        _base_voice_name("Microsoft Zira - English (United States)")
    assert _base_voice_name("Microsoft Mark - English (United States)") != \
        _base_voice_name("Microsoft David Desktop - English (United States)")


@pytest.mark.skipif(not IS_WINDOWS, reason="SAPI is Windows only")
def test_windows_lists_its_hidden_voices():
    from ttspython.core.platform import com_apartment
    from ttspython.core.tts.render import SapiRenderer

    with com_apartment():
        voices = SapiRenderer().list_voices()
    names = [_base_voice_name(v.name) for v in voices]
    assert len(names) == len(set(names))  # no voice twice
    import winreg

    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens")
        onecore = winreg.QueryInfoKey(key)[0]
    except OSError:
        onecore = 0
    if onecore:
        assert any("Speech_OneCore" in v.id for v in voices) or onecore <= len(voices)


# --- routing ------------------------------------------------------------------------------------
class FakePiper(FakeRenderer):
    name = "piper"

    def list_voices(self):
        return [Voice("piper:en_US-lessac-medium", "Lessac - Piper")]

    @staticmethod
    def native_wpm(wpm, voice_id=None):
        return max(150, min(300, wpm))


def test_each_voice_is_spoken_by_its_own_engine():
    system, natural = FakeRenderer(0.01), FakePiper(0.01)
    r = MultiRenderer(system, natural, system_voices=system.list_voices())
    assert [v.id for v in r.list_voices()] == ["v-david", "v-zira", "piper:en_US-lessac-medium"]
    r.render("Hello.", "v-zira", 200, threading.Event())
    r.render("Hello.", "piper:en_US-lessac-medium", 200, threading.Event())
    assert len(system.rendered) == 1 and len(natural.rendered) == 1
    assert r.native_wpm(400, "piper:en_US-lessac-medium") == 300  # Piper's own range; the rest is stretched
    assert r.native_wpm(400, "v-zira") == 400


def test_piper_speed_follows_the_slider_within_its_range():
    for wpm in (150, 200, 300):
        assert piper.PiperRenderer.native_wpm(wpm) == wpm
    assert piper.PiperRenderer.native_wpm(100) == 150 and piper.PiperRenderer.native_wpm(400) == 300


# --- downloads ---------------------------------------------------------------------------------
def test_first_voice_downloads_the_program_then_the_voice(data_dir, monkeypatch):
    voice = a_voice()
    web = fake_web_for(voice, monkeypatch)
    seen = []
    vid = piper.install_voice(voice.key, lambda d, t, what: seen.append(what), opener=web)
    assert vid == "piper:en_US-lessac-medium"
    assert piper.program_installed() and piper.installed_keys() == [voice.key]
    assert "program" in seen and "voice" in seen
    assert [v.id for v in piper.installed_voices()] == [vid]
    assert not [n for n in os.listdir(piper.voices_dir()) if n.endswith(".part")]
    web.requested.clear()
    piper.install_voice(voice.key, opener=web)  # the program is not downloaded again
    assert not any(u.startswith(piper.RELEASE_URL) for u in web.requested)
    piper.remove_voice(vid)
    assert piper.installed_keys() == []


def test_a_damaged_download_leaves_nothing_behind(data_dir, monkeypatch):
    voice = a_voice()
    web = fake_web_for(voice, monkeypatch, model=b"something else entirely")
    with pytest.raises(ChecksumError):
        piper.install_voice(voice.key, opener=web)
    assert piper.installed_keys() == []
    assert not [n for n in os.listdir(piper.voices_dir()) if n.startswith(voice.key)]


def test_a_cancelled_download_leaves_nothing_behind(data_dir, monkeypatch):
    voice = a_voice()
    web = fake_web_for(voice, monkeypatch)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(DownloadCancelled):
        piper.install_voice(voice.key, cancel=cancel, opener=web)
    assert piper.installed_keys() == [] and not piper.program_installed()


# --- the window -----------------------------------------------------------------------------------
def test_voice_browser_downloads_and_switches_voice(qtbot, data_dir, monkeypatch):
    from ttspython.ui.voice_browser import VoiceBrowser

    voice = a_voice()
    web = fake_web_for(voice, monkeypatch)
    monkeypatch.setattr(piper, "catalog", lambda: [voice])
    dlg = VoiceBrowser("v-zira", installer=lambda key, progress, cancel: piper.install_voice(
        key, progress, cancel, opener=web))
    qtbot.addWidget(dlg)
    assert dlg.selected_key() == voice.key and not dlg.download_btn.isHidden() and dlg.use_btn.isHidden()
    changed, used = [], []
    dlg.voices_changed.connect(lambda: changed.append(1))
    dlg.use_voice.connect(used.append)
    dlg._download()
    qtbot.waitUntil(lambda: bool(changed), timeout=5000)
    assert "Installed" in dlg.list.item(0).text()
    dlg._use()
    assert used == ["piper:en_US-lessac-medium"]
    assert "in use" in dlg.list.item(0).text()
    dlg._remove_selected()  # the voice in use cannot be removed
    assert piper.installed_keys() == [voice.key]


def test_choosing_a_downloaded_voice_updates_the_app(qtbot, tmp_path):
    from test_ui import make_controller

    c = make_controller(qtbot, tmp_path)
    try:
        c.open_settings("speech")
        c._use_voice_from_browser("v-david")
        assert c.speech.voice_id == "v-david" and c.settings["tts_voice_id"] == "v-david"
        assert c._settings_dialog.voice.currentData() == "v-david"
        assert "tts_voice_id" not in c._settings_dialog._read_fields()
        c._settings_action("add_voices")
        assert c._voice_browser is not None
        c._voice_browser.close()
        assert wait_for(lambda: c._voice_browser is None or not c._voice_browser.isVisible(), timeout=2)
    finally:
        c.quit()
