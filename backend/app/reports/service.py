"""Reports: assemble facts and insights for a document into a Markdown report.

This is the last stage of the pipeline and the only one that reads across the
other modules. It depends on them through their service functions, never by
querying their tables directly.
"""

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.extraction import service as extraction_service
from app.extraction.models import Fact
from app.ingestion import service as ingestion_service
from app.ingestion.models import Document
from app.reasoning import service as reasoning_service
from app.reasoning.models import Insight
from app.reports.models import Report
from app.reports.schemas import ReportCreate


class DocumentNotFoundError(Exception):
    """Raised when a report is requested for a document that does not exist."""


async def build_report(session: AsyncSession, payload: ReportCreate) -> Report:
    document = await ingestion_service.get_document(session, payload.document_id)
    if document is None:
        raise DocumentNotFoundError(str(payload.document_id))

    facts = [
        fact
        for fact in await extraction_service.list_facts(session, payload.document_id, limit=500)
        if fact.confidence >= payload.min_confidence
    ]
    insights = await reasoning_service.list_insights(session, payload.document_id, limit=20)

    summary = _build_summary(document, facts)
    report = Report(
        document_id=document.id,
        title=payload.title or f"ALYF report — {document.title}",
        summary=summary,
        body_markdown=_render_markdown(document, facts, insights, summary),
        fact_count=len(facts),
    )
    session.add(report)
    await session.commit()
    await session.refresh(report)
    return report


def _build_summary(document: Document, facts: list[Fact]) -> str:
    if not facts:
        return (
            f'"{document.title}" has no extracted facts yet. '
            "Run extraction on the document to populate this report."
        )

    by_kind: dict[str, int] = defaultdict(int)
    for fact in facts:
        by_kind[fact.kind] += 1
    breakdown = ", ".join(f"{count} {kind}" for kind, count in sorted(by_kind.items()))
    top = max(facts, key=lambda fact: fact.confidence)
    return (
        f'"{document.title}" yielded {len(facts)} facts ({breakdown}). '
        f"Highest-confidence finding: {top.label} — {top.value}"
    )


def _render_markdown(
    document: Document,
    facts: list[Fact],
    insights: list[Insight],
    summary: str,
) -> str:
    lines = [
        f"# ALYF report — {document.title}",
        "",
        f"- **Document id:** `{document.id}`",
        f"- **Source:** {document.source_type}"
        + (f" (`{document.source_ref}`)" if document.source_ref else ""),
        f"- **Ingested:** {document.created_at:%Y-%m-%d %H:%M UTC}",
        f"- **Facts included:** {len(facts)}",
        "",
        "## Summary",
        "",
        summary,
        "",
        "## Extracted facts",
        "",
    ]

    if facts:
        grouped: dict[str, list[Fact]] = defaultdict(list)
        for fact in facts:
            grouped[fact.kind].append(fact)
        for kind, kind_facts in sorted(grouped.items()):
            lines.append(f"### {kind.title()} ({len(kind_facts)})")
            lines.append("")
            for fact in kind_facts:
                lines.append(f"- **{fact.label}** — {fact.value} _(confidence {fact.confidence:.2f})_")
            lines.append("")
    else:
        lines.extend(["_No facts extracted._", ""])

    lines.extend(["## Questions asked about this document", ""])
    if insights:
        for insight in insights:
            lines.append(f"- **Q:** {insight.question}")
            lines.append(f"  **A:** {insight.answer.splitlines()[0]}")
    else:
        lines.append("_No questions asked yet._")
    lines.append("")

    return "\n".join(lines)


async def list_reports(
    session: AsyncSession,
    document_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[Report]:
    query = select(Report).order_by(Report.created_at.desc()).limit(limit)
    if document_id is not None:
        query = query.where(Report.document_id == document_id)
    result = await session.execute(query)
    return list(result.scalars())


async def get_report(session: AsyncSession, report_id: uuid.UUID) -> Report | None:
    return await session.get(Report, report_id)
