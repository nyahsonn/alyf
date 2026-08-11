"""Check every home's roadmap and email a reminder for anything due soon or
overdue in the next 90 days.

This is the thing to point cron / Windows Task Scheduler / your deploy
platform's scheduled-job feature at, once ALYF is running somewhere with a
reachable database -- there is no scheduler built into the app itself, and
this repo does not prescribe one (see README, "Weekly roadmap reminders").

    python scripts/send_roadmap_reminders.py [--dry-run]

Requires a running Postgres (see docker-compose.yml). Sending real email
also needs RESEND_API_KEY set (see backend/.env.example) -- --dry-run prints
each email instead of sending it, so the query and wording can be checked
without spending send quota or needing a real inbox.
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Run directly (`python scripts/send_roadmap_reminders.py`) and only this
# folder is importable, so put the backend root on the path before importing
# app.*
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionFactory, init_db  # noqa: E402
from app.notifications.emailer import EmailNotConfigured  # noqa: E402
from app.notifications.service import send_weekly_reminders  # noqa: E402

# Reminder text can include real report content; keep it readable on a
# Windows console's default cp1252 codepage rather than crashing on it.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


async def main_async(dry_run: bool) -> int:
    await init_db()
    async with SessionFactory() as session:
        try:
            sent = await send_weekly_reminders(session, dry_run=dry_run)
        except EmailNotConfigured as e:
            print(f"{e}\n(Use --dry-run to check the query/wording without sending.)")
            return 1

    verb = "Would send" if dry_run else "Sent"
    print(f"{verb} {sent} reminder email{'s' if sent != 1 else ''}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print each email instead of sending it",
    )
    args = parser.parse_args()
    return asyncio.run(main_async(args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
