"""Instant captions in French and Chinese. Models are faked here; real ones are tried by hand."""
import hashlib
import io
import os
import tarfile
import types

import pytest

from fakes import wait_for
from test_live_captions import make
from ttspython.core.stt import preview, service
from ttspython.ui.mini import LiveCaption

REAL_INSTALLED, REAL_INSTALL = preview.installed, preview.install  # conftest stops downloads in other tests


@pytest.mark.parametrize("language, wanted", [("en", True), ("fr", True), ("zh", True), ("es", False), ("de", False),
                                              ("auto", False)])
def test_the_languages_with_a_preview(language, wanted):
    svc, _model, _events = make()
    try:
        svc.language = language
        assert svc.preview_wanted() is wanted
    finally:
        svc.shutdown()


def result(tokens):
    return types.SimpleNamespace(tokens=tokens, timestamps=[i * 0.1 for i in range(len(tokens))], start_time=1.0)


def words(tokens, language="en"):
    return [w for w, _t in preview.PreviewSession._timed(result(tokens), language)]


def test_a_token_that_is_only_a_space_ends_the_word():
    assert words([" HAVE", " ", "VEGE", "TARIAN"]) == ["have", "vegetarian"]


def test_english_words_are_still_built_from_their_tokens():
    assert words([" I", " WENT", " TO", " TH", "E", " I'M"]) == ["I", "went", "to", "the", "I'm"]


def test_french_is_lower_case_with_its_apostrophes():
    assert words([" L'HIST", "OIRE", " I"], "fr") == ["l'histoire", "i"]


def test_each_chinese_character_keeps_its_own_time():
    timed = preview.PreviewSession._timed(result([" 你", " 好", "世", "界", " HELLO"]), "zh")
    assert [w for w, _t in timed] == ["你", "好", "世", "界", "hello"]
    assert [round(t, 1) for _w, t in timed] == [1.0, 1.1, 1.2, 1.3, 1.4]


def test_units_split_chinese_and_leave_other_words_alone():
    assert preview.units("hello 你好，世界 ok") == ["hello", "你", "好", "，", "世", "界", "ok"]
    assert preview.units("l'histoire est-ce") == ["l'histoire", "est-ce"]


def test_the_seam_with_whisper_works_in_chinese():
    assert service._after_overlap("你好，世界", ["世", "界", "再", "见"]) == (["再", "见"], False)


def test_the_seam_with_whisper_handles_french_apostrophes():
    assert service._after_overlap("c’est l’histoire", ["c'est", "l'histoire", "de"]) == (["de"], False)


def test_english_seams_are_unchanged():
    assert service._after_overlap("the week and", ["week", "and", "we", "could"]) == (["we", "could"], False)


def test_hiding_a_guess_does_not_empty_chinese_text():
    assert service._without_last_word("你好世界") == "你好世"
    assert service._without_last_word("boards are so") == "boards are"
    assert service._without_last_word("one") == ""


def test_the_bubble_shows_chinese_without_spaces_and_wraps_it(qtbot):
    cap = LiveCaption()
    qtbot.addWidget(cap)
    cap.set_words("你好", "世界", "再见")
    assert [w for w, _k in cap.lines()[0]] == ["你", "好", "世", "界", "再", "见"]
    assert "好</span><span" in cap.text.text()
    cap.set_words("字" * 400, "", "")
    assert len(cap.lines()) == cap.LINES
    assert cap.width() <= cap.MAX_WIDTH


def test_other_languages_in_the_bubble_keep_their_spaces(qtbot):
    cap = LiveCaption()
    qtbot.addWidget(cap)
    cap.set_words("bonjour", "tout", "le monde")
    assert "</span> <span" in cap.text.text()


# --- downloads ---------------------------------------------------------------------------------
def fake_archive(files):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:bz2") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(f"model/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class Response(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


def entry(name, data):
    return (name, len(data), hashlib.sha256(data).hexdigest())


@pytest.fixture
def archived(monkeypatch):
    contents = {"encoder.onnx": b"encoder", "tokens.txt": b"tokens"}
    blob = fake_archive({**contents, "test_wavs/0.wav": b"not wanted"})
    model = preview.Model("fake-zh", {"encoder": entry("encoder.onnx", b"encoder"), "tokens": entry("tokens.txt", b"tokens")},
                          archive=("https://example.test/m.tar.bz2", len(blob), hashlib.sha256(blob).hexdigest()))
    monkeypatch.setitem(preview.MODELS, "zh", model)
    monkeypatch.setattr(preview, "installed", REAL_INSTALLED)
    monkeypatch.setattr(preview, "install", REAL_INSTALL)
    yield blob
    preview.remove()


def test_a_model_in_an_archive_is_unpacked_and_the_archive_removed(archived):
    assert not preview.installed("zh")
    seen = []
    folder = preview.install(lambda done, total: seen.append(total), language="zh",
                             opener=lambda url, timeout: Response(archived))
    assert preview.installed("zh") and preview.any_installed()
    assert sorted(os.listdir(folder)) == ["encoder.onnx", "tokens.txt"]
    assert not preview.installed("en")
    assert preview.size_on_disk() == len(b"encoder") + len(b"tokens")


def test_a_changed_archive_is_refused(archived):
    with pytest.raises(Exception):  # noqa: B017
        preview.install(language="zh", opener=lambda url, timeout: Response(archived + b"x"))
    assert not preview.installed("zh")
    assert preview.size_on_disk() == 0


def test_a_damaged_file_inside_the_archive_is_refused(archived, monkeypatch):
    model = preview.MODELS["zh"]
    bad = model._replace(files={**model.files, "tokens": entry("tokens.txt", b"other")})
    monkeypatch.setitem(preview.MODELS, "zh", bad)
    with pytest.raises(ValueError, match="damaged|lacks"):
        preview.install(language="zh", opener=lambda url, timeout: Response(archived))
    assert not preview.installed("zh")


def test_an_archive_lacking_a_file_is_refused(archived, monkeypatch):
    model = preview.MODELS["zh"]
    more = model._replace(files={**model.files, "joiner": entry("joiner.onnx", b"joiner")})
    monkeypatch.setitem(preview.MODELS, "zh", more)
    with pytest.raises(ValueError, match="lacks joiner.onnx"):
        preview.install(language="zh", opener=lambda url, timeout: Response(archived))


def test_removing_clears_every_language(archived):
    preview.install(language="zh", opener=lambda url, timeout: Response(archived))
    assert preview.remove() == len(b"encoder") + len(b"tokens")
    assert not preview.any_installed()


def test_one_language_failing_does_not_stop_another(monkeypatch):
    svc, _model, events = make()
    try:
        monkeypatch.setattr(preview, "available", lambda: True)
        monkeypatch.setattr(preview, "installed", lambda language="en": False)
        asked = []

        def install(progress=None, language="en", **_kw):
            asked.append(language)
            if language == "fr":
                raise OSError("no network")

        monkeypatch.setattr(preview, "install", install)
        svc.language = "fr"
        svc._install_preview()
        assert wait_for(lambda: "fr" in svc._preview_failed, timeout=5)
        assert wait_for(lambda: not svc._preview_installing, timeout=5)
        svc._install_preview()
        svc.language = "zh"
        svc._install_preview()
        assert wait_for(lambda: asked.count("zh") == 1, timeout=5)
        assert asked.count("fr") == 1  # not asked again
    finally:
        svc.shutdown()


def test_only_one_recognizer_is_kept(monkeypatch):
    made = []
    monkeypatch.setattr(preview.PreviewSession, "create_recognizer",
                        staticmethod(lambda folder=None, language="en": made.append(language) or language))
    preview.release()
    try:
        assert preview.shared_recognizer("fr") == "fr"
        assert preview.shared_recognizer("fr") == "fr"
        assert preview.shared_recognizer("zh") == "zh"
        assert made == ["fr", "zh"]
    finally:
        preview.release()
