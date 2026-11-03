from ttspython.core.chunking import split_chunks, utf16_len, FIRST_MAX, CHUNK_MAX


def test_chunks_cover_text_in_order():
    text = "Hello there. This is the second sentence! And a third? Yes."
    chunks = split_chunks(text)
    assert [c.text for c in chunks][0] == "Hello there."
    for c in chunks:
        assert text[c.start:c.end] == c.text
    assert all(a.end <= b.start for a, b in zip(chunks, chunks[1:]))
    joined = " ".join(c.text for c in chunks)
    assert joined.split() == text.split()


def test_first_chunk_is_short_and_others_bounded():
    text = ("word " * 200).strip() + ". " + ("other " * 120).strip() + "."
    chunks = split_chunks(text)
    assert len(chunks[0].text) <= FIRST_MAX
    assert all(len(c.text) <= CHUNK_MAX for c in chunks)
    assert " ".join(c.text for c in chunks).split() == text.split()


def test_newlines_split_paragraphs():
    chunks = split_chunks("Title line\n\nBody text goes here and is long enough to stand alone.")
    assert chunks[0].text == "Title line"


def test_base_offset_is_added():
    chunks = split_chunks("Abc. Def ghi jkl mno pqr stu.", base16=100)
    assert chunks[0].pos16 == 100
    assert chunks[1].pos16 == 105


def test_utf16_positions_account_for_emoji():
    text = "\U0001F600 Smile now. Then this sentence follows."
    chunks = split_chunks(text)
    second = chunks[1]
    assert second.pos16 == utf16_len(text[:second.start])
    assert second.pos16 == second.start + 1  # the emoji is 2 UTF-16 units


def test_empty_text_has_no_chunks():
    assert split_chunks("   \n  ") == []
