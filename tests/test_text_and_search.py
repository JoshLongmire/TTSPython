import pytest

from ttspython.core import search, textio
from ttspython.core.transcript import normalize_transcript_text


@pytest.mark.parametrize("raw", [
    b"line one\r\nline two\r\n",
    b"line one\nline two",
    "caf\u00e9 \u2014 r\u00e9sum\u00e9\n".encode("utf-8"),
    b"\xef\xbb\xbfbom file\r\n",
    "smart \u201cquotes\u201d".encode("cp1252"),
])
def test_open_then_save_is_byte_identical(tmp_path, raw):
    path = tmp_path / "doc.txt"
    path.write_bytes(raw)
    doc = textio.read_text_file(str(path))
    textio.write_text_file(str(path), doc.text, doc.encoding, doc.newline, doc.bom)
    assert path.read_bytes() == raw
    doc2 = textio.read_text_file(str(path))
    textio.write_text_file(str(path), doc2.text, doc2.encoding, doc2.newline, doc2.bom)
    assert path.read_bytes() == raw


def test_editor_text_uses_lf():
    assert textio.decode_text(b"a\r\nb").text == "a\nb"


def test_regex_find_returns_real_match_length():
    assert search.find_next("caaat", "a+", 0, use_regex=True) == (1, 4, False)


def test_find_wraps_and_backwards():
    text = "one two one"
    assert search.find_next(text, "one", 1) == (8, 11, False)
    assert search.find_next(text, "one", 9) == (0, 3, True)
    assert search.find_next(text, "one", 8, backwards=True) == (0, 3, False)
    assert search.find_next(text, "one", 0, backwards=True) == (8, 11, True)
    assert search.find_next(text, "zzz", 0) is None


def test_case_sensitivity():
    assert search.find_next("Hello", "hello", 0) == (0, 5, False)
    assert search.find_next("Hello", "hello", 0, case_sensitive=True) is None


def test_literal_replace_all_keeps_backslashes():
    new, count = search.replace_all("path OLD and old", "old", r"C:\new\1", case_sensitive=False)
    assert new == r"path C:\new\1 and C:\new\1"
    assert count == 2


def test_regex_replace_all_uses_groups():
    new, count = search.replace_all("a1 b2", r"([a-z])(\d)", r"\2\1", use_regex=True)
    assert (new, count) == ("1a 2b", 2)


def test_invalid_regex_raises_search_error():
    with pytest.raises(search.SearchError):
        search.find_next("x", "(", 0, use_regex=True)


def test_transcript_normalization():
    assert normalize_transcript_text("  hello   world ") == "Hello world."
    assert normalize_transcript_text("are you there?") == "Are you there?"
    assert normalize_transcript_text("") == ""


def test_find_bar_counts_matches(qtbot):
    from ttspython.ui.editor import FindBar, SpeechTextEdit

    editor = SpeechTextEdit()
    qtbot.addWidget(editor)
    bar = FindBar(editor)
    qtbot.addWidget(bar)
    editor.setPlainText("one cat, two cats, three CATS and a dog")
    bar.find_edit.setText("cat")
    qtbot.waitUntil(lambda: bar.status.text() == "3 matches", timeout=2000)
    bar.find(False)
    assert bar.status.text() == "1 of 3"
    bar.find(False)
    assert bar.status.text() == "2 of 3"
    bar.case_btn.setChecked(True)
    qtbot.waitUntil(lambda: bar.status.text() in ("2 matches", "2 of 2"), timeout=2000)
    bar.find_edit.setText("zebra")
    qtbot.waitUntil(lambda: bar.status.text() == "No matches", timeout=2000)


def test_positions_map_fast_without_emoji_and_right_with_them():
    from ttspython.ui.editor import py_to_u16, u16_to_py

    plain = "word " * 200_000  # 1 MB
    assert u16_to_py(plain, 500_000) == 500_000
    emoji = "a\U0001F600b"
    assert u16_to_py(emoji, 3) == 2 and py_to_u16(emoji, 2) == 3
