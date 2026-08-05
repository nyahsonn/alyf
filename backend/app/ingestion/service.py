"""Ingestion: accept raw source material, normalise it, and split it into chunks.

This is the first stage of the pipeline. Nothing here interprets meaning -- that
is the extraction module's job.
"""

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.ingestion.models import Chunk, Document
from app.ingestion.schemas import DocumentCreate

_WORD_RE = re.compile(r"\S+")


def split_into_chunks(
    text: str,
    size_words: int | None = None,
    overlap_words: int | None = None,
) -> list[str]:
    """Split text into overlapping word windows.

    Overlap keeps sentences that straddle a boundary retrievable from both
    sides. Pure function -- easy to unit test.

    Windows are sliced out of the original string rather than rebuilt from the
    word list, so line breaks survive. Extraction reads "Label: value" pairs
    line by line and would find none in a chunk collapsed onto one line.
    """
    size = size_words or settings.chunk_size_words
    overlap = overlap_words if overlap_words is not None else settings.chunk_overlap_words

    if size <= 0:
        raise ValueError("size_words must be positive")
    if not 0 <= overlap < size:
        raise ValueError("overlap_words must be >= 0 and < size_words")

    words = list(_WORD_RE.finditer(text))
    if not words:
        return []

    step = size - overlap
    chunks: list[str] = []
    for start in range(0, len(words), step):
        window = words[start : start + size]
        if not window:
            break
        chunks.append(text[window[0].start() : window[-1].end()])
        if start + size >= len(words):
            break
    return chunks


async def ingest_document(session: AsyncSession, payload: DocumentCreate) -> Document:
    """Persist a document plus its chunks in a single transaction."""
    document = Document(
        title=payload.title.strip(),
        content=payload.content,
        source_type=payload.source_type,
        source_ref=payload.source_ref,
        status="ingested",
    )
    session.add(document)

    for position, chunk_text in enumerate(split_into_chunks(payload.content)):
        session.add(
            Chunk(
                document=document,
                position=position,
                content=chunk_text,
                word_count=len(chunk_text.split()),
            )
        )

    await session.commit()
    await session.refresh(document)
    return document


async def list_documents(session: AsyncSession, limit: int = 50) -> list[Document]:
    result = await session.execute(
        select(Document).order_by(Document.created_at.desc()).limit(limit)
    )
    return list(result.scalars())


async def get_document(session: AsyncSession, document_id: uuid.UUID) -> Document | None:
    return await session.get(Document, document_id)


async def get_document_with_chunks(
    session: AsyncSession, document_id: uuid.UUID
) -> Document | None:
    result = await session.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()
    if document is not None:
        # Explicit load: lazy loading is not available in async sessions.
        await session.refresh(document, attribute_names=["chunks"])
    return document


async def get_chunks(session: AsyncSession, document_id: uuid.UUID) -> list[Chunk]:
    result = await session.execute(
        select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.position)
    )
    return list(result.scalars())


async def delete_document(session: AsyncSession, document_id: uuid.UUID) -> bool:
    document = await session.get(Document, document_id)
    if document is None:
        return False
    await session.delete(document)
    await session.commit()
    return True
