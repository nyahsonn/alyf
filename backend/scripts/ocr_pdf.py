"""Run one PDF through Document AI and print the raw result.

Nothing is saved -- this is for looking at what the service actually returns
before you decide what the pipeline should do with it.

    pip install google-cloud-documentai
    python scripts/ocr_pdf.py path/to/file.pdf

Requires DOCAI_PROJECT_ID, DOCAI_LOCATION and DOCAI_PROCESSOR_ID (backend/.env
or real environment variables), plus GOOGLE_APPLICATION_CREDENTIALS pointing at
a service account key file. If it fails before reaching the file, check the
credentials first with scripts/check_document_ai.py.
"""

import argparse
import sys
from pathlib import Path

# Run directly (`python scripts/ocr_pdf.py`) and only this folder is importable,
# so put the backend root on the path before importing app.*
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.ocr import OcrError, OcrResult, extract_pdf  # noqa: E402

# Extracted text is whatever was in the document, so it can contain characters
# the Windows console's default cp1252 codepage renders as "?". Ask for UTF-8.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def print_result(result: OcrResult) -> None:
    print(f"==== TEXT ({result.page_count} page(s), {len(result.text)} characters) ====")
    print(result.text)

    print(f"\n==== TABLES ({len(result.tables)}) ====")
    if not result.tables:
        print(
            "None. Table structure comes back only from a Form Parser processor "
            "-- a Document OCR processor returns text alone."
        )
        return

    for position, table in enumerate(result.tables, start=1):
        rows = table.rows
        columns = max((len(row) for row in rows), default=0)
        print(
            f"\n-- table {position}: page {table.page_number}, "
            f"{len(rows)} row(s) x {columns} column(s), "
            f"{len(table.header_rows)} header row(s) --"
        )
        # Tab-separated: the cell text is printed as it came back, and a tab is
        # the least likely thing to already be inside a cell.
        for row in rows:
            print("\t".join(row))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", type=Path, help="path to the PDF to send")
    args = parser.parse_args()

    try:
        result = extract_pdf(args.path)
    except OcrError as e:
        print(e)
        return 1

    print_result(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
