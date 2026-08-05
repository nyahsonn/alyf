"""Request/response shapes for the reasoning module."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=3)
    document_id: uuid.UUID | None = None
    top_k: int = Field(default=5, ge=1, le=25)
    # Set false to answer without writing an Insight row.
    persist: bool = True


class EvidenceItem(BaseModel):
    fact_id: uuid.UUID
    document_id: uuid.UUID
    label: str
    value: str
    kind: str
    # Cosine similarity in [-1, 1]; higher is more relevant.
    score: float


class AnswerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    question: str
    answer: str
    evidence: list[EvidenceItem]
    insight_id: uuid.UUID | None = None


class InsightRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID | None
    question: str
    answer: str
    evidence: list[dict]
    created_at: datetime
