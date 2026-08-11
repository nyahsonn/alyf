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

Requires a running Postgres (see docker-compose.yml). No email is sent by
this script -- "auto_sent" only unlocks the report at its existing link
(GET /documents/{id}/buyer-report); the weekly reminder job is what emails
anything, and only once a report is approved or auto_sent (see
app/notifications/service.py).
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


async def main_async(dry_run: bool) -> int:
    await init_db()
    after = timedelta(hours=settings.auto_send_after_hours)
    async with SessionFactory() as session:
        moved = await auto_send_stale_events(session, after=after, dry_run=dry_run)

    verb = "Would auto-send" if dry_run else "Auto-sent"
    print(f"{verb} {moved} report{'s' if moved != 1 else ''} (window: {after}).")
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
