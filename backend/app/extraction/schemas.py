"""Request/response shapes for the extraction module."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
    # Parallel to `findings` (same order, same length) -- lets the inspector
    # UI know which Finding row a given piece of text belongs to when
    # editing it (PATCH /documents/{id}/findings/{finding_id}). Not exposed
    # on the public buyer-report payload, which has no edit path.
    finding_ids: list[uuid.UUID]
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
    cost_source: str
    created_at: datetime


class ActionPlanResult(BaseModel):
    document_id: uuid.UUID
    items: list[ActionItemRead]


class ActionItemEditRequest(BaseModel):
    urgency: str | None = Field(default=None, max_length=20)
    recommendation: str | None = Field(default=None, min_length=1)


class FindingEditRequest(BaseModel):
    text: str = Field(min_length=1)


class FindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    text: str


class EventStatusRead(BaseModel):
    """The review status shown on the inspector's status badge -- see
    InspectionEvent.status/reviewed_at.
    """

    model_config = ConfigDict(from_attributes=True)

    status: str
    reviewed_at: datetime | None


class BuyerReportSystem(BaseModel):
    id: uuid.UUID
    name: str
    estimated_age_years: int | None
    estimated_age_confidence: float
    condition: str
    condition_confidence: float
    findings: list[str]
    findings_confidence: float


class BuyerReportResult(BaseModel):
    """The public, unauthenticated view of a report -- what
    GET /documents/{id}/buyer-report returns. Every field but `status` is
    omitted while status is "pending_review" -- see
    extraction/service.py's get_buyer_report/BuyerReport.
    """

    status: str
    document_id: uuid.UUID
    title: str | None = None
    inspector_name: str | None = None
    # The document's upload date -- the timeline page's only available
    # anchor for "now" when back-calculating an install year from estimated
    # system age (see frontend/src/app/reports/[id]/timeline/page.tsx).
    created_at: datetime | None = None
    systems: list[BuyerReportSystem] = []
    action_items: list[ActionItemRead] = []
