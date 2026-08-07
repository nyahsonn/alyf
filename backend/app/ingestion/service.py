"""Ingestion: accept raw source material, normalise it, and split it into chunks.

This is the first stage of the pipeline. Nothing here interprets meaning -- that
is the extraction module's job.
"""

import re
import uuid
from typing import TYPE_CHECKING

import anyio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.ingestion.models import Chunk, Document
from app.ingestion.schemas import DocumentCreate

if TYPE_CHECKING:  # Type-only: importing ocr at runtime would defeat the lazy import below.
    from app.ingestion.ocr import Table

_WORD_RE = re.compile(r"\S+")

# Every PDF opens with this. The filename and the browser's content type are
# both supplied by the client and are routinely wrong, so the bytes decide.
_PDF_MAGIC = b"%PDF-"


class UnsupportedUpload(ValueError):
    """The uploaded bytes are neither a PDF nor UTF-8 text."""


class OcrFailed(RuntimeError):
    """A PDF was recognised but Document AI could not read it.

    Wraps `ocr.OcrError` so callers -- the API routes especially -- never need
    to import the Document AI client library to handle a failure.
    """


class UploadTooLarge(ValueError):
    """The PDF is over the size Document AI will accept in one request.

    Kept apart from `OcrFailed`: the service never saw this file, so it is the
    upload that was wrong rather than anything upstream. Its message carries no
    configuration detail and can go straight back to the client.
    """


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


def looks_like_pdf(raw: bytes) -> bool:
    """Decide from the bytes themselves whether this upload is a PDF."""
    return raw.startswith(_PDF_MAGIC)


def render_tables(tables: list["Table"]) -> str:
    """Render OCR tables as lines the rule-based extractor can read.

    Document AI returns a table as cells, and `document.text` holds those same
    cells one per line with nothing tying a number back to the row and column it
    came from -- "Revenue" on one line, "4.2M" on the next. Written out as
    "Label: value" pairs the relationship survives, and that is the one shape
    `extract_candidates` already recognises.

    The first column is taken as the row's label, which holds for most data
    tables; where it does not, the cost is an odd-looking label rather than a
    lost row. Tables wider than two columns fold the column header into the
    label ("Revenue Q2: 5.1M"). Two-column tables are already label/value pairs,
    so they use the row label alone.

    Each table gets a Markdown heading. The extractor reads headings as
    structure and breaks its prose blocks there -- without one, rows carry no
    terminating punctuation and the whole table merges into a single bogus claim.
    """
    blocks: list[str] = []

    for position, table in enumerate(tables, start=1):
        headers = table.header_rows[0] if table.header_rows else []
        # A table with no body is usually one the parser read as all-header;
        # treat those rows as data rather than dropping the table.
        rows = table.body_rows or table.header_rows
        lines = [f"## Table {position} (page {table.page_number})", ""]

        for row in rows:
            label = row[0].strip() if row else ""
            if len(row) == 1:
                # Nothing to pair the cell with -- keep the text, drop the shape.
                lines.extend([label] if label else [])
                continue
            for index, cell in enumerate(row[1:], start=1):
                cell = cell.strip()
                if not label or not cell:
                    continue
                header = headers[index].strip() if index < len(headers) else ""
                qualified = f"{label} {header}" if len(row) > 2 and header else label
                lines.append(f"{qualified}: {cell}")

        if len(lines) > 2:
            blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


async def text_from_upload(raw: bytes) -> tuple[str, str]:
    """Turn uploaded bytes into document text, plus the source_type to record.

    PDFs go to Document AI; everything else has to be UTF-8 text. Raises
    `UnsupportedUpload` or `OcrFailed`.
    """
    if not looks_like_pdf(raw):
        try:
            return raw.decode("utf-8"), "file"
        except UnicodeDecodeError as e:
            raise UnsupportedUpload(
                "Only PDFs and UTF-8 text files are supported (.pdf, .txt, .md, .csv)."
            ) from e

    # Imported here, not at module scope, so the offline pipeline never loads the
    # Document AI client library: only an actual PDF upload pulls it in.
    from app.ingestion.ocr import FileTooLarge, OcrError, extract_bytes

    try:
        # The Document AI client is synchronous and does network I/O, so it goes
        # to a worker thread rather than stalling the event loop for every other
        # request in flight.
        result = await anyio.to_thread.run_sync(extract_bytes, raw)
    except FileTooLarge as e:
        # Before OcrError, which it subclasses.
        raise UploadTooLarge(str(e)) from e
    except OcrError as e:
        raise OcrFailed(str(e)) from e

    # `prose` rather than `text`: the tables are rendered separately just below,
    # and storing both would duplicate every cell.
    sections = [result.prose, render_tables(result.tables)]
    return "\n\n".join(section for section in sections if section), "pdf"


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
