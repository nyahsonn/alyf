"""Request/response shapes for the reports module."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ReportCreate(BaseModel):
    document_id: uuid.UUID
    title: str | None = Field(default=None, max_length=500)
    # Facts below this confidence are left out of the report body.
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    title: str
    summary: str
    fact_count: int
    created_at: datetime


class ReportDetail(ReportRead):
    body_markdown: str
