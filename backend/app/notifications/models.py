"""The one table notifications owns -- everything else it reads belongs to
ingestion or extraction, reached through their service functions.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ReminderLog(Base):
    """When a document's roadmap reminder was last sent.

    One row per document -- upserted on every send, not appended to, since
    all `send_weekly_reminders` needs is "how long ago was the last one" to
    decide whether today's run is due, given the cadence for however urgent
    the soonest outstanding item currently is (see
    notifications/service.py's `reminder_interval_days`).
    """

    __tablename__ = "reminder_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    last_sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
