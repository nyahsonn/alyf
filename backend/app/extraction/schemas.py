"""Request/response shapes for the extraction module."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    chunk_id: uuid.UUID | None
    label: str
    value: str
    kind: str
    confidence: float
    created_at: datetime


class ExtractionResult(BaseModel):
    document_id: uuid.UUID
    facts_created: int
    facts: list[FactRead]
