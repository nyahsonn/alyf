"""Run one PDF through OCR, then Claude, and print the structured home-inspection report.

Chains two steps that can each be run alone -- `ocr_pdf.py` prints raw OCR
output; this feeds that same output to app/extraction/home_inspection.py and
prints what Claude made of it.

    pip install anthropic
    python scripts/extract_home_inspection.py path/to/report.pdf

Requires DOCAI_* configuration (see ocr_pdf.py) plus GOOGLE_APPLICATION_CREDENTIALS
for the OCR step, and ANTHROPIC_API_KEY (or an `ant auth login` profile) for the
extraction step.
"""

import argparse
import sys
from pathlib import Path

# Run directly (`python scripts/extract_home_inspection.py`) and only this folder
# is importable, so put the backend root on the path before importing app.*
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.extraction.home_inspection import ExtractionError, extract_home_systems  # noqa: E402
from app.ingestion.ocr import OcrError, extract_pdf  # noqa: E402
from app.ingestion.service import render_tables  # noqa: E402

# The report can contain characters the Windows console's default cp1252
# codepage renders as "?". Ask for UTF-8 explicitly.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", type=Path, help="path to the PDF to read")
    args = parser.parse_args()

    try:
        ocr_result = extract_pdf(args.path)
    except OcrError as e:
        print(e)
        return 1

    raw_text = "\n\n".join(
        section for section in (ocr_result.prose, render_tables(ocr_result.tables)) if section
    )

    try:
        report = extract_home_systems(raw_text)
    except ExtractionError as e:
        print(e)
        return 1

    print(report.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
