"""Weekly roadmap reminders: decide who needs one, build it, send it.

Reads across the ingestion and extraction modules the same way
app/reports/service.py does -- through their service functions, never a raw
query against another module's table (see README, "modules talk to their
neighbours only through service calls"). `ReminderLog` is the exception:
notifications owns that table itself, so querying/writing it directly here
is the same thing every other module does with its own tables.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.extraction import service as extraction_service
from app.extraction.models import ActionItem
from app.ingestion import service as ingestion_service
from app.ingestion.models import Document
from app.notifications.emailer import send_email
from app.notifications.models import ReminderLog

SYSTEM_LABELS = {
    "roof": "Roof",
    "hvac": "HVAC",
    "plumbing": "Plumbing",
    "electrical": "Electrical",
    "water_heater": "Water heater",
    "foundation": "Foundation",
}

# Same keyword list as frontend/src/lib/format.ts's isSafetyHazard -- kept in
# sync by hand, since the two run in different languages/runtimes and there
# is nothing to literally share. If one changes, change the other.
_SAFETY_HAZARD_TERMS = [
    "safety concern",
    "safety hazard",
    "safety issue",
    "unsafe",
    "hazard",
    "carbon monoxide",
    "combustion problem",
    "combustion issue",
    "flame roll-out",
    "flame rollout",
    "gas leak",
    "shock risk",
    "shock hazard",
    "electrocution",
    "fire risk",
    "fire hazard",
    "explosion",
    "structural failure",
    "structural collapse",
    "life safety",
    "life-safety",
]

# Reminders ramp up as a 90-day item's due date approaches, rather than
# firing at a flat weekly cadence from the moment it's flagged: a monthly
# check-in while there's no real urgency yet, weekly once inside the final
# month -- which also covers "overdue", since that's just a very negative
# days-until-due, still inside the <=30 branch. There's deliberately no
# further ramp-up or cap past that: an item that stays overdue keeps getting
# a weekly nudge indefinitely, since there's no "mark resolved" concept to
# know it's safe to stop. The unsubscribe link below is the release valve
# for that, not an automatic cutoff.
_FAR_OUT_INTERVAL_DAYS = 30
_DUE_SOON_INTERVAL_DAYS = 7
_DUE_SOON_THRESHOLD_DAYS = 30


def is_safety_hazard(*texts: str | None) -> bool:
    combined = " ".join(text for text in texts if text).lower()
    return any(term in combined for term in _SAFETY_HAZARD_TERMS)


def days_until_due(created_at: datetime, *, as_of: datetime) -> int:
    """Days until a next_90_days item's 90-day mark; negative once overdue.

    `created_at` is when the action plan was generated (see
    extraction/service.py's create_action_plan), not an inspection date --
    InspectionEvent.inspection_date is never populated by the pipeline today,
    so this is the closest available anchor for "how long has this been on
    the roadmap."
    """
    due_date = created_at + timedelta(days=90)
    return (due_date.date() - as_of.date()).days


def reminder_interval_days(days_until: int) -> int:
    """How long to wait before the next reminder, given how close the
    soonest outstanding item is to its due date."""
    if days_until <= _DUE_SOON_THRESHOLD_DAYS:
        return _DUE_SOON_INTERVAL_DAYS
    return _FAR_OUT_INTERVAL_DAYS


def should_send_now(*, last_sent_at: datetime | None, as_of: datetime, interval_days: int) -> bool:
    if last_sent_at is None:
        return True
    return as_of - last_sent_at >= timedelta(days=interval_days)


def _format_cost(low: int, high: int) -> str:
    if low == high:
        return f"${low:,}"
    return f"${low:,} - ${high:,}"


def _due_wording(days: int) -> str:
    if days > 0:
        return f"due in {days} day{'s' if days != 1 else ''}"
    if days == 0:
        return "due today"
    return f"overdue by {-days} day{'s' if -days != 1 else ''}"


# Same proximity-to-the-claim principle as the report page's inline cost
# disclaimer (see frontend/src/lib/format.ts) -- placed right after the cost
# figures it qualifies, not only in a footer far below them.
_COST_DISCLAIMER = (
    "Costs above are AI-generated general ranges, not quotes, and have not been "
    "independently verified. They are not part of the inspector's findings or "
    "professional opinion. Have a licensed contractor confirm scope and cost "
    "before making repair decisions."
)


def build_reminder_email(
    document: Document, items: list[ActionItem], *, as_of: datetime
) -> tuple[str, str]:
    """Returns (subject, plain_text_body). Calm and short by design -- see
    the "Blueprint Ledger" wording standard: a heads-up, not a warning, even
    for a genuinely time-sensitive item. The one exception is the same one
    the report UI already makes: wording that names a real hazard
    (is_safety_hazard) stays direct rather than being softened -- it just
    never gets shouted (no all-caps, no exclamation points).

    Lists every outstanding next_90_days item, not only ones inside the
    due-soon window -- whether *today* is a reminder day is decided
    separately (see reminder_interval_days/should_send_now), but once an
    email is going out it gives the full picture rather than just whatever
    happens to be most urgent.
    """
    subject = f"A roadmap update for {document.title}"
    report_url = f"{settings.frontend_base_url.rstrip('/')}/reports/{document.id}"
    unsubscribe_url = f"{settings.frontend_base_url.rstrip('/')}/reports/{document.id}/unsubscribe"

    lines = [
        "Hi,",
        "",
        f"Your report for {document.title} flagged a few things worth a look:",
        "",
    ]
    for item in items:
        system = SYSTEM_LABELS.get(item.system, item.system)
        timing = _due_wording(days_until_due(item.created_at, as_of=as_of))
        prefix = "Safety concern -- " if is_safety_hazard(item.recommendation) else ""
        lines.append(f"- {system} ({timing}, est. {_format_cost(item.cost_low, item.cost_high)})")
        lines.append(f"  {prefix}{item.recommendation}")
        lines.append("")

    lines.append(_COST_DISCLAIMER)
    lines.append("")
    lines.append(f"Full report: {report_url}")
    lines.append("")
    lines.append(f"Stop these reminders: {unsubscribe_url}")
    lines.append("")
    lines.append("-- ALYF")

    return subject, "\n".join(lines)


async def _last_sent_at(session: AsyncSession, document_id: uuid.UUID) -> datetime | None:
    return await session.scalar(
        select(ReminderLog.last_sent_at).where(ReminderLog.document_id == document_id)
    )


async def _record_sent(session: AsyncSession, document_id: uuid.UUID, as_of: datetime) -> None:
    # Upsert: one row per document, overwritten on every send rather than
    # appended to -- see ReminderLog's docstring.
    stmt = insert(ReminderLog).values(document_id=document_id, last_sent_at=as_of)
    stmt = stmt.on_conflict_do_update(
        index_elements=[ReminderLog.document_id], set_={"last_sent_at": as_of}
    )
    await session.execute(stmt)
    await session.commit()


async def send_weekly_reminders(session: AsyncSession, *, dry_run: bool = False) -> int:
    """Check every home's roadmap; email the ones whose reminder cadence
    says today is due, given how urgent their soonest outstanding item is.
    Returns the number of emails sent (or, in dry-run mode, that would have
    been sent).

    One email per document, not per item. Documents with no next_90_days
    items at all are skipped entirely; no "all clear" email is sent.
    """
    as_of = datetime.now(UTC)
    documents = await ingestion_service.list_documents_with_notify_email(session)

    sent = 0
    for document in documents:
        # Never reach into a report an inspector hasn't approved (or that
        # hasn't auto-sent past its review window) -- see
        # InspectionEvent.status and extraction/service.py's
        # is_report_visible.
        if not await extraction_service.is_report_visible(session, document.id):
            continue

        items = await extraction_service.get_action_plan(session, document.id)
        outstanding = [item for item in items if item.urgency == "next_90_days"]
        if not outstanding:
            continue

        soonest = min(days_until_due(item.created_at, as_of=as_of) for item in outstanding)
        interval = reminder_interval_days(soonest)
        last_sent_at = await _last_sent_at(session, document.id)
        if not should_send_now(last_sent_at=last_sent_at, as_of=as_of, interval_days=interval):
            continue

        subject, body = build_reminder_email(document, outstanding, as_of=as_of)
        if dry_run:
            print(f"--- would send to {document.notify_email} (next check-in in {interval}d) ---")
            print(f"Subject: {subject}")
            print(body)
            print()
        else:
            send_email(document.notify_email, subject, body)
            await _record_sent(session, document.id, as_of)
        sent += 1

    return sent
