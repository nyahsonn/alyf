"""Tables owned by the extraction module."""

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.core.database import Base


class Fact(Base):
    """A single structured claim pulled out of a chunk, with its embedding.

    `embedding` is a pgvector column -- the vector width is fixed at table
    creation time from EMBEDDING_DIMENSIONS.
    """

    __tablename__ = "facts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(50), nullable=False, default="statement")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(settings.embedding_dimensions), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Home(Base):
    """A physical property, matched across inspection events by address.

    Address matching (see `_normalize_address` in extraction/service.py) is a
    normalized-string exact match, not a real address normalizer -- "123 Main
    St" and "123 Main Street" will not be recognized as the same home. Good
    enough while the only address source is a single LLM reading of a
    report's cover page; revisit if that under-matches in practice.

    Unlike every other table here, a home has no direct `document_id`: it is
    meant to outlive any single document once a property has more than one
    inspection on file, so it traces to its source PDFs through its events,
    not directly.
    """

    __tablename__ = "homes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    normalized_address: Mapped[str | None] = mapped_column(
        String(500), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class InspectionEvent(Base):
    """One inspection report processed for a home.

    One row per document -- see `extract_home_report`, which replaces an
    event (and, via cascade, its systems and findings) on every re-run for
    the same document, the same idempotent-rerun pattern `Fact` uses.
    """

    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    home_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("homes.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    # Not yet extracted by the pipeline -- left for a future enhancement.
    inspection_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SystemRecord(Base):
    """One system's entry within an inspection event.

    Age, condition, and findings each carry their own confidence rather than
    the whole row sharing one, since a report can be explicit about a
    system's condition while saying nothing about its age. `document_id` is
    denormalized from `event_id` (the same pattern `Fact` uses for
    `chunk_id` + `document_id`) so a system traces to its source PDF without
    a join through events.
    """

    __tablename__ = "systems"
    __table_args__ = (UniqueConstraint("event_id", "name", name="uq_system_event_name"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    estimated_age_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_age_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    condition: Mapped[str] = mapped_column(String(30), nullable=False)
    condition_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    findings_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Finding(Base):
    """One specific issue, defect, or recommendation from a system's findings list.

    `position` preserves the list's original order, since findings are no
    longer a single JSONB array on the system row. `document_id` is
    denormalized the same way `SystemRecord.document_id` is -- `system_id` ->
    `event_id` would also reach it, but that is two joins away.
    """

    __tablename__ = "findings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    system_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("systems.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
