"""Reasoning: retrieve relevant facts with pgvector, then compose an answer.

Retrieval is real vector search -- `Fact.embedding.cosine_distance(...)` compiles
to pgvector's `<=>` operator and runs inside PostgreSQL. Answer composition is
extractive (it quotes the retrieved facts) so the module has no external
dependency; replace `compose_answer` with an LLM call to make it generative.
"""

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embeddings import embed_text
from app.extraction.models import Fact
from app.reasoning.models import Insight
from app.reasoning.schemas import AnswerRead, AskRequest, EvidenceItem

_WHITESPACE_RE = re.compile(r"\s+")


async def search_facts(
    session: AsyncSession,
    query: str,
    document_id: uuid.UUID | None = None,
    top_k: int = 5,
) -> list[tuple[Fact, float]]:
    """Nearest-neighbour search over fact embeddings.

    Returns (fact, similarity) pairs ordered most-relevant first.
    """
    query_vector = embed_text(query)
    distance = Fact.embedding.cosine_distance(query_vector)

    statement = select(Fact, distance.label("distance")).order_by(distance).limit(top_k)
    if document_id is not None:
        statement = statement.where(Fact.document_id == document_id)

    result = await session.execute(statement)
    # pgvector cosine_distance = 1 - cosine_similarity
    return [(fact, 1.0 - float(dist)) for fact, dist in result.all()]


def _one_line(text: str) -> str:
    """Flatten text onto a single line.

    Chunking preserves line breaks, so fact values carry newlines. Left in, they
    break the numbered list below and truncate any caller that previews an answer
    by its first line.
    """
    return _WHITESPACE_RE.sub(" ", text).strip()


def compose_answer(question: str, matches: list[tuple[Fact, float]]) -> str:
    """Build a readable answer from the retrieved facts.

    The opening line is the answer itself -- the best-matching fact. The question
    is already carried beside the answer everywhere it is rendered
    (`AnswerRead.question`, `Insight.question`, and the report's own "Q:" line),
    so leading with a restatement of it left first-line previews saying nothing.
    """
    if not matches:
        return (
            "No relevant facts were found. Ingest a document and run extraction "
            "on it first, then ask again."
        )

    top_fact, _ = matches[0]
    lines = [_one_line(top_fact.value)]

    if len(matches) > 1:
        lines.extend(
            ["", f'Facts retrieved for "{_one_line(question)}", most relevant first:']
        )
        for rank, (fact, score) in enumerate(matches, start=1):
            lines.append(
                f"{rank}. [{fact.kind}, relevance {score:.2f}] {_one_line(fact.value)}"
            )

    return "\n".join(lines)


async def ask(session: AsyncSession, payload: AskRequest) -> AnswerRead:
    matches = await search_facts(
        session,
        query=payload.question,
        document_id=payload.document_id,
        top_k=payload.top_k,
    )

    evidence = [
        EvidenceItem(
            fact_id=fact.id,
            document_id=fact.document_id,
            label=fact.label,
            value=fact.value,
            kind=fact.kind,
            score=round(score, 4),
        )
        for fact, score in matches
    ]
    answer_text = compose_answer(payload.question, matches)

    insight_id: uuid.UUID | None = None
    if payload.persist:
        insight = Insight(
            document_id=payload.document_id,
            question=payload.question,
            answer=answer_text,
            evidence=[item.model_dump(mode="json") for item in evidence],
        )
        session.add(insight)
        await session.commit()
        await session.refresh(insight)
        insight_id = insight.id

    return AnswerRead(
        question=payload.question,
        answer=answer_text,
        evidence=evidence,
        insight_id=insight_id,
    )


async def list_insights(
    session: AsyncSession,
    document_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[Insight]:
    query = select(Insight).order_by(Insight.created_at.desc()).limit(limit)
    if document_id is not None:
        query = query.where(Insight.document_id == document_id)
    result = await session.execute(query)
    return list(result.scalars())
