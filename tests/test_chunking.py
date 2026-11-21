import pytest

from aurai_knowledge.chunking import chunk_text


def test_splits_on_headings_and_records_section_path():
    text = "# Policy\n\nIntro.\n\n## Refunds\n\nRefund text.\n\n## Weather\n\nWeather text."
    chunks = chunk_text(text)
    assert [c.section for c in chunks] == ["Policy", "Policy > Refunds", "Policy > Weather"]
    assert chunks[1].text == "Refund text."


def test_long_section_is_packed_below_the_limit_with_overlap():
    paragraphs = [f"Paragraph {i} " + "word " * 40 for i in range(8)]
    chunks = chunk_text("\n\n".join(paragraphs), max_chars=500, overlap=80)
    assert len(chunks) > 1
    assert all(len(c.text) <= 500 for c in chunks)
    # the start of each chunk repeats the tail of the previous one
    assert chunks[1].text.split("\n\n")[0] in chunks[0].text


def test_single_long_sentence_is_split_on_words():
    chunks = chunk_text("lorem " * 400, max_chars=300, overlap=0)
    assert len(chunks) > 1
    assert all(len(c.text) <= 300 for c in chunks)


def test_empty_text_produces_no_chunks():
    assert chunk_text("   \n\n  ") == []


@pytest.mark.parametrize("max_chars,overlap", [(50, 0), (300, 300), (300, -1)])
def test_rejects_unusable_sizes(max_chars, overlap):
    with pytest.raises(ValueError):
        chunk_text("text", max_chars=max_chars, overlap=overlap)
