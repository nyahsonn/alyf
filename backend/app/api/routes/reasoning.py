"""HTTP endpoints for the reasoning module."""

import uuid

from fastapi import APIRouter, Query

from app.api.deps import CurrentInspectorDep, SessionDep
from app.reasoning import service
from app.reasoning.schemas import AnswerRead, AskRequest, InsightRead

router = APIRouter(tags=["reasoning"])


@router.post("/ask", response_model=AnswerRead)
async def ask(payload: AskRequest, current: CurrentInspectorDep, session: SessionDep) -> AnswerRead:
    """Answer a question using pgvector similarity search over the logged-in
    inspector's own extracted facts.
    """
    return await service.ask(session, payload, inspector_id=current.id)


@router.get("/insights", response_model=list[InsightRead])
async def list_insights(
    current: CurrentInspectorDep,
    session: SessionDep,
    document_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[InsightRead]:
    insights = await service.list_insights(
        session, inspector_id=current.id, document_id=document_id, limit=limit
    )
    return [InsightRead.model_validate(insight) for insight in insights]
