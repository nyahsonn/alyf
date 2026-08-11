"""Extraction: turn ingested chunks into structured, embedded facts.

The extractor below is rule-based on purpose: it runs offline, is deterministic,
and is trivial to reason about while you build out the rest of the system. Swap
`extract_candidates` for an LLM call when you are ready -- the rest of the module
(persistence, embedding, dedupe) does not need to change.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service as auth_service
from app.core.embeddings import embed_text
from app.extraction.action_plan import generate_action_plan
from app.extraction.home_inspection import extract_home_systems
from app.extraction.models import ActionItem, Fact, Finding, Home, InspectionEvent, SystemRecord
from app.ingestion import service as ingestion_service

# Terminal review states -- a report in either one has cleared the
# pending_review gate and is visible to its buyer. See InspectionEvent's
# docstring for why there's no separate third "sent" state.
_VISIBLE_STATUSES = ("approved", "auto_sent")

# Most-urgent-first, used to sort a returned action plan before persisting it
# -- the prompt asks Claude to already order items this way, but the read
# order is enforced here rather than trusted blindly.
_URGENCY_RANK = {"next_90_days": 0, "next_2_years": 1, "next_5_years": 2}

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


def _normalize_address(address: str) -> str:
    """Fold whitespace/case so a home lookup does not care about formatting noise.

    Not a full address normalizer -- "123 Main St" and "123 Main Street" are
    treated as different homes. Good enough while the only address source is
    a single LLM reading of a report's cover page; revisit if reports for the
    same property turn out not to match in practice.
    """
    return _WHITESPACE_RE.sub(" ", address.strip().lower()).rstrip(".,")


async def _resolve_home(
    session: AsyncSession, address: str | None, inspector_id: uuid.UUID | None
) -> Home:
    """The home this address already belongs to *for this inspector*, or a
    newly created one.

    Scoped by inspector_id as well as address: without that, two different
    inspectors reporting on the same address would resolve to the same Home
    row, and each would see the other's findings through that collision --
    see Home's docstring in extraction/models.py.

    Flushes so the caller can use `home.id` as a foreign key right away --
    these models use bare FK columns rather than relationship kwargs (see
    extraction/models.py), so, unlike `Chunk(document=document, ...)`
    elsewhere in the codebase, SQLAlchemy cannot resolve the id for us later.
    """
    normalized = _normalize_address(address) if address else None
    if normalized is not None:
        existing = await session.scalar(
            select(Home).where(
                Home.normalized_address == normalized, Home.inspector_id == inspector_id
            )
        )
        if existing is not None:
            return existing

    home = Home(address=address, normalized_address=normalized, inspector_id=inspector_id)
    session.add(home)
    await session.flush()
    return home


async def extract_home_report(
    session: AsyncSession, document_id: uuid.UUID
) -> list[SystemRecord] | None:
    """Run the AI Home Health Report extraction for a document, replacing any
    previous run for it.

    Unlike `extract_document`, this reads the document's whole content in one
    call rather than per-chunk: a system's age, condition, and findings can be
    scattered across a report, and Claude reads the full picture at once
    instead of the chunk-by-chunk, dedupe-afterward approach the rule-based
    extractor needs. Returns None if the document does not exist; raises
    ExtractionError (see home_inspection.py) if Claude could not be reached or
    refused the request.

    The extracted address resolves to an existing home (see `_resolve_home`)
    or creates a new one, so multiple inspections of the same property share
    one home row instead of each starting its own.
    """
    document = await ingestion_service.get_document(session, document_id)
    if document is None:
        return None

    report = extract_home_systems(document.content)

    # Idempotent: a re-run should not double up events/systems/findings.
    # Cascades through systems and findings via their ondelete="CASCADE" FKs,
    # so this one delete replaces the whole tree for this document.
    await session.execute(delete(InspectionEvent).where(InspectionEvent.document_id == document_id))

    home = await _resolve_home(session, report.address.address, document.inspector_id)

    event = InspectionEvent(home_id=home.id, document_id=document_id)
    session.add(event)
    await session.flush()

    records = [
        SystemRecord(
            event_id=event.id,
            document_id=document_id,
            name=system.name,
            estimated_age_years=system.estimated_age.years,
            estimated_age_confidence=system.estimated_age.confidence,
            condition=system.condition.rating,
            condition_confidence=system.condition.confidence,
            findings_confidence=system.findings.confidence,
        )
        for system in report.systems
    ]
    for record in records:
        session.add(record)
    await session.flush()

    for record, system in zip(records, report.systems, strict=True):
        for position, text in enumerate(system.findings.items):
            session.add(
                Finding(system_id=record.id, document_id=document_id, text=text, position=position)
            )

    await session.commit()
    for record in records:
        await session.refresh(record)
    return records


async def get_home_report(session: AsyncSession, document_id: uuid.UUID) -> list[SystemRecord]:
    query = select(SystemRecord).where(SystemRecord.document_id == document_id)
    result = await session.execute(query)
    return list(result.scalars())


async def get_finding_records(session: AsyncSession, system_id: uuid.UUID) -> list[Finding]:
    """A system's findings, in their original order, as full rows -- used
    wherever a caller needs each finding's id (e.g. the inspector-facing
    home-report read, to know which row a PATCH .../findings/{id} targets),
    not just its text.
    """
    query = select(Finding).where(Finding.system_id == system_id).order_by(Finding.position)
    result = await session.execute(query)
    return list(result.scalars())


async def get_findings(session: AsyncSession, system_id: uuid.UUID) -> list[str]:
    """A system's findings, in their original order, as plain text."""
    return [record.text for record in await get_finding_records(session, system_id)]


def _format_age(years: int | None, confidence: float) -> str:
    if years is None:
        return "unknown"
    return f"{years} years (confidence {confidence:.2f})"


def _build_action_plan_input(
    records: list[SystemRecord], findings_by_system: dict[uuid.UUID, list[str]]
) -> str:
    """Render already-saved system/finding rows as plain text for Claude to
    reason over.

    Built from database rows only, never from a document's raw text -- see
    `create_action_plan`. This is what makes "reason only over saved facts"
    an actual guarantee rather than a prompt-only request: the report's raw
    text is never in the call at all, so there is nothing beyond this text
    for the model to draw an age or condition from.
    """
    blocks = []
    for record in records:
        findings = findings_by_system.get(record.id, [])
        lines = [
            f"{record.name}:",
            f"  age: {_format_age(record.estimated_age_years, record.estimated_age_confidence)}",
            f"  condition: {record.condition} (confidence {record.condition_confidence:.2f})",
        ]
        if findings:
            lines.append(f"  findings (confidence {record.findings_confidence:.2f}):")
            lines.extend(f"    - {finding}" for finding in findings)
        else:
            lines.append("  findings: none")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


async def create_action_plan(
    session: AsyncSession, document_id: uuid.UUID
) -> list[ActionItem] | None:
    """Generate a prioritized action plan from a document's already-saved
    system/finding rows, replacing any previous run for it.

    Reasons only over what `extract_home_report` already persisted -- see
    `_build_action_plan_input`. Returns None if the document has no
    inspection event yet (run `extract_home_report` first); raises
    ExtractionError (see home_inspection.py) if Claude could not be reached
    or refused the request.
    """
    event = await _get_event(session, document_id)
    if event is None:
        return None
    event_id = event.id

    records = await get_home_report(session, document_id)
    findings_by_system: dict[uuid.UUID, list[str]] = {}
    for record in records:
        findings_by_system[record.id] = await get_findings(session, record.id)

    plan = generate_action_plan(_build_action_plan_input(records, findings_by_system))

    # Idempotent: a re-run should not double up items.
    await session.execute(delete(ActionItem).where(ActionItem.event_id == event_id))

    # A re-run replaces content the inspector may have already reviewed and
    # approved -- force a fresh review of the new content rather than
    # leaving it visible to the buyer under the old approval. Only matters
    # once this is reachable from a "regenerate" action; nothing in the
    # product does that today, but the API itself must not leave this gap.
    if event.status in _VISIBLE_STATUSES:
        event.status = "pending_review"
        event.reviewed_at = None

    ordered_items = sorted(plan.items, key=lambda item: _URGENCY_RANK[item.urgency])
    action_items = [
        ActionItem(
            event_id=event_id,
            document_id=document_id,
            system=item.system,
            urgency=item.urgency,
            recommendation=item.recommendation,
            cost_low=item.cost_low,
            cost_high=item.cost_high,
            # Always "ai_estimated" today -- Claude is never asked for this,
            # it is set here so a real pricing API can be swapped in later
            # (a different value here) without a schema change.
            cost_source="ai_estimated",
            position=position,
        )
        for position, item in enumerate(ordered_items)
    ]
    for action_item in action_items:
        session.add(action_item)

    await session.commit()
    for action_item in action_items:
        await session.refresh(action_item)
    return action_items


async def get_action_plan(session: AsyncSession, document_id: uuid.UUID) -> list[ActionItem]:
    query = (
        select(ActionItem).where(ActionItem.document_id == document_id).order_by(ActionItem.position)
    )
    result = await session.execute(query)
    return list(result.scalars())


async def _get_event(session: AsyncSession, document_id: uuid.UUID) -> InspectionEvent | None:
    return await session.scalar(
        select(InspectionEvent).where(InspectionEvent.document_id == document_id)
    )


async def get_event_status(session: AsyncSession, document_id: uuid.UUID) -> InspectionEvent | None:
    """A document's review status + when it last changed, for the
    inspector's status badge. None if the document has no inspection event
    (home report never generated)."""
    return await _get_event(session, document_id)


async def is_report_visible(session: AsyncSession, document_id: uuid.UUID) -> bool:
    """Whether a report has cleared the review gate -- approved or
    auto_sent, per InspectionEvent's docstring. Used by
    notifications/service.py so the weekly reminder job never pulls from a
    still-pending_review report.
    """
    event = await _get_event(session, document_id)
    return event is not None and event.status in _VISIBLE_STATUSES


async def approve_event(session: AsyncSession, document_id: uuid.UUID) -> InspectionEvent | None:
    """Inspector sign-off: the review gate that unlocks a report for its
    buyer. Idempotent -- callable again after auto_sent (e.g. once the
    inspector actually gets to a report the timeout already released) to
    record that a human has now also reviewed it, without erroring.
    """
    event = await _get_event(session, document_id)
    if event is None:
        return None
    event.status = "approved"
    event.reviewed_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(event)
    return event


async def auto_send_stale_events(
    session: AsyncSession, *, after: timedelta, dry_run: bool = False
) -> int:
    """Move every report still pending_review past the auto-send window to
    auto_sent, so a slow inspector doesn't block delivery to the buyer.

    Anchored on InspectionEvent.created_at -- there is no separate "review
    started" timestamp, and created_at is set the moment the event (and so
    the pending_review state) begins, right after the home report is
    generated. Returns the count that were (or, in dry-run mode, would be)
    moved.
    """
    cutoff = datetime.now(UTC) - after
    stale = list(
        await session.scalars(
            select(InspectionEvent).where(
                InspectionEvent.status == "pending_review",
                InspectionEvent.created_at < cutoff,
            )
        )
    )
    if not dry_run and stale:
        now = datetime.now(UTC)
        for event in stale:
            event.status = "auto_sent"
            event.reviewed_at = now
        await session.commit()
    return len(stale)


async def update_finding(
    session: AsyncSession, document_id: uuid.UUID, finding_id: uuid.UUID, text: str
) -> Finding | None:
    """Inspector edit during review: correct a finding's wording. Text-only
    -- no add/delete of findings, see the review-workflow plan this
    implements. Scoped to document_id as well as finding_id so a caller
    can't reach a finding belonging to a different document than the one
    ownership was already checked against (see OwnedDocumentDep).
    """
    finding = await session.scalar(
        select(Finding).where(Finding.id == finding_id, Finding.document_id == document_id)
    )
    if finding is None:
        return None
    finding.text = text
    await session.commit()
    await session.refresh(finding)
    return finding


async def update_action_item(
    session: AsyncSession,
    document_id: uuid.UUID,
    item_id: uuid.UUID,
    *,
    urgency: str | None = None,
    recommendation: str | None = None,
) -> ActionItem | None:
    """Inspector edit during review: correct an action item's urgency tier
    and/or recommendation text. Cost is deliberately not editable here --
    cost estimates are not part of what the inspector reviews and approves.
    """
    item = await session.scalar(
        select(ActionItem).where(ActionItem.id == item_id, ActionItem.document_id == document_id)
    )
    if item is None:
        return None
    if urgency is not None:
        item.urgency = urgency
    if recommendation is not None:
        item.recommendation = recommendation
    await session.commit()
    await session.refresh(item)
    return item


@dataclass(frozen=True)
class BuyerReport:
    """The public, buyer-facing view of a report -- see get_buyer_report.

    `status` is always present. Every other field stays at its default
    while status is "pending_review" -- get_buyer_report never populates
    them in that case, which is the actual liability boundary the review
    gate exists to enforce, enforced in the one function every
    unauthenticated caller goes through rather than trusted to the API
    route or the frontend to withhold.
    """

    status: str
    title: str | None = None
    inspector_name: str | None = None
    created_at: datetime | None = None
    systems: list[SystemRecord] = field(default_factory=list)
    findings_by_system: dict[uuid.UUID, list[str]] = field(default_factory=dict)
    action_items: list[ActionItem] = field(default_factory=list)


async def get_buyer_report(session: AsyncSession, document_id: uuid.UUID) -> BuyerReport | None:
    """The public, unauthenticated view of a report -- what
    GET /documents/{id}/buyer-report returns. None if the document has no
    inspection event at all (home report never generated, or the document
    doesn't exist).
    """
    event = await _get_event(session, document_id)
    if event is None:
        return None

    if event.status == "pending_review":
        return BuyerReport(status=event.status)

    document = await ingestion_service.get_document(session, document_id)
    if document is None:
        return None

    inspector_name = None
    if document.inspector_id is not None:
        inspector = await auth_service.get_inspector(session, document.inspector_id)
        inspector_name = inspector.name if inspector is not None else None

    records = await get_home_report(session, document_id)
    findings_by_system = {record.id: await get_findings(session, record.id) for record in records}
    action_items = await get_action_plan(session, document_id)

    return BuyerReport(
        status=event.status,
        title=document.title,
        inspector_name=inspector_name,
        created_at=document.created_at,
        systems=records,
        findings_by_system=findings_by_system,
        action_items=action_items,
    )
