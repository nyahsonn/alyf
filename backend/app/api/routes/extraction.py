"""HTTP endpoints for the extraction module."""

import logging
import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import SessionDep
from app.extraction import service
from app.extraction.home_inspection import ExtractionError
from app.extraction.schemas import ExtractionResult, FactRead, HomeReportResult, HomeSystemRead
from app.ingestion import service as ingestion_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["extraction"])


@router.post("/documents/{document_id}/extract", response_model=ExtractionResult)
async def extract(document_id: uuid.UUID, session: SessionDep) -> ExtractionResult:
    """Run extraction over a document's chunks.

    Safe to call repeatedly: previous facts for the document are replaced.
    """
    if await ingestion_service.get_document(session, document_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    facts = await service.extract_document(session, document_id)
    return ExtractionResult(
        document_id=document_id,
        facts_created=len(facts),
        facts=[FactRead.model_validate(fact) for fact in facts],
    )


@router.get("/facts", response_model=list[FactRead])
async def list_facts(
    session: SessionDep,
    document_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[FactRead]:
    facts = await service.list_facts(session, document_id=document_id, limit=limit)
    return [FactRead.model_validate(fact) for fact in facts]


@router.post("/documents/{document_id}/home-report", response_model=HomeReportResult)
async def create_home_report(document_id: uuid.UUID, session: SessionDep) -> HomeReportResult:
    """Generate the AI Home Health Report for a document via Claude.

    Safe to call repeatedly: previous systems for the document are replaced.
    """
    try:
        records = await service.extract_home_report(session, document_id)
    except ExtractionError as e:
        # The underlying message can include Claude's own error text, which is
        # meant for a developer reading logs rather than an API caller.
        logger.error("Home report extraction failed for document %s: %s", document_id, e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not generate the home report. See the server log for details.",
        ) from None

    if records is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    return HomeReportResult(
        document_id=document_id,
        systems=[HomeSystemRead.model_validate(record) for record in records],
    )


@router.get("/documents/{document_id}/home-report", response_model=HomeReportResult)
async def get_home_report(document_id: uuid.UUID, session: SessionDep) -> HomeReportResult:
    """The most recently generated home report for a document, if any."""
    if await ingestion_service.get_document(session, document_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    records = await service.get_home_report(session, document_id)
    return HomeReportResult(
        document_id=document_id,
        systems=[HomeSystemRead.model_validate(record) for record in records],
    )
