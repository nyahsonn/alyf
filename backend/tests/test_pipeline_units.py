"""Unit tests for the pure logic in each module. No database required.

Run with:  pytest
"""

import uuid
from dataclasses import dataclass

from app.core.embeddings import embed_text
from app.core.config import settings
from app.extraction.models import Fact
from app.extraction.service import Candidate, dedupe_candidates, extract_candidates
from app.ingestion.ocr import _remove_spans
from app.ingestion.service import looks_like_pdf, render_tables, split_into_chunks
from app.reasoning.service import compose_answer


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


def test_extractor_excludes_heading_text_from_facts():
    text = "## Highlights\n\nRevenue reached $4.2M this quarter, up 18% from Q2."
    candidates = extract_candidates(text)
    assert [candidate.value for candidate in candidates] == [
        "Revenue reached $4.2M this quarter, up 18% from Q2."
    ]
    # The heading must not survive in the label either -- labels are derived
    # from the sentence, and a report renders them verbatim.
    assert "Highlights" not in candidates[0].label


def test_extractor_does_not_merge_prose_across_a_heading():
    # The line before the heading has no closing punctuation, so dropping the
    # heading without ending the block would fuse the two sentences into one.
    text = "The rollout slipped by 3 weeks\n\n## Risks\n\nHiring is behind plan by 5 roles."
    values = [candidate.value for candidate in extract_candidates(text)]
    assert "The rollout slipped by 3 weeks" in values
    assert "Hiring is behind plan by 5 roles." in values
    assert not any("Risks" in value for value in values)


def test_extractor_ignores_hashes_that_are_not_headings():
    # A heading needs whitespace after the hashes; "#3" is part of the claim.
    text = "Support ticket #3 was closed after 2 days."
    values = [candidate.value for candidate in extract_candidates(text)]
    assert values == ["Support ticket #3 was closed after 2 days."]


def _pair(value: str, kind: str = "metric", chunk_id: uuid.UUID | None = None):
    return (chunk_id or uuid.uuid4(), Candidate(_summary(value), value, kind, 0.6))


def _summary(value: str) -> str:
    return " ".join(value.split()[:8])


def test_dedupe_drops_exact_repeats():
    value = "Revenue reached $4.2M this quarter, up 18% from Q2."
    kept = dedupe_candidates([_pair(value), _pair(value)])
    assert len(kept) == 1


def test_dedupe_ignores_wrapping_differences():
    # Chunks keep line breaks, so the same sentence can wrap in two places.
    wrapped = "Infrastructure costs grew 24%\nquarter over quarter."
    flat = "Infrastructure costs grew 24% quarter over quarter."
    kept = dedupe_candidates([_pair(wrapped), _pair(flat)])
    assert len(kept) == 1


def test_dedupe_drops_fragment_truncated_by_a_chunk_boundary():
    # The overlap window starts mid-sentence, so chunk 2 holds a suffix of chunk 1.
    whole = "The team plans to ship self-serve onboarding and fill 3 of 5 open roles."
    suffix = "plans to ship self-serve onboarding and fill 3 of 5 open roles."
    kept = dedupe_candidates([_pair(whole), _pair(suffix)])
    assert [candidate.value for _, candidate in kept] == [whole]


def test_dedupe_prefers_the_complete_sentence_over_an_earlier_fragment():
    # A chunk ending mid-sentence yields a prefix; the next chunk has all of it.
    prefix = "Leadership will revisit pricing in November once the"
    whole = "Leadership will revisit pricing in November once the funnel has 4 weeks of data."
    later_chunk = uuid.uuid4()
    kept = dedupe_candidates(
        [_pair(prefix), _pair(whole, chunk_id=later_chunk)]
    )
    assert [candidate.value for _, candidate in kept] == [whole]
    # The surviving fact is attributed to the chunk that held the whole sentence.
    assert [chunk_id for chunk_id, _ in kept] == [later_chunk]


def test_dedupe_keeps_attributes_whose_values_nest():
    # "5" reads as a substring of "15" but they are different facts, so
    # containment must not apply to attributes.
    kept = dedupe_candidates(
        [
            (uuid.uuid4(), Candidate("Open roles", "5", "attribute", 0.8)),
            (uuid.uuid4(), Candidate("Target", "15", "attribute", 0.8)),
        ]
    )
    assert len(kept) == 2


def test_dedupe_keeps_distinct_claims():
    kept = dedupe_candidates(
        [
            _pair("Revenue reached $4.2M this quarter, up 18% from Q2."),
            _pair("Churn fell to 1.4% monthly, down from 2.1%."),
        ]
    )
    assert len(kept) == 2


def _fact(value: str, kind: str = "metric"):
    # A transient SQLAlchemy instance -- compose_answer only reads attributes.
    return Fact(label=_summary(value), value=value, kind=kind, confidence=0.6)


def test_compose_answer_leads_with_the_finding_not_the_question():
    # Callers preview an answer by its first line, and the question is already
    # rendered beside it, so the opening line must carry the answer.
    answer = compose_answer(
        "what happened to revenue?",
        [(_fact("Revenue reached $4.2M this quarter, up 18% from Q2."), 0.15)],
    )
    first = answer.splitlines()[0]
    assert first == "Revenue reached $4.2M this quarter, up 18% from Q2."
    assert "what happened to revenue?" not in first


def test_compose_answer_flattens_newlines_in_values():
    # Chunking preserves line breaks, so a value can span lines. Previews take
    # the first line, which would otherwise cut the sentence in half.
    answer = compose_answer(
        "how many accounts?",
        [(_fact("The team closed 27 new\naccounts, the highest count ever."), 0.2)],
    )
    assert answer.splitlines()[0] == "The team closed 27 new accounts, the highest count ever."


def test_compose_answer_lists_every_match_with_scores():
    answer = compose_answer(
        "how did the quarter go?",
        [
            (_fact("Revenue reached $4.2M this quarter."), 0.15),
            (_fact("Churn fell to 1.4% monthly."), 0.11),
        ],
    )
    assert "1. [metric, relevance 0.15] Revenue reached $4.2M this quarter." in answer
    assert "2. [metric, relevance 0.11] Churn fell to 1.4% monthly." in answer


def test_compose_answer_explains_when_nothing_matched():
    answer = compose_answer("what happened to revenue?", [])
    assert "No relevant facts were found" in answer


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


@dataclass(frozen=True)
class _FakeTable:
    """Stands in for ocr.Table.

    `render_tables` reads these three fields and nothing else, so the suite
    stays free of the Document AI client library and its credentials.
    """

    page_number: int
    header_rows: list[list[str]]
    body_rows: list[list[str]]


def test_removing_table_spans_merges_overlaps_and_closes_the_gap():
    # Document AI can report spans that overlap or nest; cutting them one at a
    # time would shift every offset after the first cut.
    text = "Intro line.\n\nAAA\nBBB\n\nClosing line."
    assert _remove_spans(text, [(13, 17), (16, 20)]) == "Intro line.\n\nClosing line."


def test_pdf_is_detected_from_its_bytes_not_its_name():
    assert looks_like_pdf(b"%PDF-1.7\n...")
    assert not looks_like_pdf(b"Quarter: Q3 2026")


def test_wide_table_folds_the_column_header_into_the_label():
    rendered = render_tables(
        [
            _FakeTable(
                page_number=2,
                header_rows=[["Metric", "Q1", "Q2"]],
                body_rows=[["Revenue", "4.2M", "5.1M"], ["Headcount", "38", "44"]],
            )
        ]
    )
    lines = rendered.splitlines()
    assert lines[0] == "## Table 1 (page 2)"
    assert "Revenue Q1: 4.2M" in lines
    assert "Revenue Q2: 5.1M" in lines
    assert "Headcount Q2: 44" in lines


def test_two_column_table_uses_the_row_label_alone():
    # Already a label/value pair -- folding "Value" in would only add noise.
    rendered = render_tables(
        [
            _FakeTable(
                page_number=1,
                header_rows=[["Field", "Value"]],
                body_rows=[["Invoice date", "2026-08-07"]],
            )
        ]
    )
    assert "Invoice date: 2026-08-07" in rendered.splitlines()


def test_rendered_table_extracts_as_attributes_not_one_merged_claim():
    # The point of rendering at all: raw OCR puts each cell on its own line with
    # no punctuation, so the extractor would glue the whole table into a single
    # bogus "metric". Label/value lines under a heading extract cleanly instead.
    rendered = render_tables(
        [
            _FakeTable(
                page_number=1,
                header_rows=[["Metric", "Q1"]],
                body_rows=[["Revenue", "4.2M"], ["Headcount", "38"]],
            )
        ]
    )
    candidates = extract_candidates(rendered)
    assert {candidate.kind for candidate in candidates} == {"attribute"}
    assert {candidate.label for candidate in candidates} == {"Revenue", "Headcount"}
