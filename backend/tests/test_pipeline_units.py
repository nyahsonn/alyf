"""Unit tests for the pure logic in each module. No database required.

Run with:  pytest
"""

from app.core.embeddings import embed_text
from app.core.config import settings
from app.extraction.service import extract_candidates
from app.ingestion.service import split_into_chunks


def test_chunker_returns_nothing_for_blank_text():
    assert split_into_chunks("   \n  ") == []


def test_chunker_keeps_short_text_in_one_chunk():
    chunks = split_into_chunks("hello world", size_words=10, overlap_words=2)
    assert chunks == ["hello world"]


def test_chunker_overlaps_windows():
    text = " ".join(str(number) for number in range(10))
    chunks = split_into_chunks(text, size_words=4, overlap_words=1)
    assert chunks[0] == "0 1 2 3"
    # Step is size - overlap = 3, so the next window starts at index 3.
    assert chunks[1] == "3 4 5 6"
    assert " ".join(chunks[-1].split()[-1:]) == "9"


def test_chunker_preserves_line_breaks():
    # Extraction reads "Label: value" line by line, so chunking must not flatten
    # the text onto a single line.
    text = "Quarter: Q3 2026\nOwner: Priya Raman"
    chunks = split_into_chunks(text, size_words=20, overlap_words=0)
    assert chunks == [text]
    labels = {candidate.label for candidate in extract_candidates(chunks[0])}
    assert {"Quarter", "Owner"} <= labels


def test_extractor_finds_key_value_lines():
    candidates = extract_candidates("Revenue: $4.2M\nHeadcount: 32")
    labels = {candidate.label for candidate in candidates}
    assert "Revenue" in labels
    assert "Headcount" in labels
    assert all(candidate.kind == "attribute" for candidate in candidates)


def test_extractor_classifies_sentences_with_numbers_as_metrics():
    text = "The team shipped 14 releases this quarter. Morale improved noticeably across the board."
    kinds = {candidate.kind for candidate in extract_candidates(text)}
    assert "metric" in kinds
    assert "statement" in kinds


def test_embedding_has_configured_width_and_unit_length():
    vector = embed_text("alyf turns documents into reports")
    assert len(vector) == settings.embedding_dimensions
    magnitude = sum(value * value for value in vector) ** 0.5
    assert abs(magnitude - 1.0) < 1e-6


def test_embedding_is_deterministic():
    assert embed_text("same input") == embed_text("same input")


def test_similar_text_scores_higher_than_unrelated_text():
    def cosine(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b))

    query = embed_text("quarterly revenue growth")
    related = embed_text("revenue growth for the quarter was strong")
    unrelated = embed_text("the office cat is named biscuit")
    assert cosine(query, related) > cosine(query, unrelated)
