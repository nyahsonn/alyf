"""Tables owned by the extraction module."""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
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


class HomeSystemRecord(Base):
    """One system's entry in a document's AI Home Health Report.

    One row per (document, system name) -- see `extract_home_report`, which
    replaces a document's rows on every re-run the same way `extract_document`
    replaces `Fact` rows. Age, condition, and findings each carry their own
    confidence rather than the whole row sharing one, since a report can be
    explicit about a system's condition while saying nothing about its age.
    """

    __tablename__ = "home_system_records"
    __table_args__ = (
        UniqueConstraint("document_id", "name", name="uq_home_system_document_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    estimated_age_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_age_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    condition: Mapped[str] = mapped_column(String(30), nullable=False)
    condition_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    findings: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    findings_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
