"""Extraction: turn ingested chunks into structured, embedded facts.

The extractor below is rule-based on purpose: it runs offline, is deterministic,
and is trivial to reason about while you build out the rest of the system. Swap
`extract_candidates` for an LLM call when you are ready -- the rest of the module
(persistence, embedding, dedupe) does not need to change.
"""

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embeddings import embed_text
from app.extraction.home_inspection import extract_home_systems
from app.extraction.models import Fact, HomeSystemRecord
from app.ingestion import service as ingestion_service

# "Label: value" lines, e.g. "Revenue: $4.2M". A dash only separates when it is
# surrounded by whitespace -- otherwise hyphenated prose ("ship self-serve
# onboarding, ...") reads as a label/value pair.
_KEY_VALUE_RE = re.compile(r"^\s*([A-Z][\w \-/&']{2,60}?)\s*(?::|\s[–-]\s)\s*(.+?)\s*$")
# Markdown headings: structure, not claims.
_HEADING_RE = re.compile(r"^\s*#{1,6}\s")
# Sentence boundary: ., ! or ? followed by whitespace.
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_NUMBER_RE = re.compile(r"\d")
# Shorter fragments are usually headings or list bullets, not claims.
_MIN_SENTENCE_WORDS = 4
_WHITESPACE_RE = re.compile(r"\s+")
# Kinds derived from splitting prose into sentences. These are the ones a chunk
# boundary can cut in half, leaving a fragment of the claim in each neighbour.
# "Label: value" attributes are matched per line, so they survive intact.
_SENTENCE_KINDS = frozenset({"metric", "statement"})


@dataclass(frozen=True)
class Candidate:
    """An extracted claim before it is embedded and stored."""

    label: str
    value: str
    kind: str
    confidence: float


def extract_candidates(text: str) -> list[Candidate]:
    """Pull candidate facts out of a single chunk of text."""
    candidates: list[Candidate] = []
    seen: set[tuple[str, str]] = set()

    def add(label: str, value: str, kind: str, confidence: float) -> None:
        label, value = label.strip(), value.strip()
        if not label or not value:
            return
        key = (label.lower(), value.lower())
        if key in seen:
            return
        seen.add(key)
        candidates.append(
            Candidate(label=label[:200], value=value, kind=kind, confidence=confidence)
        )

    # Prose is gathered into blocks split at headings, rather than one flat run.
    # A heading is structure, not a claim, and it carries no terminating
    # punctuation -- left in the stream it would both contribute its own text and
    # glue itself onto the sentence below, since sentences only break on ".!?".
    # Ending the block at a heading also stops prose either side of it from
    # merging when the preceding line happens to lack closing punctuation.
    prose_blocks: list[list[str]] = [[]]
    for line in text.splitlines():
        if _HEADING_RE.match(line):
            prose_blocks.append([])
            continue
        match = _KEY_VALUE_RE.match(line)
        if match:
            add(match.group(1), match.group(2), "attribute", 0.8)
        else:
            prose_blocks[-1].append(line)

    # Only the leftover prose is scanned for sentences. A "Label: value" line is
    # already an attribute, and re-scanning it emits the same claim a second time
    # under a different kind -- worse when the line has no closing punctuation,
    # since consecutive lines then merge into one bogus candidate.
    for block in prose_blocks:
        for sentence in _SENTENCE_RE.split("\n".join(block)):
            sentence = sentence.strip()
            if len(sentence.split()) < _MIN_SENTENCE_WORDS:
                continue
            # Sentences containing figures are the ones worth keeping for reporting.
            if _NUMBER_RE.search(sentence):
                add(_summarise(sentence), sentence, "metric", 0.6)
            else:
                add(_summarise(sentence), sentence, "statement", 0.4)

    return candidates


def _summarise(sentence: str, max_words: int = 8) -> str:
    words = sentence.split()
    label = " ".join(words[:max_words])
    return label if len(words) <= max_words else f"{label}..."


def _normalise(text: str) -> str:
    """Fold whitespace and case so wrapping differences compare equal.

    Chunks keep their line breaks, so the same sentence can arrive wrapped in two
    places -- "grew 24%\nquarter over quarter" against "grew 24% quarter over
    quarter". Without folding, those read as two distinct claims.
    """
    return _WHITESPACE_RE.sub(" ", text).strip().lower()


def dedupe_candidates(
    pairs: list[tuple[uuid.UUID, Candidate]],
) -> list[tuple[uuid.UUID, Candidate]]:
    """Collapse candidates that repeat a claim already seen in another chunk.

    Chunks overlap by design, so a claim near a boundary is extracted twice. The
    two copies are rarely identical: the boundary falls mid-sentence, so one side
    holds a truncated fragment ("Leadership will revisit pricing in November once
    the") and the other the whole sentence. Comparing exact text keeps both.

    For sentence-derived kinds a candidate whose text is contained in another's is
    therefore treated as a partial view of the same claim, and the longer text
    wins -- it carries the complete sentence and the chunk that held all of it.
    Containment is deliberately not applied to attributes: their values are short
    ("5", "32"), and a bare number turns up inside unrelated values often enough
    that it would discard real facts.

    Quadratic in the candidate count, which runs to tens per document.
    """
    kept: list[tuple[uuid.UUID, Candidate]] = []

    for chunk_id, candidate in pairs:
        value = _normalise(candidate.value)
        if not value:
            continue

        supersedes: int | None = None
        duplicate = False

        for index, (_, existing) in enumerate(kept):
            if existing.kind != candidate.kind:
                continue
            other = _normalise(existing.value)
            if value == other:
                duplicate = True
                break
            if candidate.kind not in _SENTENCE_KINDS:
                continue
            if value in other:
                duplicate = True
                break
            if other in value:
                supersedes = index
                break

        if duplicate:
            continue
        if supersedes is not None:
            kept[supersedes] = (chunk_id, candidate)
            continue
        kept.append((chunk_id, candidate))

    return kept


async def extract_document(session: AsyncSession, document_id: uuid.UUID) -> list[Fact]:
    """Re-extract facts for a document, replacing any previous run."""
    chunks = await ingestion_service.get_chunks(session, document_id)
    if not chunks:
        return []

    # Idempotent: a re-run should not double up facts.
    await session.execute(delete(Fact).where(Fact.document_id == document_id))

    # Extract everything first, then dedupe across the whole document: a claim cut
    # by a chunk boundary is only recognisable as a duplicate once both halves are
    # in hand, and the later, more complete copy is the one worth keeping.
    extracted = [
        (chunk.id, candidate)
        for chunk in chunks
        for candidate in extract_candidates(chunk.content)
    ]

    facts = [
        _build_fact(document_id, chunk_id, candidate)
        for chunk_id, candidate in dedupe_candidates(extracted)
    ]

    for fact in facts:
        session.add(fact)

    document = await ingestion_service.get_document(session, document_id)
    if document is not None:
        document.status = "extracted"

    await session.commit()
    for fact in facts:
        await session.refresh(fact)
    return facts


def _build_fact(document_id: uuid.UUID, chunk_id: uuid.UUID, candidate: Candidate) -> Fact:
    return Fact(
        document_id=document_id,
        chunk_id=chunk_id,
        label=candidate.label,
        value=candidate.value,
        kind=candidate.kind,
        confidence=candidate.confidence,
        embedding=embed_text(f"{candidate.label}\n{candidate.value}"),
    )


async def list_facts(
    session: AsyncSession,
    document_id: uuid.UUID | None = None,
    limit: int = 200,
) -> list[Fact]:
    query = select(Fact).order_by(Fact.confidence.desc(), Fact.created_at).limit(limit)
    if document_id is not None:
        query = query.where(Fact.document_id == document_id)
    result = await session.execute(query)
    return list(result.scalars())


async def extract_home_report(
    session: AsyncSession, document_id: uuid.UUID
) -> list[HomeSystemRecord] | None:
    """Run the AI Home Health Report extraction for a document, replacing any
    previous run for it.

    Unlike `extract_document`, this reads the document's whole content in one
    call rather than per-chunk: a system's age, condition, and findings can be
    scattered across a report, and Claude reads the full picture at once
    instead of the chunk-by-chunk, dedupe-afterward approach the rule-based
    extractor needs. Returns None if the document does not exist; raises
    ExtractionError (see home_inspection.py) if Claude could not be reached or
    refused the request.
    """
    document = await ingestion_service.get_document(session, document_id)
    if document is None:
        return None

    report = extract_home_systems(document.content)

    # Idempotent: a re-run should not double up systems.
    await session.execute(
        delete(HomeSystemRecord).where(HomeSystemRecord.document_id == document_id)
    )

    records = [
        HomeSystemRecord(
            document_id=document_id,
            name=system.name,
            estimated_age_years=system.estimated_age.years,
            estimated_age_confidence=system.estimated_age.confidence,
            condition=system.condition.rating,
            condition_confidence=system.condition.confidence,
            findings=system.findings.items,
            findings_confidence=system.findings.confidence,
        )
        for system in report.systems
    ]

    for record in records:
        session.add(record)

    await session.commit()
    for record in records:
        await session.refresh(record)
    return records


async def get_home_report(session: AsyncSession, document_id: uuid.UUID) -> list[HomeSystemRecord]:
    query = select(HomeSystemRecord).where(HomeSystemRecord.document_id == document_id)
    result = await session.execute(query)
    return list(result.scalars())
