"""HTTP endpoints for the extraction module."""

import logging
import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import SessionDep
from app.extraction import service
from app.extraction.home_inspection import ExtractionError
from app.extraction.models import SystemRecord
from app.extraction.schemas import (
    ActionItemRead,
    ActionPlanResult,
    ExtractionResult,
    FactRead,
    HomeReportResult,
    HomeSystemRead,
)
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


async def _to_home_system_read(session: SessionDep, record: SystemRecord) -> HomeSystemRead:
    """Build the API read-shape for a system, which no longer carries its
    findings directly -- `SystemRecord` has no `findings` attribute for
    `model_validate` to read, since findings are now their own table.
    """
    return HomeSystemRead(
        id=record.id,
        document_id=record.document_id,
        name=record.name,
        estimated_age_years=record.estimated_age_years,
        estimated_age_confidence=record.estimated_age_confidence,
        condition=record.condition,
        condition_confidence=record.condition_confidence,
        findings=await service.get_findings(session, record.id),
        findings_confidence=record.findings_confidence,
        created_at=record.created_at,
    )


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
        systems=[await _to_home_system_read(session, record) for record in records],
    )


@router.get("/documents/{document_id}/home-report", response_model=HomeReportResult)
async def get_home_report(document_id: uuid.UUID, session: SessionDep) -> HomeReportResult:
    """The most recently generated home report for a document, if any."""
    if await ingestion_service.get_document(session, document_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    records = await service.get_home_report(session, document_id)
    return HomeReportResult(
        document_id=document_id,
        systems=[await _to_home_system_read(session, record) for record in records],
    )


@router.post("/documents/{document_id}/action-plan", response_model=ActionPlanResult)
async def create_action_plan(document_id: uuid.UUID, session: SessionDep) -> ActionPlanResult:
    """Generate a prioritized action plan from a document's already-saved home report.

    Reasons only over the system/finding rows a prior `/home-report` run
    persisted -- never the document's raw text again. Safe to call
    repeatedly: previous items for the document are replaced.
    """
    if await ingestion_service.get_document(session, document_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    try:
        items = await service.create_action_plan(session, document_id)
    except ExtractionError as e:
        logger.error("Action plan generation failed for document %s: %s", document_id, e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not generate the action plan. See the server log for details.",
        ) from None

    if items is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No home report found for this document. Run POST /documents/{id}/home-report first.",
        )

    return ActionPlanResult(
        document_id=document_id,
        items=[ActionItemRead.model_validate(item) for item in items],
    )


@router.get("/documents/{document_id}/action-plan", response_model=ActionPlanResult)
async def get_action_plan(document_id: uuid.UUID, session: SessionDep) -> ActionPlanResult:
    """The most recently generated action plan for a document, if any."""
    if await ingestion_service.get_document(session, document_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    items = await service.get_action_plan(session, document_id)
    return ActionPlanResult(
        document_id=document_id,
        items=[ActionItemRead.model_validate(item) for item in items],
    )
