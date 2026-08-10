"""Run every PDF in a directory through the full AI Home Health Report pipeline
-- ingest, home report, action plan -- and print each report's prioritized
action list.

Unlike compare_home_reports.py, this touches the database. An action plan
reasons only over already-saved system/finding rows (see
extraction/service.py's create_action_plan), never the report's raw text
again, so there is no way to produce one without first persisting a home
report for it to read back. Each run ingests every PDF as a brand new
Document -- re-running this script uploads each file again rather than
reusing a prior run's document, the same as uploading the same file twice
through the API.

    pip install anthropic
    python scripts/generate_action_plans.py [reports_dir]

reports_dir defaults to ../tests-reports. Requires a running Postgres (see
docker-compose.yml) plus the same DOCAI_* and GOOGLE_APPLICATION_CREDENTIALS
/ ANTHROPIC_API_KEY configuration as extract_home_inspection.py -- see that
script's docstring. Each PDF costs one Document AI OCR call and two Claude
calls (home report + action plan), so this is not free to re-run.
"""

import argparse
import asyncio
import hashlib
import sys
from pathlib import Path

# Run directly (`python scripts/generate_action_plans.py`) and only this
# folder is importable, so put the backend root on the path before importing
# app.*
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionFactory, init_db  # noqa: E402
from app.extraction import service as extraction_service  # noqa: E402
from app.extraction.home_inspection import ExtractionError  # noqa: E402
from app.ingestion import service as ingestion_service  # noqa: E402
from app.ingestion.ocr import OcrError, extract_pdf  # noqa: E402
from app.ingestion.schemas import DocumentCreate  # noqa: E402
from app.ingestion.service import render_tables  # noqa: E402

# The report can contain characters the Windows console's default cp1252
# codepage renders as "?". Ask for UTF-8 explicitly.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_REPORTS_DIR = Path(__file__).resolve().parents[2] / "tests-reports"

URGENCY_LABELS = {
    "next_90_days": "Next 90 days",
    "next_2_years": "Next 2 years",
    "next_5_years": "Next 5 years",
}


async def run_one(path: Path) -> None:
    """Ingest, extract, and plan for one PDF, printing its action list."""
    raw = path.read_bytes()

    try:
        ocr_result = extract_pdf(path)
    except OcrError as e:
        print(f"{path.name}: OCR failed: {e}")
        return

    content = "\n\n".join(
        section for section in (ocr_result.prose, render_tables(ocr_result.tables)) if section
    )
    if not content.strip():
        print(f"{path.name}: no text extracted, skipping")
        return

    async with SessionFactory() as session:
        document = await ingestion_service.ingest_document(
            session,
            DocumentCreate(
                title=path.name,
                content=content,
                source_type="pdf",
                source_ref=path.name,
                file_bytes=raw,
                file_sha256=hashlib.sha256(raw).hexdigest(),
            ),
        )

        try:
            await extraction_service.extract_home_report(session, document.id)
            items = await extraction_service.create_action_plan(session, document.id)
        except ExtractionError as e:
            print(f"{path.name}: extraction failed: {e}")
            return

    print(f"\n=== {path.name} (document {document.id}) ===")
    if not items:
        print("  (no action items -- nothing in the home report needed flagging)")
        return

    # create_action_plan already orders items most-urgent-first and assigns
    # `position` to match; sorting on it here is just making that order
    # explicit rather than trusting insertion order to survive the round trip.
    for item in sorted(items, key=lambda i: i.position):
        label = URGENCY_LABELS.get(item.urgency, item.urgency)
        print(f"  [{label}] {item.system}: ${item.cost_low:,} - ${item.cost_high:,}")
        print(f"    {item.recommendation}")


async def main_async(reports_dir: Path) -> int:
    paths = sorted(reports_dir.glob("*.pdf"))
    if not paths:
        print(f"No PDFs found in {reports_dir}")
        return 1

    await init_db()
    for path in paths:
        print(f"Running {path.name}...", file=sys.stderr)
        await run_one(path)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "reports_dir",
        type=Path,
        nargs="?",
        default=DEFAULT_REPORTS_DIR,
        help=f"directory of PDFs to run (default: {DEFAULT_REPORTS_DIR})",
    )
    args = parser.parse_args()
    return asyncio.run(main_async(args.reports_dir))


if __name__ == "__main__":
    sys.exit(main())
