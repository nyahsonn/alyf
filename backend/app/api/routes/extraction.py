"""HTTP endpoints for the extraction module."""

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import SessionDep
from app.extraction import service
from app.extraction.schemas import ExtractionResult, FactRead
from app.ingestion import service as ingestion_service

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
