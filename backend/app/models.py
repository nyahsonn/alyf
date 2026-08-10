"""Single import point for every ORM model.

Importing this module registers all tables on `Base.metadata`, which is what
`init_db()` (and any future Alembic autogenerate) needs.
"""

from app.extraction.models import Fact, Finding, Home, InspectionEvent, SystemRecord
from app.ingestion.models import Chunk, Document
from app.reasoning.models import Insight
from app.reports.models import Report

__all__ = [
    "Chunk",
    "Document",
    "Fact",
    "Finding",
    "Home",
    "InspectionEvent",
    "Insight",
    "Report",
    "SystemRecord",
]
