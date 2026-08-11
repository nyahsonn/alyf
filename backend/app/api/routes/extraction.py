"""HTTP endpoints for the extraction module."""

import logging
import uuid

import sentry_sdk
from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import OwnedDocumentDep, SessionDep
from app.extraction import service
from app.extraction.home_inspection import ExtractionError
from app.extraction.models import SystemRecord
from app.extraction.schemas import (
    ActionItemEditRequest,
    ActionItemRead,
    ActionPlanResult,
    BuyerReportResult,
    BuyerReportSystem,
    EventStatusRead,
    ExtractionResult,
    FactRead,
    FindingEditRequest,
    FindingRead,
    HomeReportResult,
    HomeSystemRead,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["extraction"])

_NO_HOME_REPORT_DETAIL = (
    "No home report found for this document. Run POST /documents/{id}/home-report first."
)


@router.post("/documents/{document_id}/extract", response_model=ExtractionResult)
async def extract(document: OwnedDocumentDep, session: SessionDep) -> ExtractionResult:
    """Run extraction over a document's chunks.

    Safe to call repeatedly: previous facts for the document are replaced.
    """
    facts = await service.extract_document(session, document.id)
    return ExtractionResult(
        document_id=document.id,
        facts_created=len(facts),
        facts=[FactRead.model_validate(fact) for fact in facts],
    )


@router.get("/facts", response_model=list[FactRead])
async def list_facts(
    document: OwnedDocumentDep,
    session: SessionDep,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[FactRead]:
    """A document's extracted facts. `document_id` is required (not optional
    as it might look from the shape of `service.list_facts` below) --
    without it there is no owned-document check to run, and this would be a
    global, cross-inspector fact listing.
    """
    facts = await service.list_facts(session, document_id=document.id, limit=limit)
    return [FactRead.model_validate(fact) for fact in facts]


async def _to_home_system_read(session: SessionDep, record: SystemRecord) -> HomeSystemRead:
    """Build the API read-shape for a system, which no longer carries its
    findings directly -- `SystemRecord` has no `findings` attribute for
    `model_validate` to read, since findings are now their own table.
    """
    finding_records = await service.get_finding_records(session, record.id)
    return HomeSystemRead(
        id=record.id,
        document_id=record.document_id,
        name=record.name,
        estimated_age_years=record.estimated_age_years,
        estimated_age_confidence=record.estimated_age_confidence,
        condition=record.condition,
        condition_confidence=record.condition_confidence,
        findings=[f.text for f in finding_records],
        finding_ids=[f.id for f in finding_records],
        findings_confidence=record.findings_confidence,
        created_at=record.created_at,
    )


@router.post("/documents/{document_id}/home-report", response_model=HomeReportResult)
async def create_home_report(document: OwnedDocumentDep, session: SessionDep) -> HomeReportResult:
    """Generate the AI Home Health Report for a document via Claude.

    Safe to call repeatedly: previous systems for the document are replaced.
    """
    try:
        records = await service.extract_home_report(session, document.id)
    except ExtractionError as e:
        # The underlying message can include Claude's own error text, which is
        # meant for a developer reading logs rather than an API caller.
        logger.error("Home report extraction failed for document %s: %s", document.id, e)
        with sentry_sdk.new_scope() as scope:
            scope.set_tag("document_id", str(document.id))
            scope.set_tag("stage", "home_report")
            sentry_sdk.capture_exception(e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not generate the home report. See the server log for details.",
        ) from None

    if records is None:
        # Narrow race: the document existed when OwnedDocumentDep checked it
        # moments ago but was deleted before this call reached it.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    return HomeReportResult(
        document_id=document.id,
        systems=[await _to_home_system_read(session, record) for record in records],
    )


@router.get("/documents/{document_id}/home-report", response_model=HomeReportResult)
async def get_home_report(document: OwnedDocumentDep, session: SessionDep) -> HomeReportResult:
    """The most recently generated home report for a document, if any."""
    records = await service.get_home_report(session, document.id)
    return HomeReportResult(
        document_id=document.id,
        systems=[await _to_home_system_read(session, record) for record in records],
    )


@router.post("/documents/{document_id}/action-plan", response_model=ActionPlanResult)
async def create_action_plan(document: OwnedDocumentDep, session: SessionDep) -> ActionPlanResult:
    """Generate a prioritized action plan from a document's already-saved home report.

    Reasons only over the system/finding rows a prior `/home-report` run
    persisted -- never the document's raw text again. Safe to call
    repeatedly: previous items for the document are replaced.
    """
    try:
        items = await service.create_action_plan(session, document.id)
    except ExtractionError as e:
        logger.error("Action plan generation failed for document %s: %s", document.id, e)
        with sentry_sdk.new_scope() as scope:
            scope.set_tag("document_id", str(document.id))
            scope.set_tag("stage", "action_plan")
            sentry_sdk.capture_exception(e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not generate the action plan. See the server log for details.",
        ) from None

    if items is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_NO_HOME_REPORT_DETAIL,
        )

    return ActionPlanResult(
        document_id=document.id,
        items=[ActionItemRead.model_validate(item) for item in items],
    )


@router.get("/documents/{document_id}/action-plan", response_model=ActionPlanResult)
async def get_action_plan(document: OwnedDocumentDep, session: SessionDep) -> ActionPlanResult:
    """The most recently generated action plan for a document, if any."""
    items = await service.get_action_plan(session, document.id)
    return ActionPlanResult(
        document_id=document.id,
        items=[ActionItemRead.model_validate(item) for item in items],
    )


@router.get("/documents/{document_id}/status", response_model=EventStatusRead)
async def get_status(document: OwnedDocumentDep, session: SessionDep) -> EventStatusRead:
    """The inspector-facing review status -- powers the status badge and
    whether to show the Approve button."""
    event = await service.get_event_status(session, document.id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_NO_HOME_REPORT_DETAIL,
        )
    return EventStatusRead.model_validate(event)


@router.post("/documents/{document_id}/approve", response_model=EventStatusRead)
async def approve(document: OwnedDocumentDep, session: SessionDep) -> EventStatusRead:
    """Inspector sign-off: unlocks this report at its public link. Safe to
    call again later (e.g. after an auto-send already happened) -- it just
    records that a human has now also reviewed it."""
    event = await service.approve_event(session, document.id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_NO_HOME_REPORT_DETAIL,
        )
    return EventStatusRead.model_validate(event)


@router.patch("/documents/{document_id}/findings/{finding_id}", response_model=FindingRead)
async def edit_finding(
    document: OwnedDocumentDep,
    finding_id: uuid.UUID,
    payload: FindingEditRequest,
    session: SessionDep,
) -> FindingRead:
    """Inspector edit during review: correct a finding's wording."""
    finding = await service.update_finding(session, document.id, finding_id, payload.text)
    if finding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Finding not found")
    return FindingRead.model_validate(finding)


@router.patch("/documents/{document_id}/action-items/{item_id}", response_model=ActionItemRead)
async def edit_action_item(
    document: OwnedDocumentDep,
    item_id: uuid.UUID,
    payload: ActionItemEditRequest,
    session: SessionDep,
) -> ActionItemRead:
    """Inspector edit during review: correct an action item's urgency tier
    and/or recommendation. Cost is deliberately not editable here -- cost
    estimates are not part of what the inspector reviews and approves."""
    item = await service.update_action_item(
        session,
        document.id,
        item_id,
        urgency=payload.urgency,
        recommendation=payload.recommendation,
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action item not found")
    return ActionItemRead.model_validate(item)


@router.get("/documents/{document_id}/buyer-report", response_model=BuyerReportResult)
async def get_buyer_report(document_id: uuid.UUID, session: SessionDep) -> BuyerReportResult:
    """The public, unauthenticated view of a report -- the one route in
    this file with no OwnedDocumentDep. Same trust model as the unsubscribe
    route in app/api/routes/ingestion.py: an unguessable id, no inspector
    login, since homeowners don't have accounts. Returns just `status` (no
    systems/findings/costs) while a report is still pending_review -- that
    withholding is the actual review gate, enforced in
    extraction/service.py's get_buyer_report, not here.
    """
    report = await service.get_buyer_report(session, document_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")

    return BuyerReportResult(
        status=report.status,
        document_id=document_id,
        title=report.title,
        inspector_name=report.inspector_name,
        created_at=report.created_at,
        systems=[
            BuyerReportSystem(
                id=record.id,
                name=record.name,
                estimated_age_years=record.estimated_age_years,
                estimated_age_confidence=record.estimated_age_confidence,
                condition=record.condition,
                condition_confidence=record.condition_confidence,
                findings=report.findings_by_system.get(record.id, []),
                findings_confidence=record.findings_confidence,
            )
            for record in report.systems
        ],
        action_items=[ActionItemRead.model_validate(item) for item in report.action_items],
    )
