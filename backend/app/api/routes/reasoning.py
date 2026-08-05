"""HTTP endpoints for the reasoning module."""

import uuid

from fastapi import APIRouter, Query

from app.api.deps import SessionDep
from app.reasoning import service
from app.reasoning.schemas import AnswerRead, AskRequest, InsightRead

router = APIRouter(tags=["reasoning"])


@router.post("/ask", response_model=AnswerRead)
async def ask(payload: AskRequest, session: SessionDep) -> AnswerRead:
    """Answer a question using pgvector similarity search over extracted facts."""
    return await service.ask(session, payload)


@router.get("/insights", response_model=list[InsightRead])
async def list_insights(
    session: SessionDep,
    document_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[InsightRead]:
    insights = await service.list_insights(session, document_id=document_id, limit=limit)
    return [InsightRead.model_validate(insight) for insight in insights]
