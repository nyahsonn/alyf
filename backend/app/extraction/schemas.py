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


class HomeSystemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    name: str
    estimated_age_years: int | None
    estimated_age_confidence: float
    condition: str
    condition_confidence: float
    findings: list[str]
    findings_confidence: float
    created_at: datetime


class HomeReportResult(BaseModel):
    document_id: uuid.UUID
    systems: list[HomeSystemRead]


class ActionItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    system: str
    urgency: str
    recommendation: str
    cost_low: int
    cost_high: int
    created_at: datetime


class ActionPlanResult(BaseModel):
    document_id: uuid.UUID
    items: list[ActionItemRead]
