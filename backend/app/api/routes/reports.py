"""HTTP endpoints for the reports module."""

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import SessionDep
from app.reports import service
from app.reports.schemas import ReportCreate, ReportDetail, ReportRead
from app.reports.service import DocumentNotFoundError

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("", response_model=ReportDetail, status_code=status.HTTP_201_CREATED)
async def create_report(payload: ReportCreate, session: SessionDep) -> ReportDetail:
    """Build a Markdown report from a document's facts and insights."""
    try:
        report = await service.build_report(session, payload)
    except DocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        ) from None
    return ReportDetail.model_validate(report)


@router.get("", response_model=list[ReportRead])
async def list_reports(
    session: SessionDep,
    document_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ReportRead]:
    reports = await service.list_reports(session, document_id=document_id, limit=limit)
    return [ReportRead.model_validate(report) for report in reports]


@router.get("/{report_id}", response_model=ReportDetail)
async def get_report(report_id: uuid.UUID, session: SessionDep) -> ReportDetail:
    report = await service.get_report(session, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return ReportDetail.model_validate(report)
