"""Move any report still stuck at status="pending_review" past its auto-send
window to "auto_sent", so a slow inspector doesn't block delivery to the
buyer.

This is the thing to point cron / Windows Task Scheduler / your deploy
platform's scheduled-job feature at, once ALYF is running somewhere with a
reachable database -- same story as scripts/send_roadmap_reminders.py, there
is no scheduler built into the app itself (see README, "Weekly roadmap
reminders"). Run it more often than the window itself (e.g. hourly) so a
report doesn't sit auto-sendable for long before this actually runs.

    python scripts/auto_send_pending_reports.py [--dry-run]

Requires a running Postgres (see docker-compose.yml). Also notifies each
report's buyer (if they opted in at upload) and inspector by email that it's
now visible -- see app/notifications/service.py's send_report_ready_emails --
unless --dry-run, in which case nothing is changed or sent.
"""

import argparse
import asyncio
import sys
from datetime import timedelta
from pathlib import Path

# Run directly (`python scripts/auto_send_pending_reports.py`) and only this
# folder is importable, so put the backend root on the path before importing
# app.*
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.core.database import SessionFactory, init_db  # noqa: E402
from app.extraction.service import auto_send_stale_events  # noqa: E402
from app.notifications.service import send_report_ready_emails  # noqa: E402


async def main_async(dry_run: bool) -> int:
    await init_db()
    after = timedelta(hours=settings.auto_send_after_hours)
    async with SessionFactory() as session:
        moved = await auto_send_stale_events(session, after=after, dry_run=dry_run)
        if not dry_run:
            for event in moved:
                await send_report_ready_emails(session, event.document_id, is_auto_sent=True)

    verb = "Would auto-send" if dry_run else "Auto-sent"
    count = len(moved)
    print(f"{verb} {count} report{'s' if count != 1 else ''} (window: {after}).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="count without changing any report's status",
    )
    args = parser.parse_args()
    return asyncio.run(main_async(args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
