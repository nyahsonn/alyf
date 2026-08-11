"""Single import point for every ORM model.

Importing this module registers all tables on `Base.metadata`, which is what
`init_db()` (and any future Alembic autogenerate) needs.
"""

from app.auth.models import Inspector, OAuthAccount
from app.extraction.models import ActionItem, Fact, Finding, Home, InspectionEvent, SystemRecord
from app.ingestion.models import Chunk, Document
from app.notifications.models import ReminderLog
from app.reasoning.models import Insight
from app.reports.models import Report

__all__ = [
    "ActionItem",
    "Chunk",
    "Document",
    "Fact",
    "Finding",
    "Home",
    "InspectionEvent",
    "Insight",
    "Inspector",
    "OAuthAccount",
    "ReminderLog",
    "Report",
    "SystemRecord",
]
