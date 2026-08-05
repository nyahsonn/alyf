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
from app.extraction.models import Fact
from app.ingestion import service as ingestion_service
from app.ingestion.models import Chunk

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

    prose_lines: list[str] = []
    for line in text.splitlines():
        match = _KEY_VALUE_RE.match(line)
        if match:
            add(match.group(1), match.group(2), "attribute", 0.8)
        else:
            prose_lines.append(line)

    # Only the leftover prose is scanned for sentences. A "Label: value" line is
    # already an attribute, and re-scanning it emits the same claim a second time
    # under a different kind -- worse when the line has no closing punctuation,
    # since consecutive lines then merge into one bogus candidate.
    for sentence in _SENTENCE_RE.split("\n".join(prose_lines)):
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


async def extract_document(session: AsyncSession, document_id: uuid.UUID) -> list[Fact]:
    """Re-extract facts for a document, replacing any previous run."""
    chunks = await ingestion_service.get_chunks(session, document_id)
    if not chunks:
        return []

    # Idempotent: a re-run should not double up facts.
    await session.execute(delete(Fact).where(Fact.document_id == document_id))

    facts: list[Fact] = []
    seen: set[tuple[str, str]] = set()

    for chunk in chunks:
        for candidate in extract_candidates(chunk.content):
            key = (candidate.label.lower(), candidate.value.lower())
            if key in seen:
                continue  # overlapping chunks produce duplicate candidates
            seen.add(key)
            facts.append(_build_fact(document_id, chunk, candidate))

    for fact in facts:
        session.add(fact)

    document = await ingestion_service.get_document(session, document_id)
    if document is not None:
        document.status = "extracted"

    await session.commit()
    for fact in facts:
        await session.refresh(fact)
    return facts


def _build_fact(document_id: uuid.UUID, chunk: Chunk, candidate: Candidate) -> Fact:
    return Fact(
        document_id=document_id,
        chunk_id=chunk.id,
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
