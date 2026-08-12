"""Unit tests for the weekly roadmap reminder logic. No database or network
needed -- see app/notifications/service.py.

Run with:  pytest
"""

import uuid
from datetime import UTC, datetime, timedelta

from app.extraction.models import ActionItem
from app.ingestion.models import Document
from app.notifications.service import (
    build_buyer_ready_email,
    build_inspector_ready_email,
    build_reminder_email,
    days_until_due,
    is_safety_hazard,
    reminder_interval_days,
    should_send_now,
)

NOW = datetime(2026, 8, 10, tzinfo=UTC)


def test_days_until_due_for_a_fresh_item_is_ninety():
    assert days_until_due(NOW, as_of=NOW) == 90


def test_days_until_due_is_negative_once_overdue():
    created_at = NOW - timedelta(days=120)
    assert days_until_due(created_at, as_of=NOW) == -30


def test_reminder_interval_is_monthly_when_far_from_due():
    assert reminder_interval_days(40) == 30


def test_reminder_interval_is_weekly_inside_the_last_month():
    assert reminder_interval_days(25) == 7


def test_reminder_interval_is_weekly_at_the_thirty_day_edge():
    # Inclusive boundary: exactly 30 days out already counts as "inside".
    assert reminder_interval_days(30) == 7


def test_reminder_interval_stays_weekly_once_overdue():
    # No further ramp-up or cap -- see the module docstring on why.
    assert reminder_interval_days(-45) == 7


def test_should_send_now_when_never_sent_before():
    assert should_send_now(last_sent_at=None, as_of=NOW, interval_days=30)


def test_should_send_now_is_false_within_the_interval():
    last_sent_at = NOW - timedelta(days=5)
    assert not should_send_now(last_sent_at=last_sent_at, as_of=NOW, interval_days=7)


def test_should_send_now_is_true_once_the_interval_has_elapsed():
    last_sent_at = NOW - timedelta(days=7)
    assert should_send_now(last_sent_at=last_sent_at, as_of=NOW, interval_days=7)


def test_safety_hazard_matches_known_wording():
    assert is_safety_hazard("Do not run the furnace until cleared -- unsafe combustion problem")
    assert is_safety_hazard("Exposed splices are a shock and fire safety concern")


def test_safety_hazard_does_not_match_routine_wording():
    assert not is_safety_hazard("Clean the gutters and repair minor shingle damage")


def test_safety_hazard_checks_every_text_given():
    assert is_safety_hazard(None, "routine note", "carbon monoxide detector missing")


def _document(**overrides) -> Document:
    return Document(
        id=overrides.get("id", uuid.uuid4()),
        title=overrides.get("title", "report3.pdf"),
    )


def _item(system: str, recommendation: str, *, created_at: datetime, **overrides) -> ActionItem:
    return ActionItem(
        id=uuid.uuid4(),
        system=system,
        urgency="next_90_days",
        recommendation=recommendation,
        cost_low=overrides.get("cost_low", 400),
        cost_high=overrides.get("cost_high", 1200),
        created_at=created_at,
    )


def test_reminder_email_is_short_and_calm_for_a_routine_item():
    document = _document(title="report3.pdf")
    item = _item("roof", "Clean the gutters and repair minor shingle damage.", created_at=NOW)
    subject, body = build_reminder_email(document, [item], as_of=NOW)

    assert "report3.pdf" in subject
    assert "Roof" in body
    assert "$400 - $1,200" in body
    assert "Clean the gutters" in body
    assert "Safety concern" not in body
    assert body.upper() != body  # not shouting
    assert "!" not in body


def test_reminder_email_stays_direct_but_not_shouty_for_a_hazard_item():
    document = _document(title="report3.pdf")
    item = _item(
        "hvac",
        "Have a licensed HVAC contractor evaluate the furnace -- unsafe combustion problem.",
        created_at=NOW,
    )
    subject, body = build_reminder_email(document, [item], as_of=NOW)

    assert "Safety concern" in body
    assert "URGENT" not in body
    assert "!" not in body


def test_reminder_email_lists_items_even_when_not_yet_due_soon():
    # build_reminder_email always shows the full picture -- whether *today*
    # is a send day is decided separately by reminder_interval_days/
    # should_send_now, upstream in send_weekly_reminders.
    document = _document()
    item = _item("roof", "Something 60 days out, not due soon yet.", created_at=NOW)
    _, body = build_reminder_email(document, [item], as_of=NOW)
    assert "due in 90 day" in body


def test_reminder_email_includes_a_link_to_the_report_and_an_unsubscribe_link():
    document = _document()
    item = _item("roof", "Something to check on.", created_at=NOW)
    _, body = build_reminder_email(document, [item], as_of=NOW)
    assert f"/reports/{document.id}" in body
    assert f"/reports/{document.id}/unsubscribe" in body


def test_reminder_email_notes_overdue_items_as_overdue():
    document = _document()
    item = _item("hvac", "Something overdue.", created_at=NOW - timedelta(days=100))
    _, body = build_reminder_email(document, [item], as_of=NOW)
    assert "overdue by 10 day" in body


def test_buyer_ready_email_links_to_the_report_and_names_the_inspector():
    document = _document()
    _, body = build_buyer_ready_email(document, "Nico Amah", is_auto_sent=False)
    assert f"/reports/{document.id}" in body
    assert "Nico Amah" in body
    assert "reviewed and approved" in body


def test_buyer_ready_email_omits_the_approved_line_when_auto_sent():
    document = _document()
    _, body = build_buyer_ready_email(document, None, is_auto_sent=True)
    assert "reviewed and approved" not in body


def test_buyer_ready_email_has_no_inspector_line_when_name_is_unknown():
    document = _document()
    _, body = build_buyer_ready_email(document, None, is_auto_sent=False)
    assert "Reach out to" not in body


def test_inspector_ready_email_distinguishes_approved_from_auto_sent():
    document = _document()
    subject_approved, body_approved = build_inspector_ready_email(document, is_auto_sent=False)
    subject_auto, body_auto = build_inspector_ready_email(document, is_auto_sent=True)
    assert "Approved" in subject_approved
    assert "approved and now visible" in body_approved
    assert "Auto-sent" in subject_auto
    assert "wasn't reviewed within the review window" in body_auto


def test_reminder_email_includes_a_cost_disclaimer():
    # Same proximity-to-the-claim principle as the report page's inline
    # cost disclaimer -- this is the one place cost figures actually get
    # emailed out, so they shouldn't go unguarded here either.
    document = _document()
    item = _item("roof", "Something to check on.", created_at=NOW)
    _, body = build_reminder_email(document, [item], as_of=NOW)
    assert "AI-generated" in body
    assert "not quotes" in body
    assert "licensed contractor" in body
